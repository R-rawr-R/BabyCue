"""The real models in models/ load with the vendored code and run end to end (skipped without the ml extra)."""

import pytest

from babycue_server.detection import DEFAULT_MODELS_DIR, DetectionSettings, missing_models, missing_packages

pytestmark = pytest.mark.skipif(
    bool(missing_packages() or missing_models(DEFAULT_MODELS_DIR)),
    reason="needs pip install -e .[ml] and the model files (git lfs pull)",
)


@pytest.fixture(scope="module")
def worker():
    from babycue_server.detection import build_worker

    return build_worker(DetectionSettings(device="cpu"))


def test_the_models_load_and_know_their_classes(worker):
    assert worker.hazard_model.labels == ["hard-toy", "soft-toy"]
    assert worker.pose_model.fidip.model is not None  # the FiDIP weights match the vendored HRNet (strict load)


def test_a_frame_without_a_baby_is_unknown_and_claims_nothing(worker):
    from babycue_server.detection.posture import classify_posture
    from babycue_server.devtools.fake_input import render_pattern

    frame = render_pattern(0, 480, 360)
    pose = worker.pose_model.estimate(frame, 1)
    assert classify_posture(pose) == "unknown"
    assert worker.hazard_model.detect(frame, pose) == []
