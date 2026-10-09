"""Wire contract between the server and the phone app.

The TypeScript mirror is ``mobile/src/net/wireProtocol.ts``; ``tests/test_wire_contract.py`` fails if the
two drift apart.

* Input phone -> server: ``POST /frame`` with one JPEG as the body (what the React Native app sends), or
  ``POST /ingest``, one long chunked body of ``[uint32 big-endian length][JPEG]`` records.
* Server -> output phone: ``GET /view``, ``multipart/x-mixed-replace`` with a Content-Length per part.
"""

from __future__ import annotations

import struct

DEFAULT_PORT = 8080
INGEST_PATH = "/ingest"
FRAME_PATH = "/frame"
VIEW_PATH = "/view"
STATUS_PATH = "/status"
CA_PATH = "/ca.crt"
#: GET: ``{"baby": {"name", "created_at"} | null}``. POST ``{"name": "..."}`` names (or renames) the baby.
BABY_PATH = "/baby"
#: GET ``?limit=N``: ``{"detections": [...]}``, newest first, each with its local date and time.
DETECTIONS_PATH = "/detections"
BOUNDARY = "babycueframe"
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_VIEWERS = 4
#: Send buffer for a `/view` socket: about two pictures, so a slow viewer skips frames rather than lagging.
VIEW_SEND_BUFFER = 64 * 1024
#: A phone posting single frames keeps the input slot this long after its last frame.
FRAME_LEASE_S = 5.0
JPEG_MAGIC = b"\xff\xd8"

_LENGTH = struct.Struct(">I")
LENGTH_PREFIX_BYTES = _LENGTH.size

VIEW_CONTENT_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"
#: Sent once, right after the response headers.
VIEW_PREAMBLE = f"--{BOUNDARY}\r\n".encode("ascii")
#: Ends a picture *and* opens the next part. A browser only shows a part once it sees the boundary after it,
#: so sending the boundary straight away (not with the next picture) saves a whole frame of delay.
PART_TAIL = f"\r\n--{BOUNDARY}\r\n".encode("ascii")


def pack_frame(jpeg: bytes) -> bytes:
    """One ingest record: the length prefix followed by the JPEG."""
    return _LENGTH.pack(len(jpeg)) + jpeg


def unpack_length(prefix: bytes) -> int:
    return _LENGTH.unpack(prefix)[0]


def part_head(length: int) -> bytes:
    """Bytes that precede a JPEG in a ``/view`` response (the boundary was already sent with the last part)."""
    return f"Content-Type: image/jpeg\r\nContent-Length: {length}\r\n\r\n".encode("ascii")
