package com.babycue.camera.net

import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

class FrameReceiverTest {

    /** Plays the BabyCue server's /view endpoint. */
    private class FakeViewServer(
        private val status: Int = 200,
        private val parts: List<ByteArray> = emptyList(),
        private val holdOpen: Boolean = true,
    ) {
        private val listener = ServerSocket(0, 5, InetAddress.getLoopbackAddress())
        val url = "http://127.0.0.1:${listener.localPort}/view"
        val connections = AtomicInteger()
        val requestLines = CopyOnWriteArrayList<String>()

        init {
            thread(isDaemon = true) {
                while (!listener.isClosed) {
                    val socket = try {
                        listener.accept()
                    } catch (_: IOException) {
                        break
                    }
                    connections.incrementAndGet()
                    thread(isDaemon = true) { handle(socket) }
                }
            }
        }

        fun close() = listener.close()

        private fun handle(socket: Socket) = socket.use {
            val input = it.getInputStream()
            val head = StringBuilder()
            while (!head.endsWith("\r\n\r\n")) {
                val b = input.read()
                if (b < 0) return
                head.append(b.toChar())
            }
            requestLines += head.lineSequence().first()
            val out = it.getOutputStream()
            if (status != 200) {
                out.write("HTTP/1.1 $status X\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray())
                return
            }
            out.write(
                ("HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=${WireProtocol.BOUNDARY}\r\n" +
                    "Connection: close\r\n\r\n").toByteArray(),
            )
            for (p in parts) {
                out.write("--${WireProtocol.BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: ${p.size}\r\n\r\n".toByteArray())
                out.write(p)
                out.write("\r\n".toByteArray())
                out.flush()
            }
            if (holdOpen) {
                try {
                    while (input.read() >= 0) { /* wait for the client to leave */ }
                } catch (_: IOException) {
                }
            }
        }
    }

    private val servers = ArrayList<FakeViewServer>()
    private val receivers = ArrayList<FrameReceiver>()

    @After
    fun tearDown() {
        receivers.forEach { it.stop() }
        servers.forEach { it.close() }
    }

    private fun server(status: Int = 200, parts: List<ByteArray> = emptyList(), holdOpen: Boolean = true) =
        FakeViewServer(status, parts, holdOpen).also { servers += it }

    private fun receiver(
        url: String,
        frames: CopyOnWriteArrayList<ByteArray>,
        states: CopyOnWriteArrayList<LinkState>,
        readTimeoutMs: Int = 5_000,
    ) = FrameReceiver(url, { frames.add(it) }, { states.add(it) }, 1_000, readTimeoutMs, 30, 100)
        .also { receivers += it }

    private fun jpeg(i: Int) = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), i.toByte(), 0xFF.toByte(), 0xD9.toByte())

    @Test
    fun framesAreDeliveredIntactAndInOrder() {
        val sent = (1..4).map { jpeg(it) }
        val server = server(parts = sent)
        val frames = CopyOnWriteArrayList<ByteArray>()
        val states = CopyOnWriteArrayList<LinkState>()
        receiver(server.url, frames, states).start()
        assertTrue(waitFor { frames.size == 4 })
        sent.forEachIndexed { i, bytes -> assertArrayEquals(bytes, frames[i]) }
        assertEquals(LinkState.Connecting, states.first())
        assertTrue(LinkState.Connected in states)
        assertEquals("GET /view HTTP/1.1", server.requestLines.first())
    }

    @Test
    fun aFullServerIsReportedAndRetried() {
        val server = server(status = 503)
        val states = CopyOnWriteArrayList<LinkState>()
        receiver(server.url, CopyOnWriteArrayList(), states).start()
        assertTrue(waitFor { states.count { it is LinkState.Retrying } >= 2 })
        assertTrue(server.connections.get() >= 2)
        val reason = states.filterIsInstance<LinkState.Retrying>().first().reason
        assertTrue(reason, reason.contains("maximum number of viewers"))
    }

    @Test
    fun reconnectsWhenTheServerClosesTheStream() {
        val server = server(parts = listOf(jpeg(1)), holdOpen = false)
        val frames = CopyOnWriteArrayList<ByteArray>()
        val states = CopyOnWriteArrayList<LinkState>()
        receiver(server.url, frames, states).start()
        assertTrue(waitFor(8_000) { frames.size >= 3 })
        assertTrue(server.connections.get() >= 3)
        assertTrue(states.any { it is LinkState.Retrying })
    }

    @Test
    fun anIdleStreamIsTreatedAsWaitingForTheInputPhone() {
        val server = server() // connects, then sends nothing
        val states = CopyOnWriteArrayList<LinkState>()
        receiver(server.url, CopyOnWriteArrayList(), states, readTimeoutMs = 150).start()
        assertTrue(waitFor { states.any { it is LinkState.Retrying } })
        val reason = states.filterIsInstance<LinkState.Retrying>().first().reason
        assertTrue(reason, reason.contains("Waiting for the input phone"))
    }

    @Test
    fun garbageInsteadOfVideoIsRejectedNotDecoded() {
        val listener = ServerSocket(0, 1, InetAddress.getLoopbackAddress())
        thread(isDaemon = true) {
            try {
                listener.accept().use { s ->
                    s.getInputStream().read(ByteArray(1024))
                    s.getOutputStream().write("HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n<html>nope</html>\r\n".toByteArray())
                }
            } catch (_: IOException) {
            }
        }
        val frames = CopyOnWriteArrayList<ByteArray>()
        val states = CopyOnWriteArrayList<LinkState>()
        receiver("http://127.0.0.1:${listener.localPort}/view", frames, states).start()
        assertTrue(waitFor { states.any { it is LinkState.Retrying } })
        assertEquals(0, frames.size)
        listener.close()
    }

    @Test
    fun stopLeavesPromptlyAndDeliversNothingMore() {
        val server = server(parts = listOf(jpeg(1)))
        val frames = CopyOnWriteArrayList<ByteArray>()
        val states = CopyOnWriteArrayList<LinkState>()
        val receiver = receiver(server.url, frames, states)
        receiver.start()
        assertTrue(waitFor { frames.size == 1 })
        val started = System.nanoTime()
        receiver.stop()
        receiver.stop()
        assertTrue("stop() must not block", (System.nanoTime() - started) / 1_000_000 < 500)
        Thread.sleep(200)
        val settled = states.size
        Thread.sleep(300)
        assertEquals(settled, states.size)
        assertEquals(1, server.connections.get())
    }
}
