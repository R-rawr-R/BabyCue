"""Runs the safe-sleep models beside the relay, so slow inference never delays the video.

``submit`` is a :class:`~babycue_server.pipeline.FramePipeline` stage: it keeps only the newest JPEG and returns it
unchanged. A background thread analyses whatever is newest, and ``snapshot`` gives ``/status`` the result.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

import cv2
import numpy as np

from babycue_server.detection.posture import PostureReading, PostureTracker, classify_posture
from babycue_server.detection.results import Hazard, PoseEstimate
from babycue_server.detection.rules import HazardTracker, evaluate, friendly_label

log = logging.getLogger(__name__)


#: How each confirmed sleep position is filed in the log.
POSTURE_LEVEL = {"supine": "ok", "side": "warn", "prone": "crit", "unknown": "warn"}

#: ``on_event`` receives keyword arguments for :meth:`babycue_server.db.Database.log_detection`.
DetectionEvent = dict


class PoseModel(Protocol):
    def estimate(self, frame: np.ndarray, timestamp_ms: int) -> PoseEstimate: ...

    def reset(self) -> None: ...


class HazardModel(Protocol):
    def detect(self, frame: np.ndarray, pose: PoseEstimate | None) -> list[Hazard]: ...


def _decode(jpeg: bytes) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


class DetectionWorker:
    def __init__(
        self,
        pose_model: PoseModel,
        hazard_model: HazardModel,
        *,
        stability_frames: int = 8,
        stale_after_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.pose_model = pose_model
        self.hazard_model = hazard_model
        self.stale_after_s = stale_after_s
        self._clock = clock
        self._posture = PostureTracker(stability_frames)
        self._hazards = HazardTracker()
        self._cond = threading.Condition()
        self._pending: bytes | None = None
        self._generation = 0  # bumped by reset(); results from an older generation are dropped
        self._pose_generation = 0  # the generation the pose model last tracked (worker thread only)
        self._pose_generation = 0  # the generation the pose model last tracked (worker thread only)
        self._reading: PostureReading | None = None
        self._confirmed: list[Hazard] = []
        self._analysed_at: float | None = None
        self._last_ms = -1
        self._running = False
        self._thread: threading.Thread | None = None
        self.analysed = 0
        self.failures = 0
        #: Called (on the detection thread, outside any lock) for every detection event worth logging.
        self.on_event: Callable[[DetectionEvent], None] | None = None
        self._logged_posture: str | None = None
        self._logged_hazards: dict[str, Hazard] = {}
        self._logged_alert: str | None = None

    # -- lifecycle -----------------------------------------------------------------------------

    def start(self) -> DetectionWorker:
        with self._cond:
            if self._running:
                return self
            self._running = True
        self._thread = threading.Thread(target=self._run, name="babycue-detect", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None

    def reset(self) -> None:
        """Forget everything seen so far, e.g. when the baby phone disconnects."""
        with self._cond:
            self._generation += 1
            self._pending = None
            self._reading = None
            self._confirmed = []
            self._analysed_at = None
            self._posture.reset()
            self._hazards.reset()
            self._logged_posture = None
            self._logged_hazards = {}
            self._logged_alert = None

    # -- frame stage ---------------------------------------------------------------------------

    def submit(self, jpeg: bytes) -> bytes:
        with self._cond:
            self._pending = jpeg  # an older frame still waiting is simply replaced
            self._cond.notify_all()
        return jpeg

    # -- results -------------------------------------------------------------------------------

    def snapshot(self) -> dict:
        """``{"alert", "detection"}`` for ``/status``; both ``None`` when there is no fresh analysis."""
        now = self._clock()
        with self._cond:
            fresh = self._running and self._analysed_at is not None and now - self._analysed_at <= self.stale_after_s
            if not fresh:
                return {"alert": None, "detection": None}
            reading, hazards = self._reading, list(self._confirmed)
        posture = None
        if reading is not None:
            posture = {
                "label": reading.label,
                "source": reading.source,
                "since_s": int(max(0.0, now - reading.since)),
                "stable": reading.stable,
            }
        return {
            "alert": evaluate(reading, hazards, now),
            "detection": {
                "posture": posture,
                "hazards": [
                    {"label": h.label, "score": round(h.score, 2), "near_baby": h.near_baby} for h in hazards
                ],
            },
        }

    # -- background thread ---------------------------------------------------------------------

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._running and self._pending is None:
                    self._cond.wait()
                if not self._running:
                    return
                jpeg, self._pending, generation = self._pending, None, self._generation
            try:
                self._analyse(jpeg, generation)
            except Exception:  # noqa: BLE001 - a model failure must never stop the worker
                self.failures += 1
                if self.failures == 1 or self.failures % 100 == 0:
                    log.exception("Safe-sleep analysis failed (%d so far); continuing", self.failures)

    def _analyse(self, jpeg: bytes, generation: int) -> None:
        frame = _decode(jpeg)
        if frame is None:
            return
        now = self._clock()
        # MediaPipe's video mode needs strictly increasing timestamps.
        timestamp_ms = max(self._last_ms + 1, int(now * 1000))
        self._last_ms = timestamp_ms
        with self._cond:
            if generation != self._generation:
                return
        if generation != self._pose_generation:  # a new input: don't track the pose across it
            self.pose_model.reset()
            self._pose_generation = generation
        pose = self.pose_model.estimate(frame, timestamp_ms)
        hazards = self.hazard_model.detect(frame, pose)
        label = classify_posture(pose)
        with self._cond:
            if generation != self._generation:
                return  # the input went away while we were busy
            self._reading = self._posture.update(label, pose.source, now)
            self._confirmed = self._hazards.update(hazards)
            self._analysed_at = now
            self.analysed += 1
            events = self._new_events(now)
        if self.on_event is not None:
            for event in events:
                try:
                    self.on_event(event)
                except Exception:  # noqa: BLE001 - a full disk must not stop the alerts
                    log.exception("Could not log a detection")

    def _new_events(self, now: float) -> list[DetectionEvent]:
        """What changed since the last logged state: a confirmed position, a toy coming or going, a new alert.

        Called under the lock. Logging changes rather than every analysis keeps a night's log readable.
        """
        events: list[DetectionEvent] = []
        reading = self._reading
        if reading is not None and reading.stable and reading.label != self._logged_posture:
            self._logged_posture = reading.label
            events.append(
                {"kind": "posture", "label": reading.label, "level": POSTURE_LEVEL.get(reading.label), "source": reading.source}
            )
        current = {h.label: h for h in self._confirmed}
        for name, hazard in current.items():
            if name not in self._logged_hazards:
                where = "near baby" if hazard.near_baby else "in view"
                events.append(
                    {
                        "kind": "hazard",
                        "label": name,
                        "detail": f"{friendly_label(name)} {where}",
                        "level": "warn",
                        "score": round(hazard.score, 2),
                    }
                )
        for name in self._logged_hazards.keys() - current.keys():
            events.append({"kind": "hazard-cleared", "label": name, "detail": f"{friendly_label(name)} gone", "level": "ok"})
        self._logged_hazards = current
        alert = evaluate(reading, self._confirmed, now)
        title = alert["title"] if alert else None
        if title != self._logged_alert:
            self._logged_alert = title
            if alert is not None:
                events.append({"kind": "alert", "label": alert["title"], "detail": alert["detail"], "level": alert["level"]})
        return events
