"""Wire contract between the server and the Android app.

The Kotlin mirror is ``android/app/src/main/java/com/babycue/camera/net/WireProtocol.kt``;
``tests/test_wire_contract.py`` fails if the two drift apart.

* Input phone -> server: ``POST /ingest``, chunked body of ``[uint32 big-endian length][JPEG]`` records.
* Server -> output phone: ``GET /view``, ``multipart/x-mixed-replace`` with a Content-Length per part.
"""

from __future__ import annotations

import struct

DEFAULT_PORT = 8080
INGEST_PATH = "/ingest"
VIEW_PATH = "/view"
STATUS_PATH = "/status"
BOUNDARY = "babycueframe"
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_VIEWERS = 4
JPEG_MAGIC = b"\xff\xd8"

_LENGTH = struct.Struct(">I")
LENGTH_PREFIX_BYTES = _LENGTH.size

VIEW_CONTENT_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"
PART_TAIL = b"\r\n"


def pack_frame(jpeg: bytes) -> bytes:
    """One ingest record: the length prefix followed by the JPEG."""
    return _LENGTH.pack(len(jpeg)) + jpeg


def unpack_length(prefix: bytes) -> int:
    return _LENGTH.unpack(prefix)[0]


def part_head(length: int) -> bytes:
    """Bytes that precede a JPEG in a ``/view`` response."""
    return f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {length}\r\n\r\n".encode("ascii")
