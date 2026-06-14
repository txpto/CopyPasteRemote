"""Convert between :class:`ClipData` and the wire (Envelope + plaintext bytes).

Encryption is applied by the agent *after* serialisation, so this module deals
only in plaintext.  It is pure and cross-platform (tested without Windows).
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import BinaryIO, List, Optional

from cpr_shared import crypto, protocol
from cpr_shared.protocol import Envelope

from . import packaging
from .clipdata import ClipData


# --------------------------------------------------------------------------- #
# Plaintext source abstraction (bytes in memory, or a file on disk)
# --------------------------------------------------------------------------- #
class PlaintextSource:
    """A re-openable source of plaintext bytes with a known size."""

    size: int = 0

    def open(self) -> BinaryIO:  # pragma: no cover - interface
        raise NotImplementedError

    def cleanup(self) -> None:
        pass


class BytesSource(PlaintextSource):
    def __init__(self, data: bytes):
        self._data = data
        self.size = len(data)

    def open(self) -> BinaryIO:
        return io.BytesIO(self._data)


class FileSource(PlaintextSource):
    def __init__(self, path: str, delete_on_cleanup: bool = True):
        self.path = path
        self.delete_on_cleanup = delete_on_cleanup
        self.size = os.path.getsize(path)

    def open(self) -> BinaryIO:
        return open(self.path, "rb")

    def cleanup(self) -> None:
        if self.delete_on_cleanup:
            packaging._safe_remove(self.path)


# --------------------------------------------------------------------------- #
# Serialize: ClipData -> (Envelope, PlaintextSource)
# --------------------------------------------------------------------------- #
def serialize(clip: ClipData, key: bytes, temp_dir: Optional[str] = None) -> "Serialized":
    kind = clip.kind
    if kind == protocol.KIND_TEXT:
        data = (clip.text or "").encode("utf-8")
        env = Envelope(kind=kind, size=len(data))
        source: PlaintextSource = BytesSource(data)

    elif kind == protocol.KIND_HTML:
        blob = json.dumps({"html": clip.html or "", "text": clip.text or ""}).encode("utf-8")
        env = Envelope(kind=kind, size=len(blob), meta={"has_text": bool(clip.text)})
        source = BytesSource(blob)

    elif kind == protocol.KIND_IMAGE:
        data = clip.image_png or b""
        env = Envelope(
            kind=kind,
            size=len(data),
            meta={
                "format": "png",
                "width": clip.meta.get("width", 0),
                "height": clip.meta.get("height", 0),
            },
        )
        source = BytesSource(data)

    elif kind == protocol.KIND_FILES:
        if not clip.paths:
            raise ValueError("KIND_FILES requires paths")
        zip_path, entries, total = packaging.pack_paths(clip.paths, dest_dir=temp_dir)
        env = Envelope(
            kind=kind,
            size=total,
            files=entries,
            meta={"zip_size": os.path.getsize(zip_path)},
        )
        source = FileSource(zip_path, delete_on_cleanup=True)
    else:
        raise ValueError("Unsupported clip kind: %s" % kind)

    env.key_fp = crypto.key_fingerprint(key)
    return Serialized(envelope=env, source=source)


@dataclass
class Serialized:
    envelope: Envelope
    source: PlaintextSource


# --------------------------------------------------------------------------- #
# Deserialize: (Envelope, plaintext) -> ClipData
# --------------------------------------------------------------------------- #
@dataclass
class Deserialized:
    clip: ClipData
    # Directories/files materialised on disk that the caller owns and should
    # clean up once the user has finished pasting.
    materialised: List[str]


def deserialize(
    env: Envelope,
    *,
    data: Optional[bytes] = None,
    path: Optional[str] = None,
    temp_dir: Optional[str] = None,
) -> Deserialized:
    """Rebuild a :class:`ClipData` from a decrypted plaintext source.

    ``data`` (bytes) is used for text/image/html; ``path`` (a decrypted ZIP on
    disk) is used for files.  If both are given, ``path`` wins for files.
    """
    kind = env.kind

    if kind == protocol.KIND_TEXT:
        raw = _need_bytes(data, path)
        return Deserialized(ClipData.text_data(raw.decode("utf-8", errors="replace")), [])

    if kind == protocol.KIND_HTML:
        raw = _need_bytes(data, path)
        obj = json.loads(raw.decode("utf-8", errors="replace"))
        return Deserialized(ClipData.html_data(obj.get("html", ""), obj.get("text", "")), [])

    if kind == protocol.KIND_IMAGE:
        raw = _need_bytes(data, path)
        clip = ClipData.image_data(
            raw, width=env.meta.get("width", 0), height=env.meta.get("height", 0)
        )
        return Deserialized(clip, [])

    if kind == protocol.KIND_FILES:
        if not path:
            # Materialise inline bytes to a temp zip so we can extract it.
            import tempfile

            fd, path = tempfile.mkstemp(suffix=".zip", prefix="cpr_recv_", dir=temp_dir)
            with os.fdopen(fd, "wb") as fh:
                fh.write(_need_bytes(data, None))
            delete_zip = True
        else:
            delete_zip = True

        import tempfile

        dest = tempfile.mkdtemp(prefix="cpr_files_", dir=temp_dir)
        try:
            paths = packaging.unpack_zip(path, dest)
        finally:
            if delete_zip:
                packaging._safe_remove(path)
        return Deserialized(ClipData.files_data(paths), [dest])

    raise ValueError("Unsupported envelope kind: %s" % kind)


def _need_bytes(data: Optional[bytes], path: Optional[str]) -> bytes:
    if data is not None:
        return data
    if path is not None:
        with open(path, "rb") as fh:
            return fh.read()
    raise ValueError("No plaintext provided")
