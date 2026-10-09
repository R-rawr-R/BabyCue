package com.babycue.camera.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.InputStream

class HttpRequestParserTest {

    private fun read(text: String) = HttpRequestParser.read(ByteArrayInputStream(text.toByteArray(Charsets.ISO_8859_1)))

    private fun ok(r: ParseResult): HttpRequest = (r as? ParseResult.Ok)?.request ?: throw AssertionError("expected Ok but was $r")

    private fun rejected(r: ParseResult, status: Int) {
        val rej = r as? ParseResult.Rejected ?: throw AssertionError("expected Rejected but was $r")
        assertEquals(status, rej.status)
    }

    @Test
    fun parsesSimpleGet() {
        val req = ok(read("GET /video HTTP/1.1\r\nHost: 192.168.1.10:8080\r\nUser-Agent: BabyCue-Camera/1\r\n\r\n"))
        assertEquals("GET", req.method)
        assertEquals("/video", req.path)
        assertEquals("HTTP/1.1", req.version)
        assertEquals("192.168.1.10:8080", req.headers["host"])
        assertEquals("BabyCue-Camera/1", req.headers["user-agent"])
    }

    @Test
    fun stripsQueryAndFragment() {
        assertEquals("/video", ok(read("GET /video?x=1&y=2 HTTP/1.1\r\n\r\n")).path)
        assertEquals("/video", ok(read("GET /video#a HTTP/1.0\r\n\r\n")).path)
    }

    @Test
    fun acceptsRequestWithNoHeaders() {
        assertEquals("/", ok(read("GET / HTTP/1.0\r\n\r\n")).path)
    }

    @Test
    fun rejectsMalformedRequestLines() {
        rejected(read("garbage\r\n\r\n"), 400)
        rejected(read("GET /video\r\n\r\n"), 400)             // no version
        rejected(read("GET  /video HTTP/1.1\r\n\r\n"), 400)   // double space
        rejected(read("GET /video SPDY/3\r\n\r\n"), 400)
        rejected(read("get /video HTTP/1.1\r\n\r\n"), 400)    // methods are upper-case
        rejected(read("GET http://x/video HTTP/1.1\r\n\r\n"), 400) // absolute-form unsupported
    }

    @Test
    fun rejectsMalformedHeaders() {
        rejected(read("GET /video HTTP/1.1\r\nno-colon\r\n\r\n"), 400)
        rejected(read("GET /video HTTP/1.1\r\n : x\r\n\r\n"), 400)
    }

    @Test
    fun rejectsOversizedHead() {
        val big = "GET /video HTTP/1.1\r\nX: " + "a".repeat(HttpRequestParser.MAX_HEAD_BYTES) + "\r\n\r\n"
        rejected(read(big), 431)
    }

    @Test
    fun rejectsTooManyHeaders() {
        val many = (1..80).joinToString("") { "H$it: v\r\n" }
        rejected(read("GET /video HTTP/1.1\r\n$many\r\n"), 431)
    }

    @Test
    fun incompleteOrEmptyInputIsClosed() {
        assertTrue(read("") === ParseResult.Closed)
        assertTrue(read("GET /video HTTP/1.1\r\nHost: x") === ParseResult.Closed)
    }

    @Test
    fun readTimeoutIsRequestTimeout() {
        val stalled = object : InputStream() {
            override fun read(): Int = throw java.net.SocketTimeoutException("timeout")
        }
        rejected(HttpRequestParser.read(stalled), 408)
    }

    @Test
    fun doesNotReadPastTheBlankLine() {
        val input = ByteArrayInputStream("GET /video HTTP/1.1\r\n\r\nEXTRA".toByteArray())
        ok(HttpRequestParser.read(input))
        assertEquals(5, input.available())
    }

    @Test
    fun parseDoesNotThrowOnArbitraryText() {
        for (t in listOf("", "\r\n", " ", "GET", "G E T", "\u0000\u0001", "GET / HTTP/1.1\r\n\r\n\r\n")) {
            try {
                HttpRequestParser.parse(t)
            } catch (e: Exception) {
                fail("parse threw for '$t': $e")
            }
        }
    }
}
