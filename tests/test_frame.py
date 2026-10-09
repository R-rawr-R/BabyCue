import http.client
from tests.helpers import get_status, make_jpeg


def post_frame(relay, body: bytes) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", relay.port, timeout=3)
    try:
        conn.request("POST", "/frame", body=body, headers={"Content-Type": "image/jpeg"})
        return conn.getresponse().status
    finally:
        conn.close()


def test_single_frame_posts_are_published(relay):
    frames = [make_jpeg(i) for i in range(3)]
    assert [post_frame(relay, f) for f in frames] == [204, 204, 204]
    assert relay.hub.stats()["frames"] == 3
    assert relay.hub.latest().data == frames[-1]
    assert get_status(relay.port)["input_connected"]


def test_non_jpeg_body_is_counted_and_rejected(relay):
    assert post_frame(relay, b"not a jpeg") == 400
    assert get_status(relay.port)["bad_frames"] == 1


def test_empty_body_is_rejected(relay):
    assert post_frame(relay, b"") == 400


def test_frame_input_is_released_when_it_goes_quiet(relay):
    clock = [0.0]
    relay.hub._clock = lambda: clock[0]
    assert post_frame(relay, make_jpeg(0)) == 204
    assert relay.hub.stats()["input_connected"]
    clock[0] += 6  # past the lease
    assert not relay.hub.stats()["input_connected"]
    assert relay.hub.latest() is None


def test_second_frame_poster_gets_409_while_the_first_holds_the_lease(relay):
    assert relay.hub.claim_frame_input("phone-a", 5)
    assert not relay.hub.claim_frame_input("phone-b", 5)
    assert relay.hub.claim_frame_input("phone-a", 5)  # the owner renews
    assert post_frame(relay, make_jpeg(0)) == 409  # the test client (127.0.0.1) is a different phone
    assert relay.hub.stats()["frames"] == 0


def test_a_streaming_ingest_blocks_frame_posts_and_vice_versa(relay):
    assert relay.hub.claim_input()
    assert post_frame(relay, make_jpeg(0)) == 409
    relay.hub.release_input()
    assert post_frame(relay, make_jpeg(0)) == 204
    assert not relay.hub.claim_input()


def test_many_pictures_reuse_one_connection(relay):
    conn = http.client.HTTPConnection("127.0.0.1", relay.port, timeout=3)
    try:
        for i in range(5):
            conn.request("POST", "/frame", body=make_jpeg(i), headers={"Content-Type": "image/jpeg"})
            response = conn.getresponse()
            response.read()
            assert response.status == 204
            assert response.getheader("Connection") == "keep-alive"
        assert relay.hub.stats()["frames"] == 5
    finally:
        conn.close()
