package com.babycue.camera.net

import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

sealed interface LinkState {
    data object Connecting : LinkState
    data object Connected : LinkState
    data class Retrying(val reason: String, val delayMs: Long) : LinkState
}

/** A failure whose message is already fit to show to the user. */
class LinkException(message: String) : IOException(message)

/**
 * Runs one connection to the server on a background thread and reconnects with capped exponential
 * backoff whenever it ends. [start] and [stop] are idempotent and never block; after [stop] no
 * further state is reported, even if the old thread is still unwinding.
 */
abstract class ReconnectingLink(
    private val onState: (LinkState) -> Unit,
    private val initialBackoffMs: Long = 500,
    private val maxBackoffMs: Long = 5_000,
) {
    private class Run {
        @Volatile var cancelled = false
    }

    private var run: Run? = null
    private var thread: Thread? = null

    /**
     * One connection attempt. Call [connected] once the server accepted us. Return or throw when the
     * session ends; check [isCancelled] regularly. Throw [IOException] for failures.
     */
    protected abstract fun session(isCancelled: () -> Boolean, connected: () -> Unit)

    /** Unblock [session] (close the socket) from another thread. */
    protected abstract fun abort()

    @Synchronized
    fun start() {
        if (run != null) return
        val r = Run()
        run = r
        thread = Thread({ loop(r) }, "babycue-link").apply {
            isDaemon = true
            start()
        }
    }

    @Synchronized
    fun stop() {
        val r = run ?: return
        r.cancelled = true
        run = null
        thread?.interrupt()
        thread = null
        // Closing sockets can count as network access, which Android forbids on the main thread.
        Thread({ abort() }, "babycue-link-abort").apply {
            isDaemon = true
            start()
        }
    }

    private fun loop(r: Run) {
        fun report(state: LinkState) {
            if (!r.cancelled) onState(state)
        }
        var backoff = initialBackoffMs
        while (!r.cancelled) {
            report(LinkState.Connecting)
            var reason = "The server closed the connection"
            try {
                session({ r.cancelled }) {
                    backoff = initialBackoffMs
                    report(LinkState.Connected)
                }
            } catch (e: IOException) {
                if (!r.cancelled) reason = describe(e)
            } catch (_: InterruptedException) {
                // stop() interrupted us
            }
            if (r.cancelled) break
            report(LinkState.Retrying(reason, backoff))
            try {
                Thread.sleep(backoff)
            } catch (_: InterruptedException) {
                break
            }
            backoff = (backoff * 2).coerceAtMost(maxBackoffMs)
        }
    }

    private fun describe(e: IOException): String = when (e) {
        is LinkException -> e.message ?: "Link error"
        is UnknownHostException -> "Unknown server address"
        is ConnectException -> "Cannot connect to the server"
        is SocketTimeoutException -> "The server did not respond in time"
        else -> e.message ?: e.javaClass.simpleName
    }
}
