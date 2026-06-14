"""Windows clipboard helpers for text, files/folders, and generic clipboard formats."""

from __future__ import annotations

import base64
import json
import os
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

PACKAGE_TEXT = "text"
PACKAGE_FILES = "files"
PACKAGE_CLIPBOARD = "clipboard"

# Formats that are either virtual, handles with process-local meaning, or are
# already handled by higher-fidelity paths. Other byte/string formats are copied
# into the generic snapshot so images, RTF, HTML, app-specific blobs, etc. can be
# moved when the producing/consuming application understands the same format.
SKIP_GENERIC_FORMATS = {
    2,   # CF_BITMAP
    3,   # CF_METAFILEPICT
    7,   # CF_OEMTEXT
    8,   # CF_DIB; many apps also expose PNG/HTML/other safer registered formats
    14,  # CF_ENHMETAFILE
    15,  # CF_HDROP; handled as native file/folder copy
    17,  # CF_DIBV5
}

STANDARD_FORMAT_NAMES = {
    1: "CF_TEXT",
    2: "CF_BITMAP",
    3: "CF_METAFILEPICT",
    4: "CF_SYLK",
    5: "CF_DIF",
    6: "CF_TIFF",
    7: "CF_OEMTEXT",
    8: "CF_DIB",
    9: "CF_PALETTE",
    10: "CF_PENDATA",
    11: "CF_RIFF",
    12: "CF_WAVE",
    13: "CF_UNICODETEXT",
    14: "CF_ENHMETAFILE",
    15: "CF_HDROP",
    16: "CF_LOCALE",
    17: "CF_DIBV5",
}


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Windows clipboard integration requires Windows")


def _format_name(format_id: int) -> str:
    import win32clipboard  # type: ignore

    if format_id in STANDARD_FORMAT_NAMES:
        return STANDARD_FORMAT_NAMES[format_id]
    name = win32clipboard.GetClipboardFormatName(format_id)
    return name or "FORMAT_%s" % format_id


def _serialize_clipboard_value(value: object) -> Optional[Dict[str, str]]:
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, str):
        return {"encoding": "utf-8", "data": value}
    return None


def _deserialize_clipboard_value(item: Dict[str, str]) -> object:
    if item["encoding"] == "base64":
        return base64.b64decode(item["data"].encode("ascii"))
    if item["encoding"] == "utf-8":
        return item["data"]
    raise RuntimeError("unsupported clipboard snapshot encoding: %s" % item["encoding"])


def read_clipboard() -> Dict[str, object]:
    """Read files/folders, text, or a generic serializable clipboard snapshot."""
    _require_windows()
    import win32clipboard  # type: ignore
    import win32con  # type: ignore

    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            paths = list(win32clipboard.GetClipboardData(win32con.CF_HDROP))
            return {"type": PACKAGE_FILES, "paths": paths}

        formats = []
        format_id = 0
        while True:
            format_id = win32clipboard.EnumClipboardFormats(format_id)
            if not format_id:
                break
            if format_id in SKIP_GENERIC_FORMATS:
                continue
            value = win32clipboard.GetClipboardData(format_id)
            serialized = _serialize_clipboard_value(value)
            if serialized:
                formats.append({"id": format_id, "name": _format_name(format_id), "value": serialized})

        format_ids = {int(item["id"]) for item in formats}
        text_only = bool(format_ids) and format_ids.issubset({win32con.CF_UNICODETEXT, win32con.CF_TEXT})
        if formats and not text_only:
            return {"type": PACKAGE_CLIPBOARD, "formats": formats}
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return {"type": PACKAGE_TEXT, "text": win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)}
        if formats:
            return {"type": PACKAGE_CLIPBOARD, "formats": formats}
    finally:
        win32clipboard.CloseClipboard()
    raise RuntimeError("clipboard does not contain a supported serializable format")


def write_text(text: str) -> None:
    _require_windows()
    import win32clipboard  # type: ignore
    import win32con  # type: ignore

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


def make_zip_from_paths(paths: List[str], output_zip: Path) -> None:
    """Create a zip preserving selected file/folder names, including empty directories."""
    with zipfile.ZipFile(str(output_zip), "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for item in paths:
            path = Path(item)
            if path.is_file():
                archive.write(str(path), path.name)
            elif path.is_dir():
                root = Path(path.name)
                archive.writestr(str(root).rstrip("/") + "/", b"")
                for child in path.rglob("*"):
                    relative = root / child.relative_to(path)
                    if child.is_dir():
                        archive.writestr(str(relative).rstrip("/") + "/", b"")
                    elif child.is_file():
                        archive.write(str(child), str(relative))
            else:
                raise RuntimeError("clipboard path no longer exists: %s" % item)


def extract_zip_for_clipboard(zip_path: Path, cache_dir: Path) -> List[str]:
    target = cache_dir / ("paste_" + next(tempfile._get_candidate_names()))
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(zip_path), "r") as archive:
        archive.extractall(str(target))
    return [str(child) for child in target.iterdir()]


def _build_hdrop(paths: List[str]) -> bytes:
    # DROPFILES: DWORD pFiles, POINT x/y, BOOL fNC, BOOL fWide, then double-null
    # terminated UTF-16LE path list.
    encoded_paths = "\0".join(str(Path(path).resolve()) for path in paths) + "\0\0"
    payload = encoded_paths.encode("utf-16le")
    return struct.pack("IiiII", 20, 0, 0, 0, 1) + payload


def write_file_drop(paths: List[str]) -> None:
    """Set CF_HDROP so Explorer and applications can paste downloaded files."""
    _require_windows()
    import win32clipboard  # type: ignore
    import win32con  # type: ignore

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_HDROP, _build_hdrop(paths))
    finally:
        win32clipboard.CloseClipboard()


def write_clipboard_snapshot(snapshot_path: Path) -> None:
    """Restore a generic clipboard snapshot made by read_clipboard()."""
    _require_windows()
    import win32clipboard  # type: ignore

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    formats = snapshot.get("formats", [])
    if not formats:
        raise RuntimeError("clipboard snapshot has no formats")
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        for item in formats:
            format_id = int(item["id"])
            if format_id >= 0xC000 and item.get("name"):
                format_id = win32clipboard.RegisterClipboardFormat(item["name"])
            win32clipboard.SetClipboardData(format_id, _deserialize_clipboard_value(item["value"]))
    finally:
        win32clipboard.CloseClipboard()


def write_clipboard_snapshot_file(content: Dict[str, object], output_path: Path) -> None:
    output_path.write_text(json.dumps(content, indent=2, sort_keys=True), encoding="utf-8")


def clean_cache(cache_dir: Path, keep_latest: int = 20) -> None:
    if not cache_dir.exists():
        return
    children = sorted(cache_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in children[keep_latest:]:
        if stale.is_dir():
            shutil.rmtree(str(stale), ignore_errors=True)
        else:
            stale.unlink()
