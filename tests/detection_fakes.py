"""Synthetic poses and fake models, so the safe-sleep logic is tested without loading any real model."""

from __future__ import annotations

import threading

import numpy as np

from babycue_server.detection.geometry import (
    LEFT_EYE,
    LEFT_HIP,
    LEFT_SHOULDER,
    NOSE,
    RIGHT_EYE,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    body_bounds,
)
from babycue_server.detection.results import Hazard, PoseEstimate


def make_pose(posture: str, source: str = "FiDIP") -> PoseEstimate:
    """A baby lying head-up in a 640×480 frame, keypoints in pixels. ``posture``: supine, side, prone or absent.

    Face-up, the baby's left shoulder is on the image right; face-down it is mirrored; on a side the shoulders
    overlap, one above the other.
    """
    points = np.full((17, 2), np.nan)
    scores = np.zeros(17)
    if posture != "absent":
        left, right = {"supine": ([360, 200], [280, 200]), "prone": ([280, 200], [360, 200])}.get(
            posture, ([325, 185], [315, 215])
        )
        points[LEFT_SHOULDER], points[RIGHT_SHOULDER] = left, right
        points[LEFT_HIP], points[RIGHT_HIP] = [left[0], 320], [right[0], 320]
        points[NOSE], points[LEFT_EYE], points[RIGHT_EYE] = [320, 150], [330, 140], [310, 140]
        scores[[LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, NOSE, LEFT_EYE, RIGHT_EYE]] = 0.9
    valid = scores >= 0.5
    return PoseEstimate(points, scores, valid, source, body_bounds(points, valid))


class FakePose:
    """Returns whatever posture the test sets; can be told to fail."""

    def __init__(self, posture: str = "supine"):
        self.posture = posture
        self.fail = False
        self.resets = 0
        self.calls = 0
        self.gate: threading.Event | None = None

    def estimate(self, frame, timestamp_ms):
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise RuntimeError("pose model exploded")
        return make_pose(self.posture)

    def reset(self):
        self.resets += 1


class FakeHazards:
    def __init__(self, hazards: list[Hazard] | None = None):
        self.hazards = hazards or []

    def detect(self, frame, pose):
        return list(self.hazards)


SOFT_TOY = Hazard("soft-toy", 0.82, (100.0, 100.0, 160.0, 160.0), True)
