"""The detection worker beside the relay, with fake models: fresh results only, never stale or invented ones."""

import threading

import pytest

from babycue_server.detection.rules import HAZARD_TITLE, PRONE_TITLE
from babycue_server.detection.worker import DetectionWorker
from babycue_server.devtools.fake_input import FakeInput
from babycue_server.http_server import RelayServer
from tests.conftest import wait_until
from tests.detection_fakes import SOFT_TOY, FakeHazards, FakePose
from tests.helpers import get_status, make_jpeg


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def worker():
    clock = Clock()
    pose = FakePose("prone")
    w = DetectionWorker(pose, FakeHazards(), stability_frames=2, stale_after_s=5.0, clock=clock)
    w.clock, w.pose = clock, pose
    w.start()
    yield w
    w.stop()


def feed(worker, frames=1):
    for i in range(frames):
        target = worker.analysed + 1
        assert worker.submit(make_jpeg(i)) == make_jpeg(i)  # the video passes through untouched
        assert wait_until(lambda target=target: worker.analysed >= target)


def test_nothing_is_reported_before_any_frame(worker):
    assert worker.snapshot() == {"alert": None, "detection": None}


def test_a_lasting_tummy_position_becomes_a_critical_alert(worker):
    feed(worker, 1)
    snap = worker.snapshot()
    assert snap["alert"] is None  # one frame is not yet a roll-over
    assert snap["detection"]["posture"] == {"label": "prone", "source": "FiDIP", "since_s": 0, "stable": False}
    feed(worker, 1)
    worker.clock.now += 3
    snap = worker.snapshot()
    assert snap["alert"]["level"] == "crit" and snap["alert"]["title"] == PRONE_TITLE
    assert snap["detection"]["posture"]["since_s"] == 3


def test_results_go_stale_when_frames_stop(worker):
    feed(worker, 2)
    worker.clock.now += 6
    assert worker.snapshot() == {"alert": None, "detection": None}


def test_reset_forgets_everything(worker):
    feed(worker, 2)
    worker.reset()
    assert worker.snapshot()["detection"] is None
    feed(worker, 1)
    assert worker.pose.resets == 1  # the pose model is not tracked across inputs
    assert worker.snapshot()["detection"]["posture"]["stable"] is False


def test_a_failing_model_never_stops_the_worker(worker):
    worker.pose.fail = True
    worker.submit(make_jpeg(0))
    assert wait_until(lambda: worker.failures == 1)
    worker.pose.fail = False
    feed(worker, 1)
    assert worker.snapshot()["detection"] is not None


def test_only_the_newest_frame_waits_while_the_model_is_busy(worker):
    worker.pose.gate = gate = threading.Event()
    worker.submit(make_jpeg(0))
    assert wait_until(lambda: worker.pose.calls == 1)
    for i in range(1, 6):
        worker.submit(make_jpeg(i))
    gate.set()
    assert wait_until(lambda: worker.analysed == 2)
    assert not wait_until(lambda: worker.analysed > 2, timeout=0.3)  # frames 1-4 were dropped, not queued


def test_toys_reach_status_through_the_relay():
    worker = DetectionWorker(FakePose("supine"), FakeHazards([SOFT_TOY]), stability_frames=2)
    with RelayServer("127.0.0.1", 0, input_timeout=2.0, detector=worker) as server:
        assert get_status(server.port)["detection"] is None
        with FakeInput("127.0.0.1", server.port, fps=30):
            assert wait_until(lambda: (get_status(server.port)["alert"] or {}).get("title") == HAZARD_TITLE, 10)
            status = get_status(server.port)
            assert status["detection"]["hazards"] == [{"label": "soft-toy", "score": 0.82, "near_baby": True}]
            assert status["detection"]["posture"]["label"] == "supine"
        # The baby phone left: nothing about the baby is claimed any more.
        assert wait_until(lambda: get_status(server.port)["detection"] is None)
        assert get_status(server.port)["alert"] is None


def test_without_a_detector_status_is_unchanged(relay):
    assert "detection" not in get_status(relay.port)
