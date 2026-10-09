"""The phone app and the server must agree on the wire protocol; this reads the TypeScript source to prove it."""

import math
import re
from pathlib import Path

import pytest

from babycue_server import protocol

TYPESCRIPT = Path(__file__).resolve().parents[1] / "web/src/net/wireProtocol.ts"


def typescript_constants() -> dict[str, object]:
    constants: dict[str, object] = {}
    for name, raw in re.findall(r"export const (\w+) = ([^;]+);", TYPESCRIPT.read_text(encoding="utf-8")):
        raw = raw.strip()
        if raw.startswith(("'", '"')):
            constants[name] = raw.strip("'\"")
        else:
            constants[name] = math.prod(float(part) for part in raw.split("*"))
    return constants


@pytest.mark.parametrize(
    ("ts_name", "python_value"),
    [
        ("DEFAULT_PORT", protocol.DEFAULT_PORT),
        ("INGEST_PATH", protocol.INGEST_PATH),
        ("FRAME_PATH", protocol.FRAME_PATH),
        ("VIEW_PATH", protocol.VIEW_PATH),
        ("STATUS_PATH", protocol.STATUS_PATH),
        ("CA_PATH", protocol.CA_PATH),
        ("BABY_PATH", protocol.BABY_PATH),
        ("DETECTIONS_PATH", protocol.DETECTIONS_PATH),
        ("PUSH_KEY_PATH", protocol.PUSH_KEY_PATH),
        ("PUSH_SUBSCRIBE_PATH", protocol.PUSH_SUBSCRIBE_PATH),
        ("PUSH_UNSUBSCRIBE_PATH", protocol.PUSH_UNSUBSCRIBE_PATH),
        ("PUSH_TEST_PATH", protocol.PUSH_TEST_PATH),
        ("MAX_FRAME_BYTES", protocol.MAX_FRAME_BYTES),
    ],
)
def test_typescript_constant_matches_python(ts_name, python_value):
    assert typescript_constants()[ts_name] == python_value


def test_every_typescript_constant_is_covered():
    assert set(typescript_constants()) == {
        "DEFAULT_PORT",
        "INGEST_PATH",
        "FRAME_PATH",
        "VIEW_PATH",
        "STATUS_PATH",
        "CA_PATH",
        "BABY_PATH",
        "DETECTIONS_PATH",
        "PUSH_KEY_PATH",
        "PUSH_SUBSCRIBE_PATH",
        "PUSH_UNSUBSCRIBE_PATH",
        "PUSH_TEST_PATH",
        "MAX_FRAME_BYTES",
    }
