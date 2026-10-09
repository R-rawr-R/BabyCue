package com.babycue.camera.capture

import android.content.Context
import android.graphics.ImageFormat
import android.os.Handler
import android.os.Looper
import android.util.Size
import android.view.OrientationEventListener
import android.view.Surface
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

enum class CaptureErrorKind { PROVIDER_UNAVAILABLE, NO_REAR_CAMERA, BIND_FAILED, UNSUPPORTED_FORMAT, ENCODE_FAILED }

class CaptureError(val kind: CaptureErrorKind, val message: String)

/**
 * Rear-camera capture with CameraX `ImageAnalysis` (no preview). Frames are converted to JPEG and
 * published to [store]; analysis uses STRATEGY_KEEP_ONLY_LATEST on a single thread, so slow
 * encoding drops camera frames instead of queueing them.
 *
 * All public methods and [Listener] callbacks run on the main thread. The camera is bound to
 * [owner]'s lifecycle: it stops delivering frames when the owner is stopped (see README, Batch 2).
 */
class CameraCapture(
    private val context: Context,
    private val owner: LifecycleOwner,
    private val store: LatestFrameStore,
    private val listener: Listener,
    private val encoder: JpegEncoder = AndroidJpegEncoder(),
) {
    interface Listener {
        fun onCaptureStarted()

        /** Capture has already been stopped when this is called. */
        fun onCaptureError(error: CaptureError)
    }

    private val main = Handler(Looper.getMainLooper())
    private val analysisExecutor: ExecutorService = Executors.newSingleThreadExecutor { r -> Thread(r, "babycue-analysis") }
    private val pipeline = FramePipeline(encoder, store)

    // Main-thread state. `generation` is also read by the analysis thread to drop late frames.
    @Volatile private var generation = 0
    private var running = false
    private var provider: ProcessCameraProvider? = null
    private var analysis: ImageAnalysis? = null
    private var orientationListener: OrientationEventListener? = null

    val isRunning: Boolean get() = running

    fun start() {
        if (running) return
        running = true
        val gen = ++generation
        val future = try {
            ProcessCameraProvider.getInstance(context)
        } catch (e: Exception) {
            // Reported asynchronously so the caller's start() never re-enters its own state handling.
            main.post { fail(gen, CaptureErrorKind.PROVIDER_UNAVAILABLE, e) }
            return
        }
        future.addListener(
            {
                if (gen != generation) return@addListener // stopped while the provider was starting
                try {
                    bind(future.get(), gen)
                } catch (e: Exception) {
                    fail(gen, CaptureErrorKind.PROVIDER_UNAVAILABLE, e)
                }
            },
            ContextCompat.getMainExecutor(context),
        )
    }

    private fun bind(cameraProvider: ProcessCameraProvider, gen: Int) {
        if (!cameraProvider.hasCamera(CameraSelector.DEFAULT_BACK_CAMERA)) {
            fail(gen, CaptureErrorKind.NO_REAR_CAMERA, null, "This device has no rear camera.")
            return
        }
        val useCase = ImageAnalysis.Builder()
            .setResolutionSelector(
                ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(TARGET_SIZE, ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER),
                    )
                    .build(),
            )
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
            .build()
        useCase.setAnalyzer(analysisExecutor, analyzerFor(gen))
        try {
            cameraProvider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, useCase)
        } catch (e: Exception) {
            useCase.clearAnalyzer()
            fail(gen, CaptureErrorKind.BIND_FAILED, e)
            return
        }
        provider = cameraProvider
        analysis = useCase
        startOrientationTracking(useCase)
        listener.onCaptureStarted()
    }

    private fun analyzerFor(gen: Int) = ImageAnalysis.Analyzer { image ->
        try {
            if (gen != generation) return@Analyzer
            val planes = image.planes
            if (image.format != ImageFormat.YUV_420_888 || planes.size != 3) {
                postFail(gen, CaptureErrorKind.UNSUPPORTED_FORMAT, "Unexpected camera image format ${image.format}.")
                return@Analyzer
            }
            pipeline.process(
                image.width,
                image.height,
                YuvPlane(planes[0].buffer, planes[0].rowStride, planes[0].pixelStride),
                YuvPlane(planes[1].buffer, planes[1].rowStride, planes[1].pixelStride),
                YuvPlane(planes[2].buffer, planes[2].rowStride, planes[2].pixelStride),
                image.imageInfo.rotationDegrees,
                image.imageInfo.timestamp,
            )
            // stop() bumps `generation` before clearing the store, so a frame published after
            // stop() is always caught here and removed.
            if (gen != generation) store.clear()
        } catch (e: Exception) {
            postFail(gen, CaptureErrorKind.ENCODE_FAILED, "Frame conversion failed: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            image.close() // always release, or CameraX stops delivering frames
        }
    }

    /** Without a preview, CameraX needs the target rotation fed from the device orientation sensor. */
    private fun startOrientationTracking(useCase: ImageAnalysis) {
        val l = object : OrientationEventListener(context) {
            override fun onOrientationChanged(orientation: Int) {
                if (orientation == ORIENTATION_UNKNOWN) return
                useCase.targetRotation = when (orientation) {
                    in 45..134 -> Surface.ROTATION_270
                    in 135..224 -> Surface.ROTATION_180
                    in 225..314 -> Surface.ROTATION_90
                    else -> Surface.ROTATION_0
                }
            }
        }
        if (l.canDetectOrientation()) l.enable()
        orientationListener = l
    }

    fun stop() {
        if (!running) return
        running = false
        generation++
        orientationListener?.disable()
        orientationListener = null
        analysis?.let {
            it.clearAnalyzer()
            try {
                provider?.unbind(it)
            } catch (_: Exception) {
                // Provider already shut down; nothing left to release.
            }
        }
        analysis = null
        provider = null
        store.clear()
    }

    /** Stops capture and releases the analysis thread. The instance cannot be reused afterwards. */
    fun release() {
        stop()
        analysisExecutor.shutdown()
    }

    private fun postFail(gen: Int, kind: CaptureErrorKind, message: String) {
        main.post { if (gen == generation) fail(gen, kind, null, message) }
    }

    private fun fail(gen: Int, kind: CaptureErrorKind, cause: Exception?, message: String? = null) {
        if (gen != generation) return
        val text = message ?: (cause?.message ?: cause?.javaClass?.simpleName ?: "unknown error")
        stop()
        listener.onCaptureError(CaptureError(kind, text))
    }

    private companion object {
        /**
         * Landscape sensor size; CameraX picks the closest supported size. Kept small because every
         * frame crosses the Wi-Fi twice (phone -> server -> viewer) and phone CPUs encode the JPEG.
         */
        val TARGET_SIZE = Size(640, 480)
    }
}
