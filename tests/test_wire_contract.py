"""The Android app and the server must agree on the wire protocol; this reads the Kotlin source to prove it."""

import math
import re
from pathlib import Path

import pytest

from babycue_server import protocol

KOTLIN = Path(__file__).resolve().parents[1] / "android/app/src/main/java/com/babycue/camera/net/WireProtocol.kt"


def kotlin_constants() -> dict[str, object]:
    constants: dict[str, object] = {}
    for name, raw in re.findall(r"const val (\w+) = (.+)", KOTLIN.read_text(encoding="utf-8")):
        raw = raw.strip()
        if raw.startswith('"'):
            constants[name] = raw.strip('"')
        else:
            constants[name] = math.prod(int(part) for part in raw.split("*"))
    return constants


@pytest.mark.parametrize(
    ("kotlin_name", "python_value"),
    [
        ("DEFAULT_PORT", protocol.DEFAULT_PORT),
        ("INGEST_PATH", protocol.INGEST_PATH),
        ("VIEW_PATH", protocol.VIEW_PATH),
        ("BOUNDARY", protocol.BOUNDARY),
        ("MAX_FRAME_BYTES", protocol.MAX_FRAME_BYTES),
        ("LENGTH_PREFIX_BYTES", protocol.LENGTH_PREFIX_BYTES),
    ],
)
def test_kotlin_constant_matches_python(kotlin_name, python_value):
    assert kotlin_constants()[kotlin_name] == python_value


def test_every_kotlin_constant_is_covered():
    assert set(kotlin_constants()) == {
        "DEFAULT_PORT",
        "INGEST_PATH",
        "VIEW_PATH",
        "BOUNDARY",
        "MAX_FRAME_BYTES",
        "LENGTH_PREFIX_BYTES",
    }


def test_length_prefix_bytes_match_the_kotlin_test_vectors():
    # Same vectors as WireProtocolTest.lengthPrefixIsFourBytesBigEndian.
    assert protocol.pack_frame(b"")[:4] == bytes([0, 0, 0, 0])
    assert protocol.pack_frame(b"x" * 256)[:4] == bytes([0, 0, 1, 0])
    assert protocol.pack_frame(b"x" * 0x010203)[:4] == bytes([0, 1, 2, 3])
    assert protocol.MAX_FRAME_BYTES.to_bytes(4, "big") == bytes([0, 0x80, 0, 0])
