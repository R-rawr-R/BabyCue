"""Keypoint helpers shared by the pose models and the hazard check. Points are COCO-17, one row per joint.

Ported from the hackathon ``test2.py`` so MediaPipe and FiDIP keypoints are judged the same way.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

NOSE, LEFT_EYE, RIGHT_EYE = 0, 1, 2
LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP = 5, 6, 11, 12
TORSO = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]
FACE = [NOSE, LEFT_EYE, RIGHT_EYE]

#: MediaPipe's 33 pose landmarks picked out in COCO-17 order.
MP_TO_COCO = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]

Box = Sequence[float]  # x0, y0, x1, y1


def valid_points(points: np.ndarray, scores: np.ndarray, threshold: float) -> np.ndarray:
    """Which points to trust: finite, confident enough and inside the [0, 1] normalized image."""
    return (
        np.isfinite(points).all(axis=1)
        & np.isfinite(scores)
        & (scores >= threshold)
        & (points >= 0).all(axis=1)
        & (points <= 1).all(axis=1)
    )


def body_bounds(points: np.ndarray, valid: np.ndarray) -> list[float] | None:
    """The box around the trusted points, but only when the whole torso was found."""
    if not valid[TORSO].all():
        return None
    low, high = points[valid].min(axis=0), points[valid].max(axis=0)
    return [*low.tolist(), *high.tolist()] if (high > low).all() else None


def near_body(box: Box, baby: Box | None, margin: float) -> bool | None:
    """Whether ``box`` is within ``margin`` of the baby's diagonal; ``None`` when the baby was not found."""
    if baby is None:
        return None
    dx = max(baby[0] - box[2], box[0] - baby[2], 0)
    dy = max(baby[1] - box[3], box[1] - baby[3], 0)
    return bool(math.hypot(dx, dy) <= margin * math.hypot(baby[2] - baby[0], baby[3] - baby[1]))


def covers_body(box: Box, baby: Box | None, points: np.ndarray, valid: np.ndarray) -> bool:
    """Heuristic for a 'toy' box that is really the whole baby (e.g. a swaddle), not a semantic test."""
    if baby is None or valid.sum() < 8:
        return False
    inside = (points[:, 0] >= box[0]) & (points[:, 0] <= box[2]) & (points[:, 1] >= box[1]) & (points[:, 1] <= box[3])
    area = (baby[2] - baby[0]) * (baby[3] - baby[1])
    ratio = (box[2] - box[0]) * (box[3] - box[1]) / area
    return bool(inside[TORSO].all() and inside[valid].mean() >= 0.85 and 0.75 <= ratio <= 1.8)
