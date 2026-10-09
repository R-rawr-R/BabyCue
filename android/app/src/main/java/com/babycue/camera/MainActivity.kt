package com.babycue.camera

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import com.babycue.camera.capture.CameraCapture
import com.babycue.camera.capture.CaptureError
import com.babycue.camera.capture.LatestFrameStore
import com.babycue.camera.server.LanAddress
import com.babycue.camera.server.MjpegProtocol
import com.babycue.camera.server.MjpegServer
import com.babycue.camera.server.ServerState
import com.babycue.camera.server.StreamingController
import com.babycue.camera.ui.ServerLineKind
import com.babycue.camera.ui.serverLine
import com.babycue.camera.ui.CameraPermission
import com.babycue.camera.ui.CaptureState
import com.babycue.camera.ui.StatusMessage
import com.babycue.camera.ui.effectiveCapture
import com.babycue.camera.ui.reconcilePermission
import com.babycue.camera.ui.screenModel

/**
 * Permission handling, Start/Stop controls, CameraX capture and the local MJPEG server.
 * Start runs camera and server together; Stop, leaving the foreground, or destroying the activity
 * stops the server. Streaming is activity-bound by design (no foreground service yet).
 */
class MainActivity : ComponentActivity(), CameraCapture.Listener {

    val frameStore = LatestFrameStore()
    private lateinit var camera: CameraCapture
    private lateinit var server: MjpegServer
    private lateinit var controller: StreamingController
    private var serverState: ServerState = ServerState.Stopped
    private var destroyed = false
    private var cameraError: String? = null
    private val ui = Handler(Looper.getMainLooper())
    private var statsBaseSequence = 0L
    private var statsLastSequence = 0L
    private var statsLastTimeMs = 0L

    private var permission = CameraPermission.NOT_REQUESTED
    private var capture = CaptureState.STOPPED

    private lateinit var statusText: TextView
    private lateinit var statsText: TextView
    private lateinit var serverText: TextView
    private lateinit var startButton: Button
    private lateinit var stopButton: Button
    private lateinit var settingsButton: Button

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            permission = when {
                granted -> CameraPermission.GRANTED
                // After a denial, rationale == true means the system will still show the dialog next time.
                shouldShowRequestPermissionRationale(Manifest.permission.CAMERA) -> CameraPermission.DENIED
                else -> CameraPermission.DENIED_PERMANENTLY
            }
            if (granted) capture = CaptureState.STARTED
            render()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        statusText = findViewById(R.id.statusText)
        statsText = findViewById(R.id.statsText)
        serverText = findViewById(R.id.serverText)
        camera = CameraCapture(this, this, frameStore, this)
        server = MjpegServer(frameStore, MjpegProtocol.DEFAULT_PORT) { state ->
            // Called from server threads.
            ui.post {
                if (!destroyed) {
                    serverState = state
                    renderServer()
                }
            }
        }
        controller = StreamingController(
            startCamera = camera::start,
            stopCamera = camera::stop,
            startServer = server::start,
            stopServer = server::stop,
            clearFrames = frameStore::clear,
            releaseCamera = camera::release,
        )
        startButton = findViewById(R.id.startButton)
        stopButton = findViewById(R.id.stopButton)
        settingsButton = findViewById(R.id.settingsButton)

        savedInstanceState?.let {
            permission = enumValueOrDefault(it.getString(KEY_PERMISSION), CameraPermission.NOT_REQUESTED)
            capture = enumValueOrDefault(it.getString(KEY_CAPTURE), CaptureState.STOPPED)
        }

