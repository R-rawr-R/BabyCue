"""The server's database: the baby's name, the detection log, and the HTTP endpoints in front of them."""

import http.client
import json
from datetime import datetime

import pytest

from babycue_server.db import MAX_NAME_LENGTH, Database
from babycue_server.detection.rules import PRONE_TITLE
from babycue_server.detection.worker import DetectionWorker
from babycue_server.devtools.fake_input import FakeInput
from babycue_server.http_server import RelayServer
from tests.conftest import wait_until
from tests.detection_fakes import SOFT_TOY, FakeHazards, FakePose
from tests.helpers import make_jpeg


def call(port: int, method: str, path: str, body: object = None) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = json.dumps(body).encode() if body is not None else None
    conn.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
    response = conn.getresponse()
    result = response.status, json.loads(response.read())
    conn.close()
    return result


def test_no_baby_until_named_and_the_name_survives_a_restart(tmp_path):
    path = tmp_path / "babycue.db"
    db = Database(path)
    assert db.baby() is None
    assert db.set_baby_name("  Ada   Mae ")["name"] == "Ada Mae"
    db.close()
    reopened = Database(path)
    assert reopened.baby()["name"] == "Ada Mae"
    assert reopened.set_baby_name("Ada")["name"] == "Ada"  # renaming keeps the one baby
    reopened.close()


@pytest.mark.parametrize("name", ["", "   ", "x" * (MAX_NAME_LENGTH + 1)])
def test_bad_names_are_refused(name):
    with pytest.raises(ValueError):
        Database(":memory:").set_baby_name(name)


def test_log_rows_carry_a_local_date_and_time_and_come_newest_first():
    db = Database(":memory:")
    db.log_detection("posture", "supine", level="ok", source="MediaPipe")
    db.log_detection("hazard", "soft-toy", detail="Soft toy near baby", level="warn", score=0.82)
    rows = db.detections()
    assert [r["label"] for r in rows] == ["soft-toy", "supine"]
    at = datetime.fromisoformat(rows[0]["at"])
    assert at.tzinfo is not None and abs((datetime.now().astimezone() - at).total_seconds()) < 60
    assert rows[0]["score"] == 0.82 and rows[1]["source"] == "MediaPipe"
    assert len(db.detections(limit=1)) == 1


def test_the_baby_endpoint_asks_then_remembers(relay):
    assert call(relay.port, "GET", "/baby") == (200, {"baby": None})
    status, body = call(relay.port, "POST", "/baby", {"name": "Ada"})
    assert status == 200 and body["baby"]["name"] == "Ada"
    assert call(relay.port, "GET", "/baby")[1]["baby"]["name"] == "Ada"


@pytest.mark.parametrize("body", [{"name": ""}, {"name": 5}, {"nom": "Ada"}, ["Ada"]])
def test_the_baby_endpoint_refuses_bad_input(relay, body):
    status, reply = call(relay.port, "POST", "/baby", body)
    assert status == 400 and reply["error"]
    assert call(relay.port, "GET", "/baby")[1] == {"baby": None}


def test_every_detection_event_is_logged_once_with_its_time():
    pose = FakePose("supine")
    worker = DetectionWorker(pose, FakeHazards([SOFT_TOY]), stability_frames=2)
    db = Database(":memory:")
    with RelayServer("127.0.0.1", 0, input_timeout=2.0, detector=worker, db=db) as server:
        with FakeInput("127.0.0.1", server.port, fps=30):
            assert wait_until(lambda: {r["kind"] for r in db.detections()} >= {"posture", "hazard", "alert"}, 10)
            first = len(db.detections())
            assert not wait_until(lambda: len(db.detections()) > first, timeout=0.5)  # unchanged scene: no new rows
            pose.posture = "prone"
            assert wait_until(lambda: any(r["label"] == PRONE_TITLE for r in db.detections()), 10)
        status, body = call(server.port, "GET", "/detections?limit=50")
    assert status == 200
    rows = body["detections"]
    kinds = [(r["kind"], r["label"]) for r in reversed(rows)]  # oldest first
    assert kinds.index(("posture", "supine")) < kinds.index(("posture", "prone"))
    assert ("hazard", "soft-toy") in kinds
    assert all(datetime.fromisoformat(r["at"]).tzinfo is not None for r in rows)


def test_a_toy_that_leaves_is_logged_as_gone():
    hazards = FakeHazards([SOFT_TOY])
    worker = DetectionWorker(FakePose("supine"), hazards, stability_frames=1)
    events = []
    worker.on_event = events.append
    worker.start()
    try:
        for i in range(3):
            target = worker.analysed + 1
            worker.submit(make_jpeg(i))
            assert wait_until(lambda target=target: worker.analysed >= target)
        assert ("hazard", "soft-toy") in [(e["kind"], e["label"]) for e in events]
        hazards.hazards = []
        for i in range(8):  # a toy must be missing for several analyses before it counts as gone
            target = worker.analysed + 1
            worker.submit(make_jpeg(i))
            assert wait_until(lambda target=target: worker.analysed >= target)
        assert ("hazard-cleared", "soft-toy") in [(e["kind"], e["label"]) for e in events]
    finally:
        worker.stop()
