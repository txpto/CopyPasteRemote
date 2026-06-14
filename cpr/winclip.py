"""Windows clipboard helpers for text and Explorer file/folder selections."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List

PACKAGE_TEXT = "text"
PACKAGE_FILES = "files"


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Windows clipboard integration requires Windows")


def read_clipboard() -> Dict[str, object]:
    """Read text or file-list clipboard content from Windows."""
    _require_windows()
    import win32clipboard  # type: ignore
    import win32con  # type: ignore

    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            paths = list(win32clipboard.GetClipboardData(win32con.CF_HDROP))
            return {"type": PACKAGE_FILES, "paths": paths}
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return {"type": PACKAGE_TEXT, "text": win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)}
    finally:
        win32clipboard.CloseClipboard()
    raise RuntimeError("clipboard does not contain supported text, files, or folders")


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
    """Create a zip preserving selected file/folder names."""
    with zipfile.ZipFile(str(output_zip), "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for item in paths:
            path = Path(item)
            if path.is_file():
                archive.write(str(path), path.name)
            elif path.is_dir():
                for child in path.rglob("*"):
                    archive.write(str(child), str(Path(path.name) / child.relative_to(path)))
            else:
                raise RuntimeError("clipboard path no longer exists: %s" % item)


def extract_zip_for_clipboard(zip_path: Path, cache_dir: Path) -> List[str]:
    target = cache_dir / ("paste_" + next(tempfile._get_candidate_names()))
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(zip_path), "r") as archive:
        archive.extractall(str(target))
    return [str(child) for child in target.iterdir()]


def write_file_drop(paths: List[str]) -> None:
    """Set CF_HDROP so Explorer and applications can paste downloaded files."""
    _require_windows()
    import pythoncom  # type: ignore
    import win32clipboard  # type: ignore
    import win32con  # type: ignore
    from win32com.shell import shell  # type: ignore

    absolute_paths = [str(Path(path).resolve()) for path in paths]
    data_object = shell.SHCreateDataObject(None, None, absolute_paths, pythoncom.IID_IDataObject)
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_HDROP, data_object.GetData((win32con.CF_HDROP, None, 1, -1, pythoncom.TYMED_HGLOBAL)))
    finally:
        win32clipboard.CloseClipboard()


def clean_cache(cache_dir: Path, keep_latest: int = 20) -> None:
    if not cache_dir.exists():
        return
    children = sorted(cache_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in children[keep_latest:]:
        if stale.is_dir():
            shutil.rmtree(str(stale), ignore_errors=True)
        else:
            stale.unlink()
