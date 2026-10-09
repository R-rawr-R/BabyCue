"""Client-side helpers for tests: a viewer that speaks the output side of the wire protocol."""

from __future__ import annotations

import json
import socket
import threading
import urllib.request

from babycue_server.devtools.fake_input import encode_jpeg, render_pattern
from babycue_server.protocol import BOUNDARY, VIEW_PATH


def make_jpeg(index: int) -> bytes:
    """A real, decodable JPEG whose content differs per index."""
    return encode_jpeg(render_pattern(index, 160, 120))


def get_status(port: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=3) as response:
        return json.loads(response.read())


class Viewer:
    """Connects to ``/view`` and collects the JPEGs it receives, parsed strictly by Content-Length."""

    def __init__(self, port: int):
        self.port = port
        self.frames: list[bytes] = []
        self.status: int | None = None
        self.content_type: str | None = None
        self.error: Exception | None = None
        self.ended = threading.Event()
        self._sock: socket.socket | None = None
        self._thread = threading.Thread(target=self._run, name="test-viewer", daemon=True)

    def start(self) -> Viewer:
        self._sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self._sock.sendall(f"GET {VIEW_PATH} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        self._thread.start()
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._thread.join(3)

    def _read_until(self, buffer: bytearray, marker: bytes) -> int:
        while (index := buffer.find(marker)) < 0:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise EOFError
            buffer += chunk
        return index

    def _read_n(self, buffer: bytearray, n: int) -> bytes:
        while len(buffer) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise EOFError
            buffer += chunk
        data = bytes(buffer[:n])
        del buffer[:n]
        return data

    def _run(self) -> None:
        buffer = bytearray()
        try:
            end = self._read_until(buffer, b"\r\n\r\n")
            head = bytes(buffer[:end]).decode("latin-1")
            del buffer[: end + 4]
            self.status = int(head.split(" ", 2)[1])
            for line in head.split("\r\n")[1:]:
                if line.lower().startswith("content-type:"):
                    self.content_type = line.split(":", 1)[1].strip()
            if self.status != 200:
                return
            while True:
                end = self._read_until(buffer, b"\r\n\r\n")
                part_head = bytes(buffer[:end]).decode("latin-1")
                del buffer[: end + 4]
                assert f"--{BOUNDARY}" in part_head, part_head
                length = int(
                    next(
                        line.split(":")[1]
                        for line in part_head.split("\r\n")
                        if line.lower().startswith("content-length")
                    )
                )
                self.frames.append(self._read_n(buffer, length))
                assert self._read_n(buffer, 2) == b"\r\n"
        except (EOFError, OSError):
            pass
        except Exception as exc:  # noqa: BLE001 - surfaced to the test
            self.error = exc
        finally:
            self.ended.set()
