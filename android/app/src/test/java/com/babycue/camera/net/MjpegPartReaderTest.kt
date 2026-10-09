package com.babycue.camera.net

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.EOFException
import java.io.IOException

class MjpegPartReaderTest {

    private fun part(body: ByteArray, extraHeaders: String = ""): ByteArray =
        ("--${WireProtocol.BOUNDARY}\r\nContent-Type: image/jpeg\r\n${extraHeaders}Content-Length: ${body.size}\r\n\r\n")
            .toByteArray() + body + "\r\n".toByteArray()

    private fun reader(vararg chunks: ByteArray, max: Int = WireProtocol.MAX_FRAME_BYTES) =
        MjpegPartReader(ByteArrayInputStream(chunks.fold(ByteArray(0)) { acc, c -> acc + c }), max)

    @Test
    fun consecutivePartsAreReadInOrder() {
        val a = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 2, 3)
        val b = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 9)
        val r = reader(part(a), part(b))
        assertArrayEquals(a, r.readPart())
        assertArrayEquals(b, r.readPart())
        assertNull(r.readPart())
    }

    @Test
    fun payloadContainingTheBoundaryTextIsNotSplit() {
        val body = "xx--${WireProtocol.BOUNDARY}\r\nContent-Length: 1\r\n\r\nyy".toByteArray()
        assertArrayEquals(body, reader(part(body)).readPart())
    }

    @Test
    fun headerNamesAreCaseInsensitiveAndOtherHeadersIgnored() {
        val body = byteArrayOf(7, 7, 7)
        val raw = "--${WireProtocol.BOUNDARY}\r\nX-Other: 1\r\ncontent-LENGTH: 3\r\n\r\n".toByteArray() + body
        assertArrayEquals(body, reader(raw).readPart())
    }

    @Test
    fun closingBoundaryEndsTheStream() {
        assertNull(reader("--${WireProtocol.BOUNDARY}--\r\n".toByteArray()).readPart())
    }

    @Test
    fun cleanEndBetweenPartsReturnsNull() {
        assertNull(reader().readPart())
    }

    @Test
    fun truncatedPartThrowsInsteadOfReturningAPartialImage() {
        val full = part(ByteArray(100) { 1 })
        assertThrows(EOFException::class.java) { reader(full.copyOf(full.size - 40)).readPart() }
    }

    @Test
    fun missingOrBadLengthIsRejected() {
        val noLength = "--${WireProtocol.BOUNDARY}\r\nContent-Type: image/jpeg\r\n\r\nabc".toByteArray()
        assertThrows(IOException::class.java) { reader(noLength).readPart() }
        val badLength = "--${WireProtocol.BOUNDARY}\r\nContent-Length: abc\r\n\r\n".toByteArray()
        assertThrows(IOException::class.java) { reader(badLength).readPart() }
    }

    @Test
    fun oversizedPartIsRejectedBeforeAllocating() {
        assertThrows(IOException::class.java) { reader(part(ByteArray(50)), max = 10).readPart() }
    }

    @Test
    fun garbageInsteadOfABoundaryIsRejected() {
        assertThrows(IOException::class.java) { reader("<html>not a stream</html>\r\n".toByteArray()).readPart() }
    }

    @Test
    fun overlongHeaderLineIsRejected() {
        assertThrows(IOException::class.java) { reader(ByteArray(5000) { 'a'.code.toByte() }).readPart() }
    }
}
