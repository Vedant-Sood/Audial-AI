"""Bounded diagnostic history and stable duplicate suppression for UI alerts."""

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import threading
import time

from app.utils.paths import atomic_json, data_root


@dataclass
class Notice:
    code: str
    message: str
    severity: str
    action: str | None
    created: str
    count: int = 1


class NoticeHistory:
    def __init__(self, limit=200, cooldown=20, clock=time.monotonic, persist=True):
        self.items = deque(maxlen=limit)
        self.cooldown = cooldown
        self.clock = clock
        self.persist = persist
        self.recent = {}
        self.lock = threading.Lock()
        self.persistence_error = None
        if persist:
            try:
                path = data_root() / "logs" / "notifications.json"
                if path.is_file() and path.stat().st_size <= 2_000_000:
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    for item in saved[-limit:]:
                        notice = Notice(**item)
                        if notice.severity in {"info", "warning", "error"}:
                            self.items.append(notice)
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.persistence_error = str(error)

    def publish(self, message, severity="warning", code=None, action=None):
        if severity not in {"info", "warning", "error"}:
            raise ValueError("Unknown notification severity")
        message = str(message).strip()[:4000]
        if not message:
            return None, False
        code = code or message
        key = (code, message, severity)
        now = self.clock()
        with self.lock:
            previous = self.recent.get(key)
            if previous is not None and now - previous[0] < self.cooldown:
                previous[1].count += 1
                return previous[1], False
            notice = Notice(
                code, message, severity, action, datetime.now(timezone.utc).isoformat()
            )
            self.items.append(notice)
            self.recent = {
                k: v for k, v in self.recent.items() if now - v[0] < self.cooldown
            }
            while len(self.recent) >= self.items.maxlen:
                self.recent.pop(next(iter(self.recent)))
            self.recent[key] = (now, notice)
            if self.persist:
                try:
                    atomic_json(
                        data_root() / "logs" / "notifications.json",
                        [asdict(item) for item in self.items],
                    )
                except OSError as error:
                    # Disk-full or permissions errors must not hide the alert.
                    self.persistence_error = str(error)
            return notice, True

    def snapshot(self):
        with self.lock:
            return [asdict(item) for item in self.items]
