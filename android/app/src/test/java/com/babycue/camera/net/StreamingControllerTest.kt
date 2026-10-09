package com.babycue.camera.net

import org.junit.Assert.assertEquals
import org.junit.Test

class StreamingControllerTest {

    private class Fake {
        val log = ArrayList<String>()
        val controller = StreamingController(
            startCamera = { log += "camera+" }, stopCamera = { log += "camera-" },
            startLink = { log += "link+" }, stopLink = { log += "link-" },
            clearFrames = { log += "clear" }, releaseCamera = { log += "release" },
        )
    }

    @Test
    fun startConnectsBeforeCameraAndStopLeavesTheServerFirst() {
        val f = Fake()
        f.controller.setStreaming(true)
        assertEquals(listOf("link+", "camera+"), f.log)
        f.log.clear()
        f.controller.setStreaming(false)
        assertEquals(listOf("link-", "camera-", "clear"), f.log)
    }

    @Test
    fun backgroundingStopsTheLinkButLeavesCameraToItsLifecycle() {
        val f = Fake()
        f.controller.setStreaming(true)
        f.log.clear()
        f.controller.onBackgrounded()
        assertEquals(listOf("link-", "clear"), f.log)
        f.log.clear()
        f.controller.setStreaming(true) // back in the foreground
        assertEquals(listOf("link+", "camera+"), f.log)
    }

    @Test
    fun shutdownStopsEverythingAndReleasesCamera() {
        val f = Fake()
        f.controller.setStreaming(true)
        f.log.clear()
        f.controller.shutdown()
        assertEquals(listOf("link-", "camera-", "clear", "release"), f.log)
    }

    @Test
    fun repeatedCallsAreForwardedSoCallbacksMustBeIdempotent() {
        val f = Fake()
        f.controller.setStreaming(true)
        f.controller.setStreaming(true)
        assertEquals(listOf("link+", "camera+", "link+", "camera+"), f.log)
    }
}
