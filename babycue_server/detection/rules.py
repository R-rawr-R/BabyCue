"""Safe-sleep rules: turn what the models saw into at most one alert for the parent phone.

Follows the AAP guidance for preventing SUID/SIDS: back to sleep, and a bare crib (no toys or soft objects).
Titles stay the same while a condition lasts, because the parent phone mutes an alert by its title.
"""

from __future__ import annotations

from collections import deque

from babycue_server.detection.posture import PostureReading
from babycue_server.detection.results import Hazard

PRONE_TITLE = "Baby is on their tummy"
SIDE_TITLE = "Baby is on their side"
HAZARD_TITLE = "Toy in the crib"


class HazardTracker:
    """Confirms an object seen in ``need`` of the last ``window`` analyses, so one false box is ignored."""

    def __init__(self, window: int = 5, need: int = 3):
        if not 1 <= need <= window:
            raise ValueError("need must be between 1 and window")
        self.window, self.need = window, need
        self.reset()

    def reset(self) -> None:
        self._seen: deque[frozenset[str]] = deque(maxlen=self.window)
        self._last: dict[str, Hazard] = {}

    def update(self, hazards: list[Hazard]) -> list[Hazard]:
        best: dict[str, Hazard] = {}
        for hazard in hazards:
            if hazard.label not in best or hazard.score > best[hazard.label].score:
                best[hazard.label] = hazard
        self._seen.append(frozenset(best))
        self._last.update(best)
        return self.confirmed()

    def confirmed(self) -> list[Hazard]:
        counts: dict[str, int] = {}
        for labels in self._seen:
            for label in labels:
                counts[label] = counts.get(label, 0) + 1
        keep = [self._last[label] for label, n in counts.items() if n >= self.need]
        return sorted(keep, key=lambda h: (-h.score, h.label))


def friendly_label(label: str) -> str:
    return label.replace("-", " ").replace("_", " ").capitalize()


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


def evaluate(posture: PostureReading | None, hazards: list[Hazard], now: float) -> dict | None:
    """The single most urgent alert, or ``None`` when nothing needs the parent."""
    if posture is not None and posture.stable:
        held = format_duration(now - posture.since)
        if posture.label == "prone":
            return {"level": "crit", "title": PRONE_TITLE, "detail": f"Lying face-down for {held} · {posture.source}"}
        if posture.label == "side":
            return {"level": "warn", "title": SIDE_TITLE, "detail": f"On their side for {held} · {posture.source}"}
    if hazards:
        parts = []
        for hazard in hazards:
            where = "near baby" if hazard.near_baby else "in view"
            parts.append(f"{friendly_label(hazard.label)} {where} ({round(hazard.score * 100)}%)")
        return {"level": "warn", "title": HAZARD_TITLE, "detail": " · ".join(parts)}
    return None
