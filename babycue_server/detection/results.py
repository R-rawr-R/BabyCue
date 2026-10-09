"""What the models report for one frame. Plain data, so the safe-sleep logic can be tested without any model."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PoseEstimate:
    """One infant's COCO-17 keypoints in pixels of the analyzed frame."""

    points: np.ndarray  # (17, 2) pixels
    scores: np.ndarray  # (17,)
    valid: np.ndarray  # (17,) bool
    source: str  # "MediaPipe" or "FiDIP"
    baby_box: list[float] | None = None  # pixels, only when the whole torso was found


@dataclass(frozen=True)
class Hazard:
    """An object the crib-hazard model found, e.g. ``soft-toy``."""

    label: str
    score: float
    box: tuple[float, float, float, float]  # pixels
    near_baby: bool | None  # None when the baby's position is unknown
