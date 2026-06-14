"""Global hotkey manager (built on the cross-platform ``keyboard`` library).

Hotkey callbacks must return fast (they run inside the keyboard hook), so each
press only *enqueues* an action.  A single worker thread then runs the actual
push/pull operations one at a time - this also guarantees we never touch the
clipboard from two operations at once.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

from .config import ClientConfig

log = logging.getLogger("cpr.client.hotkeys")


class HotkeyManager:
    def __init__(
        self,
        config: ClientConfig,
        on_push: Callable[[int], None],
        on_pull: Callable[[int], None],
        on_pull_own: Callable[[], None],
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.config = config
        self.on_push = on_push
        self.on_pull = on_pull
        self.on_pull_own = on_pull_own
        self.on_error = on_error or (lambda m: log.error(m))
        self._queue: "queue.Queue" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._registered = False
        self._keyboard = None

    # ------------------------------------------------------------------ start
    def start(self) -> None:
        import keyboard  # lazy: only needed when actually running the agent

        self._keyboard = keyboard
        self._stop.clear()
        self._worker = threading.Thread(target=self._run_worker, name="cpr-hotkeys", daemon=True)
        self._worker.start()
        self._register(keyboard)

    def _register(self, keyboard) -> None:
        registered = []
        # Push: send local clipboard to mailbox N.
        for slot_str, combo in (self.config.push_hotkeys or {}).items():
            if not combo:
                continue
            slot = int(slot_str)
            try:
                keyboard.add_hotkey(combo, self._enqueue, args=("push", slot))
                registered.append(combo)
            except Exception as exc:  # noqa: BLE001
                self.on_error("Could not bind push hotkey %s: %s" % (combo, exc))

        # Pull: fetch mailbox N into the local clipboard (and paste).
        for slot_str, combo in (self.config.pull_hotkeys or {}).items():
            if not combo:
                continue
            slot = int(slot_str)
            try:
                keyboard.add_hotkey(combo, self._enqueue, args=("pull", slot))
                registered.append(combo)
            except Exception as exc:  # noqa: BLE001
                self.on_error("Could not bind pull hotkey %s: %s" % (combo, exc))

        # Pull own mailbox.
        if self.config.pull_own_hotkey:
            try:
                keyboard.add_hotkey(
                    self.config.pull_own_hotkey, self._enqueue, args=("pull_own", 0)
                )
                registered.append(self.config.pull_own_hotkey)
            except Exception as exc:  # noqa: BLE001
                self.on_error(
                    "Could not bind pull-own hotkey %s: %s"
                    % (self.config.pull_own_hotkey, exc)
                )

        self._registered = True
        log.info("Registered %d hotkeys: %s", len(registered), ", ".join(registered))

    # ------------------------------------------------------------------- stop
    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        if self._keyboard and self._registered:
            try:
                self._keyboard.remove_all_hotkeys()
            except Exception:
                pass
            self._registered = False

    # ------------------------------------------------------------- internals
    def _enqueue(self, action: str, slot: int) -> None:
        # Runs inside the keyboard hook -> keep it trivial.
        self._queue.put((action, slot))

    def _run_worker(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                break
            action, slot = item
            try:
                if action == "push":
                    self.on_push(slot)
                elif action == "pull":
                    self.on_pull(slot)
                elif action == "pull_own":
                    self.on_pull_own()
            except Exception as exc:  # noqa: BLE001
                self.on_error("%s failed: %s" % (action, exc))
