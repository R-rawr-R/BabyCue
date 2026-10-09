package com.babycue.camera.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenModelTest {

    @Test
    fun initialStateAllowsStartAndExplainsPermissionPrompt() {
        val m = screenModel(CameraPermission.NOT_REQUESTED, CaptureState.STOPPED)
        assertEquals(StatusMessage.IDLE_PERMISSION_NEEDED, m.message)
        assertTrue(m.startEnabled)
        assertFalse(m.stopEnabled)
        assertFalse(m.showOpenSettings)
    }

    @Test
    fun grantedAndStartedEnablesStopOnly() {
        val m = screenModel(CameraPermission.GRANTED, CaptureState.STARTED)
        assertEquals(StatusMessage.STARTED_CAPTURING, m.message)
        assertFalse(m.startEnabled)
        assertTrue(m.stopEnabled)
    }

    @Test
    fun grantedAndStoppedIsReady() {
        val m = screenModel(CameraPermission.GRANTED, CaptureState.STOPPED)
        assertEquals(StatusMessage.IDLE_READY, m.message)
        assertTrue(m.startEnabled)
        assertFalse(m.stopEnabled)
    }

    @Test
    fun deniedAllowsRetry() {
        val m = screenModel(CameraPermission.DENIED, CaptureState.STOPPED)
        assertEquals(StatusMessage.DENIED, m.message)
        assertTrue(m.startEnabled)
        assertFalse(m.showOpenSettings)
    }

    @Test
    fun permanentlyDeniedOffersSettingsAndDisablesStart() {
        val m = screenModel(CameraPermission.DENIED_PERMANENTLY, CaptureState.STOPPED)
        assertEquals(StatusMessage.DENIED_PERMANENTLY, m.message)
        assertFalse(m.startEnabled)
        assertTrue(m.showOpenSettings)
    }

    @Test
    fun captureCannotRunWithoutPermission() {
        for (p in CameraPermission.entries.filter { it != CameraPermission.GRANTED }) {
            assertEquals(CaptureState.STOPPED, effectiveCapture(p, CaptureState.STARTED))
            assertFalse(screenModel(p, CaptureState.STARTED).stopEnabled)
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
}
