package com.babycue.camera.server

import com.babycue.camera.capture.LatestFrameStore
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.CopyOnWriteArrayList

/** Real-socket tests on 127.0.0.1 with an ephemeral port. */
class MjpegServerTest {

    private fun jpeg(tag: Int, size: Int = 50): ByteArray {
        val b = ByteArray(size) { (tag + it).toByte() }
        b[0] = 0xFF.toByte(); b[1] = 0xD8.toByte()
        b[size - 2] = 0xFF.toByte(); b[size - 1] = 0xD9.toByte()
        return b
    }

    private class Running(val server: MjpegServer, val port: Int, val states: List<ServerState>)

    private fun startServer(store: LatestFrameStore, maxClients: Int = 4, port: Int = 0): Running {
        val states = CopyOnWriteArrayList<ServerState>()
        val settled = CountDownLatch(1)
        val server = MjpegServer(store, port, maxClients) {
            states.add(it)
            if (it is ServerState.Running || it is ServerState.Failed) settled.countDown()
        }
        server.start()
        assertTrue("server did not settle", settled.await(5, TimeUnit.SECONDS))
        val s = server.state
        return Running(server, (s as? ServerState.Running)?.port ?: 0, states)
    }

    private fun connect(port: Int, request: String = "GET /video HTTP/1.1\r\nHost: x\r\n\r\n"): Socket =
        Socket(InetAddress.getLoopbackAddress(), port).apply {
            soTimeout = 3000
            getOutputStream().apply { write(request.toByteArray()); flush() }
        }

    private fun InputStream.readLine(): String? {
        val sb = StringBuilder()
        while (true) {
            val c = read()
            if (c < 0) return if (sb.isEmpty()) null else sb.toString()
            if (c == '\n'.code) return sb.toString().trimEnd('\r')
            sb.append(c.toChar())
        }
    }

    private fun InputStream.readHead(): List<String> {
        val lines = ArrayList<String>()
        while (true) {
            val l = readLine() ?: return lines
            if (l.isEmpty()) return lines
            lines.add(l)
        }
    }

    private fun InputStream.readFully(n: Int): ByteArray {
        val out = ByteArray(n)
        var off = 0
        while (off < n) {
            val r = read(out, off, n - off)
            if (r < 0) throw AssertionError("EOF after $off of $n bytes")
            off += r
        }
        return out
    }

    /** Strict reader of one multipart part; fails on any framing deviation. */
    private fun InputStream.readPart(): ByteArray {
        assertEquals("--babycueframe", readLine())
        val headers = readHead()
        assertEquals("Content-Type: image/jpeg", headers[0])
        val len = headers[1].removePrefix("Content-Length: ").toInt()
        assertEquals(2, headers.size)
        return readFully(len)
    }

