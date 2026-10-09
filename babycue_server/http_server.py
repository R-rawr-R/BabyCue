"""HTTP relay: accepts one input phone's frame stream and fans it out to output viewers."""

from __future__ import annotations

import json
import logging
import os
import mimetypes
import select
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

from babycue_server.bodyreader import ChunkedSource, IdleTimeout, ServerStopping, SocketSource, read_exact
from babycue_server.db import Database
from babycue_server.hub import FrameHub
from babycue_server.pipeline import FramePipeline
from babycue_server.protocol import (
    BABY_PATH,
    CA_PATH,
    DETECTIONS_PATH,
    DEFAULT_PORT,
    FRAME_LEASE_S,
    FRAME_PATH,
    INGEST_PATH,
    JPEG_MAGIC,
    LENGTH_PREFIX_BYTES,
    MAX_FRAME_BYTES,
    MAX_VIEWERS,
    PART_TAIL,
    STATUS_PATH,
    VIEW_CONTENT_TYPE,
    VIEW_PATH,
    VIEW_PREAMBLE,
    VIEW_SEND_BUFFER,
    part_head,
    unpack_length,
)

if TYPE_CHECKING:
    from babycue_server.detection.worker import DetectionWorker

log = logging.getLogger(__name__)

_FALLBACK_HTML = (
    b"<!doctype html><meta charset=utf-8><title>BabyCue server</title>"
    b"<body style='margin:0;background:#111;color:#ddd;font-family:sans-serif'>"
    b"<p style='padding:8px'>BabyCue relay. <a style='color:#8cf' href='/status'>status</a> "
    b"&middot; the app is not built yet: run <code>npm run build</code> in <code>web/</code></p>"
    b"<img src='/view' style='max-width:100%'></body>"
)

class _ProtocolViolation(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class _Httpd(ThreadingHTTPServer):
    daemon_threads = True
    ssl_context: ssl.SSLContext | None = None

    def get_request(self):
        sock, addr = super().get_request()
        if self.ssl_context is not None:
            # The handshake happens in the handler thread, so one slow client cannot stall accept().
            sock = self.ssl_context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

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
        web_root: Path | str | None = None,
        ca_path: Path | str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        detector: DetectionWorker | None = None,
        db: Database | None = None,
    ):
        self.host = host
        self.port = port
        self.hub = hub or FrameHub()
        self.pipeline = pipeline or FramePipeline()
        #: Safe-sleep analysis; it sees every frame after the pipeline and reports through ``/status``.
        self.detector = detector
        #: The baby's name and the detection log. Without a file it lives in memory and is lost on restart.
        self.db = db or Database(":memory:")
        if detector is not None:
            self.pipeline = FramePipeline([*self.pipeline.stages, detector.submit])
            self.hub.on_input_released = detector.reset
            detector.on_event = lambda event: self.db.log_detection(**event)
        self.input_timeout = input_timeout
        #: The built website (``web/dist``) served at ``/``; without it a bare test page is shown.
        self.web_root = Path(web_root).resolve() if web_root else None
        #: The local CA certificate offered at ``/ca.crt`` so a phone can trust this server.
        self.ca_path = Path(ca_path) if ca_path else None
        self.ssl_context = ssl_context
        self._stopping = threading.Event()
        self._httpd: _Httpd | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> RelayServer:
        if self.detector is not None:
            self.detector.start()
        self._httpd = _Httpd((self.host, self.port), _make_handler(self))
        self._httpd.ssl_context = self.ssl_context
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
        if self.detector is not None:
            self.detector.stop()

    def __enter__(self) -> RelayServer:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def status(self) -> dict:
        """What ``GET /status`` returns. Detection results are only included while a camera is connected."""
        stats = self.hub.stats()
        if self.detector is not None:
            found = self.detector.snapshot() if stats["input_connected"] else {}
            stats["alert"] = found.get("alert")
            stats["detection"] = found.get("detection")
        return stats


def _client_gone(conn: socket.socket) -> bool:
    """True if the peer has closed its end. A viewer sends nothing after its request, so a read means EOF."""
    try:
        readable, _, _ = select.select([conn], [], [], 0)
        if not readable:
            return False
        if isinstance(conn, ssl.SSLSocket):
            return conn.recv(1) == b""  # MSG_PEEK is not allowed on TLS sockets
        return conn.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


