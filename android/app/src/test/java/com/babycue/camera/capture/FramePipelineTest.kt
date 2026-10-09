package com.babycue.camera.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.nio.ByteBuffer

class FramePipelineTest {

    private fun planes(w: Int, h: Int) = Triple(
        YuvPlane(ByteBuffer.allocate(w * h), w, 1),
        YuvPlane(ByteBuffer.allocate(w * h / 4), w / 2, 1),
        YuvPlane(ByteBuffer.allocate(w * h / 4), w / 2, 1),
    )

    private class FakeEncoder(val result: ByteArray = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 2, 0xFF.toByte(), 0xD9.toByte())) : JpegEncoder {
        var seen: IntArray? = null
        var nv21Size = -1
        override fun encode(nv21: ByteArray, width: Int, height: Int, quality: Int): ByteArray {
            seen = intArrayOf(width, height, quality)
            nv21Size = nv21.size
            return result
        }
    }

    @Test
    fun publishesJpegWithRotatedDimensions() {
        val enc = FakeEncoder()
        val store = LatestFrameStore()
        val (y, u, v) = planes(8, 4)
        val frame = FramePipeline(enc, store, jpegQuality = 70).process(8, 4, y, u, v, 90, 123L)
        assertEquals(4, frame.width)
        assertEquals(8, frame.height)
        assertEquals(123L, frame.timestampNanos)
        assertEquals(listOf(4, 8, 70), enc.seen!!.toList())
        assertEquals(4 * 8 * 3 / 2, enc.nv21Size)
        assertEquals(frame.sequence, store.latest()!!.sequence)
    }

    @Test
    fun nonJpegEncoderOutputIsRejectedAndNotPublished() {
        val store = LatestFrameStore()
        val (y, u, v) = planes(4, 4)
        try {
            FramePipeline(FakeEncoder(byteArrayOf(1, 2, 3, 4, 5)), store).process(4, 4, y, u, v, 0, 0)
            fail("expected IllegalStateException")
        } catch (_: IllegalStateException) {
        }
        assertNull(store.latest())
    }

    @Test
    fun badInputDoesNotPublish() {
        val store = LatestFrameStore()
        val (y, u, v) = planes(4, 4)
        try {
            FramePipeline(FakeEncoder(), store).process(4, 4, y, u, v, 30, 0)
            fail("expected IllegalArgumentException")
        } catch (_: IllegalArgumentException) {
        }
        assertNull(store.latest())
        assertTrue(store.lastSequence == 0L)
    }

    @Test
    fun rejectsOutOfRangeQuality() {
        try {
            FramePipeline(FakeEncoder(), LatestFrameStore(), jpegQuality = 0)
            fail("expected IllegalArgumentException")
        } catch (_: IllegalArgumentException) {
        }
    }
}
