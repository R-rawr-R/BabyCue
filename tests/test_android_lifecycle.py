"""Stream lifecycle of the real StreamWorker against a replica of the Android server's wire format.

Same scope as test_android_protocol.py: the receiver (StreamWorker -> MjpegStream -> MjpegParser,
real sockets) is the real code; the sender is ``LiveAndroidServer``, a byte-level replica of
Android's MjpegServer (see that module's docstring). Not an end-to-end test of the Android app,
and not a substitute for the manual phone-to-PC checklist.
"""

from __future__ import annotations

import socket
import threading
import time

from babycue_camera.capture import ConnectionState, StreamWorker
from babycue_camera.config import parse_stream_url
from tests.conftest import wait_until
from tests.test_android_protocol import make_jpeg, part, stream_response_head


class LiveAndroidServer:
    """Streams a new frame every ``1/fps`` s until stopped; can be stopped and restarted on one port."""

    def __init__(self, port: int = 0, fps: float = 25.0):
        self.fps = fps
        self.inject: list[bytes] = []  # raw byte chunks sent instead of the next frame (one-shot)
        self.drop_with: bytes | None = None  # one-shot: send these bytes, then close the connection
        self._port = port
        self._listener: socket.socket | None = None
        self._clients: set[socket.socket] = set()
        self._lock = threading.Lock()
        self._running = False

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}/video"

    def start(self) -> LiveAndroidServer:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self._port))
        sock.listen(4)
        self._port = sock.getsockname()[1]
        self._listener = sock
        self._running = True
        threading.Thread(target=self._accept, args=(sock,), daemon=True).start()
        return self

    def stop(self) -> None:
        """Like Android's MjpegServer.stop(): close the listener and every client connection."""
        self._running = False
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()

    def _accept(self, listener: socket.socket) -> None:
        while self._running:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with self._lock:
                self._clients.add(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(3)
            head = b""
            while not head.endswith(b"\r\n\r\n"):
                chunk = conn.recv(1024)
                if not chunk:
                    return
                head += chunk
            conn.sendall(stream_response_head())
            index = 0
            while self._running:
                dropping, self.drop_with = self.drop_with, None
                if dropping is not None:
                    conn.sendall(dropping)  # e.g. half a frame, then the link dies
                    return
                if self.inject:
                    conn.sendall(self.inject.pop(0))
                else:
                    conn.sendall(part(make_jpeg(index)))
                    index += 1
                time.sleep(1.0 / self.fps)
        except OSError:
            pass
        finally:
            with self._lock:
                self._clients.discard(conn)
            try:
                conn.close()
            except OSError:
                pass


def run_worker(url: str, **kw) -> StreamWorker:
    worker = StreamWorker(parse_stream_url(url), reconnect_initial_delay=0.1, reconnect_max_delay=0.4, **kw)
    worker.start()
    return worker


def test_worker_receives_consecutive_frames_from_android_format():
    srv = LiveAndroidServer().start()
    worker = run_worker(srv.url)
    try:
        assert wait_until(lambda: worker.stats().frames_received >= 10)
        stats = worker.stats()
        assert stats.state is ConnectionState.STREAMING
        assert stats.resolution == (64, 48)
        assert stats.frames_malformed == 0
        assert worker.latest_frame().image.shape == (48, 64, 3)
    finally:
        worker.stop()
        srv.stop()


def test_server_stop_is_detected_and_restart_reconnects():
    srv = LiveAndroidServer().start()
    port = srv.port
    worker = run_worker(srv.url)
    try:
        assert wait_until(lambda: worker.stats().frames_received >= 5)
        srv.stop()  # phone app backgrounded / server stopped
        assert wait_until(lambda: worker.stats().state is ConnectionState.RECONNECTING)
        assert wait_until(lambda: "refused" in worker.stats().message.lower(), timeout=3)
        srv = LiveAndroidServer(port).start()  # phone app back in the foreground
        before = worker.stats().frames_received
        assert wait_until(lambda: worker.stats().frames_received > before + 5, timeout=8)
        stats = worker.stats()
        assert stats.state is ConnectionState.STREAMING
        assert stats.reconnect_attempts >= 1
    finally:
        worker.stop()
        srv.stop()


def test_retries_while_server_is_down_are_paced_by_backoff():
    srv = LiveAndroidServer().start()
    worker = run_worker(srv.url)
    try:
        assert wait_until(lambda: worker.stats().frames_received >= 3)
        srv.stop()
        assert wait_until(lambda: worker.stats().state is ConnectionState.RECONNECTING)
        base = worker.stats().reconnect_attempts
        time.sleep(2.0)
        made = worker.stats().reconnect_attempts - base
        # delays 0.1, 0.2, 0.4, 0.4 ... => at most ~7 in 2 s; a tight loop would make hundreds.
        assert made <= 12, f"{made} reconnect attempts in 2 s"
        assert made >= 3
    finally:
        worker.stop()


def test_corrupt_frame_is_counted_and_streaming_continues():
    srv = LiveAndroidServer().start()
    worker = run_worker(srv.url)
    try:
        assert wait_until(lambda: worker.stats().frames_received >= 3)
        srv.inject.append(part(b"this is not a jpeg" * 8))  # valid framing, invalid JPEG
        assert wait_until(lambda: worker.stats().frames_malformed == 1)
        before = worker.stats().frames_received
        assert wait_until(lambda: worker.stats().frames_received > before + 5)
        assert worker.stats().state is ConnectionState.STREAMING
        assert worker.latest_frame() is not None
    finally:
        worker.stop()
        srv.stop()


def test_truncated_frame_then_drop_never_shows_a_partial_image_and_recovers():
    srv = LiveAndroidServer().start()
    worker = run_worker(srv.url)
    try:
        assert wait_until(lambda: worker.stats().frames_received >= 3)
        cut = part(make_jpeg(7, 320, 240))
        srv.drop_with = cut[: len(cut) // 2]
        received_before = worker.stats().frames_received
        assert wait_until(lambda: worker.stats().reconnect_attempts >= 1, timeout=5)
        assert wait_until(lambda: worker.stats().frames_received > received_before + 5, timeout=8)
        stats = worker.stats()
        assert stats.state is ConnectionState.STREAMING
        # No 320x240 frame can have been produced from the cut-off part.
        assert stats.resolution == (64, 48)
    finally:
        worker.stop()
        srv.stop()


def test_memory_stays_bounded_while_streaming_fast():
    srv = LiveAndroidServer(fps=100).start()
    worker = run_worker(srv.url)
    try:
        assert wait_until(lambda: worker.stats().frames_received >= 150, timeout=10)
        # Only the newest frame is kept, and the fps window holds at most ~window*fps timestamps.
        assert worker._frame_times.maxlen is None and len(worker._frame_times) < 400
        assert worker.latest_frame().seq == worker.stats().frames_received
    finally:
        worker.stop()
        srv.stop()


def test_stop_while_reconnecting_exits_quickly():
    srv = LiveAndroidServer().start()
    worker = run_worker(srv.url)
    assert wait_until(lambda: worker.stats().frames_received >= 3)
    srv.stop()
    assert wait_until(lambda: worker.stats().state is ConnectionState.RECONNECTING)
    started = time.monotonic()
    assert worker.stop(timeout=3)
    assert time.monotonic() - started < 1.0
    assert not worker.is_alive()
    assert worker.stats().state is ConnectionState.STOPPED
