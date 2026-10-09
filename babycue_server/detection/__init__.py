"""Safe-sleep detection: sleep position (back / side / tummy) and toys in the crib, from the baby phone's video.

The pure logic (``geometry``, ``posture``, ``rules``, ``worker``) needs only numpy and OpenCV. The models
(``pose``, ``hazards``, ``fidip``) need the ``ml`` extra: ``pip install -e .[ml]``.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
POSE_MODEL = "pose_landmarker_lite.task"
FIDIP_WEIGHTS = "hrnet_fidip.pth"
HAZARD_MODEL = "cribhd_t_best_20261009.pt"
ML_PACKAGES = ("mediapipe", "torch", "ultralytics", "yacs")


def resolve_device(setting: str) -> str:
    """``"cuda:N"`` or ``"cpu"`` for a ``--device`` value (``auto``, ``cpu``, ``cuda``, ``cuda:N`` or ``N``).

    ``auto`` takes the first GPU when PyTorch can use one. Asking for a GPU that is not there is an error,
    not a quiet fall back to the much slower CPU.
    """
    import torch

    setting = setting.strip().lower()
    if setting == "cpu":
        return "cpu"
    if setting == "auto":
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    index = setting.removeprefix("cuda").lstrip(":") or "0"
    if not index.isdecimal():
        raise ValueError(f"Unknown device {setting!r}: use auto, cpu, cuda or a GPU index such as 0")
    if not torch.cuda.is_available():
        raise RuntimeError(
            f"--device {setting} needs a GPU, but this PyTorch ({torch.__version__}) cannot use CUDA. "
            "Install the CUDA build: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126"
        )
    if int(index) >= torch.cuda.device_count():
        raise RuntimeError(f"--device {setting}: there are only {torch.cuda.device_count()} GPU(s)")
    return f"cuda:{index}"


def describe_device(device: str) -> str:
    if device == "cpu":
        return "CPU"
    import torch

    return f"{torch.cuda.get_device_name(torch.device(device))} ({device})"


def missing_packages() -> list[str]:
    return [name for name in ML_PACKAGES if importlib.util.find_spec(name) is None]


def missing_models(models_dir: Path) -> list[Path]:
    paths = [models_dir / POSE_MODEL, models_dir / FIDIP_WEIGHTS, models_dir / HAZARD_MODEL]
    # A Git LFS pointer that was never pulled is a small text file, not a model.
    return [p for p in paths if not p.is_file() or p.stat().st_size < 1024]


@dataclass(frozen=True)
class DetectionSettings:
    models_dir: Path = DEFAULT_MODELS_DIR
    device: str = "auto"
    yolo_confidence: float = 0.65
    mp_threshold: float = 0.5
    fidip_threshold: float = 0.2
    stability_frames: int = 8


def build_worker(settings: DetectionSettings):
    """Load every model (slow: a few seconds) and return a ready, not yet started, ``DetectionWorker``."""
    import numpy as np

    from babycue_server.detection.hazards import HazardDetector
    from babycue_server.detection.pose import BabyPose
    from babycue_server.detection.worker import DetectionWorker

    device = resolve_device(settings.device)
    d = settings.models_dir
    pose = BabyPose(
        d / POSE_MODEL,
        d / FIDIP_WEIGHTS,
        device=device,
        mp_threshold=settings.mp_threshold,
        fidip_threshold=settings.fidip_threshold,
    )
    hazards = HazardDetector(d / HAZARD_MODEL, device=device, confidence=settings.yolo_confidence)
    # The first GPU inference sets up CUDA kernels and takes seconds; do it now, not on the baby's first frames.
    blank = np.zeros((360, 480, 3), np.uint8)
    pose.fidip.predict(blank)
    hazards.detect(blank, None)
    return DetectionWorker(pose, hazards, stability_frames=settings.stability_frames)
