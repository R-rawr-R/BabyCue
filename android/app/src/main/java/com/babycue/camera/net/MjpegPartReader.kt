package com.babycue.camera.net

import java.io.EOFException
import java.io.IOException
import java.io.InputStream

/**
 * Reads the JPEGs out of the server's `multipart/x-mixed-replace` `/view` response, strictly by each
 * part's `Content-Length` (the server always sends one), so no byte pattern in the image data can
 * be mistaken for a boundary.
 */
class MjpegPartReader(
    private val input: InputStream,
    private val maxPartBytes: Int = WireProtocol.MAX_FRAME_BYTES,
) {
    /** The next JPEG, or null when the stream ended cleanly between parts. Throws [IOException] if malformed. */
    fun readPart(): ByteArray? {
        var line = readLine() ?: return null
        while (line.isEmpty()) line = readLine() ?: return null // the CRLF that ends the previous part
        if (line == "--${WireProtocol.BOUNDARY}--") return null
        if (!line.startsWith("--")) throw IOException("Expected a multipart boundary but got \"${line.take(40)}\"")

        var length = -1
        while (true) {
            val header = readLine() ?: throw EOFException("Stream ended inside part headers")
            if (header.isEmpty()) break
            if (header.startsWith("content-length:", ignoreCase = true)) {
                length = header.substring("content-length:".length).trim().toIntOrNull()
                    ?: throw IOException("Bad Content-Length \"${header.take(40)}\"")
            }
        }
        if (length <= 0 || length > maxPartBytes) throw IOException("Bad part length $length")

        val data = ByteArray(length)
        var got = 0
        while (got < length) {
            val n = input.read(data, got, length - got)
            if (n < 0) throw EOFException("Stream ended inside a part ($got of $length bytes)")
            got += n
        }
        return data
    }

    private fun readLine(): String? {
        val line = StringBuilder()
        while (true) {
            val b = input.read()
            if (b < 0) {
                if (line.isEmpty()) return null
                throw EOFException("Stream ended inside a header line")
            }
            if (b == '\n'.code) return line.toString().trimEnd('\r')
            if (line.length >= MAX_LINE) throw IOException("Header line too long")
            line.append(b.toChar())
        }
    }

    private companion object {
        const val MAX_LINE = 1024
    }
}
