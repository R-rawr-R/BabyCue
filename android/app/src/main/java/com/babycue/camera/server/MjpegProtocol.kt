package com.babycue.camera.server

/**
 * Byte-level formatting of the HTTP/MJPEG response. Layout (every line ends in CRLF):
 *
 * ```
 * HTTP/1.1 200 OK
 * Content-Type: multipart/x-mixed-replace; boundary=babycueframe
 * ...
 *
 * --babycueframe
 * Content-Type: image/jpeg
 * Content-Length: <n>
 *
 * <n JPEG bytes>
 * --babycueframe
 * ...
 * ```
 * The delimiter line precedes every part; the CRLF after the JPEG bytes belongs to the next delimiter.
 */
object MjpegProtocol {
    const val BOUNDARY = "babycueframe"
    const val STREAM_PATH = "/video"
    const val DEFAULT_PORT = 8080

    private const val CRLF = "\r\n"

    fun streamResponseHead(): ByteArray = (
        "HTTP/1.1 200 OK$CRLF" +
            "Content-Type: multipart/x-mixed-replace; boundary=$BOUNDARY$CRLF" +
            "Cache-Control: no-cache, no-store, must-revalidate$CRLF" +
            "Pragma: no-cache$CRLF" +
            "Connection: close$CRLF" +
            CRLF
        ).toByteArray(Charsets.ISO_8859_1)

    /** Delimiter + part headers for a JPEG of [jpegLength] bytes. */
    fun partHead(jpegLength: Int): ByteArray = (
        "--$BOUNDARY$CRLF" +
            "Content-Type: image/jpeg$CRLF" +
            "Content-Length: $jpegLength$CRLF" +
            CRLF
        ).toByteArray(Charsets.ISO_8859_1)

    val partTail: ByteArray = CRLF.toByteArray(Charsets.ISO_8859_1)

    /** A complete short plain-text error response (Connection: close). */
    fun errorResponse(status: Int, reason: String, extraHeaders: List<Pair<String, String>> = emptyList()): ByteArray {
        val body = "$status $reason$CRLF".toByteArray(Charsets.ISO_8859_1)
        val sb = StringBuilder("HTTP/1.1 $status $reason$CRLF")
        sb.append("Content-Type: text/plain; charset=iso-8859-1$CRLF")
        sb.append("Content-Length: ${body.size}$CRLF")
        for ((k, v) in extraHeaders) sb.append("$k: $v$CRLF")
        sb.append("Connection: close$CRLF$CRLF")
        return sb.toString().toByteArray(Charsets.ISO_8859_1) + body
    }
}