        startButton.setOnClickListener { onStartClicked() }
        stopButton.setOnClickListener {
            capture = CaptureState.STOPPED
            cameraError = null
            render()
        }
        settingsButton.setOnClickListener {
            startActivity(
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)),
            )
        }
    }

    override fun onResume() {
        super.onResume()
        // The user may have changed the permission in system settings while the app was in the background.
        permission = reconcilePermission(isCameraGranted(), permission)
        capture = effectiveCapture(permission, capture)
        render()
    }

    override fun onStop() {
        // The camera stops delivering frames now (it is bound to this lifecycle), so stop serving too.
        controller.onBackgrounded()
        ui.removeCallbacks(statsTick)
        super.onStop()
    }

    override fun onDestroy() {
        destroyed = true
        ui.removeCallbacks(statsTick)
        // Orientation changes are handled in place (see manifest), so this is a real shutdown.
        controller.shutdown()
        super.onDestroy()
    }

    override fun onCaptureStarted() {
        statsBaseSequence = frameStore.lastSequence
        statsLastSequence = statsBaseSequence
        statsLastTimeMs = android.os.SystemClock.elapsedRealtime()
        ui.removeCallbacks(statsTick)
        ui.post(statsTick)
    }

    override fun onCaptureError(error: CaptureError) {
        // CameraCapture has already stopped itself.
        capture = CaptureState.STOPPED
        cameraError = getString(R.string.status_camera_error, error.message)
        render()
    }

    private val statsTick = object : Runnable {
        override fun run() {
            val now = android.os.SystemClock.elapsedRealtime()
            val seq = frameStore.lastSequence
            val fps = (seq - statsLastSequence) * 1000.0 / (now - statsLastTimeMs).coerceAtLeast(1)
            val frame = frameStore.latest()
            statsText.text = if (frame == null) {
                getString(R.string.stats_waiting)
            } else {
                getString(
                    R.string.stats_format,
                    seq - statsBaseSequence, fps, frame.width, frame.height, frame.bytes.size / 1024.0,
                )
            }
            statsLastSequence = seq
            statsLastTimeMs = now
            renderServer() // refreshes the LAN address and client count
            if (capture == CaptureState.STARTED) ui.postDelayed(this, 1000)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(KEY_PERMISSION, permission.name)
        outState.putString(KEY_CAPTURE, capture.name)
    }

    private fun onStartClicked() {
        cameraError = null
        if (isCameraGranted()) {
            permission = CameraPermission.GRANTED
            capture = CaptureState.STARTED
            render()
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun isCameraGranted(): Boolean =
        checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    private fun render() {
        val model = screenModel(permission, capture)
        val started = effectiveCapture(permission, capture) == CaptureState.STARTED
        controller.setStreaming(started)
        if (started) {
            // (Re)start the 1 s status refresh; also resumes it after returning from the background.
            ui.removeCallbacks(statsTick)
            ui.post(statsTick)
        }
        // Keep the screen on while capturing: CameraX is tied to this activity and stops when it is stopped.
        if (started) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        statsText.visibility = if (started) android.view.View.VISIBLE else android.view.View.GONE
        serverText.visibility = if (started || serverState is ServerState.Failed) android.view.View.VISIBLE else android.view.View.GONE
        renderServer()

        val error = cameraError
        if (error != null && !started) {
            statusText.text = error
        } else statusText.setText(
            when (model.message) {
                StatusMessage.IDLE_PERMISSION_NEEDED -> R.string.status_idle_permission_needed
                StatusMessage.IDLE_READY -> R.string.status_idle_ready
                StatusMessage.STARTED_CAPTURING -> R.string.status_started_capturing
                StatusMessage.DENIED -> R.string.status_denied
                StatusMessage.DENIED_PERMANENTLY -> R.string.status_denied_permanent
            },
        )
        startButton.isEnabled = model.startEnabled
        stopButton.isEnabled = model.stopEnabled
        settingsButton.visibility = if (model.showOpenSettings) android.view.View.VISIBLE else android.view.View.GONE
    }

    private fun renderServer() {
        val line = serverLine(serverState, LanAddress.find(), server.clientCount)
        val head = when (line.kind) {
            ServerLineKind.STOPPED -> getString(R.string.server_stopped)
            ServerLineKind.STARTING -> getString(R.string.server_starting)
            ServerLineKind.FAILED -> getString(R.string.server_failed, line.error)
            ServerLineKind.RUNNING_NO_ADDRESS -> getString(R.string.server_running_no_address, line.port)
            ServerLineKind.RUNNING -> getString(R.string.server_running, line.url, line.clients)
        }
        val running = line.kind == ServerLineKind.RUNNING || line.kind == ServerLineKind.RUNNING_NO_ADDRESS
        serverText.text = if (running) head + "\n" + getString(R.string.server_security_note) else head
    }

    private inline fun <reified T : Enum<T>> enumValueOrDefault(name: String?, default: T): T =
        enumValues<T>().firstOrNull { it.name == name } ?: default

    private companion object {
        const val KEY_PERMISSION = "permission"
        const val KEY_CAPTURE = "capture"
    }
}
