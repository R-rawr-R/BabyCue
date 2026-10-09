package com.babycue.camera.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenModelTest {

    @Test
    fun initialStateAllowsStartAndExplainsPermissionPrompt() {
        val m = screenModel(Role.INPUT, CameraPermission.NOT_REQUESTED, CaptureState.STOPPED)
        assertEquals(StatusMessage.IDLE_PERMISSION_NEEDED, m.message)
        assertTrue(m.startEnabled)
        assertFalse(m.stopEnabled)
        assertFalse(m.showOpenSettings)
    }

    @Test
    fun grantedAndStartedEnablesStopOnly() {
        val m = screenModel(Role.INPUT, CameraPermission.GRANTED, CaptureState.STARTED)
        assertEquals(StatusMessage.STARTED_CAPTURING, m.message)
        assertFalse(m.startEnabled)
        assertTrue(m.stopEnabled)
    }

    @Test
    fun grantedAndStoppedIsReady() {
        val m = screenModel(Role.INPUT, CameraPermission.GRANTED, CaptureState.STOPPED)
        assertEquals(StatusMessage.IDLE_READY, m.message)
        assertTrue(m.startEnabled)
        assertFalse(m.stopEnabled)
    }

    @Test
    fun deniedAllowsRetry() {
        val m = screenModel(Role.INPUT, CameraPermission.DENIED, CaptureState.STOPPED)
        assertEquals(StatusMessage.DENIED, m.message)
        assertTrue(m.startEnabled)
        assertFalse(m.showOpenSettings)
    }

    @Test
    fun permanentlyDeniedOffersSettingsAndDisablesStart() {
        val m = screenModel(Role.INPUT, CameraPermission.DENIED_PERMANENTLY, CaptureState.STOPPED)
        assertEquals(StatusMessage.DENIED_PERMANENTLY, m.message)
        assertFalse(m.startEnabled)
        assertTrue(m.showOpenSettings)
    }

    @Test
    fun captureCannotRunWithoutPermission() {
        for (p in CameraPermission.entries.filter { it != CameraPermission.GRANTED }) {
            assertEquals(CaptureState.STOPPED, effectiveCapture(p, CaptureState.STARTED))
            assertFalse(screenModel(Role.INPUT, p, CaptureState.STARTED).stopEnabled)
        }
    }

    @Test
    fun revokedPermissionResetsToNotRequested() {
        assertEquals(CameraPermission.NOT_REQUESTED, reconcilePermission(false, CameraPermission.GRANTED))
    }

    @Test
    fun grantedInSettingsIsPickedUp() {
        assertEquals(CameraPermission.GRANTED, reconcilePermission(true, CameraPermission.DENIED_PERMANENTLY))
    }

    @Test
    fun denialIsRememberedWhileStillNotGranted() {
        assertEquals(CameraPermission.DENIED, reconcilePermission(false, CameraPermission.DENIED))
        assertEquals(CameraPermission.DENIED_PERMANENTLY, reconcilePermission(false, CameraPermission.DENIED_PERMANENTLY))
    }

    @Test
    fun outputRoleNeedsNoCameraPermission() {
        val idle = screenModel(Role.OUTPUT, CameraPermission.NOT_REQUESTED, CaptureState.STOPPED)
        assertEquals(StatusMessage.OUTPUT_IDLE, idle.message)
        assertTrue(idle.startEnabled)
        assertFalse(idle.stopEnabled)
        val watching = screenModel(Role.OUTPUT, CameraPermission.DENIED_PERMANENTLY, CaptureState.STARTED)
        assertEquals(StatusMessage.OUTPUT_WATCHING, watching.message)
        assertFalse(watching.startEnabled)
        assertTrue(watching.stopEnabled)
        assertFalse(watching.showOpenSettings)
    }

    @Test
    fun effectiveRunningIgnoresPermissionOnlyForOutput() {
        assertEquals(CaptureState.STARTED, effectiveRunning(Role.OUTPUT, CameraPermission.DENIED, CaptureState.STARTED))
        assertEquals(CaptureState.STOPPED, effectiveRunning(Role.INPUT, CameraPermission.DENIED, CaptureState.STARTED))
        assertEquals(CaptureState.STARTED, effectiveRunning(Role.INPUT, CameraPermission.GRANTED, CaptureState.STARTED))
    }
}
