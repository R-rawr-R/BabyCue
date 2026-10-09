"""A stand-in input phone: pushes a clearly labelled synthetic test pattern to the server.

Used by the automated tests and for trying the server without a phone. Every frame is stamped
"SYNTHETIC TEST PATTERN" so it cannot be mistaken for a real camera feed.

    python -m babycue_server.devtools.fake_input --server 127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import select
import socket
import threading
import time

import cv2
import numpy as np

from babycue_server.protocol import DEFAULT_PORT, INGEST_PATH, pack_frame


def render_pattern(
    index: int,
    width: int = 640,
    height: int = 480,
    *,
    brightness: float = 1.0,
    blur: int = 0,
) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width]
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[..., 0] = (x * 255 // max(1, width - 1)).astype(np.uint8)
    image[..., 1] = (y * 255 // max(1, height - 1)).astype(np.uint8)
    image[..., 2] = 96
    checker = ((x // 40 + y // 40) % 2).astype(bool)
    image[checker] = image[checker] // 2
    offset = (index * 8) % max(1, width - 80)
    cv2.rectangle(image, (offset, height // 2 - 40), (offset + 80, height // 2 + 40), (255, 255, 255), -1)
    cv2.putText(image, "SYNTHETIC TEST PATTERN", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
    cv2.putText(image, f"frame {index}", (20, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    if blur > 0:
        k = blur * 2 + 1
        image = cv2.GaussianBlur(image, (k, k), 0)
    if brightness != 1.0:
        image = np.clip(image.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
    return image


def encode_jpeg(image: np.ndarray, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


class IngestClient:
    """Speaks the input side of the wire protocol over a raw socket (what the Android app does)."""

    def __init__(self, host: str, port: int, *, timeout: float = 5.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock: socket.socket | None = None

    def connect(self) -> IngestClient:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        head = (
            f"POST {INGEST_PATH} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
            "Content-Type: application/octet-stream\r\nTransfer-Encoding: chunked\r\n\r\n"
        )
        self.sock.sendall(head.encode("ascii"))
        return self

    def send_chunk(self, payload: bytes) -> None:
        assert self.sock is not None
        self.sock.sendall(b"%x\r\n" % len(payload) + payload + b"\r\n")

    def send_frame(self, jpeg: bytes) -> None:
        self.send_chunk(pack_frame(jpeg))

    def response_status(self, wait: float = 0.0) -> int | None:
        """The HTTP status if the server has already replied (e.g. 409), else ``None``."""
        assert self.sock is not None
        readable, _, _ = select.select([self.sock], [], [], wait)
        if not readable:
            return None
        try:
            data = self.sock.recv(4096)
        except OSError:
            return None
        parts = data.split(b" ", 2)
        return int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None

    def finish(self) -> int | None:
        """End the body cleanly and return the server's status."""
        try:
            assert self.sock is not None
            self.sock.sendall(b"0\r\n\r\n")
        except OSError:
            pass
        return self.response_status(wait=2.0)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


class FakeInput:
    """Pushes the test pattern on a background thread until stopped."""

    def __init__(self, host: str, port: int, *, fps: float = 15.0, width: int = 640, height: int = 480):
        self.host, self.port, self.fps = host, port, fps
        self.width, self.height = width, height
        self.frames_sent = 0
        self.rejected_status: int | None = None
        self.sent: list[bytes] = []  # last few frames, so tests can compare what viewers received
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> FakeInput:
        self._thread = threading.Thread(target=self._run, name="fake-input", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(3)

    def _run(self) -> None:
        client = IngestClient(self.host, self.port)
        try:
            client.connect()
            index = 0
            while not self._stop.is_set():
                status = client.response_status()
                if status is not None:
                    self.rejected_status = status
                    return
                jpeg = encode_jpeg(render_pattern(index, self.width, self.height))
                client.send_frame(jpeg)
                self.sent = (self.sent + [jpeg])[-50:]
                self.frames_sent += 1
                index += 1
                self._stop.wait(1.0 / self.fps)
        except OSError:
            pass
        finally:
            client.close()

    def __enter__(self) -> FakeInput:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default=f"127.0.0.1:{DEFAULT_PORT}", help="host:port of the BabyCue server")
    parser.add_argument("--fps", type=float, default=15.0)
    args = parser.parse_args()
    host, _, port = args.server.partition(":")
    fake = FakeInput(host, int(port or DEFAULT_PORT), fps=args.fps).start()
    print(f"Pushing a synthetic test pattern to {args.server} (Ctrl+C to stop)")
    try:
        while fake._thread is not None and fake._thread.is_alive():
            time.sleep(0.5)
        if fake.rejected_status:
            print(f"The server rejected the stream with HTTP {fake.rejected_status}")
    except KeyboardInterrupt:
        pass
    finally:
        fake.stop()


if __name__ == "__main__":
    main()
