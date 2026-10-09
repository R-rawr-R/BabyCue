"""Thread-safe hand-off between the one input phone and any number of output viewers."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Frame:
    data: bytes
    seq: int
    timestamp: float


class FrameHub:
    """Keeps only the newest frame, so a slow viewer skips frames instead of building a backlog."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, fps_window_s: float = 2.0):
        self._clock = clock
        self._fps_window = fps_window_s
        self._cond = threading.Condition()
        self._latest: Frame | None = None
        self._seq = 0
        self._input_active = False
        self._viewers = 0
        self._bad_frames = 0
        self._times: deque[float] = deque()
        self._closed = False

    # -- input side ---------------------------------------------------------------------------

    def claim_input(self) -> bool:
        with self._cond:
            if self._input_active or self._closed:
                return False
            self._input_active = True
            return True

    def release_input(self) -> None:
        with self._cond:
            self._input_active = False
            self._latest = None
            self._times.clear()
            self._cond.notify_all()

    def publish(self, data: bytes) -> Frame:
        now = self._clock()
        with self._cond:
            self._seq += 1
            self._latest = Frame(data, self._seq, now)
            self._times.append(now)
            self._trim(now)
            self._cond.notify_all()
            return self._latest

    def count_bad_frame(self) -> None:
        with self._cond:
            self._bad_frames += 1

    # -- viewer side --------------------------------------------------------------------------

    def add_viewer(self, limit: int) -> bool:
        with self._cond:
            if self._viewers >= limit or self._closed:
                return False
            self._viewers += 1
            return True

    def remove_viewer(self) -> None:
        with self._cond:
            self._viewers = max(0, self._viewers - 1)

    def latest(self) -> Frame | None:
        with self._cond:
            return self._latest

    def await_next(self, after_seq: int, timeout: float) -> Frame | None:
        """The newest frame whose ``seq`` is greater than ``after_seq``, or ``None`` on timeout/close."""
        deadline = self._clock() + timeout
        with self._cond:
            while not self._closed:
                if self._latest is not None and self._latest.seq > after_seq:
                    return self._latest
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
            return None

    # -- lifecycle / stats --------------------------------------------------------------------

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def stats(self) -> dict:
        now = self._clock()
        with self._cond:
            self._trim(now)
            fps = 0.0
            if len(self._times) >= 2 and self._times[-1] > self._times[0]:
                fps = (len(self._times) - 1) / (self._times[-1] - self._times[0])
            return {
                "input_connected": self._input_active,
                "frames": self._seq,
                "bad_frames": self._bad_frames,
                "fps": round(fps, 1),
                "viewers": self._viewers,
            }

    def _trim(self, now: float) -> None:
        cutoff = now - self._fps_window
        while self._times and self._times[0] < cutoff:
            self._times.popleft()
