"""Clipboard change monitor for continuous bidirectional sync.

Watches the local clipboard and fires ``on_change`` when the user copies
something new. To avoid echo loops, the agent calls :meth:`note_self_write`
right after *it* writes the clipboard (e.g. applying incoming content), so that
self-induced change is absorbed instead of being re-broadcast.

Change detection:
* If the backend exposes ``change_token()`` (Windows clipboard sequence number),
  that is used - cheap and exact.
* Otherwise a content *signature* function is polled (used on Linux/macOS).
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

log = logging.getLogger("cpr.client.sync")


class ClipboardMonitor(threading.Thread):
    def __init__(
        self,
        backend,
        on_change: Callable[[], None],
        interval: float = 0.8,
        signature_fn: Optional[Callable[[], Optional[str]]] = None,
    ):
        super().__init__(name="cpr-clip-monitor", daemon=True)
        self.backend = backend
        self.on_change = on_change
        self.interval = max(0.2, float(interval))
        self.signature_fn = signature_fn
        self._stop = threading.Event()
        self._last = None

    def _token(self):
        try:
            tok = self.backend.change_token()
        except Exception:  # noqa: BLE001
            tok = None
        if tok is not None:
            return ("seq", tok)
        sig = None
        if self.signature_fn is not None:
            try:
                sig = self.signature_fn()
            except Exception:  # noqa: BLE001
                sig = None
        return ("sig", sig)

    def note_self_write(self) -> None:
        """Absorb the change produced by our own clipboard write."""
        self._last = self._token()

    def run(self) -> None:
        self._last = self._token()
        while not self._stop.wait(self.interval):
            tok = self._token()
            if tok != self._last:
                self._last = tok
                if tok[0] == "sig" and tok[1] is None:
                    continue  # empty/unreadable clipboard, ignore
                try:
                    self.on_change()
                except Exception as exc:  # noqa: BLE001
                    log.debug("clipboard on_change error: %s", exc)

    def stop(self) -> None:
        self._stop.set()
