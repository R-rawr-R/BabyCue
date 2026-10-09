"""Reading a request body straight from the socket, in a way that can always be interrupted.

``rfile`` reads block in ``recv()``, and on Windows closing or shutting down a socket from another
thread does not wake a blocked ``recv()``. These readers instead wait in ``select()`` with a short
timeout and re-check a stop flag and an idle deadline, so a vanished phone or a server shutdown
always releases the handler thread.
"""

from __future__ import annotations

import select
import socket
import time
from collections.abc import Callable


class ServerStopping(Exception):
    """The server is shutting down."""


class IdleTimeout(TimeoutError):
    """No data arrived within the idle limit."""


class SocketSource:
    """``read(n)`` over a connected socket; ``b""`` means the peer closed the connection."""

    def __init__(
        self,
        conn: socket.socket,
        *,
        should_stop: Callable[[], bool] = lambda: False,
        idle_timeout: float = 10.0,
        poll_interval: float = 0.25,
    ):
        self._conn = conn
        self._should_stop = should_stop
        self._idle_timeout = idle_timeout
        self._poll = poll_interval

    def read(self, n: int) -> bytes:
        deadline = time.monotonic() + self._idle_timeout
        while True:
            if self._should_stop():
                raise ServerStopping
            pending = getattr(self._conn, "pending", None)  # TLS: decrypted bytes select() cannot see
            readable = bool(pending and pending()) or bool(select.select([self._conn], [], [], self._poll)[0])
            if readable:
                try:
                    return self._conn.recv(n)
                except (ConnectionResetError, ConnectionAbortedError):
                    return b""
            if time.monotonic() >= deadline:
                raise IdleTimeout(f"No data for {self._idle_timeout:g} s")


def read_exact(source, n: int, *, eof_ok_at_start: bool = False) -> bytes:
    """Read exactly ``n`` bytes. Clean EOF before the first byte returns ``b""`` if allowed;
    EOF after that raises ``EOFError`` (a truncated record)."""
    parts: list[bytes] = []
    got = 0
    while got < n:
        chunk = source.read(n - got)
        if not chunk:
            if got == 0 and eof_ok_at_start:
                return b""
            raise EOFError(f"Stream ended after {got} of {n} bytes")
        parts.append(chunk)
        got += len(chunk)
    return b"".join(parts)


class ChunkedSource:
    """Decodes an HTTP ``Transfer-Encoding: chunked`` body read from ``source``."""

    _MAX_LINE = 64

    def __init__(self, source):
        self._source = source
        self._left = 0
        self._done = False

    def read(self, n: int) -> bytes:
        if self._done:
            return b""
        if self._left == 0:
            size = self._read_chunk_size()
            if size == 0:
                self._skip_trailers()
                self._done = True
                return b""
            self._left = size
        chunk = self._source.read(min(n, self._left))
        if not chunk:
            raise EOFError("Connection closed inside a chunk")
        self._left -= len(chunk)
        if self._left == 0:
            self._expect_crlf()
        return chunk

    def _read_line(self) -> bytes:
        line = bytearray()
        while len(line) <= self._MAX_LINE:
            byte = read_exact(self._source, 1)
            line += byte
            if line.endswith(b"\r\n"):
                return bytes(line[:-2])
        raise ValueError("Chunk header line too long")

    def _read_chunk_size(self) -> int:
        line = self._read_line()
        try:
            return int(line.split(b";", 1)[0].strip(), 16)
        except ValueError:
            raise ValueError(f"Bad chunk size {line[:20]!r}") from None

    def _expect_crlf(self) -> None:
        if read_exact(self._source, 2) != b"\r\n":
            raise ValueError("Missing CRLF after chunk")

    def _skip_trailers(self) -> None:
        while self._read_line():
            pass
