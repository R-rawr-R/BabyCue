package com.babycue.camera

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.RadioGroup
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import com.babycue.camera.capture.CameraCapture
import com.babycue.camera.capture.CaptureError
import com.babycue.camera.capture.LatestFrameStore
import com.babycue.camera.net.FramePusher
import com.babycue.camera.net.FrameReceiver
import com.babycue.camera.net.LinkState
import com.babycue.camera.net.ServerAddress
import com.babycue.camera.net.StreamingController
import com.babycue.camera.ui.CameraPermission
import com.babycue.camera.ui.CaptureState
import com.babycue.camera.ui.Role
import com.babycue.camera.ui.StatusMessage
import com.babycue.camera.ui.effectiveRunning
import com.babycue.camera.ui.reconcilePermission
import com.babycue.camera.ui.screenModel
import java.util.concurrent.atomic.AtomicLong

/**
 * One app, two roles. Input: CameraX capture streamed to the BabyCue server. Output: shows the video
 * the server relays. Start runs the server link (and, for input, the camera) together; Stop, leaving
 * the foreground, or destroying the activity stops both. Streaming is activity-bound by design
 * (no foreground service yet).
 */
class MainActivity : ComponentActivity(), CameraCapture.Listener {

    val frameStore = LatestFrameStore()
    private lateinit var camera: CameraCapture
    private lateinit var controller: StreamingController
    private var pusher: FramePusher? = null
    private var receiver: FrameReceiver? = null
    private var address: ServerAddress? = null
    private var linkState: LinkState? = null
    private var destroyed = false
    private var cameraError: String? = null
    private var addressError = false
    private val ui = Handler(Looper.getMainLooper())
    private val framesShown = AtomicLong()
    private var statsRunning = false
    private var statsBase = 0L
    private var statsLastCount = 0L
    private var statsLastTimeMs = 0L

    private var role = Role.INPUT
    private var permission = CameraPermission.NOT_REQUESTED
    private var capture = CaptureState.STOPPED

    private lateinit var roleGroup: RadioGroup
    private lateinit var serverEdit: EditText
    private lateinit var statusText: TextView
    private lateinit var linkText: TextView
    private lateinit var statsText: TextView
    private lateinit var videoView: ImageView
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
        roleGroup = findViewById(R.id.roleGroup)
        serverEdit = findViewById(R.id.serverEdit)
        statusText = findViewById(R.id.statusText)
        linkText = findViewById(R.id.linkText)
        statsText = findViewById(R.id.statsText)
        videoView = findViewById(R.id.videoView)
        startButton = findViewById(R.id.startButton)
        stopButton = findViewById(R.id.stopButton)
        settingsButton = findViewById(R.id.settingsButton)

        camera = CameraCapture(this, this, frameStore, this)
        controller = StreamingController(
            startCamera = { if (role == Role.INPUT) camera.start() },
            stopCamera = camera::stop,
            startLink = ::startLink,
            stopLink = ::stopLink,
            clearFrames = ::clearFrames,
            releaseCamera = camera::release,
        )

        val prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        role = enumValueOrDefault(prefs.getString(KEY_ROLE, null), Role.INPUT)
        serverEdit.setText(prefs.getString(KEY_SERVER, ""))
        savedInstanceState?.let {
            role = enumValueOrDefault(it.getString(KEY_ROLE), role)
            permission = enumValueOrDefault(it.getString(KEY_PERMISSION), CameraPermission.NOT_REQUESTED)
            capture = enumValueOrDefault(it.getString(KEY_CAPTURE), CaptureState.STOPPED)
        }
        roleGroup.check(if (role == Role.INPUT) R.id.radioInput else R.id.radioOutput)
        roleGroup.setOnCheckedChangeListener { _, checkedId ->
            role = if (checkedId == R.id.radioOutput) Role.OUTPUT else Role.INPUT
            addressError = false
            render()
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
        render()
    }

    override fun onStop() {
        // The camera stops delivering frames now (it is bound to this lifecycle), so leave the server too.
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
        ui.post { resetStats() }
    }

    override fun onCaptureError(error: CaptureError) {
        // CameraCapture has already stopped itself.
        capture = CaptureState.STOPPED
        cameraError = getString(R.string.status_camera_error, error.message)
        render()
    }

    // -- link to the server ------------------------------------------------------------------

    private fun startLink() {
        val target = address ?: return
        if (role == Role.INPUT) {
            if (pusher == null) {
                pusher = FramePusher(frameStore, target.ingestUrl, ::onLinkState).also { it.start() }
            }
        } else if (receiver == null) {
            framesShown.set(0)
            receiver = FrameReceiver(target.viewUrl, ::onFrameReceived, ::onLinkState).also { it.start() }
        }
    }

    private fun stopLink() {
        pusher?.stop()
        pusher = null
        receiver?.stop()
        receiver = null
        linkState = null
    }

    private fun clearFrames() {
        frameStore.clear()
        ui.post { if (!destroyed) videoView.setImageDrawable(null) }
    }

    /** Called from the link thread. */
    private fun onLinkState(state: LinkState) {
        ui.post {
            if (!destroyed && (pusher != null || receiver != null)) {
                linkState = state
                renderLink()
            }
        }
    }

