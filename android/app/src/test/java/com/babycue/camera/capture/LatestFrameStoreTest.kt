package com.babycue.camera.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.atomic.AtomicReference

class LatestFrameStoreTest {

    private fun LatestFrameStore.put(tag: Int) = publish(byteArrayOf(tag.toByte()), 2, 2, tag * 1000L)

    @Test
    fun startsEmpty() {
        val s = LatestFrameStore()
        assertNull(s.latest())
        assertEquals(0L, s.lastSequence)
    }

    @Test
    fun keepsOnlyTheNewestFrame() {
        val s = LatestFrameStore()
        s.put(1); s.put(2); val third = s.put(3)
        assertEquals(3L, third.sequence)
        assertEquals(3L, s.latest()!!.sequence)
        // A slow reader skips intermediate frames rather than seeing a backlog.
        assertEquals(3L, s.awaitNext(0, 10)!!.sequence)
        assertNull(s.awaitNext(3, 10))
    }

    @Test
    fun awaitNextTimesOutWithNull() {
        val start = System.nanoTime()
        assertNull(LatestFrameStore().awaitNext(0, 50))
        assertTrue((System.nanoTime() - start) >= 40_000_000L)
    }

    @Test
    fun awaitNextWakesWhenAFrameIsPublished() {
        val s = LatestFrameStore()
        val result = AtomicReference<JpegFrame?>()
        val t = Thread { result.set(s.awaitNext(0, 5_000)) }
        t.start()
        Thread.sleep(50)
        s.put(7)
        t.join(2_000)
        assertNotNull(result.get())
        assertEquals(1L, result.get()!!.sequence)
    }

    @Test
    fun clearDropsFrameButSequenceKeepsCounting() {
        val s = LatestFrameStore()
        s.put(1); s.put(2)
        s.clear()
        assertNull(s.latest())
        assertNull(s.awaitNext(0, 10)) // stale frame must not be served after clear
        assertEquals(3L, s.put(3).sequence)
    }

    @Test
    fun interruptedWaiterReturnsNull() {
        val s = LatestFrameStore()
        val result = AtomicReference<JpegFrame?>(JpegFrame(ByteArray(0), 0, 0, -1, 0))
        val t = Thread { result.set(s.awaitNext(0, 5_000)) }
        t.start()
        Thread.sleep(50)
        t.interrupt()
        t.join(2_000)
        assertNull(result.get())
    }
}
