"""Real-time presence + notification hub over WebSockets.

Each connected machine gets one entry here.  The hub lets the REST layer push
"there is new clipboard content in your mailbox" notifications and broadcasts
online/offline transitions so every client's pool view stays fresh.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List

from starlette.websockets import WebSocket

from cpr_shared import protocol


class PresenceHub:
    def __init__(self) -> None:
        # slot -> set of websockets (a machine may briefly have >1 during reconnect)
        self._conns: Dict[int, List[WebSocket]] = {}
        # Created lazily inside the running loop: on Python 3.8 an asyncio.Lock
        # built at import time can bind to the wrong event loop.
        self._lock_obj = None

    @property
    def _lock(self) -> asyncio.Lock:
        if self._lock_obj is None:
            self._lock_obj = asyncio.Lock()
        return self._lock_obj

    async def connect(self, slot: int, ws: WebSocket) -> bool:
        """Register a socket. Returns True if this machine just came online."""
        async with self._lock:
            was_offline = slot not in self._conns or not self._conns[slot]
            self._conns.setdefault(slot, []).append(ws)
        return was_offline

    async def disconnect(self, slot: int, ws: WebSocket) -> bool:
        """Deregister a socket. Returns True if this machine is now fully offline."""
        async with self._lock:
            conns = self._conns.get(slot, [])
            if ws in conns:
                conns.remove(ws)
            now_offline = not conns
            if now_offline and slot in self._conns:
                del self._conns[slot]
        return now_offline

    async def online_slots(self) -> List[int]:
        async with self._lock:
            return sorted(self._conns.keys())

    async def is_online(self, slot: int) -> bool:
        async with self._lock:
            return bool(self._conns.get(slot))

    async def send_to(self, slot: int, message: str) -> None:
        async with self._lock:
            targets = list(self._conns.get(slot, []))
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                # Drop on failure; the socket's own loop will clean up.
                pass

    async def broadcast(self, message: str, exclude_slot: int = None) -> None:
        async with self._lock:
            targets = [
                (slot, ws)
                for slot, conns in self._conns.items()
                for ws in conns
                if slot != exclude_slot
            ]
        for _slot, ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                pass

    async def notify_clip_available(self, slot: int, envelope_meta: dict) -> None:
        await self.send_to(
            slot,
            protocol.ws_message(
                protocol.WS_CLIP_AVAILABLE,
                slot=slot,
                kind=envelope_meta.get("kind"),
                size=envelope_meta.get("size"),
                from_id=envelope_meta.get("from_id"),
                from_name=envelope_meta.get("from_name"),
                summary=envelope_meta.get("summary"),
            ),
        )

    async def announce_presence(self, slot: int, online: bool) -> None:
        await self.broadcast(
            protocol.ws_message(protocol.WS_PRESENCE, slot=slot, online=online),
            exclude_slot=slot,
        )
