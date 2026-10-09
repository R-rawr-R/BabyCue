package com.babycue.camera.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MjpegProtocolTest {

    private fun String.bytes() = toByteArray(Charsets.ISO_8859_1)

    @Test
    fun streamResponseHeadIsExactAndEndsWithBlankLine() {
        val text = String(MjpegProtocol.streamResponseHead(), Charsets.ISO_8859_1)
        assertEquals(
            "HTTP/1.1 200 OK\r\n" +
                "Content-Type: multipart/x-mixed-replace; boundary=babycueframe\r\n" +
                "Cache-Control: no-cache, no-store, must-revalidate\r\n" +
                "Pragma: no-cache\r\n" +
                "Connection: close\r\n\r\n",
            text,
        )
    }

    @Test
    fun partHeadIsExact() {
        assertEquals(
            "--babycueframe\r\nContent-Type: image/jpeg\r\nContent-Length: 12345\r\n\r\n",
            String(MjpegProtocol.partHead(12345), Charsets.ISO_8859_1),
        )
    }

    @Test
    fun partTailIsCrlf() {
        assertEquals("\r\n", String(MjpegProtocol.partTail, Charsets.ISO_8859_1))
    }

    @Test
    fun boundaryIsAValidTokenWithoutDashesOrSpaces() {
        assertTrue(MjpegProtocol.BOUNDARY.all { it.isLetterOrDigit() })
    }

    @Test
    fun errorResponseHasAccurateContentLength() {
        val raw = MjpegProtocol.errorResponse(405, "Method Not Allowed", listOf("Allow" to "GET"))
        val text = String(raw, Charsets.ISO_8859_1)
        val (head, body) = text.split("\r\n\r\n", limit = 2)
        assertTrue(head.startsWith("HTTP/1.1 405 Method Not Allowed\r\n"))
        assertTrue(head.contains("\r\nAllow: GET"))
        assertTrue(head.contains("\r\nConnection: close"))
        val declared = Regex("Content-Length: (\\d+)").find(head)!!.groupValues[1].toInt()
        assertEquals(declared, body.bytes().size)
    }
}
