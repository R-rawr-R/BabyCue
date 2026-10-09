"""HTTP relay: accepts one input phone's frame stream and fans it out to output viewers."""

from __future__ import annotations

import json
import logging
import os
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from babycue_server.bodyreader import ChunkedSource, IdleTimeout, ServerStopping, SocketSource, read_exact
from babycue_server.hub import FrameHub
from babycue_server.pipeline import FramePipeline
from babycue_server.protocol import (
    DEFAULT_PORT,
    INGEST_PATH,
    JPEG_MAGIC,
    LENGTH_PREFIX_BYTES,
    MAX_FRAME_BYTES,
    MAX_VIEWERS,
    PART_TAIL,
    STATUS_PATH,
    VIEW_CONTENT_TYPE,
    VIEW_PATH,
    part_head,
    unpack_length,
)

log = logging.getLogger(__name__)

_INDEX_HTML = (
    b"<!doctype html><meta charset=utf-8><title>BabyCue server</title>"
    b"<body style='margin:0;background:#111;color:#ddd;font-family:sans-serif'>"
    b"<p style='padding:8px'>BabyCue relay. <a style='color:#8cf' href='/status'>status</a> "
    b"&middot; <a style='color:#8cf' href='/install'>install the Android app</a></p>"
    b"<img src='/view' style='max-width:100%'></body>"
)

APK_PATH = "/app.apk"
INSTALL_PATH = "/install"
APK_CONTENT_TYPE = "application/vnd.android.package-archive"


def _install_page(apk_available: bool) -> bytes:
    style = "font-family:sans-serif;max-width:32em;margin:2em auto;padding:0 1em;line-height:1.5"
    if apk_available:
        body = (
            f"<h1>Install BabyCue</h1><p><a href='{APK_PATH}' style='display:inline-block;padding:.8em 1.2em;"
            "background:#2a6;color:#fff;text-decoration:none;border-radius:6px'>Download the Android app</a></p>"
            "<ol><li>Open the downloaded <b>app-debug.apk</b>.</li>"
            "<li>If Android asks, allow <b>Install unknown apps</b> for this browser, "
            "then go back and tap Install.</li>"
            "<li>Open BabyCue, choose <b>Input</b> (camera) or <b>Output</b> (viewer), and enter this server's "
            "address.</li></ol><p>Only install apps from a network and a PC you trust: this download is plain "
            "unencrypted HTTP.</p>"
        )
    else:
        body = (
            "<h1>App not available</h1><p>This server has no Android app file to share. On the PC, build it "
            "(<code>gradlew assembleDebug</code> in <code>android/</code>) or start the server with "
            "<code>--apk path\\to\\app-debug.apk</code>.</p>"
        )
    head = "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
    return f"{head}<title>Install BabyCue</title><body style='{style}'>{body}</body>".encode()


class _ProtocolViolation(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class _Httpd(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second process bind a port that is already in use.
    allow_reuse_address = os.name != "nt"


class RelayServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        *,
        hub: FrameHub | None = None,
        pipeline: FramePipeline | None = None,
        input_timeout: float = 10.0,
        apk_path: Path | str | None = None,
    ):
        self.host = host
        self.port = port
        self.hub = hub or FrameHub()
        self.pipeline = pipeline or FramePipeline()
        self.input_timeout = input_timeout
        #: The one file served at ``/app.apk`` so phones on the network can install the app from this server.
        self.apk_path = Path(apk_path) if apk_path else None
        self._stopping = threading.Event()
        self._httpd: _Httpd | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> RelayServer:
        self._httpd = _Httpd((self.host, self.port), _make_handler(self))
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.1}, name="babycue-http", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stopping.set()
        self.hub.close()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(2)

    def __enter__(self) -> RelayServer:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()


def _client_gone(conn: socket.socket) -> bool:
    """True if the peer has closed its end (readable with no data), without consuming anything."""
    try:
        readable, _, _ = select.select([conn], [], [], 0)
        return bool(readable) and conn.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


