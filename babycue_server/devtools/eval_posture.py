"""Measure the sleep-position classifier on labelled photos and print a confusion matrix.

Each photo's label is the start of its file name (``Prone_3.jpg`` -> prone, ``Side.jpg`` -> side, ``Supine_1.jpg``).

    python -m babycue_server.devtools.eval_posture PHOTO_DIR [--source auto|mediapipe|fidip]
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from babycue_server.detection import DEFAULT_MODELS_DIR, FIDIP_WEIGHTS, POSE_MODEL
from babycue_server.detection.posture import classify_posture

LABELS = ("supine", "side", "prone")
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def label_of(path: Path) -> str | None:
    match = re.match(r"(prone|side|supine)", path.stem.lower())
    return match.group(1) if match else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("photos", type=Path)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--source", choices=["auto", "mediapipe", "fidip"], default="auto")
    parser.add_argument("--device", default="auto")
    args = parser.parse_args(argv)

    from babycue_server.detection.pose import BabyPose

    pose = BabyPose(args.models_dir / POSE_MODEL, args.models_dir / FIDIP_WEIGHTS, device=args.device, video=False)
    results: list[tuple[str, str, str]] = []
    for path in sorted(args.photos.iterdir()):
        truth = label_of(path)
        if truth is None or path.suffix.lower() not in IMAGE_TYPES:
            continue
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"skip (unreadable): {path.name}")
            continue
        pose.reset()  # every photo is a new scene
        estimate = pose.estimate(frame, 0, force_fallback=args.source == "fidip")
        if args.source == "mediapipe" and estimate.source != "MediaPipe":
            got = "unknown"  # MediaPipe alone could not find the torso
        else:
            got = classify_posture(estimate)
        results.append((truth, got, estimate.source))

    columns = (*LABELS, "unknown")
    counts = Counter((truth, got) for truth, got, _ in results)
    print(f"\n{len(results)} photos, pose source: {args.source}")
    print("truth \\ got " + "".join(f"{c:>9}" for c in columns))
    for truth in LABELS:
        print(f"{truth:<12}" + "".join(f"{counts[(truth, c)]:>9}" for c in columns))
    correct = sum(counts[(t, t)] for t in LABELS)
    decided = sum(1 for _, got, _ in results if got != "unknown")
    print(f"accuracy {correct}/{len(results)} = {correct / max(1, len(results)):.0%}")
    print(f"accuracy when decided {correct}/{decided} = {correct / max(1, decided):.0%}")
    recall = np.mean([counts[(t, t)] / max(1, sum(counts[(t, c)] for c in columns)) for t in LABELS])
    print(f"mean per-class recall {recall:.0%}")
    print("sources:", dict(Counter(source for _, _, source in results)))
    pose.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
