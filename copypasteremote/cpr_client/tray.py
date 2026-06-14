"""System-tray UI (pystray): status, pool browser and manual push/pull.

The tray runs on the main thread (required on Windows); the agent, WebSocket and
hotkey worker all run on background threads.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Optional

from cpr_shared.protocol import Envelope

from .agent import Agent, AgentEvents
from .config import ClientConfig

log = logging.getLogger("cpr.client.tray")


def _make_icon_image(connected: bool):
    """Build a simple tray icon (green dot when connected, grey when not)."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, size - 6, size - 6], radius=12, fill=(40, 44, 52, 255))
    # Two overlapping "clipboard pages".
    d.rectangle([18, 16, 40, 44], fill=(220, 220, 220, 255))
    d.rectangle([24, 22, 46, 50], fill=(255, 255, 255, 255))
    status = (60, 200, 90, 255) if connected else (150, 150, 150, 255)
    d.ellipse([40, 40, 58, 58], fill=status)
    return img


class TrayEvents(AgentEvents):
    """Bridges agent events to tray notifications + pool cache updates."""

    def __init__(self, tray: "CprTray"):
        self.tray = tray

    def on_hello(self, machines: list) -> None:
        self.tray.update_pool_from_ws(machines)

    def on_presence(self, slot: int, online: bool) -> None:
        self.tray.set_presence(slot, online)

    def on_connection(self, connected: bool) -> None:
        self.tray.set_connected(connected)

    def on_clip_available(self, slot: int, info: dict) -> None:
        if slot == self.tray.config.machine_id:
            summary = info.get("summary") or info.get("kind") or "content"
            frm = info.get("from_name") or ("machine %s" % info.get("from_id"))
            self.tray.notify("Clipboard ready", "%s from %s" % (summary, frm))

    def on_pushed(self, slot: int, env: Envelope) -> None:
        name = self.tray.name_for(slot)
        self.tray.notify("Sent", "%s -> %s" % (env.human_summary(), name))

    def on_pulled(self, slot: int, env: Envelope) -> None:
        self.tray.notify("Pasted", env.human_summary())

    def on_error(self, message: str) -> None:
        log.error(message)
        self.tray.notify("CopyPasteRemote", message)


class CprTray:
    def __init__(self, config: ClientConfig):
        self.config = config
        self.agent: Optional[Agent] = None
        self.hotkeys = None
        self._icon = None
        self._connected = False
        self._pool: List[Dict] = []
        self._lock = threading.Lock()

    # -- wiring -------------------------------------------------------------
    def attach(self, agent: Agent, hotkeys) -> None:
        self.agent = agent
        self.hotkeys = hotkeys

    # -- pool state ---------------------------------------------------------
    def refresh_pool(self) -> None:
        if not self.agent:
            return
        try:
            data = self.agent.get_pool()
            with self._lock:
                self._pool = data.get("machines", [])
        except Exception as exc:  # noqa: BLE001
            log.debug("refresh_pool failed: %s", exc)
        self._update_icon()

    def update_pool_from_ws(self, machines: list) -> None:
        with self._lock:
            self._pool = [
                {
                    "slot": m.get("slot"),
                    "name": m.get("name"),
                    "online": m.get("online", False),
                    "is_me": m.get("slot") == self.config.machine_id,
                }
                for m in machines
            ]
        self._update_icon()

    def set_presence(self, slot: int, online: bool) -> None:
        with self._lock:
            for m in self._pool:
                if m.get("slot") == slot:
                    m["online"] = online
        self._update_icon()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._update_icon()
        if connected:
            self.refresh_pool()

    def name_for(self, slot: int) -> str:
        with self._lock:
            for m in self._pool:
                if m.get("slot") == slot:
                    return "%d:%s" % (slot, m.get("name", "?"))
        return "slot %d" % slot

    # -- notifications ------------------------------------------------------
    def notify(self, title: str, message: str) -> None:
        if not self.config.notifications:
            return
        try:
            if self._icon is not None:
                self._icon.notify(message, title)
        except Exception as exc:  # noqa: BLE001
            log.debug("notify failed: %s", exc)

    # -- menu ---------------------------------------------------------------
    def _target_items(self, action: str):
        import pystray

        items = []
        with self._lock:
            pool = list(self._pool)
        for m in pool:
            slot = m.get("slot")
            if slot is None:
                continue
            mark = "● " if m.get("online") else "○ "
            me = " (me)" if m.get("slot") == self.config.machine_id else ""
            label = "%s%d: %s%s" % (mark, slot, m.get("name", "?"), me)
            if action == "push":
                cb = (lambda s: (lambda icon, item: self._do_push(s)))(slot)
            else:
                cb = (lambda s: (lambda icon, item: self._do_pull(s)))(slot)
            items.append(pystray.MenuItem(label, cb))
        if not items:
            items.append(pystray.MenuItem("(pool empty - refresh)", lambda i, it: self.refresh_pool()))
        return items

    def _build_menu(self):
        import pystray

        return pystray.Menu(
            pystray.MenuItem(
                "%s  (slot %d)" % (self.config.machine_name or "this PC", self.config.machine_id),
                None,
                enabled=False,
            ),
            pystray.MenuItem(
                lambda item: "Status: %s" % ("connected" if self._connected else "offline"),
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Send clipboard to", pystray.Menu(lambda: self._target_items("push"))),
            pystray.MenuItem("Paste from", pystray.Menu(lambda: self._target_items("pull"))),
            pystray.MenuItem("Paste my mailbox", lambda i, it: self._do_pull_own()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Refresh pool", lambda i, it: self.refresh_pool()),
            pystray.MenuItem("Open config folder", lambda i, it: self._open_config_dir()),
            pystray.MenuItem("Quit", lambda i, it: self.stop()),
        )

    # -- actions (run off the UI thread to avoid blocking the menu) ---------
    def _do_push(self, slot: int) -> None:
        threading.Thread(target=self._safe, args=(self.agent.push, slot), daemon=True).start()

    def _do_pull(self, slot: int) -> None:
        threading.Thread(target=self._safe, args=(self.agent.pull, slot), daemon=True).start()

    def _do_pull_own(self) -> None:
        threading.Thread(target=self._safe, args=(self.agent.pull_own,), daemon=True).start()

    def _safe(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            self.notify("CopyPasteRemote", str(exc))

    def _open_config_dir(self) -> None:
        try:
            os.startfile(os.path.dirname(self.config.config_path))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            log.debug("open config dir failed: %s", exc)

    # -- lifecycle ----------------------------------------------------------
    def _update_icon(self) -> None:
        if self._icon is not None:
            try:
                self._icon.icon = _make_icon_image(self._connected)
            except Exception:
                pass

    def run(self) -> None:
        import pystray

        self._icon = pystray.Icon(
            "CopyPasteRemote",
            icon=_make_icon_image(False),
            title="CopyPasteRemote",
            menu=self._build_menu(),
        )
        # Populate the pool shortly after the tray appears.
        threading.Timer(1.0, self.refresh_pool).start()
        self._icon.run()

    def stop(self) -> None:
        if self.hotkeys:
            self.hotkeys.stop()
        if self.agent:
            self.agent.close()
        if self._icon is not None:
            self._icon.stop()
