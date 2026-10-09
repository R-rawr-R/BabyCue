"""Protocol compatibility: Android BabyCue MJPEG wire format -> the real Python receiver.

What this is, precisely
-----------------------
The Android server (``android/.../server/MjpegProtocol.kt`` + ``MjpegServer.kt``) is Kotlin and
cannot run inside pytest. ``AndroidWireServer`` below is therefore a *byte-level replica* of what
that code writes to the socket (HTTP/1.1, ``Connection: close``, no Content-Length on the stream
response, ``--babycueframe`` parts with Content-Type + Content-Length, CRLF after each JPEG,
plain-text error responses). Everything on the *receiving* side is the real code under test:
``MjpegParser`` and ``MjpegStream`` (requests/urllib3 over a real TCP socket).

This is a protocol-compatibility test, NOT an end-to-end test of the Android app. The replica is
kept honest by ``test_wire_constants_match_android_source`` (skipped when the Android sources
are not checked out next to the Python package) and by the Android-side ``MjpegProtocolTest`` /
``MjpegServerTest`` that pin the same strings.
"""

from __future__ import annotations

import re
import socket
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from babycue_camera.config import parse_stream_url
from babycue_camera.stream import (
    MjpegParser,
    MjpegStream,
    StreamEnded,
    StreamHttpError,
    StreamTimeout,
)
from babycue_camera.stream.mjpeg import boundary_from_content_type

# ---- Android wire format (mirrors MjpegProtocol.kt) ------------------------------------------
BOUNDARY = "babycueframe"
CRLF = b"\r\n"
STREAM_CONTENT_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"


def stream_response_head() -> bytes:
    return (
        "HTTP/1.1 200 OK\r\n"
        f"Content-Type: {STREAM_CONTENT_TYPE}\r\n"
        "Cache-Control: no-cache, no-store, must-revalidate\r\n"
        "Pragma: no-cache\r\n"
        "Connection: close\r\n\r\n"
    ).encode("latin-1")


def part_head(length: int) -> bytes:
    return f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {length}\r\n\r\n".encode("latin-1")


def part(jpeg: bytes) -> bytes:
    return part_head(len(jpeg)) + jpeg + CRLF


def error_response(status: int, reason: str, extra: list[tuple[str, str]] | None = None) -> bytes:
    body = f"{status} {reason}\r\n".encode("latin-1")
    head = (
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain; charset=iso-8859-1\r\n"
        f"Content-Length: {len(body)}\r\n"
    )
    for k, v in extra or []:
        head += f"{k}: {v}\r\n"
    return (head + "Connection: close\r\n\r\n").encode("latin-1") + body


# ---- helpers ---------------------------------------------------------------------------------
def make_jpeg(index: int, width: int = 64, height: int = 48) -> bytes:
    """A real, decodable JPEG whose content differs per index."""
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[..., 0] = (index * 40) % 256
    image[..., 1] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    cv2.rectangle(image, (index % 8, 5), (index % 8 + 20, 25), (255, 255, 255), -1)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    return buf.tobytes()


def decode(jpeg: bytes):
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


class AndroidWireServer:
    """Replica of the Android server's bytes on a real localhost socket (see module docstring).

    ``chunks`` are written after the stream head for GET /video; then the connection is either
    closed (``then="close"``, what the phone does on stop) or left silent (``then="hold"``).
    Any other path gets the Android 404 response.
    """

    def __init__(self, chunks=(), then="close", respond=None):
        self.chunks = list(chunks)
        self.then = then
        self.respond = respond  # optional fixed bytes sent instead of the stream (for HTTP errors)
        self.requests: list[bytes] = []
        self._stop = threading.Event()
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/video"

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(3)
            head = b""
            while not head.endswith(b"\r\n\r\n"):
                data = conn.recv(1024)
                if not data:
                    return
                head += data
            self.requests.append(head)
            path = head.split(b" ", 2)[1].split(b"?")[0]
            if self.respond is not None:
                conn.sendall(self.respond)
            elif path != b"/video":
                conn.sendall(error_response(404, "Not Found"))
            else:
                conn.sendall(stream_response_head())
                for chunk in self.chunks:
                    conn.sendall(chunk)
                    time.sleep(0.002)
                if self.then == "hold":
                    self._stop.wait(10)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


