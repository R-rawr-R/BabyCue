package com.babycue.camera.server

import com.babycue.camera.capture.JpegFrameSource
import java.io.IOException
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.net.SocketTimeoutException
import java.util.Collections
import java.util.concurrent.atomic.AtomicInteger

sealed interface ServerState {
    data object Stopped : ServerState
    data object Starting : ServerState
    data class Running(val port: Int) : ServerState
    data class Failed(val message: String) : ServerState
}

/**
 * Minimal MJPEG-over-HTTP server on plain [ServerSocket]s.
 *
 * Threads: one accept thread plus one thread per streaming client (at most [maxClients]); no work
 * happens on the caller's thread, so [start] and [stop] are safe to call from the UI thread.
 * [onStateChanged] is invoked from server threads (and from [stop] on the caller's thread); post to
 * the main thread before touching views.
 *
 * Frames are pulled from [source] with `awaitNext`, so each client always gets the newest frame
 * and skips any it was too slow for. Nothing is queued. A client sees a new frame at most once.
 *
 * Unencrypted HTTP, no authentication: trusted local networks only.
 */
class MjpegServer(
    private val source: JpegFrameSource,
    private val port: Int = MjpegProtocol.DEFAULT_PORT,
    private val maxClients: Int = DEFAULT_MAX_CLIENTS,
    private val onStateChanged: (ServerState) -> Unit = {},
) {
    private val lock = Any()
    private var session: Session? = null

    @Volatile
    var state: ServerState = ServerState.Stopped
        private set

    /** Number of clients currently receiving the stream. */
    val clientCount: Int get() = synchronized(lock) { session?.streaming?.get() ?: 0 }

    /** Begins listening. No-op if already starting/running. Result is reported through [state]. */
    fun start() {
        val s: Session
        synchronized(lock) {
            if (session != null) return
            s = Session()
            session = s
            setState(s, ServerState.Starting)
        }
        val t = Thread(s::acceptLoop, "babycue-http-accept")
        s.acceptThread = t
        t.start()
    }

    /** Stops listening, disconnects all clients and releases the port. Safe to call repeatedly. */
    fun stop() {
        val s: Session
        synchronized(lock) {
            val current = session
            if (current == null) {
                // Not running; clear a previous failure so the UI can show "stopped".
                if (state !is ServerState.Failed) return
                state = ServerState.Stopped
                onStateChanged(ServerState.Stopped)
                return
            }
            s = current
            session = null
        }
        s.close()
        synchronized(lock) { state = ServerState.Stopped }
        onStateChanged(ServerState.Stopped)
    }

    private fun setState(s: Session, new: ServerState) {
        // Ignore reports from a session that has already been stopped or replaced.
        synchronized(lock) {
            if (session !== s) return
            state = new
        }
        onStateChanged(new)
    }

    private inner class Session {
        @Volatile var closed = false
        @Volatile var acceptThread: Thread? = null
        private var serverSocket: ServerSocket? = null
        private val clients: MutableSet<Socket> = Collections.synchronizedSet(HashSet())
        val streaming = AtomicInteger(0)

        fun acceptLoop() {
            if (closed) return
            val ss = try {
                ServerSocket().apply {
                    reuseAddress = true
                    bind(InetSocketAddress(port))
                }
            } catch (e: IOException) {
                fail("Cannot listen on port $port: ${e.message ?: e.javaClass.simpleName}")
                return
            } catch (e: SecurityException) {
                fail("Not allowed to listen on port $port: ${e.message}")
                return
            }
            synchronized(this) {
                if (closed) {
                    runCatching { ss.close() }
                    return
                }
                serverSocket = ss
            }
            setState(this, ServerState.Running(ss.localPort))
            while (!closed) {
                val client = try {
                    ss.accept()
                } catch (e: IOException) {
                    if (!closed) fail("Server socket error: ${e.message ?: e.javaClass.simpleName}")
                    return
                }
                try {
                    Thread({ handle(client) }, "babycue-http-client").apply { isDaemon = true }.start()
                } catch (e: Throwable) {
                    runCatching { client.close() }
                }
            }
        }

        private fun fail(message: String) {
            val failed = ServerState.Failed(message)
            synchronized(lock) {
                if (session !== this@Session) return // already stopped
                session = null
                state = failed
            }
            close()
            onStateChanged(failed)
        }

        fun close() {
            val ss: ServerSocket?
            synchronized(this) {
                closed = true
                ss = serverSocket
                serverSocket = null
            }
            runCatching { ss?.close() }
            val snapshot = synchronized(clients) { clients.toList() }
            snapshot.forEach { runCatching { it.close() } }
            // Wait for the accept thread so the port is really released when stop() returns
            // (a following start() must not hit "address in use"). Closing is immediate, so this is short.
            val t = acceptThread
            if (t != null && t !== Thread.currentThread()) runCatching { t.join(JOIN_TIMEOUT_MS) }
        }

        private fun handle(socket: Socket) {
            clients.add(socket)
            try {
                if (closed) return
                socket.tcpNoDelay = true
                socket.soTimeout = REQUEST_TIMEOUT_MS
                val out = socket.getOutputStream()
                when (val parsed = HttpRequestParser.read(socket.getInputStream())) {
                    ParseResult.Closed -> Unit
                    is ParseResult.Rejected -> out.send(MjpegProtocol.errorResponse(parsed.status, parsed.reason))
                    is ParseResult.Ok -> route(socket, out, parsed.request)
                }
            } catch (_: IOException) {
                // Client vanished or the server is stopping: nothing to report.
            } finally {
                clients.remove(socket)
                runCatching { socket.close() }
            }
        }

        private fun route(socket: Socket, out: OutputStream, req: HttpRequest) {
            when {
                req.method != "GET" ->
                    out.send(MjpegProtocol.errorResponse(405, "Method Not Allowed", listOf("Allow" to "GET")))
                req.path != MjpegProtocol.STREAM_PATH ->
                    out.send(MjpegProtocol.errorResponse(404, "Not Found"))
                else -> {
                    // Reserve a slot atomically.
                    if (streaming.incrementAndGet() > maxClients) {
                        streaming.decrementAndGet()
                        out.send(MjpegProtocol.errorResponse(503, "Service Unavailable", listOf("Retry-After" to "2")))
                        return
                    }
                    try {
                        stream(socket, out)
                    } finally {
                        streaming.decrementAndGet()
                    }
                }
            }
        }

        private fun stream(socket: Socket, out: OutputStream) {
            out.send(MjpegProtocol.streamResponseHead())
            var lastSequence = 0L
            while (!closed) {
                val frame = source.awaitNext(lastSequence, FRAME_WAIT_MS)
                if (frame == null) {
                    // No new frame: nothing to send. Use the pause to notice a client that went away.
                    if (Thread.currentThread().isInterrupted || peerClosed(socket)) return
                    continue
                }
                lastSequence = frame.sequence
                out.write(MjpegProtocol.partHead(frame.bytes.size))
                out.write(frame.bytes)
                out.write(MjpegProtocol.partTail)
                out.flush()
            }
        }
    }

    private fun OutputStream.send(bytes: ByteArray) {
        write(bytes)
        flush()
    }

    /** True if the client closed its side. Clients never send after the request, so any read result is EOF/error. */
    private fun peerClosed(socket: Socket): Boolean {
        val previous = try {
            socket.soTimeout
        } catch (_: SocketException) {
            return true
        }
        return try {
            socket.soTimeout = 1
            socket.getInputStream().read() < 0 // -1 = orderly close; stray bytes are ignored
        } catch (_: SocketTimeoutException) {
            false
        } catch (_: IOException) {
            true
        } finally {
            runCatching { socket.soTimeout = previous }
        }
    }

    companion object {
        const val DEFAULT_MAX_CLIENTS = 4
        private const val REQUEST_TIMEOUT_MS = 5_000
        private const val FRAME_WAIT_MS = 1_000L
        private const val JOIN_TIMEOUT_MS = 1_000L
    }
}
