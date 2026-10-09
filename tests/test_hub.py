import threading
import time

from babycue_server.hub import FrameHub


def test_only_one_input_may_be_claimed_until_released():
    hub = FrameHub()
    assert hub.claim_input()
    assert not hub.claim_input()
    hub.release_input()
    assert hub.claim_input()


def test_latest_is_the_newest_frame_and_seq_increases():
    hub = FrameHub()
    hub.publish(b"a")
    second = hub.publish(b"b")
    assert hub.latest() == second
    assert second.seq == 2


def test_await_next_returns_only_frames_newer_than_requested():
    hub = FrameHub()
    first = hub.publish(b"a")
    assert hub.await_next(first.seq, timeout=0.05) is None
    assert hub.await_next(0, timeout=0.05) == first


def test_await_next_wakes_when_a_frame_is_published():
    hub = FrameHub()
    result = []
    waiter = threading.Thread(target=lambda: result.append(hub.await_next(0, timeout=5)))
    waiter.start()
    time.sleep(0.1)
    hub.publish(b"x")
    waiter.join(2)
    assert result and result[0].data == b"x"


def test_slow_viewer_skips_to_the_newest_frame():
    hub = FrameHub()
    for i in range(10):
        hub.publish(bytes([i]))
    assert hub.await_next(0, timeout=0.05).data == bytes([9])


def test_release_input_clears_the_stale_frame():
    hub = FrameHub()
    hub.claim_input()
    hub.publish(b"a")
    hub.release_input()
    assert hub.latest() is None


def test_close_wakes_waiters_and_refuses_new_work():
    hub = FrameHub()
    result = []
    waiter = threading.Thread(target=lambda: result.append(hub.await_next(0, timeout=5)))
    waiter.start()
    time.sleep(0.1)
    started = time.monotonic()
    hub.close()
    waiter.join(2)
    assert result == [None] and time.monotonic() - started < 1
    assert not hub.claim_input()
    assert not hub.add_viewer(4)


def test_viewer_limit():
    hub = FrameHub()
    assert [hub.add_viewer(2) for _ in range(3)] == [True, True, False]
    hub.remove_viewer()
    assert hub.add_viewer(2)


def test_stats_report_fps_and_counts():
    now = [0.0]
    hub = FrameHub(clock=lambda: now[0])
    hub.claim_input()
    for _ in range(11):
        hub.publish(b"x")
        now[0] += 0.1
    hub.count_bad_frame()
    stats = hub.stats()
    assert stats["frames"] == 11 and stats["bad_frames"] == 1 and stats["input_connected"]
    assert 9.5 <= stats["fps"] <= 10.5
