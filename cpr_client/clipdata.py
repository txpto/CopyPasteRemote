"""Platform-neutral representation of one clipboard payload.

The Windows clipboard backend produces/consumes :class:`ClipData`; everything
else in the client (serializer, agent, tests) works against this struct, never
against Win32 directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from cpr_shared import protocol


@dataclass
class ClipData:
    kind: str
    text: Optional[str] = None            # KIND_TEXT, and plain fallback for KIND_HTML
    html: Optional[str] = None            # KIND_HTML fragment
    paths: Optional[List[str]] = None     # KIND_FILES: absolute local paths
    image_png: Optional[bytes] = None     # KIND_IMAGE: PNG-encoded bytes
    meta: Dict = field(default_factory=dict)

    @staticmethod
    def text_data(text: str) -> "ClipData":
        return ClipData(kind=protocol.KIND_TEXT, text=text)

    @staticmethod
    def files_data(paths: List[str]) -> "ClipData":
        return ClipData(kind=protocol.KIND_FILES, paths=list(paths))

    @staticmethod
    def image_data(png: bytes, width: int = 0, height: int = 0) -> "ClipData":
        return ClipData(
            kind=protocol.KIND_IMAGE, image_png=png, meta={"width": width, "height": height}
        )

    @staticmethod
    def html_data(html: str, text: Optional[str] = None) -> "ClipData":
        return ClipData(kind=protocol.KIND_HTML, html=html, text=text)

    def describe(self) -> str:
        if self.kind == protocol.KIND_TEXT:
            n = len(self.text or "")
            return "text (%d chars)" % n
        if self.kind == protocol.KIND_FILES:
            return "%d item(s)" % len(self.paths or [])
        if self.kind == protocol.KIND_IMAGE:
            return "image"
        if self.kind == protocol.KIND_HTML:
            return "rich text"
        return "empty"
