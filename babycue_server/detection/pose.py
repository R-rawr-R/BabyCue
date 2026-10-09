"""Infant pose: MediaPipe first, FiDIP when MediaPipe loses the torso. Ported from the hackathon ``test2.py``.

MediaPipe is fast but was trained on adults. FiDIP is an infant model and takes over until MediaPipe has found the
torso again for ``recovery_frames`` frames in a row.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from babycue_server.detection.geometry import MP_TO_COCO, TORSO, body_bounds, valid_points
from babycue_server.detection.results import PoseEstimate

log = logging.getLogger(__name__)


class BabyPose:
    def __init__(
        self,
        pose_model: Path,
        fidip_weights: Path,
        *,
        device: str = "auto",
        mp_threshold: float = 0.5,
        fidip_threshold: float = 0.2,
        recovery_frames: int = 5,
        video: bool = True,
    ):
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

        from babycue_server.detection.fidip.estimator import FiDIP

        self.mp_threshold = mp_threshold
        self.fidip_threshold = fidip_threshold
        self.recovery_frames = recovery_frames
        self.video = video
        self._landmarker = PoseLandmarker.create_from_options(
            PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(pose_model)),
                running_mode=RunningMode.VIDEO if video else RunningMode.IMAGE,
                num_poses=1,
            )
        )
        # Loaded up front so a bad weights file fails at start-up, not at night when it is first needed.
        self.fidip = FiDIP(fidip_weights, device=device)
        self.reset()

    def reset(self) -> None:
        self._fallback_active = False
        self._recovery = 0

    def close(self) -> None:
        self._landmarker.close()

    def estimate(self, frame: np.ndarray, timestamp_ms: int, *, force_fallback: bool = False) -> PoseEstimate:
        import mediapipe as mp

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        if self.video:
            result = self._landmarker.detect_for_video(image, timestamp_ms)
        else:
            result = self._landmarker.detect(image)
        points, scores = np.zeros((17, 2)), np.zeros(17)
        if result.pose_landmarks:
            landmarks = [result.pose_landmarks[0][i] for i in MP_TO_COCO]
            points = np.array([[p.x, p.y] for p in landmarks])
            scores = np.array([min(p.visibility or 0, p.presence or 0) for p in landmarks])
        valid = valid_points(points, scores, self.mp_threshold)
        ready = bool(valid[TORSO].all() and valid.sum() >= 6)
        if not ready:
            self._fallback_active, self._recovery = True, 0
        elif self._fallback_active:
            self._recovery += 1
            if self._recovery >= self.recovery_frames:
                self._fallback_active, self._recovery = False, 0
        source = "MediaPipe"
        if self._fallback_active or force_fallback:
            points, scores = self.fidip.predict(rgb)
            valid = valid_points(points, scores, self.fidip_threshold)
            source = "FiDIP"
        pixels = points * np.array([w, h])
        return PoseEstimate(
            points=pixels,
            scores=scores,
            valid=valid,
            source=source,
            baby_box=body_bounds(pixels, valid),
        )
