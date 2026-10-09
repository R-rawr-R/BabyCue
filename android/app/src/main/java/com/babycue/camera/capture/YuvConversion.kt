package com.babycue.camera.capture

import java.nio.ByteBuffer

/** One plane of a YUV_420_888 image, as exposed by CameraX/`Image.Plane`. */
class YuvPlane(val buffer: ByteBuffer, val rowStride: Int, val pixelStride: Int)

/** NV21 pixel data: width*height luma bytes followed by interleaved V,U at half resolution. */
class Nv21Frame(val data: ByteArray, val width: Int, val height: Int)

/**
 * Converts YUV_420_888 planes to NV21 while applying [rotationDegrees] (clockwise, one of
 * 0/90/180/270; this is `ImageInfo.rotationDegrees`, the rotation needed to make the image upright).
 *
 * Handles arbitrary row strides and pixel strides, so it works for both planar (pixelStride 1)
 * and semi-planar (pixelStride 2, shared U/V buffer) layouts. Reads use absolute indexes and
 * never touch the buffers' position/limit. The full (uncropped) image is assumed.
 *
 * @throws IllegalArgumentException for odd/non-positive sizes, bad rotation, or buffers too small
 */
fun yuv420ToNv21(
    width: Int,
    height: Int,
    y: YuvPlane,
    u: YuvPlane,
    v: YuvPlane,
    rotationDegrees: Int,
): Nv21Frame {
    require(width > 0 && height > 0 && width % 2 == 0 && height % 2 == 0) {
        "Image size must be positive and even, was ${width}x$height"
    }
    val rot = ((rotationDegrees % 360) + 360) % 360
    require(rot % 90 == 0) { "Rotation must be a multiple of 90, was $rotationDegrees" }
    val cw = width / 2
    val ch = height / 2
    requirePlane("Y", y, width, height)
    requirePlane("U", u, cw, ch)
    requirePlane("V", v, cw, ch)

    val swap = rot == 90 || rot == 270
    val ow = if (swap) height else width
    val oh = if (swap) width else height
    val ySize = ow * oh
    val out = ByteArray(ySize + ySize / 2)

    val yb = y.buffer
    var o = 0
    for (oy in 0 until oh) {
        for (ox in 0 until ow) {
            val sx = srcX(rot, ox, oy, width)
            val sy = srcY(rot, ox, oy, height)
            out[o++] = yb.get(sy * y.rowStride + sx * y.pixelStride)
        }
    }

    val ocw = ow / 2
    val och = oh / 2
    val ub = u.buffer
    val vb = v.buffer
    o = ySize
    for (oy in 0 until och) {
        for (ox in 0 until ocw) {
            val sx = srcX(rot, ox, oy, cw)
            val sy = srcY(rot, ox, oy, ch)
            out[o++] = vb.get(sy * v.rowStride + sx * v.pixelStride)
            out[o++] = ub.get(sy * u.rowStride + sx * u.pixelStride)
        }
    }
    return Nv21Frame(out, ow, oh)
}

// Source coordinate for output pixel (ox, oy) of an image rotated clockwise by `rot`.
// w/h are the SOURCE plane dimensions.
private fun srcX(rot: Int, ox: Int, oy: Int, w: Int): Int = when (rot) {
    0 -> ox
    90 -> oy
    180 -> w - 1 - ox
    else -> w - 1 - oy
}

private fun srcY(rot: Int, ox: Int, oy: Int, h: Int): Int = when (rot) {
    0 -> oy
    90 -> h - 1 - ox
    180 -> h - 1 - oy
    else -> ox
}

private fun requirePlane(name: String, p: YuvPlane, w: Int, h: Int) {
    require(p.rowStride >= 1 && p.pixelStride >= 1) { "$name plane has invalid strides" }
    require(p.rowStride >= (w - 1) * p.pixelStride + 1) { "$name plane rowStride too small for width $w" }
    val lastIndex = (h - 1).toLong() * p.rowStride + (w - 1).toLong() * p.pixelStride
    require(lastIndex < p.buffer.limit()) { "$name plane buffer too small (needs ${lastIndex + 1}, has ${p.buffer.limit()})" }
}