def _make_handler(owner: RelayServer) -> type[BaseHTTPRequestHandler]:
    hub = owner.hub

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        rbufsize = 0  # no read-ahead: the ingest body is read straight from the socket
        timeout = 15  # a kept-alive connection that goes quiet is closed

        _tls_ok = True

        def setup(self):
            if isinstance(self.request, ssl.SSLSocket):
                self.request.settimeout(10)
                try:
                    self.request.do_handshake()
                except OSError as exc:  # includes ssl.SSLError: a client that does not trust the certificate
                    log.info("TLS handshake with %s failed: %s", self.client_address[0], exc)
                    self._tls_ok = False
                    return
                self.request.settimeout(None)
            super().setup()

        def handle(self):
            if self._tls_ok:
                super().handle()

        def finish(self):
            if self._tls_ok:
                super().finish()

        def log_message(self, format, *args):  # noqa: A002
            log.debug("%s %s", self.address_string(), format % args)

        def log_error(self, format, *args):  # noqa: A002
            log.info("%s %s", self.address_string(), format % args)

        def _send(
            self, status: int, body: bytes = b"", content_type: str = "text/plain", keep_alive: bool = False, **headers: str
        ) -> None:
            self.close_connection = not keep_alive
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "keep-alive" if keep_alive else "close")
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
                body = json.dumps(owner.status()).encode()
                self._send(200, body, "application/json", Cache_Control="no-cache")
            elif path == CA_PATH:
                self._send_ca()
            elif path == BABY_PATH:
                self._json(200, {"baby": owner.db.baby()})
            elif path == DETECTIONS_PATH:
                try:
                    limit = int(parse_qs(urlsplit(self.path).query).get("limit", ["100"])[0])
                except ValueError:
                    limit = 100
                self._json(200, {"detections": owner.db.detections(limit)})
            else:
                self._static(path)

        def _json(self, status: int, value: object) -> None:
            self._send(status, json.dumps(value).encode(), "application/json", Cache_Control="no-cache")

        def _name_baby(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json(411, {"error": "Content-Length required"})
                return
            if not 0 < length <= 1024:
                self._json(413 if length > 0 else 400, {"error": 'Send {"name": "..."}'})
                return
            try:
                body = read_exact(SocketSource(self.connection, idle_timeout=owner.input_timeout), length)
            except (EOFError, IdleTimeout, OSError):
                return
            try:
                name = json.loads(body)["name"]
            except (ValueError, KeyError, TypeError):
                name = None
            if not isinstance(name, str):
                self._json(400, {"error": 'Send {"name": "..."}'})
                return
            try:
                baby = owner.db.set_baby_name(name)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            log.info("Baby named %r", baby["name"])
            self._json(200, {"baby": baby})

        def _send_ca(self) -> None:
            ca = owner.ca_path
            if ca is None or not ca.is_file():
                self._send(404, b"No certificate on this server" + bytes([10]))
                return
            self._send(
                200, ca.read_bytes(), "application/x-x509-ca-cert", Content_Disposition='attachment; filename="babycue-ca.crt"'
            )

        def _static(self, path: str) -> None:
            root = owner.web_root
            if root is None or not (root / "index.html").is_file():
                if path == "/":
                    self._send(200, _FALLBACK_HTML, "text/html")
                else:
                    self._send(404, b"Not found" + bytes([10]))
                return
            target = (root / unquote(path).lstrip("/")).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                # Only page-like paths fall back to the app; a missing file or API call is a real 404.
                if "." in Path(path).name or path.startswith("/assets/"):
                    self._send(404, b"Not found" + bytes([10]))
                    return
                target = root / "index.html"
            try:
                data = target.read_bytes()
            except OSError:
                self._send(404, b"Not found" + bytes([10]))
                return
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix == ".webmanifest":
                kind = "application/manifest+json"
            if kind.startswith("text/") or kind in ("application/javascript", "application/manifest+json"):
                kind += "; charset=utf-8"
            immutable = path.startswith("/assets/")
            self._send(200, data, kind, Cache_Control="public, max-age=31536000, immutable" if immutable else "no-cache")

        def _view(self) -> None:
            if not hub.add_viewer(MAX_VIEWERS):
                self._send(503, b"Too many viewers\n", Retry_After="2")
                return
            try:
                self.close_connection = True
                self.connection.settimeout(10)  # a viewer that stops reading releases its slot
                self._no_delay()
                try:
                    # A small send buffer makes a slow viewer block here, so the hub skips stale pictures
                    # instead of the OS queueing several of them on the way to the phone.
                    self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, VIEW_SEND_BUFFER)
                except OSError:
                    pass
                self.send_response(200)
                self.send_header("Content-Type", VIEW_CONTENT_TYPE)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(VIEW_PREAMBLE)
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
            path = urlsplit(self.path).path
            if path == FRAME_PATH:
                self._frame()
                return
            if path == BABY_PATH:
                self._name_baby()
                return
            if path != INGEST_PATH:
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

        def _frame(self) -> None:
            """One JPEG per request, for phones that cannot hold a streaming upload open."""
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send(411, b"Content-Length required\n")
                return
            if length <= 0 or length > MAX_FRAME_BYTES:
                self._send(413 if length > 0 else 400, b"Bad frame length\n")
                return
            was_live = hub.stats()["input_connected"]
            if not hub.claim_frame_input(self.client_address[0], FRAME_LEASE_S):
                log.warning("Frame from %s refused: another input holds the slot", self.client_address[0])
                self._send(409, b"Another input is already streaming\n")
                self._drain()
                return
            source = SocketSource(
                self.connection,
                should_stop=lambda: hub.closed or owner.stopping,
                idle_timeout=owner.input_timeout,
            )
            try:
                data = read_exact(source, length)
            except (EOFError, IdleTimeout, ServerStopping, OSError) as exc:
                log.info("Frame upload ended early: %s", exc or type(exc).__name__)
                return
            if not data.startswith(JPEG_MAGIC):
                hub.count_bad_frame()
                self._reply_quietly(400, b"Not a JPEG\n")
                return
            # Renew the lease now the picture is in: a slow upload must not let it lapse mid-request.
            if not hub.claim_frame_input(self.client_address[0], FRAME_LEASE_S):
                self._reply_quietly(409, b"Another input is already streaming\n")
                return
            hub.publish(owner.pipeline.process(data))
            if not was_live:
                log.info("Frame input connected from %s", self.client_address[0])
            # Keep the connection: a phone sends many pictures a second, and a new TLS handshake for each would
            # add delay. The next request reuses this one.
            self._no_delay()
            self._reply_quietly(204, b"", keep_alive=True)

        def _no_delay(self) -> None:
            """Send small writes at once instead of waiting to batch them (lower delay for video)."""
            try:
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass

        def _reply_quietly(self, status: int, body: bytes, keep_alive: bool = False) -> None:
            try:
                self._send(status, body, keep_alive=keep_alive)
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
