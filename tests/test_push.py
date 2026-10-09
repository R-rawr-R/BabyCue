"""Background alarms (Web Push): phones sign up, a new alert reaches them, a phone that left is dropped.

Nothing is sent to a real push service: ``webpush`` is replaced by a recorder.
"""

import base64
import json

import pytest

pytest.importorskip("pywebpush")

import pywebpush  # noqa: E402

from babycue_server.db import Database  # noqa: E402
from babycue_server.detection.rules import PRONE_TITLE  # noqa: E402
from babycue_server.detection.worker import DetectionWorker  # noqa: E402
from babycue_server.devtools.fake_input import FakeInput  # noqa: E402
from babycue_server.http_server import RelayServer  # noqa: E402
from babycue_server.push import PushNotifier  # noqa: E402
from tests.conftest import wait_until  # noqa: E402
from tests.detection_fakes import FakeHazards, FakePose  # noqa: E402
from tests.test_database import call  # noqa: E402

PHONE = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "BNc", "auth": "tBH"}}


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_webpush(subscription, data=None, **kwargs):
        calls.append((subscription["endpoint"], json.loads(data), kwargs))

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)
    return calls


@pytest.fixture
def notifier(tmp_path):
    db = Database(":memory:")
    return PushNotifier(db, tmp_path / "vapid.pem")


def test_the_key_is_a_p256_point_and_survives_a_restart(tmp_path):
    first = PushNotifier(Database(":memory:"), tmp_path / "vapid.pem").public_key
    raw = base64.urlsafe_b64decode(first + "=" * (-len(first) % 4))
    assert len(raw) == 65 and raw[0] == 4  # uncompressed P-256 point, as pushManager.subscribe expects
    assert PushNotifier(Database(":memory:"), tmp_path / "vapid.pem").public_key == first


def test_phones_sign_up_and_leave_through_the_server(notifier):
    with RelayServer("127.0.0.1", 0, db=notifier._db, push=notifier) as server:
        assert call(server.port, "GET", "/push/key") == (200, {"publicKey": notifier.public_key})
        assert call(server.port, "POST", "/push/subscribe", PHONE)[0] == 200
        assert call(server.port, "POST", "/push/subscribe", PHONE)[0] == 200  # twice is still one phone
        assert notifier._db.push_subscriptions() == [PHONE]
        assert call(server.port, "POST", "/push/subscribe", {"endpoint": "http://insecure"})[0] == 400
        assert call(server.port, "POST", "/push/unsubscribe", {"endpoint": PHONE["endpoint"]})[0] == 200
        assert notifier._db.push_subscriptions() == []


def test_without_push_the_server_says_so(relay):
    assert call(relay.port, "GET", "/push/key")[0] == 503
    assert call(relay.port, "POST", "/push/subscribe", PHONE)[0] == 503


def test_a_new_alert_wakes_every_phone_once(notifier, sent):
    notifier._db.add_push_subscription(PHONE)
    pose = FakePose("supine")
    worker = DetectionWorker(pose, FakeHazards(), stability_frames=2)
    with RelayServer("127.0.0.1", 0, input_timeout=2.0, detector=worker, db=notifier._db, push=notifier) as server:
        with FakeInput("127.0.0.1", server.port, fps=30):
            assert not wait_until(lambda: sent, timeout=1)  # sleeping on their back: nothing to wake anyone for
            pose.posture = "prone"
            assert wait_until(lambda: sent, 10)
            assert not wait_until(lambda: len(sent) > 1, timeout=1)  # the same alert is not sent again
    endpoint, payload, options = sent[0]
    assert endpoint == PHONE["endpoint"]
    assert payload["title"] == PRONE_TITLE and payload["level"] == "crit"
    assert options["headers"]["Urgency"] == "high"


def test_a_phone_that_left_is_forgotten(notifier, monkeypatch):
    notifier._db.add_push_subscription(PHONE)

    class Gone:
        status_code = 410

    def gone(*args, **kwargs):
        raise pywebpush.WebPushException("Gone", response=Gone())

    monkeypatch.setattr(pywebpush, "webpush", gone)
    assert notifier._send_all("{}", "warn") == 0
    assert notifier._db.push_subscriptions() == []


def test_a_test_alarm_goes_only_to_the_phone_that_asked(notifier, sent):
    other = {"endpoint": "https://push.example.com/other", "keys": {"p256dh": "BNc", "auth": "tBH"}}
    notifier._db.add_push_subscription(PHONE)
    notifier._db.add_push_subscription(other)
    with RelayServer("127.0.0.1", 0, db=notifier._db, push=notifier) as server:
        assert call(server.port, "POST", "/push/test", {"endpoint": PHONE["endpoint"]})[0] == 200
        assert wait_until(lambda: sent)
        assert not wait_until(lambda: len(sent) > 1, timeout=0.5)
        assert call(server.port, "POST", "/push/test", {"endpoint": "https://push.example.com/stranger"})[0] == 404
    endpoint, payload, _ = sent[0]
    assert endpoint == PHONE["endpoint"] and payload["test"] is True
