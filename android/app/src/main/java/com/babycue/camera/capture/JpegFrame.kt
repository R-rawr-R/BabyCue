package com.babycue.camera.capture

import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * One encoded camera frame. [bytes] is a complete JPEG (SOI..EOI). The array is shared between
 * all readers and must never be modified.
 */
class JpegFrame(
    val bytes: ByteArray,
    val width: Int,
    val height: Int,
    /** Strictly increasing per [LatestFrameStore]; never reset, even across stop/start. */
    val sequence: Long,
    /** Camera sensor timestamp in nanoseconds (arbitrary epoch; only differences are meaningful). */
    val timestampNanos: Long,
)

/**
 * Read side of the capture pipeline. The Batch 3 MJPEG server depends only on this interface.
 *
 * Typical client loop:
 * ```
 * var last = 0L
 * while (open) {
 *     val frame = source.awaitNext(last, 1000) ?: continue   // timeout: nothing new
 *     last = frame.sequence
 *     write(frame.bytes)
 * }
 * ```
 */
interface JpegFrameSource {
    /** The newest frame, or null if capture has not produced one since the last [LatestFrameStore.clear]. */
    fun latest(): JpegFrame?

    /**
     * Blocks until a frame with `sequence > afterSequence` exists, then returns the newest frame
     * (intermediate frames are skipped by design). Returns null on timeout or if interrupted.
     */
    fun awaitNext(afterSequence: Long, timeoutMs: Long): JpegFrame?
}

/**
 * Keep-only-latest hand-off: holds at most one frame, so memory is bounded no matter how slow
 * the readers are. A slow reader simply skips frames.
 */
class LatestFrameStore : JpegFrameSource {
    private val lock = ReentrantLock()
    private val changed = lock.newCondition()
    private var current: JpegFrame? = null
    private var sequence = 0L

    /** Sequence of the most recently published frame (0 before the first). */
    val lastSequence: Long get() = lock.withLock { sequence }

    fun publish(bytes: ByteArray, width: Int, height: Int, timestampNanos: Long): JpegFrame =
        lock.withLock {
            val frame = JpegFrame(bytes, width, height, ++sequence, timestampNanos)
            current = frame
            changed.signalAll()
            frame
        }

    /** Drops the held frame (e.g. on Stop) so a stale picture is never served. Sequence keeps counting. */
    fun clear() = lock.withLock {
        current = null
        changed.signalAll()
    }

    override fun latest(): JpegFrame? = lock.withLock { current }

    override fun awaitNext(afterSequence: Long, timeoutMs: Long): JpegFrame? {
        var remaining = TimeUnit.MILLISECONDS.toNanos(timeoutMs.coerceAtLeast(0))
        lock.lock()
        try {
            while (true) {
                val frame = current
                if (frame != null && frame.sequence > afterSequence) return frame
                if (remaining <= 0L) return null
                remaining = try {
                    changed.awaitNanos(remaining)
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                    return null
                }
            }
        } finally {
            lock.unlock()
        }
    }
}