def consume(stream: MjpegStream, limit: float = 5.0):
    """Drain ``stream.frames()`` on a thread. Returns (frames, terminal_exception_or_None).

    Fails the test if the iterator neither ends nor raises within ``limit`` seconds (a hang).
    """
    frames: list[bytes] = []
    outcome: list[BaseException | None] = []

    def run():
        try:
            for f in stream.frames():
                frames.append(f)
            outcome.append(None)
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            outcome.append(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(limit)
    if t.is_alive():
        stream.abort()
        t.join(2)
        raise AssertionError(f"stream.frames() did not terminate within {limit} s")
    return frames, outcome[0]


def open_stream(url: str, **kw) -> MjpegStream:
    stream = MjpegStream(parse_stream_url(url), connect_timeout=2.0, read_timeout=kw.pop("read_timeout", 2.0), **kw)
    stream.open()
    return stream


# ---- parser level: exact Android bytes into the real MjpegParser -----------------------------
def test_boundary_is_taken_from_the_android_content_type():
    assert boundary_from_content_type(STREAM_CONTENT_TYPE) == BOUNDARY


@pytest.mark.parametrize("chunk", [None, 1, 3, 7, 1460])
def test_parser_decodes_consecutive_android_parts(chunk):
    jpegs = [make_jpeg(i) for i in range(5)]
    data = b"".join(part(j) for j in jpegs)
    parser = MjpegParser(boundary_from_content_type(STREAM_CONTENT_TYPE))
    out: list[bytes] = []
    if chunk is None:
        out = parser.feed(data)
    else:
        for i in range(0, len(data), chunk):
            out.extend(parser.feed(data[i : i + chunk]))
    assert out == jpegs  # byte-identical, in order, none merged or lost
    for jpeg in out:
        assert jpeg[:2] == b"\xff\xd8" and jpeg[-2:] == b"\xff\xd9"
        image = decode(jpeg)
        assert image is not None and image.shape == (48, 64, 3)


def test_last_frame_is_delivered_without_a_following_delimiter():
    # The Android server sends no closing delimiter; the final part must not wait for one.
    jpeg = make_jpeg(1)
    assert MjpegParser(BOUNDARY).feed(part(jpeg)) == [jpeg]


def test_payload_containing_the_delimiter_text_is_not_split():
    # Content-Length framing must protect the payload even if its bytes look like a delimiter.
    payload = b"\xff\xd8" + b"x" + f"\r\n--{BOUNDARY}\r\n".encode() + b"y" * 20 + b"\xff\xd9"
    assert MjpegParser(BOUNDARY).feed(part(payload) + part(make_jpeg(0))) == [payload, make_jpeg(0)]


def test_incomplete_part_yields_nothing_until_complete():
    jpeg = make_jpeg(2)
    data = part(jpeg)
    parser = MjpegParser(BOUNDARY)
    assert parser.feed(data[:-30]) == []  # truncated mid-JPEG: no partial frame is emitted
    assert parser.feed(data[-30:]) == [jpeg]


def test_resynchronises_after_a_truncated_part_when_a_new_delimiter_follows():
    # What a reconnect looks like if a stale tail were fed: the parser must not stay stuck.
    good = make_jpeg(3)
    parser = MjpegParser(BOUNDARY)
    out = parser.feed(part(make_jpeg(0))[:-40])  # incomplete, never finishes
    assert out == []
    # A fresh connection gets a fresh parser (MjpegStream creates one per open()).
    assert MjpegParser(BOUNDARY).feed(part(good)) == [good]


def test_corrupt_jpeg_with_valid_framing_passes_parser_but_fails_decode():
    # Framing is valid, payload is not a JPEG: the parser hands it on; the capture worker's
    # decode step is what rejects it (counted as a malformed frame).
    bad = b"this is not a jpeg" * 4
    out = MjpegParser(BOUNDARY).feed(part(bad) + part(make_jpeg(1)))
    assert out[0] == bad and decode(out[0]) is None
    assert decode(out[1]) is not None


# ---- over a real socket: MjpegStream (requests/urllib3 + parser) -----------------------------
def test_stream_receives_and_decodes_consecutive_frames():
    jpegs = [make_jpeg(i, 80, 60) for i in range(6)]
    with AndroidWireServer([part(j) for j in jpegs]) as srv:
        stream = open_stream(srv.url)
        try:
            assert stream.content_type == STREAM_CONTENT_TYPE
            frames, end = consume(stream)
        finally:
            stream.close()
    assert frames == jpegs
    assert all(decode(f).shape == (60, 80, 3) for f in frames)
    assert isinstance(end, StreamEnded)  # server closed after the last frame
    assert "closed" in str(end).lower()
    request = srv.requests[0].decode("latin-1")
    assert request.startswith("GET /video HTTP/1.1\r\n")


def test_frames_split_across_tcp_segments_are_reassembled():
    jpegs = [make_jpeg(i, 320, 240) for i in range(3)]
    data = b"".join(part(j) for j in jpegs)
    pieces = [data[i : i + 997] for i in range(0, len(data), 997)]
    with AndroidWireServer(pieces) as srv:
        stream = open_stream(srv.url)
        try:
            frames, end = consume(stream)
        finally:
            stream.close()
    assert frames == jpegs and isinstance(end, StreamEnded)


def test_wrong_endpoint_reports_http_404():
    with AndroidWireServer() as srv:
        stream = MjpegStream(parse_stream_url(srv.url.replace("/video", "/stream")), connect_timeout=2.0)
        with pytest.raises(StreamHttpError, match="404") as info:
            stream.open()
        stream.close()
    assert info.value.status == 404 and not info.value.retryable


def test_client_limit_503_is_reported_as_retryable():
    resp = error_response(503, "Service Unavailable", [("Retry-After", "2")])
    with AndroidWireServer(respond=resp) as srv:
        stream = MjpegStream(parse_stream_url(srv.url), connect_timeout=2.0)
        with pytest.raises(StreamHttpError, match="503") as info:
            stream.open()
        stream.close()
    assert info.value.status == 503 and info.value.retryable


def test_connection_closed_mid_frame_ends_cleanly_without_a_partial_frame():
    good = [make_jpeg(0), make_jpeg(1)]
    cut = part(make_jpeg(2, 320, 240))
    cut = cut[: len(cut) // 2]
    with AndroidWireServer([part(j) for j in good] + [cut]) as srv:
        stream = open_stream(srv.url)
        try:
            started = time.monotonic()
            frames, end = consume(stream)
        finally:
            stream.close()
    assert frames == good  # the truncated third frame is never emitted
    assert isinstance(end, StreamEnded)
    assert time.monotonic() - started < 3


def test_server_closing_right_after_headers_ends_with_stream_ended():
    with AndroidWireServer([]) as srv:
        stream = open_stream(srv.url)
        try:
            frames, end = consume(stream)
        finally:
            stream.close()
    assert frames == [] and isinstance(end, StreamEnded)


def test_silent_server_times_out_instead_of_hanging():
    # The Android server sends headers then nothing while no camera frame exists.
    with AndroidWireServer([], then="hold") as srv:
        stream = open_stream(srv.url, read_timeout=0.5)
        try:
            started = time.monotonic()
            frames, end = consume(stream)
        finally:
            stream.close()
    assert frames == [] and isinstance(end, StreamTimeout)
    assert time.monotonic() - started < 3


def test_abort_unblocks_a_stream_that_is_waiting_for_frames():
    with AndroidWireServer([part(make_jpeg(0))], then="hold") as srv:
        stream = open_stream(srv.url, read_timeout=30)
        threading.Timer(0.3, stream.abort).start()
        try:
            started = time.monotonic()
            frames, end = consume(stream, limit=5)
        finally:
            stream.close()
    assert len(frames) == 1 and isinstance(end, StreamEnded)
    assert time.monotonic() - started < 3


def test_reopening_after_server_closed_gets_a_fresh_working_stream():
    # Phone stopped streaming, then started again on the same port: a new open() works.
    first = [make_jpeg(0)]
    with AndroidWireServer([part(j) for j in first]) as srv:
        s1 = open_stream(srv.url)
        frames1, end1 = consume(s1)
        s1.close()
        assert frames1 == first and isinstance(end1, StreamEnded)
        s2 = open_stream(srv.url)
        frames2, _ = consume(s2)
        s2.close()
    assert frames2 == first


# ---- drift guard against the Android source --------------------------------------------------
def test_wire_constants_match_android_source():
    root = Path(__file__).resolve().parents[1] / "android"
    kt = root / "app/src/main/java/com/babycue/camera/server/MjpegProtocol.kt"
    if not kt.exists():
        pytest.skip("Android sources not present next to the Python package")
    text = kt.read_text(encoding="utf-8")
    assert re.search(rf'BOUNDARY\s*=\s*"{BOUNDARY}"', text)
    assert 'STREAM_PATH = "/video"' in text
    for line in (
        '"HTTP/1.1 200 OK$CRLF"',
        '"Content-Type: multipart/x-mixed-replace; boundary=$BOUNDARY$CRLF"',
        '"Connection: close$CRLF"',
        '"--$BOUNDARY$CRLF"',
        '"Content-Type: image/jpeg$CRLF"',
        '"Content-Length: $jpegLength$CRLF"',
    ):
        assert line in text, f"Android protocol line changed: {line}"
