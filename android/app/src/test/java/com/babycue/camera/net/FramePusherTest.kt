package com.babycue.camera.net

import com.babycue.camera.capture.LatestFrameStore
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.io.InputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

class FramePusherTest {

    /** Plays the BabyCue server's /ingest endpoint: decodes the chunked body into length-prefixed frames. */
    private class FakeIngestServer(
        private val rejectWith409: Boolean = false,
        private val closeAfterFrames: Int = Int.MAX_VALUE,
    ) {
        private val listener = ServerSocket(0, 5, InetAddress.getLoopbackAddress())
        val url = "http://127.0.0.1:${listener.localPort}/ingest"
        val frames = CopyOnWriteArrayList<ByteArray>()
        val connections = AtomicInteger()
        val requestHeads = CopyOnWriteArrayList<String>()

        init {
            thread(isDaemon = true) {
                while (!listener.isClosed) {
                    val socket = try {
                        listener.accept()
                    } catch (_: IOException) {
                        break
                    }
                    connections.incrementAndGet()
                    thread(isDaemon = true) { handle(socket) }
                }
            }
        }

        fun close() = listener.close()

        private fun line(input: InputStream): String? {
            val sb = StringBuilder()
            while (true) {
                val b = input.read()
                if (b < 0) return if (sb.isEmpty()) null else sb.toString()
                if (b == '\n'.code) return sb.toString().trimEnd('\r')
                sb.append(b.toChar())
            }
        }

        private fun handle(socket: Socket) = socket.use {
            val input = it.getInputStream().buffered()
            val head = StringBuilder()
            while (true) {
                val l = line(input) ?: return
                if (l.isEmpty()) break
                head.append(l).append('\n')
            }
            requestHeads += head.toString()
            if (rejectWith409) {
                it.getOutputStream().write(
                    "HTTP/1.1 409 Conflict\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray(),
                )
                return
            }
            var pending = ByteArray(0)
            var received = 0
            while (true) {
                val size = line(input)?.trim()?.toIntOrNull(16) ?: return
                if (size == 0) return
                pending += input.readNBytes(size)
                input.read()
                input.read() // CRLF after the chunk
                while (pending.size >= 4) {
                    val length = java.nio.ByteBuffer.wrap(pending, 0, 4).int
                    if (pending.size < 4 + length) break
                    frames += pending.copyOfRange(4, 4 + length)
                    pending = pending.copyOfRange(4 + length, pending.size)
                    if (++received >= closeAfterFrames) return
                }
            }
        }
    }

    private val servers = ArrayList<FakeIngestServer>()
    private val pushers = ArrayList<FramePusher>()

    @After
    fun tearDown() {
        pushers.forEach { it.stop() }
        servers.forEach { it.close() }
    }

    private fun server(rejectWith409: Boolean = false, closeAfterFrames: Int = Int.MAX_VALUE) =
        FakeIngestServer(rejectWith409, closeAfterFrames).also { servers += it }

    private fun pusher(
        store: LatestFrameStore,
        url: String,
        states: CopyOnWriteArrayList<LinkState>,
    ) = FramePusher(store, url, { states.add(it) }, connectTimeoutMs = 1_000, initialBackoffMs = 30, maxBackoffMs = 100)
        .also { pushers += it }

