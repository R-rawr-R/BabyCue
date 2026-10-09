package com.babycue.camera.net

import java.io.BufferedInputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL

/**
 * Output mode: pulls the relayed video from the server's `/view` endpoint and hands each JPEG to
 * [onFrame] on the link thread. [onFrame] should be quick; while it runs, TCP back-pressure makes
 * the server skip frames for this viewer rather than queue them.
 */
class FrameReceiver(
    private val url: String,
    private val onFrame: (ByteArray) -> Unit,
    onState: (LinkState) -> Unit,
    private val connectTimeoutMs: Int = 4_000,
    private val readTimeoutMs: Int = 30_000,
    initialBackoffMs: Long = 500,
    maxBackoffMs: Long = 5_000,
) : ReconnectingLink(onState, initialBackoffMs, maxBackoffMs) {

    @Volatile
    private var connection: HttpURLConnection? = null

    override fun session(isCancelled: () -> Boolean, connected: () -> Unit) {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = connectTimeoutMs
            readTimeout = readTimeoutMs
        }
        connection = conn
        try {
            val code = conn.responseCode
            if (code == 503) throw LinkException("The server already has the maximum number of viewers")
            if (code != 200) throw LinkException("The server answered HTTP $code")
            connected()
            val reader = MjpegPartReader(BufferedInputStream(conn.inputStream, 64 * 1024))
            try {
                while (!isCancelled()) {
                    val jpeg = reader.readPart() ?: throw LinkException("The server closed the video stream")
                    onFrame(jpeg)
                }
            } catch (_: SocketTimeoutException) {
                // The server sends nothing while no input phone is streaming; just reconnect.
                if (!isCancelled()) throw LinkException("Waiting for the input phone to start sending")
            } catch (e: IOException) {
                if (!isCancelled()) throw e
            }
        } finally {
            connection = null
            conn.disconnect()
        }
    }

    override fun abort() {
        connection?.disconnect()
    }
}
