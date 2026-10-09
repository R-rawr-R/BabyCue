"""Background alarms: Web Push notifications that reach a parent phone even when BabyCue is closed.

A browser only wakes a closed web app through its vendor's push service (Google for Chrome, Apple for Safari), so
this needs the PC and the phone to be online. The message is end-to-end encrypted to the phone (RFC 8291): the
push service sees only that something was sent, never the alert. Video never takes this path.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from pathlib import Path

from babycue_server.db import Database

log = logging.getLogger(__name__)

#: VAPID "subject": how a push service could reach whoever runs this server. Apple insists on a real-looking one.
CONTACT = "mailto:babycue-monitor@example.com"
#: An alarm older than this is not worth delivering.
TTL_S = 120


def available() -> bool:
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return False
    return True


class PushNotifier:
    def __init__(self, db: Database, key_path: Path):
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from py_vapid import Vapid02

        if key_path.is_file():
            self._vapid = Vapid02.from_file(str(key_path))
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            self._vapid = Vapid02()
            self._vapid.generate_keys()
            self._vapid.save_key(str(key_path))
        raw = self._vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        #: What a phone passes to ``pushManager.subscribe`` as ``applicationServerKey``.
        self.public_key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        self._db = db
        self._lock = threading.Lock()  # one send round at a time, in order

    def notify(self, title: str, body: str, level: str, *, test: bool = False, only: str | None = None) -> None:
        """Send to every subscribed phone (or just the one whose endpoint is ``only``), on a background thread.

        A ``test`` shows even on a phone with BabyCue open.
        """
        payload = json.dumps({"title": title, "body": body, "level": level, "test": test})
        threading.Thread(target=self._send_all, args=(payload, level, only), name="babycue-push", daemon=True).start()

    def _send_all(self, payload: str, level: str, only: str | None = None) -> int:
        from pywebpush import WebPushException, webpush

        sent = 0
        with self._lock:
            for subscription in self._db.push_subscriptions():
                if only is not None and subscription["endpoint"] != only:
                    continue
                try:
                    webpush(
                        subscription,
                        data=payload,
                        vapid_private_key=self._vapid,
                        vapid_claims={"sub": CONTACT},
                        ttl=TTL_S,
                        timeout=10,
                        headers={"Urgency": "high" if level == "crit" else "normal"},
                    )
                    sent += 1
                except WebPushException as exc:
                    status = exc.response.status_code if exc.response is not None else None
                    if status in (404, 410):  # the phone unsubscribed or the app was removed
                        self._db.remove_push_subscription(subscription["endpoint"])
                        log.info("Dropped a phone that no longer takes alarms")
                    else:
                        log.warning("Background alarm not delivered (%s): %s", status, exc)
                except Exception as exc:  # noqa: BLE001 - no network must not break detection
                    log.warning("Background alarm not delivered: %s", exc)
        return sent
