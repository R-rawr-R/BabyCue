package com.babycue.camera.net

/**
 * Keeps the camera and the server link in step, independent of Android so the ordering and
 * idempotence can be unit-tested. All callbacks must themselves be idempotent (CameraCapture,
 * FramePusher and FrameReceiver are). In output mode the camera callbacks are no-ops. Call from
 * the main thread.
 */
class StreamingController(
    private val startCamera: () -> Unit,
    private val stopCamera: () -> Unit,
    private val startLink: () -> Unit,
    private val stopLink: () -> Unit,
    /** Drops the held JPEG so a stale picture is never sent or shown. */
    private val clearFrames: () -> Unit,
    private val releaseCamera: () -> Unit,
) {
    /** Bring both parts to the wanted state. Safe to call repeatedly. */
    fun setStreaming(on: Boolean) {
        if (on) {
            startLink()     // connect first so the server connection is up while the camera warms up
            startCamera()
        } else {
            stopLink()      // leave the server before the source goes away
            stopCamera()
            clearFrames()
        }
    }

    /**
     * The app left the foreground. CameraX stops delivering frames on its own then, so also stop
     * the link: the input must not claim to stream while nothing is captured, and the output must
     * not keep decoding unseen video. [setStreaming]`(true)` on return restarts it.
     */
    fun onBackgrounded() {
        stopLink()
        clearFrames()
    }

    /** Final teardown (activity destroyed). */
    fun shutdown() {
        setStreaming(false)
        releaseCamera()
    }
}
