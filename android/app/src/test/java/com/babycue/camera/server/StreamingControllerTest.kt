package com.babycue.camera.server

import com.babycue.camera.capture.LatestFrameStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class StreamingControllerTest {

    private class Fake {
        val log = ArrayList<String>()
        val controller = StreamingController(
            startCamera = { log += "camera+" }, stopCamera = { log += "camera-" },
            startServer = { log += "server+" }, stopServer = { log += "server-" },
            clearFrames = { log += "clear" }, releaseCamera = { log += "release" },
        )
    }

    @Test
    fun startListensBeforeCameraAndStopTearsDownServerFirst() {
        val f = Fake()
        f.controller.setStreaming(true)
        assertEquals(listOf("server+", "camera+"), f.log)
        f.log.clear()
        f.controller.setStreaming(false)
        assertEquals(listOf("server-", "camera-", "clear"), f.log)
    }

    @Test
    fun backgroundingStopsServerButLeavesCameraToItsLifecycle() {
        val f = Fake()
        f.controller.setStreaming(true)
        f.log.clear()
        f.controller.onBackgrounded()
        assertEquals(listOf("server-", "clear"), f.log)
        f.log.clear()
        f.controller.setStreaming(true) // back in the foreground
        assertEquals(listOf("server+", "camera+"), f.log)
    }

    @Test
    fun shutdownStopsEverythingAndReleasesCamera() {
        val f = Fake()
        f.controller.setStreaming(true)
        f.log.clear()
        f.controller.shutdown()
        assertEquals(listOf("server-", "camera-", "clear", "release"), f.log)
    }

    // --- with the real MjpegServer ---------------------------------------------------------

    private fun running(server: MjpegServer, latch: CountDownLatch) {
        assertTrue("server not running: ${server.state}", latch.await(5, TimeUnit.SECONDS))
    }

    @Test
    fun repeatedStartStopCyclesWithRealServerLeaveNothingBound() {
        val store = LatestFrameStore()
        var cameraRunning = false
        var latch = CountDownLatch(1)
        lateinit var server: MjpegServer
        server = MjpegServer(store, 0) { if (it is ServerState.Running) latch.countDown() }
        val c = StreamingController(
            startCamera = { cameraRunning = true }, stopCamera = { cameraRunning = false },
            startServer = server::start, stopServer = server::stop,
            clearFrames = store::clear, releaseCamera = { cameraRunning = false },
        )
        repeat(10) { i ->
            latch = CountDownLatch(1)
            c.setStreaming(true)
            c.setStreaming(true) // redundant render() calls must be harmless
            running(server, latch)
            val port = (server.state as ServerState.Running).port
            assertTrue(cameraRunning)

            store.publish(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 0xD9.toByte()), 2, 2, 0)
            Socket(InetAddress.getLoopbackAddress(), port).use { s ->
                s.soTimeout = 3000
                s.getOutputStream().write("GET /video HTTP/1.1\r\n\r\n".toByteArray())
                assertTrue(s.getInputStream().read() == 'H'.code)
            }
            if (i % 2 == 0) c.onBackgrounded() else c.setStreaming(false)
            assertEquals(ServerState.Stopped, server.state)
            assertNull("stale frame survived stop", store.latest())
            ServerSocket(port).close() // port is free again
            c.setStreaming(false)
        }
        c.shutdown()
        assertTrue(!cameraRunning)
        assertNotNull(server)
    }
}
