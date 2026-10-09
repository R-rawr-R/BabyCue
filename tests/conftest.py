import time

import pytest

from babycue_server.http_server import RelayServer


@pytest.fixture
def relay():
    server = RelayServer("127.0.0.1", 0, input_timeout=2.0).start()
    yield server
    server.stop()


def wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
