import time
import urllib.request

from babycue_server.devtools.fake_input import IngestClient
from babycue_server.protocol import MAX_VIEWERS, VIEW_CONTENT_TYPE
from tests.conftest import wait_until
from tests.helpers import Viewer, get_status, make_jpeg


def push(relay, count: int, start: int = 0):
    client = IngestClient("127.0.0.1", relay.port).connect()
    frames = [make_jpeg(start + i) for i in range(count)]
    for frame in frames:
        client.send_frame(frame)
    return client, frames


def test_viewer_gets_multipart_headers_and_byte_identical_frames(relay):
    viewer = Viewer(relay.port).start()
    assert wait_until(lambda: relay.hub.stats()["viewers"] == 1)
    client = IngestClient("127.0.0.1", relay.port).connect()
    sent = []
    for i in range(5):
        sent.append(make_jpeg(i))
        client.send_frame(sent[-1])
        assert wait_until(lambda n=i + 1: len(viewer.frames) >= n)
    assert viewer.status == 200 and viewer.content_type == VIEW_CONTENT_TYPE
    assert viewer.frames == sent and viewer.error is None
    client.close()
    viewer.close()


def test_a_viewer_joining_late_starts_with_the_newest_frame_not_a_backlog(relay):
    client, frames = push(relay, 5)
    assert wait_until(lambda: relay.hub.stats()["frames"] == 5)
    viewer = Viewer(relay.port).start()
    assert wait_until(lambda: len(viewer.frames) >= 1)
    assert viewer.frames[0] == frames[-1]
    client.close()
    viewer.close()


def test_several_viewers_each_receive_the_stream(relay):
    viewers = [Viewer(relay.port).start() for _ in range(3)]
    assert wait_until(lambda: relay.hub.stats()["viewers"] == 3)
    client, frames = push(relay, 1)
    assert wait_until(lambda: all(len(v.frames) == 1 for v in viewers))
    assert all(v.frames == frames for v in viewers)
    client.close()
    for v in viewers:
        v.close()


def test_viewer_over_the_limit_gets_503(relay):
    viewers = [Viewer(relay.port).start() for _ in range(MAX_VIEWERS)]
    assert wait_until(lambda: relay.hub.stats()["viewers"] == MAX_VIEWERS)
    extra = Viewer(relay.port).start()
    assert extra.ended.wait(3) and extra.status == 503
    for v in [*viewers, extra]:
        v.close()


def test_a_disconnected_viewer_frees_its_slot_even_when_no_frames_are_flowing(relay):
    viewer = Viewer(relay.port).start()
    assert wait_until(lambda: relay.hub.stats()["viewers"] == 1)
    viewer.close()
    assert wait_until(lambda: relay.hub.stats()["viewers"] == 0, timeout=4)


def test_viewer_keeps_working_across_input_restarts(relay):
    viewer = Viewer(relay.port).start()
    first, _ = push(relay, 2)
    assert wait_until(lambda: len(viewer.frames) >= 1)
    first.close()
    assert wait_until(lambda: not relay.hub.stats()["input_connected"])
    before = len(viewer.frames)
    second, frames = push(relay, 2, start=10)
    assert wait_until(lambda: len(viewer.frames) > before)
    assert viewer.frames[-1] == frames[-1] and viewer.ended.is_set() is False
    second.close()
    viewer.close()


def test_stopping_the_server_ends_viewer_streams_quickly(relay):
    viewer = Viewer(relay.port).start()
    assert wait_until(lambda: relay.hub.stats()["viewers"] == 1)
    started = time.monotonic()
    relay.stop()
    assert viewer.ended.wait(3)
    assert time.monotonic() - started < 3
    viewer.close()


def test_status_and_index_endpoints(relay):
    stats = get_status(relay.port)
    assert stats == {"input_connected": False, "frames": 0, "bad_frames": 0, "fps": 0.0, "viewers": 0}
    with urllib.request.urlopen(f"http://127.0.0.1:{relay.port}/", timeout=3) as response:
        assert b"/view" in response.read()
