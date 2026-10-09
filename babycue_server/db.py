"""The server's own records, in one SQLite file: the baby's name, a log of every detection event, and the
phones that asked for background alarms.

SQLite comes with Python, so this needs no extra package. One connection is shared by the HTTP threads and the
detection thread; a lock keeps their writes apart.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

#: Longest name accepted, so a stray paste cannot fill the screen.
MAX_NAME_LENGTH = 40
#: Most log rows returned by one request.
MAX_LOG_ROWS = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS baby (
    id         INTEGER PRIMARY KEY CHECK (id = 1),  -- one monitor watches one baby
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS detection (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT    NOT NULL,  -- local date and time with its UTC offset, e.g. 2026-10-10T05:41:01+08:00
    kind   TEXT    NOT NULL,  -- posture | hazard | hazard-cleared | alert
    label  TEXT    NOT NULL,  -- prone, soft-toy, "Baby is on their tummy", ...
    detail TEXT    NOT NULL DEFAULT '',
    level  TEXT,              -- ok | warn | crit
    source TEXT,              -- the model that saw it
    score  REAL               -- the model's confidence, when it gives one
);
CREATE INDEX IF NOT EXISTS detection_at ON detection (at);
CREATE TABLE IF NOT EXISTS push_subscription (
    endpoint   TEXT PRIMARY KEY,  -- the phone's push address (unique per phone and browser)
    data       TEXT NOT NULL,     -- the whole PushSubscription JSON, keys included
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")  # readers never wait for the detection thread's writes
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- baby -----------------------------------------------------------------------------------

    def baby(self) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT name, created_at FROM baby WHERE id = 1").fetchone()
        return dict(row) if row else None

    def set_baby_name(self, name: str) -> dict:
        """Create the baby, or rename them. Raises ``ValueError`` for an empty or overlong name."""
        name = " ".join(name.split())
        if not name:
            raise ValueError("The name is empty")
        if len(name) > MAX_NAME_LENGTH:
            raise ValueError(f"The name is longer than {MAX_NAME_LENGTH} characters")
        with self._lock:
            self._conn.execute(
                "INSERT INTO baby (id, name, created_at) VALUES (1, ?, ?) ON CONFLICT (id) DO UPDATE SET name = excluded.name",
                (name, _now()),
            )
        baby = self.baby()
        assert baby is not None
        return baby

    # -- detection log --------------------------------------------------------------------------

    def log_detection(
        self,
        kind: str,
        label: str,
        *,
        detail: str = "",
        level: str | None = None,
        source: str | None = None,
        score: float | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO detection (at, kind, label, detail, level, source, score) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_now(), kind, label, detail, level, source, score),
            )

    def detections(self, limit: int = 100) -> list[dict]:
        """Newest first."""
        limit = max(1, min(limit, MAX_LOG_ROWS))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, at, kind, label, detail, level, source, score FROM detection ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # -- background alarms ----------------------------------------------------------------------

    def add_push_subscription(self, subscription: dict) -> None:
        """Remember a phone's ``PushSubscription``. Raises ``ValueError`` if it is not one."""
        endpoint = subscription.get("endpoint")
        keys = subscription.get("keys")
        if not (isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) <= 2048):
            raise ValueError("The subscription has no https endpoint")
        if not (isinstance(keys, dict) and isinstance(keys.get("p256dh"), str) and isinstance(keys.get("auth"), str)):
            raise ValueError("The subscription has no encryption keys")
        data = json.dumps({"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}})
        with self._lock:
            self._conn.execute(
                "INSERT INTO push_subscription (endpoint, data, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT (endpoint) DO UPDATE SET data = excluded.data",
                (endpoint, data, _now()),
            )

    def remove_push_subscription(self, endpoint: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM push_subscription WHERE endpoint = ?", (endpoint,))

    def push_subscriptions(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT data FROM push_subscription").fetchall()
        return [json.loads(row["data"]) for row in rows]
