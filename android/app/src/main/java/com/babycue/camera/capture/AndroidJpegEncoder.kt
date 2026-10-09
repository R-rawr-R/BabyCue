package com.babycue.camera.capture

import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import java.io.ByteArrayOutputStream

/** [JpegEncoder] backed by the platform JPEG encoder. */
class AndroidJpegEncoder : JpegEncoder {
    override fun encode(nv21: ByteArray, width: Int, height: Int, quality: Int): ByteArray {
        val out = ByteArrayOutputStream(nv21.size / 8)
        val ok = YuvImage(nv21, ImageFormat.NV21, width, height, null)
            .compressToJpeg(Rect(0, 0, width, height), quality, out)
        check(ok) { "YuvImage.compressToJpeg failed" }
        return out.toByteArray()
    }
}