    /** Called from the receiver thread; decoding here applies back-pressure instead of queueing frames. */
    private fun onFrameReceived(jpeg: ByteArray) {
        val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size) ?: return
        framesShown.incrementAndGet()
        ui.post {
            if (!destroyed && receiver != null) {
                videoView.setImageBitmap(bitmap)
                renderLink()
            }
        }
    }

    // -- stats --------------------------------------------------------------------------------

    private fun frameCount(): Long = if (role == Role.INPUT) frameStore.lastSequence else framesShown.get()

    private fun resetStats() {
        statsBase = frameCount()
        statsLastCount = statsBase
        statsLastTimeMs = SystemClock.elapsedRealtime()
        ui.removeCallbacks(statsTick)
        ui.post(statsTick)
    }

    private val statsTick = object : Runnable {
        override fun run() {
            val now = SystemClock.elapsedRealtime()
            val count = frameCount()
            val fps = (count - statsLastCount) * 1000.0 / (now - statsLastTimeMs).coerceAtLeast(1)
            val frame = frameStore.latest()
            statsText.text = when {
                role == Role.OUTPUT -> getString(R.string.stats_output_format, count - statsBase, fps)
                frame == null -> getString(R.string.stats_waiting)
                else -> getString(
                    R.string.stats_format,
                    count - statsBase, fps, frame.width, frame.height, frame.bytes.size / 1024.0,
                )
            }
            statsLastCount = count
            statsLastTimeMs = now
            if (effectiveRunning(role, permission, capture) == CaptureState.STARTED) ui.postDelayed(this, 1000)
        }
    }

    // -- state --------------------------------------------------------------------------------

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(KEY_ROLE, role.name)
        outState.putString(KEY_PERMISSION, permission.name)
        outState.putString(KEY_CAPTURE, capture.name)
    }

    private fun onStartClicked() {
        cameraError = null
        val parsed = ServerAddress.parse(serverEdit.text.toString())
        if (parsed == null) {
            addressError = true
            render()
            return
        }
        addressError = false
        address = parsed
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
            .putString(KEY_ROLE, role.name)
            .putString(KEY_SERVER, parsed.display)
            .apply()
        when {
            role == Role.OUTPUT -> {
                capture = CaptureState.STARTED
                render()
            }
            isCameraGranted() -> {
                permission = CameraPermission.GRANTED
                capture = CaptureState.STARTED
                render()
            }
            else -> permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun isCameraGranted(): Boolean =
        checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    private fun render() {
        val model = screenModel(role, permission, capture)
        var started = effectiveRunning(role, permission, capture) == CaptureState.STARTED
        if (started && address == null) {
            // Restored after the process was recreated: re-read the address field, or stay stopped.
            address = ServerAddress.parse(serverEdit.text.toString())
            if (address == null) {
                capture = CaptureState.STOPPED
                started = false
            }
        }
        controller.setStreaming(started)
        if (started) {
            if (statsRunning) {
                // Also resumes the 1 s refresh after returning from the background.
                ui.removeCallbacks(statsTick)
                ui.post(statsTick)
            } else {
                resetStats()
            }
        }
        statsRunning = started
        // Keep the screen on while streaming: CameraX is tied to this activity and stops when it is stopped.
        if (started) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        statsText.visibility = if (started) View.VISIBLE else View.GONE
        linkText.visibility = if (started) View.VISIBLE else View.GONE
        videoView.visibility = if (started && role == Role.OUTPUT) View.VISIBLE else View.GONE
        roleGroup.isEnabled = !started
        for (i in 0 until roleGroup.childCount) roleGroup.getChildAt(i).isEnabled = !started
        serverEdit.isEnabled = !started
        renderLink()

        val error = cameraError
        when {
            addressError && !started -> statusText.setText(R.string.status_bad_address)
            error != null && !started -> statusText.text = error
            else -> statusText.setText(
                when (model.message) {
                    StatusMessage.IDLE_PERMISSION_NEEDED -> R.string.status_idle_permission_needed
                    StatusMessage.IDLE_READY -> R.string.status_idle_ready
                    StatusMessage.STARTED_CAPTURING -> R.string.status_started_capturing
                    StatusMessage.DENIED -> R.string.status_denied
                    StatusMessage.DENIED_PERMANENTLY -> R.string.status_denied_permanent
                    StatusMessage.OUTPUT_IDLE -> R.string.status_output_idle
                    StatusMessage.OUTPUT_WATCHING -> R.string.status_output_watching
                },
            )
        }
        startButton.isEnabled = model.startEnabled
        stopButton.isEnabled = model.stopEnabled
        settingsButton.visibility = if (model.showOpenSettings) View.VISIBLE else View.GONE
    }

    private fun renderLink() {
        val target = address?.display ?: ""
        linkText.text = when (val state = linkState) {
            null -> ""
            LinkState.Connecting -> getString(R.string.link_connecting, target)
            LinkState.Connected -> when {
                role == Role.INPUT -> getString(R.string.link_sending, target)
                framesShown.get() > 0 -> getString(R.string.link_receiving, target)
                else -> getString(R.string.link_waiting, target)
            }
            is LinkState.Retrying ->
                getString(R.string.link_retrying, state.reason, (state.delayMs + 999) / 1000)
        }
    }

    private inline fun <reified T : Enum<T>> enumValueOrDefault(name: String?, default: T): T =
        enumValues<T>().firstOrNull { it.name == name } ?: default

    private companion object {
        const val PREFS = "babycue"
        const val KEY_ROLE = "role"
        const val KEY_SERVER = "server"
        const val KEY_PERMISSION = "permission"
        const val KEY_CAPTURE = "capture"
    }
}
