package com.babycue.camera.net

/**
 * Wire contract with the Python server (`babycue_server/protocol.py`); `tests/test_wire_contract.py`
 * fails if the two drift apart.
 *
 * Input phone -> server: `POST /ingest`, chunked body of `[uint32 big-endian length][JPEG]` records.
 * Server -> output phone: `GET /view`, `multipart/x-mixed-replace` with a Content-Length per part.
 */
object WireProtocol {
    const val DEFAULT_PORT = 8080
    const val INGEST_PATH = "/ingest"
    const val VIEW_PATH = "/view"
    const val BOUNDARY = "babycueframe"
    const val MAX_FRAME_BYTES = 8 * 1024 * 1024
    const val LENGTH_PREFIX_BYTES = 4

    /** The 4-byte big-endian length that precedes each JPEG sent to `/ingest`. */
    fun lengthPrefix(length: Int): ByteArray = byteArrayOf(
        (length ushr 24).toByte(),
        (length ushr 16).toByte(),
        (length ushr 8).toByte(),
        length.toByte(),
    )
}
