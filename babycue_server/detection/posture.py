"""Sleep position from keypoints, and a tracker that only reports a roll-over once it has lasted.

Safe-sleep guidance (AAP): a baby should sleep on their back. Side and tummy positions raise the risk of SIDS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from babycue_server.detection.geometry import LEFT_HIP, LEFT_SHOULDER, RIGHT_HIP, RIGHT_SHOULDER, TORSO
from babycue_server.detection.results import PoseEstimate

Posture = Literal["supine", "side", "prone", "unknown"]

# Thresholds on ``facing`` (see below), calibrated on the 104 labelled hackathon photos with
# ``python -m babycue_server.devtools.eval_posture``: 70% correct with MediaPipe (tummy found 24/34, a back
# mistaken for tummy 1/34) and 62% with FiDIP alone, against 55% and 40% for depth/face-visibility rules.
# Side-lying is the hardest: it is often read as back.
PRONE_BELOW = -0.65
SIDE_BELOW = 0.8


def facing(pose: PoseEstimate) -> float | None:
    """Which way the chest faces, from the order of the left and right shoulders around the spine.

    Seen from above, a baby on their back has their left shoulder on one side of the hip-to-shoulder line; face-down
    mirrors it. The value is the sine of the angle between that line and the right-to-left shoulder line:
    about +1 on the back, about -1 on the tummy, and in between on a side, where the shoulders overlap and skew.
    Rotation of the camera does not change it. ``None`` without a whole torso.
    """
    points, valid = pose.points, pose.valid
    if not valid[TORSO].all():
        return None
    spine = (points[LEFT_SHOULDER] + points[RIGHT_SHOULDER]) / 2 - (points[LEFT_HIP] + points[RIGHT_HIP]) / 2
    shoulders = points[LEFT_SHOULDER] - points[RIGHT_SHOULDER]
    size = float(np.hypot(*spine) * np.hypot(*shoulders))
    if not size > 0:
        return None
    return float(spine[0] * shoulders[1] - spine[1] * shoulders[0]) / size


def classify_posture(pose: PoseEstimate) -> Posture:
    """Back (``supine``), ``side``, tummy (``prone``), or ``unknown`` when the torso was not found."""
    value = facing(pose)
    if value is None:
        return "unknown"
    if value < PRONE_BELOW:
        return "prone"
    if value < SIDE_BELOW:
        return "side"
    return "supine"


@dataclass(frozen=True)
class PostureReading:
    label: Posture
    source: str
    since: float  # clock time the label started
    stable: bool  # held for the whole stability window


class PostureTracker:
    """Reports a new position only after ``stability_frames`` analyses in a row agree (a roll-over that lasted).

    Ported from the notebook's ``RollOverDetector``: a single odd frame never flips the reported position.
    """

    def __init__(self, stability_frames: int = 8):
        if stability_frames < 1:
            raise ValueError("stability_frames must be at least 1")
        self.stability_frames = stability_frames
        self.reset()

    def reset(self) -> None:
        self._stable: PostureReading | None = None
        self._candidate: Posture | None = None
        self._candidate_since = math.nan
        self._count = 0

    def update(self, label: Posture, source: str, now: float) -> PostureReading:
        if label != self._candidate:
            self._candidate, self._candidate_since, self._count = label, now, 0
        self._count += 1
        if self._count >= self.stability_frames:
            if self._stable is None or self._stable.label != label:
                self._stable = PostureReading(label, source, self._candidate_since, True)
            elif self._stable.source != source:
                self._stable = PostureReading(label, source, self._stable.since, True)
        if self._stable is not None:
            return self._stable
        return PostureReading(label, source, self._candidate_since, False)
