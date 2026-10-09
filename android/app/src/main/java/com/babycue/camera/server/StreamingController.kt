package com.babycue.camera.server

/**
 * Keeps camera capture and the HTTP server in step, independent of Android so the ordering and
 * idempotence can be unit-tested. All callbacks must themselves be idempotent (CameraCapture and
 * MjpegServer are). Call from the main thread.
 */
class StreamingController(
    private val startCamera: () -> Unit,
    private val stopCamera: () -> Unit,
    private val startServer: () -> Unit,
    private val stopServer: () -> Unit,
    /** Drops the held JPEG so a stale picture is never served. */
    private val clearFrames: () -> Unit,
    private val releaseCamera: () -> Unit,
) {
    /** Bring both parts to the wanted state. Safe to call repeatedly. */
    fun setStreaming(on: Boolean) {
        if (on) {
            startServer()   // listen first so a client can connect while the camera warms up
            startCamera()
        } else {
            stopServer()    // disconnect clients before the source goes away
            stopCamera()
            clearFrames()
        }
    }

    /**
     * The app left the foreground. CameraX stops delivering frames on its own then, so also stop
     * serving: the server must not claim to stream while nothing is captured. [setStreaming]`(true)`
     * on return restarts it.
     */
    fun onBackgrounded() {
        stopServer()
        clearFrames()
    }

    /** Final teardown (activity destroyed). */
    fun shutdown() {
        setStreaming(false)
        releaseCamera()
    }
}
