"""Crib hazards: the CribHD-T YOLO model finds toys, and the baby's pose says whether they are close to the baby.

Safe-sleep guidance (AAP): keep the crib bare, with no toys, pillows, bumpers or loose bedding.
Ported from the hackathon ``test2.py`` ``process_frame``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from babycue_server.detection.geometry import covers_body, near_body
from babycue_server.detection.results import Hazard, PoseEstimate

PERSON_LABELS = {"person", "baby", "infant"}


class HazardDetector:
    def __init__(
        self,
        weights: Path,
        *,
        device: str = "auto",
        confidence: float = 0.65,
        imgsz: int = 640,
        near_margin: float = 0.25,
        suppress_body_overlap: bool = False,  # can hide a real object lying on the baby, so off by default
    ):
        from ultralytics import YOLO

        self.model = YOLO(str(weights))
        if self.model.task not in ("detect", "segment"):
            raise ValueError(f"{weights} is a {self.model.task} model; a detect or segment model is needed")
        if device == "auto":
            import torch

            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.half = device != "cpu"  # half precision: about twice as fast on a GPU, same detections
        self.confidence = confidence
        self.imgsz = imgsz
        self.near_margin = near_margin
        self.suppress_body_overlap = suppress_body_overlap

    @property
    def labels(self) -> list[str]:
        return list(self.model.names.values())

    def detect(self, frame: np.ndarray, pose: PoseEstimate | None) -> list[Hazard]:
        result = self.model.predict(
            frame, conf=self.confidence, device=self.device, imgsz=self.imgsz, half=self.half, verbose=False
        )[0]
        baby = pose.baby_box if pose is not None else None
        found: list[Hazard] = []
        for box in result.boxes.cpu():
            label = result.names[int(box.cls.item())]
            if label.lower() in PERSON_LABELS:
                continue
            bounds = tuple(float(v) for v in box.xyxy[0].tolist())
            # A "toy" box around the whole baby is usually the baby or their sleep sack, not a toy.
            if self.suppress_body_overlap and pose is not None and covers_body(bounds, baby, pose.points, pose.valid):
                continue
            found.append(Hazard(label, float(box.conf.item()), bounds, near_body(bounds, baby, self.near_margin)))
        return found
