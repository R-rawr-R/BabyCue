"""Fake input phone -> real server -> fake output phone, all over real sockets on localhost."""

from babycue_server.devtools.fake_input import FakeInput
from babycue_server.http_server import RelayServer
from babycue_server.pipeline import FramePipeline
from tests.conftest import wait_until
from tests.helpers import Viewer


def test_frames_relay_unchanged_from_input_to_output(relay):
    viewer = Viewer(relay.port).start()
    with FakeInput("127.0.0.1", relay.port, fps=30) as fake:
        assert wait_until(lambda: len(viewer.frames) >= 10, timeout=10)
    viewer.close()
    sent = set(fake.sent)  # the fake keeps its last 50 frames, far more than this test sends
    assert fake.frames_sent < 50
    assert all(frame in sent for frame in viewer.frames)
    assert len(set(viewer.frames)) > 1  # the picture actually changes frame to frame


def test_a_second_fake_input_is_turned_away_while_the_first_streams(relay):
    with FakeInput("127.0.0.1", relay.port, fps=30) as first:
        assert wait_until(lambda: first.frames_sent >= 2)
        with FakeInput("127.0.0.1", relay.port, fps=30) as second:
            assert wait_until(lambda: second.rejected_status == 409)
        assert first.rejected_status is None


def test_pipeline_stage_transforms_what_the_viewer_receives():
    marker = b"PROCESSED"
    pipeline = FramePipeline([lambda jpeg: jpeg + marker])
    with RelayServer("127.0.0.1", 0, pipeline=pipeline) as server:
        viewer = Viewer(server.port).start()
        with FakeInput("127.0.0.1", server.port, fps=30):
            assert wait_until(lambda: len(viewer.frames) >= 2, timeout=10)
        assert all(frame.endswith(marker) for frame in viewer.frames)
        viewer.close()


def test_a_failing_pipeline_stage_never_stops_the_video():
    def broken(_jpeg: bytes) -> bytes:
        raise RuntimeError("boom")

    with RelayServer("127.0.0.1", 0, pipeline=FramePipeline([broken])) as server:
        viewer = Viewer(server.port).start()
        with FakeInput("127.0.0.1", server.port, fps=30):
            assert wait_until(lambda: len(viewer.frames) >= 2, timeout=10)
        viewer.close()
