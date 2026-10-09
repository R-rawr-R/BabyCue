# Vendored third-party code: FiDIP / HRNet

These files are copied, with minimal changes, so BabyCue does not depend on any code outside this repository.

| File | Origin |
|---|---|
| `hrnet.py` | `lib/models/adaptive_pose_hrnet.py` |
| `transforms.py` | `lib/utils/transforms.py` |
| `inference.py` | `lib/core/inference.py` |
| `config.py` | `lib/config/default.py` |
| `w48_384x288_infant.yaml` | `experiments/coco/hrnet/w48_384x288_adam_lr1e-3_infant.yaml` |

Source: FiDIP, "Invariant Representation Learning for Infant Pose Estimation with Small Data" (Huang, Fu, Liu, Ostadabbas; Augmented Cognition Lab, Northeastern University), https://github.com/ostadabbas/Infant-Pose-Estimation. It builds on HRNet / Simple Baselines code (Copyright (c) Microsoft, MIT License; authors are in each file header) and on DARK decoding (Hanbin Dai, Feng Zhang).

## Licence

**The FiDIP code and the `hrnet_fidip.pth` weights are for non-commercial use only.** For other uses, contact the Augmented Cognition Lab at Northeastern University: http://www.northeastern.edu/ostadabbas/

## BabyCue changes

- Package-relative imports (`from .transforms import ...`).
- In `hrnet.py`, `is '*'` was changed to `== '*'` (a string identity check warns on Python 3.12+).
- In `inference.py`, the Taylor (DARK) step uses plain arrays instead of the deprecated `np.matrix`. The maths is the same.
- `estimator.py` is BabyCue's own wrapper, ported from the hackathon `test2_fidip.py`.
