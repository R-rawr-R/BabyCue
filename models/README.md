# Safe-sleep models

The server loads these by default (`--models-dir models`). They are stored with Git LFS: run `git lfs install` once, before you clone or pull.

| File | What it does | Source |
|---|---|---|
| `pose_landmarker_lite.task` | MediaPipe Pose Landmarker (lite). The main infant pose model; it gives the sleep position. | Google MediaPipe, Apache-2.0 |
| `hrnet_fidip.pth` | FiDIP HRNet-W48 infant pose. Used as the fallback when MediaPipe cannot find the torso (covered or unusual poses). | FiDIP, Northeastern University. **Non-commercial use only**; see `babycue_server/detection/fidip/NOTICE.md` |
| `cribhd_t_best_20261009.pt` | YOLO26n-seg trained on CribHD-T. It finds objects in the crib: `hard-toy` and `soft-toy`. | Trained for the AppBuilders 2026 hackathon (`train_cribhd_yolo26.ipynb`) |

Each file is a copy of the hackathon model, so BabyCue does not need any files outside this repository.
