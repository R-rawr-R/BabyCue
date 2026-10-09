package com.babycue.camera.capture

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test
import java.nio.ByteBuffer

class YuvConversionTest {

    private class Img(val w: Int, val h: Int) {
        val y = Array(h) { r -> IntArray(w) { c -> (r * w + c) and 0x7F } }
        val u = Array(h / 2) { r -> IntArray(w / 2) { c -> 100 + r * (w / 2) + c } }
        val v = Array(h / 2) { r -> IntArray(w / 2) { c -> 200 + r * (w / 2) + c } }
    }

    // Independent reference: clockwise rotation of a matrix.
    private fun rotCw(m: Array<IntArray>, times: Int): Array<IntArray> {
        var cur = m
        repeat(times) {
            val h = cur.size
            val w = cur[0].size
            cur = Array(w) { r -> IntArray(h) { c -> cur[h - 1 - c][r] } }
        }
        return cur
    }

    private fun expectedNv21(img: Img, rotation: Int): ByteArray {
        val t = (rotation / 90) and 3
        val y = rotCw(img.y, t)
        val u = rotCw(img.u, t)
        val v = rotCw(img.v, t)
        val out = ArrayList<Byte>()
        y.forEach { row -> row.forEach { out.add(it.toByte()) } }
        for (r in u.indices) for (c in u[0].indices) {
            out.add(v[r][c].toByte())
            out.add(u[r][c].toByte())
        }
        return out.toByteArray()
    }

    /** Tight planar layout: pixelStride 1, rowStride == width. */
    private fun planar(img: Img): Triple<YuvPlane, YuvPlane, YuvPlane> {
        fun plane(m: Array<IntArray>): YuvPlane {
            val w = m[0].size
            val b = ByteBuffer.allocate(w * m.size)
            m.forEach { row -> row.forEach { b.put(it.toByte()) } }
            return YuvPlane(b, w, 1)
        }
        return Triple(plane(img.y), plane(img.u), plane(img.v))
    }

    /**
     * Android-style padded layout: luma rowStride = width + 5 (padding bytes are 0x55 garbage);
     * chroma is semi-planar with pixelStride 2 and rowStride = width + 6, V at offset 0 and U at
     * offset 1 of one shared buffer, with garbage in the unused interleave slots.
     */
    private fun padded(img: Img): Triple<YuvPlane, YuvPlane, YuvPlane> {
        val w = img.w
        val h = img.h
        val yStride = w + 5
        val yBuf = ByteBuffer.allocate(yStride * h)
        for (i in 0 until yBuf.capacity()) yBuf.put(i, 0x55)
        for (r in 0 until h) for (c in 0 until w) yBuf.put(r * yStride + c, img.y[r][c].toByte())

        val cStride = w + 6
        val cBuf = ByteBuffer.allocate(cStride * (h / 2))
        for (i in 0 until cBuf.capacity()) cBuf.put(i, 0x55)
        for (r in 0 until h / 2) for (c in 0 until w / 2) {
            cBuf.put(r * cStride + c * 2, img.v[r][c].toByte())
            cBuf.put(r * cStride + c * 2 + 1, img.u[r][c].toByte())
        }
        // V plane starts at offset 0, U plane at offset 1 of the same memory (as Camera2 delivers it).
        val vBuf = cBuf.duplicate()
        val uBuf = cBuf.duplicate().apply { position(1) }.slice()
        return Triple(YuvPlane(yBuf, yStride, 1), YuvPlane(uBuf, cStride, 2), YuvPlane(vBuf, cStride, 2))
    }

    @Test
    fun knownRotation90OfFourByTwo() {
        // Y rows: [0 1 2 3] / [4 5 6 7]; rotated clockwise -> 2 wide, 4 tall:
        // [4 0] / [5 1] / [6 2] / [7 3]
        val img = Img(4, 2)
        val (y, u, v) = planar(img)
        val out = yuv420ToNv21(4, 2, y, u, v, 90)
        assertEquals(2, out.width)
        assertEquals(4, out.height)
        assertArrayEquals(byteArrayOf(4, 0, 5, 1, 6, 2, 7, 3), out.data.copyOfRange(0, 8))
    }

    @Test
    fun allRotationsMatchReferenceForPlanarInput() {
        for (rot in intArrayOf(0, 90, 180, 270)) {
            val img = Img(8, 6)
            val (y, u, v) = planar(img)
            val out = yuv420ToNv21(8, 6, y, u, v, rot)
            assertArrayEquals("rotation $rot", expectedNv21(img, rot), out.data)
            val swapped = rot == 90 || rot == 270
            assertEquals(if (swapped) 6 else 8, out.width)
            assertEquals(if (swapped) 8 else 6, out.height)
        }
    }

    @Test
    fun rowAndPixelStridesArePaddedCorrectly() {
        for (rot in intArrayOf(0, 90, 180, 270)) {
            val img = Img(8, 6)
            val (y, u, v) = padded(img)
            val out = yuv420ToNv21(8, 6, y, u, v, rot)
            assertArrayEquals("padded rotation $rot", expectedNv21(img, rot), out.data)
        }
    }

    @Test
    fun readingDoesNotDisturbBufferPositions() {
        val img = Img(4, 4)
        val (y, u, v) = planar(img)
        yuv420ToNv21(4, 4, y, u, v, 0)
        assertEquals(y.buffer.capacity(), y.buffer.position()) // untouched since allocation+put
    }

    @Test
    fun negativeAndWrappedRotationsNormalise() {
        val img = Img(4, 2)
        val (y, u, v) = planar(img)
        assertArrayEquals(expectedNv21(img, 270), yuv420ToNv21(4, 2, y, u, v, -90).data)
        assertArrayEquals(expectedNv21(img, 90), yuv420ToNv21(4, 2, y, u, v, 450).data)
    }

    @Test
    fun rejectsInvalidInput() {
        val img = Img(4, 2)
        val (y, u, v) = planar(img)
        expectIllegalArgument { yuv420ToNv21(3, 2, y, u, v, 0) }          // odd width
        expectIllegalArgument { yuv420ToNv21(4, 2, y, u, v, 45) }         // bad rotation
        expectIllegalArgument { yuv420ToNv21(4, 4, y, u, v, 0) }          // buffers too small for height 4
        expectIllegalArgument { yuv420ToNv21(4, 2, YuvPlane(y.buffer, 2, 1), u, v, 0) } // rowStride < width
    }

    private fun expectIllegalArgument(block: () -> Unit) {
        try {
            block()
        } catch (_: IllegalArgumentException) {
            return
        }
        fail("expected IllegalArgumentException")
    }
}