    private fun waitUntil(timeoutMs: Long = 3000, cond: () -> Boolean): Boolean {
        val end = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < end) {
            if (cond()) return true
            Thread.sleep(10)
        }
        return cond()
    }

    @Test
    fun startReportsRunningWithBoundPort() {
        val r = startServer(LatestFrameStore())
        try {
            assertTrue(r.port > 0)
            assertEquals(ServerState.Starting, r.states.first())
            assertEquals(ServerState.Running(r.port), r.server.state)
        } finally {
            r.server.stop()
        }
        assertEquals(ServerState.Stopped, r.server.state)
    }

    @Test
    fun streamsValidMultipartFramesWithExactBytes() {
        val store = LatestFrameStore()
        val r = startServer(store)
        try {
            val sock = connect(r.port)
            val input = sock.getInputStream()
            val head = input.readHead()
            assertEquals("HTTP/1.1 200 OK", head[0])
            assertTrue(head.contains("Content-Type: multipart/x-mixed-replace; boundary=babycueframe"))

            val a = jpeg(1, 80)
            store.publish(a, 2, 2, 1)
            val gotA = input.readPart()
            assertArrayEquals(a, gotA)
            assertEquals("", input.readLine()) // the CRLF after the JPEG bytes

            val b = jpeg(9, 5000)
            store.publish(b, 2, 2, 2)
            assertArrayEquals(b, input.readPart())
            sock.close()
        } finally {
            r.server.stop()
        }
    }

    @Test
    fun lateClientGetsOnlyTheNewestFrame() {
        val store = LatestFrameStore()
        store.publish(jpeg(1), 2, 2, 1)
        store.publish(jpeg(2), 2, 2, 2)
        val newest = jpeg(3, 64)
        store.publish(newest, 2, 2, 3)
        val r = startServer(store)
        try {
            val sock = connect(r.port)
            val input = sock.getInputStream()
            input.readHead()
            assertArrayEquals(newest, input.readPart())
            sock.close()
        } finally {
            r.server.stop()
        }
    }

    @Test
    fun noFrameMeansHeadersOnlyAndNoBusyBytes() {
        val r = startServer(LatestFrameStore())
        try {
            val sock = connect(r.port)
            sock.soTimeout = 400
            val input = sock.getInputStream()
            assertEquals("HTTP/1.1 200 OK", input.readHead()[0])
            try {
                val b = input.read()
                fail("unexpected data byte $b without any frame")
            } catch (_: SocketTimeoutException) {
            }
            sock.close()
        } finally {
            r.server.stop()
        }
    }

    @Test
    fun unchangedFrameIsNotResent() {
        val store = LatestFrameStore()
        val r = startServer(store)
        try {
            val sock = connect(r.port)
            val input = sock.getInputStream()
            input.readHead()
            store.publish(jpeg(1), 2, 2, 1)
            input.readPart()
            input.readLine()
            sock.soTimeout = 1300 // longer than the server's 1 s idle wait
            try {
                input.read()
                fail("frame was resent")
            } catch (_: SocketTimeoutException) {
            }
            sock.close()
        } finally {
            r.server.stop()
        }
    }

    private fun statusLine(port: Int, request: String): Pair<String, List<String>> {
        val sock = connect(port, request)
        val input = sock.getInputStream()
        val head = input.readHead()
        sock.close()
        return head[0] to head
    }

    @Test
    fun invalidRequestsGetProperHttpErrors() {
        val r = startServer(LatestFrameStore())
        try {
            assertEquals("HTTP/1.1 404 Not Found", statusLine(r.port, "GET /nope HTTP/1.1\r\n\r\n").first)
            assertEquals("HTTP/1.1 404 Not Found", statusLine(r.port, "GET / HTTP/1.1\r\n\r\n").first)
            val post = statusLine(r.port, "POST /video HTTP/1.1\r\nContent-Length: 0\r\n\r\n")
            assertEquals("HTTP/1.1 405 Method Not Allowed", post.first)
            assertTrue(post.second.contains("Allow: GET"))
            assertEquals("HTTP/1.1 400 Bad Request", statusLine(r.port, "nonsense\r\n\r\n").first)
            // Query strings do not change routing.
            assertEquals("HTTP/1.1 200 OK", statusLine(r.port, "GET /video?cache=1 HTTP/1.1\r\n\r\n").first)
        } finally {
            r.server.stop()
        }
    }

    @Test
    fun clientThatNeverFinishesItsRequestIsDroppedWithoutBlockingOthers() {
        val store = LatestFrameStore()
        val r = startServer(store)
        try {
            val slow = Socket(InetAddress.getLoopbackAddress(), r.port)
            slow.getOutputStream().apply { write("GET /vid".toByteArray()); flush() }
            // A second client is served immediately although the first is stalled.
            val ok = connect(r.port)
            assertEquals("HTTP/1.1 200 OK", ok.getInputStream().readHead()[0])
            ok.close(); slow.close()
        } finally {
            r.server.stop()
        }
    }

    @Test
    fun clientDisconnectIsDetectedWithAndWithoutFrames() {
        val store = LatestFrameStore()
        val r = startServer(store)
        try {
            val idle = connect(r.port)               // disconnects while no frames flow
            idle.getInputStream().readHead()
            assertTrue(waitUntil { r.server.clientCount == 1 })
            idle.close()
            assertTrue("idle client not released", waitUntil(4000) { r.server.clientCount == 0 })

            val busy = connect(r.port)               // disconnects while frames flow
            busy.getInputStream().readHead()
            val stop = java.util.concurrent.atomic.AtomicBoolean(false)
            val pump = Thread { var i = 0; while (!stop.get()) { store.publish(jpeg(i++, 20_000), 2, 2, 0); Thread.sleep(5) } }
            pump.start()
            busy.getInputStream().readPart()
            busy.setSoLinger(true, 0); busy.close()  // RST
            assertTrue("busy client not released", waitUntil(4000) { r.server.clientCount == 0 })
            stop.set(true); pump.join()

            // Server still healthy.
            val again = connect(r.port)
            assertEquals("HTTP/1.1 200 OK", again.getInputStream().readHead()[0])
            again.close()
        } finally {
            r.server.stop()
        }
    }

    @Test
    fun clientLimitReturns503AndFreesSlotOnDisconnect() {
        val r = startServer(LatestFrameStore(), maxClients = 2)
        try {
            val c1 = connect(r.port); c1.getInputStream().readHead()
            val c2 = connect(r.port); c2.getInputStream().readHead()
            assertTrue(waitUntil { r.server.clientCount == 2 })
            val (status, head) = statusLine(r.port, "GET /video HTTP/1.1\r\n\r\n")
            assertEquals("HTTP/1.1 503 Service Unavailable", status)
            assertTrue(head.contains("Retry-After: 2"))
            c1.close()
            assertTrue(waitUntil(4000) { r.server.clientCount == 1 })
            val c3 = connect(r.port)
            assertEquals("HTTP/1.1 200 OK", c3.getInputStream().readHead()[0])
            c2.close(); c3.close()
        } finally {
            r.server.stop()
        }
    }

    @Test
    fun stopDisconnectsClientsAndReleasesPort() {
        val store = LatestFrameStore()
        val r = startServer(store)
        val sock = connect(r.port)
        sock.getInputStream().readHead()
        assertTrue(waitUntil { r.server.clientCount == 1 })
        r.server.stop()
        assertEquals(ServerState.Stopped, r.server.state)
        assertEquals(0, r.server.clientCount)
        // The client sees EOF (or reset) promptly.
        val ended = try { sock.getInputStream().read() < 0 } catch (_: java.io.IOException) { true }
        assertTrue(ended)
        // Port can be bound again immediately.
        ServerSocket(r.port).close()
        // Idempotent.
        r.server.stop()
    }

    @Test
    fun portConflictReportsFailedAndCanRecover() {
        val blocker = ServerSocket(0)
        try {
            val r = startServer(LatestFrameStore(), port = blocker.localPort)
            val s = r.server.state
            assertTrue("expected Failed but was $s", s is ServerState.Failed)
            assertTrue((s as ServerState.Failed).message.contains("${blocker.localPort}"))
            r.server.stop() // clears failure
            assertEquals(ServerState.Stopped, r.server.state)
            blocker.close()
            // Same instance can start again once the port is free.
            val settled = CountDownLatch(1)
            val again = MjpegServer(LatestFrameStore(), blocker.localPort) { if (it is ServerState.Running) settled.countDown() }
            again.start()
            assertTrue(settled.await(5, TimeUnit.SECONDS))
            again.stop()
        } finally {
            blocker.close()
        }
    }

    @Test
    fun repeatedStartStopCyclesWork() {
        val store = LatestFrameStore()
        repeat(15) { i ->
            val r = startServer(store)
            assertTrue("cycle $i not running: ${r.server.state}", r.server.state is ServerState.Running)
            if (i % 3 == 0) {
                val c = connect(r.port); c.getInputStream().readHead(); c.close()
            }
            r.server.stop()
            assertEquals(ServerState.Stopped, r.server.state)
        }
    }

    @Test
    fun stopRightAfterStartLeavesNothingRunning() {
        val servers = (1..20).map { MjpegServer(LatestFrameStore(), 0) }
        servers.forEach { it.start(); it.stop() }
        Thread.sleep(300) // late accept threads must not flip state back to Running
        servers.forEach { assertEquals(ServerState.Stopped, it.state) }
    }

    @Test
    fun startIsIdempotentWhileRunning() {
        val r = startServer(LatestFrameStore())
        try {
            val before = r.server.state
            r.server.start()
            r.server.start()
            assertEquals(before, r.server.state)
            assertNotNull(connect(r.port))
        } finally {
            r.server.stop()
        }
    }
}
