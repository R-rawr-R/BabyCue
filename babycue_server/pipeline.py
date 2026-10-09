"""Where server-side logic plugs in between the input phone and the output phone."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

log = logging.getLogger(__name__)

FrameStage = Callable[[bytes], bytes]


class FramePipeline:
    """Runs each incoming JPEG through ``stages`` in order. With no stages it is a passthrough.

    A stage that raises is logged and skipped, so one faulty stage never stops the video.
    """

    def __init__(self, stages: Iterable[FrameStage] = ()):
        self.stages = list(stages)

    def process(self, jpeg: bytes) -> bytes:
        for stage in self.stages:
            try:
                jpeg = stage(jpeg)
            except Exception:  # noqa: BLE001 - isolate faulty stages
                log.exception("Frame stage %r failed; passing the frame through unchanged", stage)
        return jpeg