def _make_handler(owner: RelayServer) -> type[BaseHTTPRequestHandler]:
    hub = owner.hub

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        rbufsize = 0  # no read-ahead: the ingest body is read straight from the socket

        def log_message(self, format, *args):  # noqa: A002
            log.debug("%s %s", self.address_string(), format % args)

        def _send(self, status: int, body: bytes = b"", content_type: str = "text/plain", **headers: str) -> None:
            self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            for name, value in headers.items():
                self.send_header(name.replace("_", "-"), value)
            self.end_headers()
            self.wfile.write(body)

        # -- GET ------------------------------------------------------------------------------

        def do_GET(self):  # noqa: N802
            path = urlsplit(self.path).path
            if path == VIEW_PATH:
                self._view()
            elif path == STATUS_PATH:
                self._send(200, json.dumps(hub.stats()).encode(), "application/json", Cache_Control="no-cache")
            elif path == "/":
                self._send(200, _INDEX_HTML, "text/html")
            elif path == INSTALL_PATH:
                self._send(200, _install_page(self._apk() is not None), "text/html; charset=utf-8")
            elif path == APK_PATH:
                self._send_apk()
            else:
                self._send(404, b"Not found\n")

        def _apk(self) -> Path | None:
            apk = owner.apk_path
            return apk if apk is not None and apk.is_file() else None

        def _send_apk(self) -> None:
            apk = self._apk()
            if apk is None:
                self._send(404, b"No app file is available on this server\n")
                return
            try:
                data = apk.read_bytes()
            except OSError:
                self._send(404, b"No app file is available on this server\n")
                return
            self._send(200, data, APK_CONTENT_TYPE, Content_Disposition=f'attachment; filename="{apk.name}"')

        def _view(self) -> None:
            if not hub.add_viewer(MAX_VIEWERS):
                self._send(503, b"Too many viewers\n", Retry_After="2")
                return
            try:
                self.close_connection = True
                self.connection.settimeout(10)  # a viewer that stops reading releases its slot
                self.send_response(200)
                self.send_header("Content-Type", VIEW_CONTENT_TYPE)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                last = 0
                while not (hub.closed or owner.stopping):
                    frame = hub.await_next(last, 0.5)
                    if frame is None:
                        if _client_gone(self.connection):
                            break
                        continue
                    self.wfile.write(part_head(len(frame.data)) + frame.data + PART_TAIL)
                    last = frame.seq
            except OSError:
                pass
            finally:
                hub.remove_viewer()

        # -- POST /ingest ---------------------------------------------------------------------

        def do_POST(self):  # noqa: N802
            if urlsplit(self.path).path != INGEST_PATH:
                self._send(404, b"Not found\n")
                return
            if not hub.claim_input():
                self._send(409, b"Another input is already streaming\n")
                self._drain()
                return
            log.info("Input connected from %s", self.address_string())
            try:
                self._ingest()
            finally:
                hub.release_input()
                log.info("Input disconnected")

        def _ingest(self) -> None:
            source = SocketSource(
                self.connection,
                should_stop=lambda: hub.closed or owner.stopping,
                idle_timeout=owner.input_timeout,
            )
            if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
                source = ChunkedSource(source)
            try:
                while True:
                    prefix = read_exact(source, LENGTH_PREFIX_BYTES, eof_ok_at_start=True)
                    if not prefix:
                        break
                    length = unpack_length(prefix)
                    if length == 0 or length > MAX_FRAME_BYTES:
                        raise _ProtocolViolation(413 if length else 400, f"Bad frame length {length}")
                    data = read_exact(source, length)
                    if not data.startswith(JPEG_MAGIC):
                        hub.count_bad_frame()
                        continue
                    hub.publish(owner.pipeline.process(data))
            except _ProtocolViolation as exc:
                log.warning("Input rejected: %s", exc)
                self._reply_quietly(exc.status, f"{exc}\n".encode())
            except ValueError as exc:
                log.warning("Input sent a malformed body: %s", exc)
                self._reply_quietly(400, b"Malformed request body\n")
            except (EOFError, IdleTimeout, ServerStopping, OSError) as exc:
                log.info("Input stream ended: %s", exc or type(exc).__name__)
            else:
                self._reply_quietly(200, b"OK\n")

        def _reply_quietly(self, status: int, body: bytes) -> None:
            try:
                self._send(status, body)
            except OSError:
                pass

        def _drain(self) -> None:
            """After rejecting a request, let the client finish sending so it can read our reply."""
            deadline = time.monotonic() + 1.0
            try:
                self.connection.shutdown(socket.SHUT_WR)
                source = SocketSource(self.connection, idle_timeout=0.5)
                while source.read(65536) and time.monotonic() < deadline:
                    pass
            except (OSError, IdleTimeout):
                pass

    return Handler