    private fun jpeg(i: Int) = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), i.toByte(), (i * 2).toByte(), 0xFF.toByte(), 0xD9.toByte())

    @Test
    fun framesArriveAtTheServerIntactAndInOrder() {
        val server = server()
        val store = LatestFrameStore()
        val states = CopyOnWriteArrayList<LinkState>()
        val pusher = pusher(store, server.url, states)
        pusher.start()
        assertTrue(waitFor { LinkState.Connected in states })

        val sent = (1..5).map { jpeg(it) }
        sent.forEachIndexed { index, bytes ->
            store.publish(bytes, 2, 2, 0)
            assertTrue("frame $index not received", waitFor { server.frames.size == index + 1 })
        }
        sent.forEachIndexed { i, bytes -> assertArrayEquals(bytes, server.frames[i]) }
        assertEquals(5L, pusher.framesSent)
        val head = server.requestHeads.first()
        assertTrue(head, head.startsWith("POST /ingest HTTP/1.1"))
        assertTrue(head, head.contains("Transfer-Encoding: chunked", ignoreCase = true))
    }

    @Test
    fun largeFramesSpanningManyChunksSurvive() {
        val server = server()
        val store = LatestFrameStore()
        val states = CopyOnWriteArrayList<LinkState>()
        pusher(store, server.url, states).start()
        assertTrue(waitFor { LinkState.Connected in states })
        val big = ByteArray(300_000) { (it % 251).toByte() }.also { it[0] = 0xFF.toByte(); it[1] = 0xD8.toByte() }
        store.publish(big, 640, 480, 0)
        assertTrue(waitFor { server.frames.size == 1 })
        assertArrayEquals(big, server.frames[0])
    }

    @Test
    fun aRejectedInputKeepsRetryingInsteadOfGivingUp() {
        val server = server(rejectWith409 = true)
        val store = LatestFrameStore()
        val states = CopyOnWriteArrayList<LinkState>()
        val pusher = pusher(store, server.url, states)
        pusher.start()
        val feeder = thread(isDaemon = true) {
            var i = 0
            while (!Thread.currentThread().isInterrupted) {
                store.publish(jpeg(i++), 2, 2, 0)
                try {
                    Thread.sleep(20)
                } catch (_: InterruptedException) {
                    break
                }
            }
        }
        assertTrue(waitFor(8_000) { states.count { it is LinkState.Retrying } >= 2 })
        assertTrue("should reconnect repeatedly", server.connections.get() >= 2)
        feeder.interrupt()
    }

    @Test
    fun reconnectsAfterTheServerDropsTheConnection() {
        val server = server(closeAfterFrames = 1)
        val store = LatestFrameStore()
        val states = CopyOnWriteArrayList<LinkState>()
        pusher(store, server.url, states).start()
        val feeder = thread(isDaemon = true) {
            var i = 0
            while (!Thread.currentThread().isInterrupted) {
                store.publish(jpeg(i++ % 100), 2, 2, 0)
                try {
                    Thread.sleep(20)
                } catch (_: InterruptedException) {
                    break
                }
            }
        }
        assertTrue(waitFor(8_000) { server.connections.get() >= 3 })
        assertTrue(states.any { it is LinkState.Retrying })
        assertTrue(server.frames.size >= 3)
        feeder.interrupt()
    }

    @Test
    fun unreachableServerReportsAReasonAndRetries() {
        val dead = ServerSocket(0, 1, InetAddress.getLoopbackAddress()).use { it.localPort }
        val states = CopyOnWriteArrayList<LinkState>()
        pusher(LatestFrameStore(), "http://127.0.0.1:$dead/ingest", states).start()
        assertTrue(waitFor { states.count { it is LinkState.Retrying } >= 2 })
        assertEquals("Cannot connect to the server", states.filterIsInstance<LinkState.Retrying>().first().reason)
    }

    @Test
    fun stopDisconnectsPromptlyAndReportsNothingAfterwards() {
        val server = server()
        val store = LatestFrameStore()
        val states = CopyOnWriteArrayList<LinkState>()
        val pusher = pusher(store, server.url, states)
        pusher.start()
        assertTrue(waitFor { LinkState.Connected in states })
        val started = System.nanoTime()
        pusher.stop()
        pusher.stop()
        assertTrue("stop() must not block", (System.nanoTime() - started) / 1_000_000 < 500)
        Thread.sleep(200)
        val settled = states.size
        store.publish(jpeg(1), 2, 2, 0)
        Thread.sleep(300)
        assertEquals(settled, states.size)
        assertEquals(0, server.frames.size)
    }
}
