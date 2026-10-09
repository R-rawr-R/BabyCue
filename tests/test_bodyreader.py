import socket
import threading
import time

import pytest

from babycue_server.bodyreader import ChunkedSource, IdleTimeout, ServerStopping, SocketSource, read_exact


class ListSource:
    """Feeds fixed byte pieces, mimicking arbitrary TCP segmentation."""

    def __init__(self, *pieces: bytes):
        self._data = bytearray(b"".join(pieces))

    def read(self, n: int) -> bytes:
        out = bytes(self._data[:n])
        del self._data[:n]
        return out


def drain(source) -> bytes:
    out = bytearray()
    while chunk := source.read(7):
        out += chunk
    return bytes(out)


def test_chunked_body_is_decoded_across_chunk_boundaries():
    body = b"4\r\nWiki\r\n5\r\npedia\r\nE\r\n in\r\n\r\nchunks.\r\n0\r\n\r\n"
    assert drain(ChunkedSource(ListSource(body))) == b"Wikipedia in\r\n\r\nchunks."


def test_chunk_extensions_and_trailers_are_ignored():
    body = b"3;ext=1\r\nabc\r\n0\r\nX-Trailer: 1\r\n\r\n"
    assert drain(ChunkedSource(ListSource(body))) == b"abc"


@pytest.mark.parametrize("body", [b"zz\r\nabc\r\n", b"3\r\nabcXX", b"3\r\nab"])
def test_malformed_or_truncated_chunked_body_raises(body):
    with pytest.raises((ValueError, EOFError)):
        drain(ChunkedSource(ListSource(body)))


def test_read_exact_distinguishes_clean_eof_from_truncation():
    assert read_exact(ListSource(), 4, eof_ok_at_start=True) == b""
    with pytest.raises(EOFError):
        read_exact(ListSource(b"ab"), 4, eof_ok_at_start=True)


def socket_pair():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    client = socket.create_connection(listener.getsockname())
    server, _ = listener.accept()
    listener.close()
    return client, server


def test_socket_source_reads_then_reports_eof():
    client, server = socket_pair()
    client.sendall(b"hello")
    client.close()
    source = SocketSource(server, idle_timeout=2)
    assert read_exact(source, 5) == b"hello"
    assert source.read(1) == b""
    server.close()


def test_socket_source_times_out_when_the_peer_goes_silent():
    client, server = socket_pair()
    source = SocketSource(server, idle_timeout=0.3, poll_interval=0.05)
    started = time.monotonic()
    with pytest.raises(IdleTimeout):
        source.read(1)
    assert time.monotonic() - started < 2
    client.close()
    server.close()


def test_socket_source_stops_promptly_when_the_server_shuts_down():
    client, server = socket_pair()
    stop = threading.Event()
    source = SocketSource(server, should_stop=stop.is_set, idle_timeout=30, poll_interval=0.05)
    threading.Timer(0.2, stop.set).start()
    started = time.monotonic()
    with pytest.raises(ServerStopping):
        source.read(1)
    assert time.monotonic() - started < 2
    client.close()
    server.close()
