package com.babycue.camera.ui

import com.babycue.camera.server.ServerState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ServerStatusTest {
    @Test
    fun runningWithAddressShowsFullUrl() {
        val l = serverLine(ServerState.Running(8080), "192.168.1.10", 2)
        assertEquals(ServerLineKind.RUNNING, l.kind)
        assertEquals("http://192.168.1.10:8080/video", l.url)
        assertEquals(2, l.clients)
    }

    @Test
    fun runningWithoutAddressIsNotReportedAsReachable() {
        val l = serverLine(ServerState.Running(8080), null, 0)
        assertEquals(ServerLineKind.RUNNING_NO_ADDRESS, l.kind)
        assertNull(l.url)
    }

    @Test
    fun urlUsesTheActualBoundPort() {
        assertEquals("http://10.0.0.2:9090/video", serverLine(ServerState.Running(9090), "10.0.0.2", 0).url)
    }

    @Test
    fun nonRunningStatesNeverCarryAUrl() {
        for (s in listOf(ServerState.Stopped, ServerState.Starting, ServerState.Failed("x"))) {
            assertNull(serverLine(s, "192.168.1.10", 3).url)
        }
        assertEquals(ServerLineKind.STOPPED, serverLine(ServerState.Stopped, "1.2.3.4", 0).kind)
        assertEquals(ServerLineKind.STARTING, serverLine(ServerState.Starting, "1.2.3.4", 0).kind)
        val f = serverLine(ServerState.Failed("port busy"), "1.2.3.4", 0)
        assertEquals(ServerLineKind.FAILED, f.kind)
        assertEquals("port busy", f.error)
    }
}
