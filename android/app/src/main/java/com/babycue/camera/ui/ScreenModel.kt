package com.babycue.camera.ui

/**
 * Pure (Android-free) description of what the main screen shows, so it can be unit-tested on the JVM.
 * Camera and streaming logic deliberately do not live here.
 */
enum class CameraPermission { NOT_REQUESTED, GRANTED, DENIED, DENIED_PERMANENTLY }

enum class CaptureState { STOPPED, STARTED }

enum class StatusMessage {
    IDLE_PERMISSION_NEEDED,
    IDLE_READY,
    STARTED_CAPTURING,
    DENIED,
    DENIED_PERMANENTLY,
}

data class ScreenModel(
    val message: StatusMessage,
    val startEnabled: Boolean,
    val stopEnabled: Boolean,
    val showOpenSettings: Boolean,
)

/** Capture can only be running while permission is granted. */
fun effectiveCapture(permission: CameraPermission, capture: CaptureState): CaptureState =
    if (permission == CameraPermission.GRANTED) capture else CaptureState.STOPPED

/**
 * Re-sync the remembered permission with the system's answer (e.g. after returning from settings).
 * A permission that was granted and later revoked goes back to "not requested".
 */
fun reconcilePermission(isGranted: Boolean, current: CameraPermission): CameraPermission = when {
    isGranted -> CameraPermission.GRANTED
    current == CameraPermission.GRANTED -> CameraPermission.NOT_REQUESTED
    else -> current
}

fun screenModel(permission: CameraPermission, capture: CaptureState): ScreenModel {
    if (effectiveCapture(permission, capture) == CaptureState.STARTED) {
        return ScreenModel(StatusMessage.STARTED_CAPTURING, startEnabled = false, stopEnabled = true, showOpenSettings = false)
    }
    return when (permission) {
        CameraPermission.NOT_REQUESTED ->
            ScreenModel(StatusMessage.IDLE_PERMISSION_NEEDED, startEnabled = true, stopEnabled = false, showOpenSettings = false)
        CameraPermission.GRANTED ->
            ScreenModel(StatusMessage.IDLE_READY, startEnabled = true, stopEnabled = false, showOpenSettings = false)
        CameraPermission.DENIED ->
            ScreenModel(StatusMessage.DENIED, startEnabled = true, stopEnabled = false, showOpenSettings = false)
        CameraPermission.DENIED_PERMANENTLY ->
            ScreenModel(StatusMessage.DENIED_PERMANENTLY, startEnabled = false, stopEnabled = false, showOpenSettings = true)
    }
}
