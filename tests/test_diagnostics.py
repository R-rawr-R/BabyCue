"""User-facing diagnostics for the failure modes seen when connecting to the Android app."""

import logging

import requests

from babycue_camera.capture import ConnectionState, StreamWorker
from babycue_camera.config import parse_stream_url
from babycue_camera.stream import MjpegStream, StreamTimeout
from tests.conftest import wait_until
from tests.test_android_protocol import AndroidWireServer, make_jpeg, part


def run_worker(url, **kw):
    worker = StreamWorker(parse_stream_url(url), reconnect_initial_delay=0.1, **kw)
    worker.start()
    return worker


def test_wrong_endpoint_message_points_at_the_path():
    with AndroidWireServer() as srv:
        worker = run_worker(srv.url.replace("/video", "/stream"))
        try:
            assert wait_until(lambda: worker.stats().state is ConnectionState.FAILED)
            message = worker.stats().message
        finally:
            worker.stop()
    assert "404" in message and "/video" in message


def test_connect_timeout_message_mentions_network_and_client_isolation(monkeypatch):
    # A real black-holed address is not reproducible offline, so inject the timeout requests raises.
    def boom(self, *args, **kwargs):
        raise requests.exceptions.ConnectTimeout("simulated")

    monkeypatch.setattr(requests.Session, "get", boom)
    stream = MjpegStream(parse_stream_url("http://192.168.1.50:8080/video"), connect_timeout=4)
    try:
        stream.open()
    except StreamTimeout as exc:
        text = str(exc)
    else:
        raise AssertionError("expected StreamTimeout")
    finally:
        stream.close()
    assert "192.168.1.50:8080" in text and "same network" in text and "isolate" in text


def test_only_corrupt_frames_produce_an_explanatory_message():
    with AndroidWireServer([part(b"not a jpeg" * 5)] * 40, then="hold") as srv:
        worker = run_worker(srv.url)
        try:
            assert wait_until(lambda: worker.stats().frames_malformed >= 10)
            stats = worker.stats()
        finally:
            worker.stop()
    assert stats.frames_received == 0
    assert "cannot be decoded" in stats.message


def test_valid_frames_after_a_few_corrupt_ones_do_not_leave_a_warning():
    chunks = [part(b"bad" * 10)] * 6 + [part(make_jpeg(i)) for i in range(10)]
    with AndroidWireServer(chunks, then="hold") as srv:
        worker = run_worker(srv.url)
        try:
            assert wait_until(lambda: worker.stats().frames_received >= 5)
            stats = worker.stats()
        finally:
            worker.stop()
    assert stats.state is ConnectionState.STREAMING and "decoded" not in stats.message


def test_credentials_never_appear_in_messages_or_logs():
    records: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Collect()
    root = logging.getLogger("babycue_camera")
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        with AndroidWireServer() as srv:
            url = srv.url.replace("http://", "http://admin:hunter2@").replace("/video", "/nope")
            worker = run_worker(url)
            try:
                assert wait_until(lambda: worker.stats().state is ConnectionState.FAILED)
                message = worker.stats().message
            finally:
                worker.stop()
    finally:
        root.removeHandler(handler)
    assert "hunter2" not in message
    assert records and all("hunter2" not in r for r in records)
