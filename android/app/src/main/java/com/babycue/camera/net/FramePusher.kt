package com.babycue.camera.net

import com.babycue.camera.capture.JpegFrameSource
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicLong

/**
 * Input mode: streams every new JPEG from [source] to the server's `/ingest` endpoint as one long
 * chunked POST of length-prefixed records (see [WireProtocol]). Frames are never queued: after a
 * slow write the next record is simply the newest frame.
 */
class FramePusher(
    private val source: JpegFrameSource,
    private val url: String,
    onState: (LinkState) -> Unit,
    private val connectTimeoutMs: Int = 4_000,
    initialBackoffMs: Long = 500,
    maxBackoffMs: Long = 5_000,
) : ReconnectingLink(onState, initialBackoffMs, maxBackoffMs) {

    @Volatile
    private var connection: HttpURLConnection? = null
    private val sent = AtomicLong()

    /** Frames written to the server since this object was created. */
    val framesSent: Long get() = sent.get()

    override fun session(isCancelled: () -> Boolean, connected: () -> Unit) {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            setChunkedStreamingMode(0)
            connectTimeout = connectTimeoutMs
            readTimeout = READ_TIMEOUT_MS
            setRequestProperty("Content-Type", "application/octet-stream")
        }
        connection = conn
        try {
            val out = conn.outputStream
            connected()
            var last = 0L
            try {
                while (!isCancelled()) {
                    val frame = source.awaitNext(last, POLL_MS) ?: continue
                    out.write(WireProtocol.lengthPrefix(frame.bytes.size))
                    out.write(frame.bytes)
                    out.flush()
                    last = frame.sequence
                    sent.incrementAndGet()
                }
            } catch (e: IOException) {
                if (isCancelled()) return
                throw rejection(conn) ?: e
            }
        } finally {
            connection = null
            conn.disconnect()
        }
    }

    /** The server answers 409 before reading any body when another phone is already the input. */
    private fun rejection(conn: HttpURLConnection): LinkException? = try {
        if (conn.responseCode == 409) LinkException("Another phone is already sending video") else null
    } catch (_: Exception) {
        null
    }

    override fun abort() {
        connection?.disconnect()
    }

    private companion object {
        const val POLL_MS = 500L
        const val READ_TIMEOUT_MS = 10_000
    }
}
