package com.babycue.camera.capture

/** Turns NV21 pixels into a JPEG. The Android implementation uses `YuvImage`; tests use a fake. */
fun interface JpegEncoder {
    fun encode(nv21: ByteArray, width: Int, height: Int, quality: Int): ByteArray
}

/**
 * YUV planes -> rotated NV21 -> JPEG -> [LatestFrameStore]. Android-free so it is JVM-testable.
 * Call from a single analysis thread; each call allocates its own buffers, so published frames
 * are never mutated afterwards.
 */
class FramePipeline(
    private val encoder: JpegEncoder,
    private val store: LatestFrameStore,
    private val jpegQuality: Int = DEFAULT_JPEG_QUALITY,
) {
    init {
        require(jpegQuality in 1..100) { "JPEG quality must be 1..100" }
    }

    /** @return the published frame */
    fun process(
        width: Int,
        height: Int,
        y: YuvPlane,
        u: YuvPlane,
        v: YuvPlane,
        rotationDegrees: Int,
        timestampNanos: Long,
    ): JpegFrame {
        val nv21 = yuv420ToNv21(width, height, y, u, v, rotationDegrees)
        val jpeg = encoder.encode(nv21.data, nv21.width, nv21.height, jpegQuality)
        check(jpeg.size >= 4 && jpeg[0] == 0xFF.toByte() && jpeg[1] == 0xD8.toByte()) {
            "Encoder did not return a JPEG"
        }
        return store.publish(jpeg, nv21.width, nv21.height, timestampNanos)
    }

    companion object {
        const val DEFAULT_JPEG_QUALITY = 50
    }
}
