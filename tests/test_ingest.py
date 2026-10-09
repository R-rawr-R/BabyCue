import time
import urllib.error
import urllib.request

from babycue_server.devtools.fake_input import IngestClient
from babycue_server.protocol import MAX_FRAME_BYTES, pack_frame
from tests.conftest import wait_until
from tests.helpers import get_status, make_jpeg


def connect(relay) -> IngestClient:
    return IngestClient("127.0.0.1", relay.port).connect()


def test_valid_frames_are_published_in_order(relay):
    client = connect(relay)
    frames = [make_jpeg(i) for i in range(3)]
    for frame in frames:
        client.send_frame(frame)
    assert wait_until(lambda: relay.hub.stats()["frames"] == 3)
    assert relay.hub.latest().data == frames[-1]
    assert client.finish() == 200
    client.close()


def test_frames_split_across_chunk_and_tcp_boundaries_are_reassembled(relay):
    client = connect(relay)
    record = pack_frame(make_jpeg(1))
    for i in range(0, len(record), 7):  # 7-byte chunks: record and chunk boundaries never line up
        client.send_chunk(record[i : i + 7])
    assert wait_until(lambda: relay.hub.stats()["frames"] == 1)
    assert relay.hub.latest().data == record[4:]
    client.close()


def test_non_jpeg_frames_are_counted_and_dropped_but_the_stream_continues(relay):
    client = connect(relay)
    client.send_frame(b"this is not a jpeg")
    client.send_frame(make_jpeg(0))
    assert wait_until(lambda: relay.hub.stats()["frames"] == 1)
    stats = get_status(relay.port)
    assert stats["bad_frames"] == 1 and stats["input_connected"]
    client.close()


def test_oversized_frame_length_is_rejected_with_413(relay):
    client = connect(relay)
    client.send_chunk((MAX_FRAME_BYTES + 1).to_bytes(4, "big"))
    assert client.response_status(wait=3) == 413
    assert wait_until(lambda: not relay.hub.stats()["input_connected"])
    client.close()


def test_zero_length_frame_is_rejected_with_400(relay):
    client = connect(relay)
    client.send_chunk((0).to_bytes(4, "big"))
    assert client.response_status(wait=3) == 400
    client.close()


def test_malformed_chunk_header_is_rejected_with_400(relay):
    client = connect(relay)
    client.sock.sendall(b"zz\r\n")
    assert client.response_status(wait=3) == 400
    client.close()


def test_truncated_frame_then_disconnect_publishes_nothing_and_frees_the_input(relay):
    client = connect(relay)
    client.send_chunk(pack_frame(make_jpeg(0))[:50])
    time.sleep(0.2)
    client.close()
    assert wait_until(lambda: not relay.hub.stats()["input_connected"])
    assert relay.hub.stats()["frames"] == 0


def test_second_input_is_rejected_with_409_until_the_first_leaves(relay):
    first = connect(relay)
    first.send_frame(make_jpeg(0))
    assert wait_until(lambda: relay.hub.stats()["input_connected"])

    second = connect(relay)
    assert second.response_status(wait=3) == 409
    second.close()
    assert relay.hub.stats()["frames"] == 1  # the first input is unaffected

    first.close()
    assert wait_until(lambda: not relay.hub.stats()["input_connected"])
    third = connect(relay)
    third.send_frame(make_jpeg(1))
    assert wait_until(lambda: relay.hub.stats()["frames"] == 2)
    third.close()


def test_input_that_goes_silent_is_released_after_the_idle_timeout(relay):
    client = connect(relay)
    client.send_frame(make_jpeg(0))
    assert wait_until(lambda: relay.hub.stats()["input_connected"])
    started = time.monotonic()
    assert wait_until(lambda: not relay.hub.stats()["input_connected"], timeout=6)
    assert time.monotonic() - started < 5  # fixture idle timeout is 2 s
    client.close()


def test_unknown_paths_return_404(relay):
    for path in ("/nope", "/ingest/x"):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{relay.port}{path}", timeout=3)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError(f"{path} should be 404")


def test_stopping_the_server_releases_a_connected_input_quickly(relay):
    client = connect(relay)
    client.send_frame(make_jpeg(0))
    assert wait_until(lambda: relay.hub.stats()["input_connected"])
    started = time.monotonic()
    relay.stop()
    assert time.monotonic() - started < 3
    client.close()
