"""Wire protocol shared by client and server.

Kept dependency-free (standard library only) so it imports cleanly on a bare
Python 3.8 install on Windows 7.  The server validates the same structures with
pydantic, but the canonical definition lives here.

Core concepts
-------------
* **Machine / slot** - every machine registered in the pool has an integer id in
  ``1..255``.  That id doubles as its *mailbox* (a.k.a. *slot*) number, which is
  what hotkeys refer to.  "Push to slot 2" means "drop my clipboard into the
  mailbox of machine 2".
* **Envelope** - a description of one clipboard payload (kind + metadata +
  either inline ciphertext or a reference to an uploaded blob).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from .version import PROTOCOL_VERSION

# --------------------------------------------------------------------------- #
# Clipboard content kinds
# --------------------------------------------------------------------------- #
KIND_EMPTY = "empty"
KIND_TEXT = "text"
KIND_FILES = "files"  # files and/or folders, packaged as a ZIP archive
KIND_IMAGE = "image"  # raster image, stored as PNG
KIND_HTML = "html"    # HTML fragment with a plain-text fallback

ALL_KINDS = (KIND_EMPTY, KIND_TEXT, KIND_FILES, KIND_IMAGE, KIND_HTML)

# Payloads at or below this size are carried inline (base64) inside the envelope
# JSON to save a round trip.  Larger payloads are uploaded as blobs first.
INLINE_THRESHOLD = 64 * 1024  # 64 KiB of ciphertext

MIN_SLOT = 1
MAX_SLOT = 255


def valid_slot(slot: int) -> bool:
    return isinstance(slot, int) and MIN_SLOT <= slot <= MAX_SLOT


# --------------------------------------------------------------------------- #
# File manifest entry (for KIND_FILES)
# --------------------------------------------------------------------------- #
@dataclass
class FileEntry:
    """One top-level item the user copied (a file or a folder root)."""

    name: str
    is_dir: bool
    size: int = 0  # total size in bytes (sum of contained files for folders)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "is_dir": self.is_dir, "size": self.size}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FileEntry":
        return FileEntry(
            name=d["name"], is_dir=bool(d.get("is_dir", False)), size=int(d.get("size", 0))
        )


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #
@dataclass
class Envelope:
    """Metadata describing a single clipboard payload.

    The actual bytes are always AES-GCM encrypted.  They travel either:

    * inline -> ``data_b64`` holds base64(ciphertext); ``blob_id`` is None, or
    * out-of-line -> ``blob_id`` references a blob uploaded ahead of time.
    """

    kind: str = KIND_EMPTY
    size: int = 0                 # plaintext size in bytes
    enc_size: int = 0             # ciphertext size in bytes
    sha256: str = ""              # sha256 of plaintext (integrity check)
    key_fp: str = ""              # pool-key fingerprint (detect key mismatch)
    meta: Dict[str, Any] = field(default_factory=dict)
    files: List[FileEntry] = field(default_factory=list)

    inline: bool = False
    data_b64: Optional[str] = None
    blob_id: Optional[str] = None

    # Filled in as the payload moves through the system.
    from_id: Optional[int] = None
    from_name: Optional[str] = None
    created_at: float = field(default_factory=lambda: time.time())
    protocol: str = PROTOCOL_VERSION

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["files"] = [f.to_dict() for f in self.files]
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Envelope":
        files = [FileEntry.from_dict(f) for f in d.get("files", []) or []]
        return Envelope(
            kind=d.get("kind", KIND_EMPTY),
            size=int(d.get("size", 0)),
            enc_size=int(d.get("enc_size", 0)),
            sha256=d.get("sha256", ""),
            key_fp=d.get("key_fp", ""),
            meta=d.get("meta", {}) or {},
            files=files,
            inline=bool(d.get("inline", False)),
            data_b64=d.get("data_b64"),
            blob_id=d.get("blob_id"),
            from_id=d.get("from_id"),
            from_name=d.get("from_name"),
            created_at=float(d.get("created_at", time.time())),
            protocol=d.get("protocol", PROTOCOL_VERSION),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_json(text: str) -> "Envelope":
        return Envelope.from_dict(json.loads(text))

    # Convenience -----------------------------------------------------------
    def human_summary(self) -> str:
        """Short human readable description, e.g. for tray notifications."""
        if self.kind == KIND_TEXT:
            return "text (%s)" % _human_size(self.size)
        if self.kind == KIND_IMAGE:
            w = self.meta.get("width")
            h = self.meta.get("height")
            dims = " %sx%s" % (w, h) if w and h else ""
            return "image%s (%s)" % (dims, _human_size(self.size))
        if self.kind == KIND_HTML:
            return "rich text (%s)" % _human_size(self.size)
        if self.kind == KIND_FILES:
            n = len(self.files)
            folders = sum(1 for f in self.files if f.is_dir)
            files = n - folders
            bits = []
            if files:
                bits.append("%d file%s" % (files, "s" if files != 1 else ""))
            if folders:
                bits.append("%d folder%s" % (folders, "s" if folders != 1 else ""))
            return "%s (%s)" % (", ".join(bits) or "items", _human_size(self.size))
        return "empty"


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return "%d B" % int(value)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%d B" % num


# --------------------------------------------------------------------------- #
# WebSocket message types (server <-> client real-time channel)
# --------------------------------------------------------------------------- #
WS_HELLO = "hello"             # server -> client, on connect
WS_PRESENCE = "presence"       # server -> client, a machine went online/offline
WS_CLIP_AVAILABLE = "clip"     # server -> client, new content in your mailbox
WS_POOL = "pool"               # server -> client, full pool snapshot
WS_PING = "ping"               # either direction, keepalive
WS_PONG = "pong"               # response to ping


def ws_message(msg_type: str, **fields: Any) -> str:
    payload = {"type": msg_type, "ts": time.time()}
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Hotkey action vocabulary (used by the client config)
# --------------------------------------------------------------------------- #
ACTION_PUSH = "push"     # send local clipboard to a target slot
ACTION_PULL = "pull"     # fetch a slot into the local clipboard (and maybe paste)
ACTION_PULL_OWN = "pull_own"  # fetch *my* mailbox into the local clipboard
