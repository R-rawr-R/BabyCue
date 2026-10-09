"""Safe-sleep logic: sleep position, roll-over stability, hazard confirmation and the alert it all becomes."""

import numpy as np
import pytest

from babycue_server.detection.geometry import body_bounds, near_body, valid_points
from babycue_server.detection.posture import PostureReading, PostureTracker, classify_posture, facing
from babycue_server.detection.results import Hazard, PoseEstimate
from babycue_server.detection.rules import (
    HAZARD_TITLE,
    PRONE_TITLE,
    SIDE_TITLE,
    HazardTracker,
    evaluate,
    format_duration,
)
from tests.detection_fakes import SOFT_TOY, make_pose

# -- geometry -----------------------------------------------------------------------------------


def test_points_outside_the_image_or_unsure_are_not_trusted():
    points = np.array([[0.5, 0.5], [1.2, 0.5], [0.5, 0.5], [np.nan, 0.1]])
    scores = np.array([0.9, 0.9, 0.1, 0.9])
    assert valid_points(points, scores, 0.5).tolist() == [True, False, False, False]


def test_the_baby_box_needs_the_whole_torso():
    assert body_bounds(make_pose("supine").points, make_pose("supine").valid) == [280.0, 140.0, 360.0, 320.0]
    assert make_pose("absent").baby_box is None


def test_near_body_is_relative_to_the_baby_size():
    baby = [0, 0, 30, 40]  # diagonal 50
    assert near_body([35, 0, 40, 10], baby, 0.25) is True  # 5 px away
    assert near_body([100, 0, 110, 10], baby, 0.25) is False
    assert near_body([0, 0, 1, 1], None, 0.25) is None


# -- posture ------------------------------------------------------------------------------------


@pytest.mark.parametrize("posture", ["supine", "side", "prone"])
def test_each_position_is_recognised_from_the_shoulders(posture):
    assert classify_posture(make_pose(posture)) == posture


def test_no_torso_means_unknown_never_a_guess():
    assert classify_posture(make_pose("absent")) == "unknown"


def test_facing_ignores_how_the_camera_is_turned():
    pose = make_pose("prone")
    turn = np.array([[0.0, -1.0], [1.0, 0.0]])  # 90 degrees
    turned = PoseEstimate(pose.points @ turn.T, pose.scores, pose.valid, pose.source)
    assert facing(pose) == pytest.approx(-1.0)
    assert facing(turned) == pytest.approx(-1.0)
    assert classify_posture(turned) == "prone"


def test_a_roll_over_is_reported_only_once_it_has_lasted():
    tracker = PostureTracker(stability_frames=3)
    for t in range(3):
        reading = tracker.update("supine", "MediaPipe", float(t))
    assert reading == PostureReading("supine", "MediaPipe", 0.0, True)
    # One odd frame and a short run do not flip it.
    assert tracker.update("prone", "FiDIP", 10.0).label == "supine"
    assert tracker.update("prone", "FiDIP", 11.0).label == "supine"
    reading = tracker.update("prone", "FiDIP", 12.0)
    assert (reading.label, reading.since, reading.stable) == ("prone", 10.0, True)


def test_before_anything_is_stable_the_reading_says_so():
    reading = PostureTracker(stability_frames=5).update("side", "FiDIP", 1.0)
    assert reading.label == "side" and not reading.stable


# -- hazards and alerts -------------------------------------------------------------------------


def test_a_toy_counts_only_when_seen_in_most_recent_frames():
    tracker = HazardTracker(window=5, need=3)
    assert tracker.update([SOFT_TOY]) == []
    assert tracker.update([]) == []
    assert tracker.update([SOFT_TOY]) == []
    assert tracker.update([SOFT_TOY]) == [SOFT_TOY]
    for _ in range(3):
        tracker.update([])
    assert tracker.confirmed() == []


def test_lying_face_down_is_critical():
    alert = evaluate(PostureReading("prone", "FiDIP", 0.0, True), [SOFT_TOY], 75.0)
    assert alert == {"level": "crit", "title": PRONE_TITLE, "detail": "Lying face-down for 1 min · FiDIP"}


def test_side_lying_is_a_warning_and_outranks_toys():
    alert = evaluate(PostureReading("side", "MediaPipe", 0.0, True), [SOFT_TOY], 12.0)
    assert alert["level"] == "warn" and alert["title"] == SIDE_TITLE


def test_a_toy_is_a_warning_only():
    far = Hazard("hard-toy", 0.7, (0, 0, 1, 1), False)
    alert = evaluate(PostureReading("supine", "MediaPipe", 0.0, True), [SOFT_TOY, far], 5.0)
    assert alert == {
        "level": "warn",
        "title": HAZARD_TITLE,
        "detail": "Soft toy near baby (82%) · Hard toy in view (70%)",
    }


def test_an_unconfirmed_position_or_back_sleeping_raises_nothing():
    assert evaluate(PostureReading("prone", "FiDIP", 0.0, False), [], 9.0) is None
    assert evaluate(PostureReading("supine", "FiDIP", 0.0, True), [], 9.0) is None
    assert evaluate(None, [], 9.0) is None


def test_durations_read_naturally():
    assert [format_duration(s) for s in (5, 59, 61, 3725)] == ["5 s", "59 s", "1 min", "1 h 2 min"]
