"""FiDIP infant pose (HRNet-W48, 384×288): the fallback when MediaPipe cannot find the baby's torso.

Ported from the hackathon ``test2_fidip.py``. The model code beside this file is vendored; see ``NOTICE.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "w48_384x288_infant.yaml"
#: Left/right COCO joint pairs, swapped back after the flip test.
PAIRS = [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10], [11, 12], [13, 14], [15, 16]]


class FiDIP:
    def __init__(self, weights: Path, *, device: str = "auto", flip_test: bool = False):
        import torch

        from babycue_server.detection.fidip.config import _C
        from babycue_server.detection.fidip.hrnet import PoseHighResolutionNet

        self.torch = torch
        self.cfg = _C.clone()
        self.cfg.merge_from_file(str(CONFIG))
        self.cfg.freeze()
        self.size = tuple(int(v) for v in self.cfg.MODEL.IMAGE_SIZE)  # width, height
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        elif device.isdecimal():  # the YOLO-style GPU index, e.g. "0"
            device = f"cuda:{device}"
        self.device = torch.device(device)
        if self.device.type == "cuda":
            torch.backends.cudnn.benchmark = True  # the input size never changes, so the fastest kernels can be picked once
        self.model = PoseHighResolutionNet(self.cfg)
        state = torch.load(str(weights), map_location="cpu", weights_only=True)
        self.model.load_state_dict(state, strict=True)
        self.model.to(self.device).eval()
        self.flip = flip_test
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device)[None, :, None, None]
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device)[None, :, None, None]
        log.info("FiDIP loaded on %s", self.device)

    def predict(self, rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Keypoints normalized to the image (17×2) and their heatmap peaks (not probabilities)."""
        from babycue_server.detection.fidip.inference import get_final_preds
        from babycue_server.detection.fidip.transforms import flip_back, get_affine_transform

        torch = self.torch
        h, w = rgb.shape[:2]
        center = np.array([(w - 1) / 2, (h - 1) / 2], dtype=np.float32)
        aspect = self.size[0] / self.size[1]
        scale = np.array([max(w, h * aspect), max(h, w / aspect)], dtype=np.float32) / 200 * 1.25
        crop = cv2.warpAffine(rgb, get_affine_transform(center, scale, 0, self.size), self.size)
        x = torch.from_numpy(crop.copy()).permute(2, 0, 1)[None].to(self.device, dtype=torch.float32) / 255
        x = (x - self.mean) / self.std
        with torch.inference_mode():
            _, heatmaps = self.model(x)
            hm = heatmaps.cpu().numpy()
            if self.flip:
                _, flipped = self.model(torch.flip(x, [3]))
                hm = (hm + flip_back(flipped.cpu().numpy(), PAIRS)) / 2
        if hm.shape[1] != 17 or not np.isfinite(hm).all():
            raise RuntimeError("FiDIP did not produce 17 finite heatmaps")
        points, scores = get_final_preds(self.cfg, hm, center[None], scale[None])
        return points[0] / np.array([w, h]), scores[0, :, 0]
