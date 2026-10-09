package com.babycue.camera.net

/** Polls [condition] until it holds or [timeoutMs] passes; returns the final value. */
fun waitFor(timeoutMs: Long = 5_000, condition: () -> Boolean): Boolean {
    val deadline = System.nanoTime() + timeoutMs * 1_000_000
    while (System.nanoTime() < deadline) {
        if (condition()) return true
        Thread.sleep(10)
    }
    return condition()
}
