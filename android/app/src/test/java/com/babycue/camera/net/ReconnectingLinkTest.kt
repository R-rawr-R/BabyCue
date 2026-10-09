package com.babycue.camera.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger

class ReconnectingLinkTest {

    /** Fails every attempt, optionally reporting a successful connection first. */
    private class FailingLink(
        val states: CopyOnWriteArrayList<LinkState>,
        private val connectOn: Set<Int> = emptySet(),
        initialMs: Long = 10,
        maxMs: Long = 40,
    ) : ReconnectingLink({ states.add(it) }, initialMs, maxMs) {
        val attempts = AtomicInteger()

        override fun session(isCancelled: () -> Boolean, connected: () -> Unit) {
            val n = attempts.incrementAndGet()
            if (n in connectOn) connected()
            throw IOException("attempt $n failed")
        }

        override fun abort() {}
    }

    private fun delays(states: List<LinkState>) = states.filterIsInstance<LinkState.Retrying>().map { it.delayMs }

    @Test
    fun backoffDoublesAndIsCapped() {
        val states = CopyOnWriteArrayList<LinkState>()
        val link = FailingLink(states)
        link.start()
        assertTrue(waitFor { delays(states).size >= 5 })
        link.stop()
        assertEquals(listOf(10L, 20L, 40L, 40L, 40L), delays(states).take(5))
    }

    @Test
    fun backoffResetsAfterAConnectionSucceeds() {
        val states = CopyOnWriteArrayList<LinkState>()
        val link = FailingLink(states, connectOn = setOf(3))
        link.start()
        assertTrue(waitFor { delays(states).size >= 4 })
        link.stop()
        // attempts 1 and 2 fail to connect (10, 20); attempt 3 connects then fails (reset -> 10); attempt 4 (20)
        assertEquals(listOf(10L, 20L, 10L, 20L), delays(states).take(4))
        assertTrue(states.contains(LinkState.Connected))
    }

    @Test
    fun failureReasonsAreReportedToTheUser() {
        val states = CopyOnWriteArrayList<LinkState>()
        val link = FailingLink(states)
        link.start()
        assertTrue(waitFor { states.any { it is LinkState.Retrying } })
        link.stop()
        assertEquals("attempt 1 failed", states.filterIsInstance<LinkState.Retrying>().first().reason)
    }

    @Test
    fun nothingIsReportedAfterStopAndStartStopAreIdempotent() {
        val states = CopyOnWriteArrayList<LinkState>()
        val link = FailingLink(states)
        link.start()
        link.start()
        assertTrue(waitFor { states.size >= 3 })
        link.stop()
        link.stop()
        Thread.sleep(100) // let a thread that was mid-attempt unwind
        val settled = states.size
        Thread.sleep(200)
        assertEquals(settled, states.size)
    }

    @Test
    fun canBeRestartedAfterStop() {
        val states = CopyOnWriteArrayList<LinkState>()
        val link = FailingLink(states)
        link.start()
        assertTrue(waitFor { link.attempts.get() >= 1 })
        link.stop()
        Thread.sleep(100)
        val before = link.attempts.get()
        link.start()
        assertTrue(waitFor { link.attempts.get() > before })
        link.stop()
    }
}
