package com.babycue.camera.server

import java.io.IOException
import java.io.InputStream
import java.net.SocketTimeoutException

class HttpRequest(
    val method: String,
    /** Request path with any query string removed. Always starts with '/'. */
    val path: String,
    val version: String,
    /** Header names lower-cased. */
    val headers: Map<String, String>,
)

sealed interface ParseResult {
    class Ok(val request: HttpRequest) : ParseResult

    /** The request was unusable; reply with [status] and close. */
    class Rejected(val status: Int, val reason: String) : ParseResult

    /** The peer closed the connection before sending a complete request; reply with nothing. */
    data object Closed : ParseResult
}

/** Minimal, strict HTTP/1.x request-head parser. The body (if any) is never read. */
object HttpRequestParser {
    const val MAX_HEAD_BYTES = 8 * 1024
    private const val MAX_HEADERS = 64

    /** Reads one request head. A read timeout (socket SO_TIMEOUT) yields 408. */
    fun read(input: InputStream): ParseResult {
        val head = ByteArray(MAX_HEAD_BYTES)
        var n = 0
        try {
            while (true) {
                val b = input.read()
                if (b < 0) return ParseResult.Closed
                if (n == head.size) return ParseResult.Rejected(431, "Request Header Fields Too Large")
                head[n++] = b.toByte()
                if (n >= 4 && head[n - 4] == CR && head[n - 3] == LF && head[n - 2] == CR && head[n - 1] == LF) break
            }
        } catch (_: SocketTimeoutException) {
            return ParseResult.Rejected(408, "Request Timeout")
        } catch (_: IOException) {
            return ParseResult.Closed
        }
        return parse(String(head, 0, n - 4, Charsets.ISO_8859_1))
    }

    /** Parses a head with the terminating blank line already removed. Visible for tests. */
    fun parse(head: String): ParseResult {
        val lines = head.split("\r\n")
        val parts = lines[0].split(' ')
        if (parts.size != 3 || parts.any { it.isEmpty() }) return bad()
        val (method, target, version) = parts
        if (!version.startsWith("HTTP/1.")) return bad()
        if (!method.all { it in 'A'..'Z' }) return bad()
        if (!target.startsWith("/")) return bad()
        if (lines.size - 1 > MAX_HEADERS) return ParseResult.Rejected(431, "Request Header Fields Too Large")
        val headers = HashMap<String, String>()
        for (line in lines.drop(1)) {
            val colon = line.indexOf(':')
            if (colon <= 0 || line[0] == ' ' || line[0] == '\t') return bad()
            headers[line.substring(0, colon).trim().lowercase()] = line.substring(colon + 1).trim()
        }
        val path = target.substringBefore('?').substringBefore('#')
        return ParseResult.Ok(HttpRequest(method, path, version, headers))
    }

    private fun bad() = ParseResult.Rejected(400, "Bad Request")

    private const val CR = '\r'.code.toByte()
    private const val LF = '\n'.code.toByte()
}
