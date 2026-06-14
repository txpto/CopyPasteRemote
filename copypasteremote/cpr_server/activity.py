"""In-memory activity log for the admin dashboard.

Keeps a bounded ring buffer of recent events (connections, pushes, pulls, …) so
the dashboard can show "who connected", "what was shared", origin and destination.
It is intentionally ephemeral (reset on restart) and never stores clipboard
*contents* — only metadata.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List


class ActivityLog:
    def __init__(self, maxlen: int = 500):
        self._events: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0

    def add(self, event_type: str, **fields: Any) -> None:
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "ts": time.time(), "type": event_type}
            event.update(fields)
            self._events.append(event)

    def recent(self, since_seq: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            items = [e for e in self._events if e["seq"] > since_seq]
        return items[-limit:]

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq
