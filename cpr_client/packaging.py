"""Package files/folders into a ZIP and back, preserving structure.

This is how "copy a file or a folder" works across machines: Windows only puts
file *references* on the clipboard, so the client reads the referenced files,
packs them here, transfers the archive, then unpacks on the far side and puts the
*new* local paths back on the clipboard.

Pure standard library, so it unit-tests on any OS.
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from typing import List, Tuple

from cpr_shared.protocol import FileEntry


class PackagingError(Exception):
    pass


def _iter_dir_files(root: str):
    """Yield (absolute_path, arc_relative_path) for everything under ``root``."""
    base_parent = os.path.dirname(os.path.normpath(root))
    for dirpath, dirnames, filenames in os.walk(root):
        # Record empty directories explicitly so they survive the round trip.
        if not dirnames and not filenames:
            arc = os.path.relpath(dirpath, base_parent)
            yield dirpath, arc + "/", True
        for fname in filenames:
            absf = os.path.join(dirpath, fname)
            arc = os.path.relpath(absf, base_parent)
            yield absf, arc, False


def pack_paths(paths: List[str], dest_dir: str = None) -> Tuple[str, List[FileEntry], int]:
    """Pack the given top-level paths into a temp ZIP.

    Returns ``(zip_path, entries, total_uncompressed_size)``.
    Arc names are rooted at each item's *base name*, so a folder ``C:\\a\\b`` is
    stored as ``b/...`` and restored as ``b`` on the other machine.
    """
    if not paths:
        raise PackagingError("No paths to pack")

    fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="cpr_pack_", dir=dest_dir)
    os.close(fd)

    entries: List[FileEntry] = []
    total = 0
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for raw in paths:
                p = os.path.normpath(raw)
                if not os.path.exists(p):
                    raise PackagingError("Path does not exist: %s" % p)
                name = os.path.basename(p.rstrip("\\/"))
                if os.path.isdir(p):
                    size = 0
                    wrote_anything = False
                    for absf, arc, is_dir in _iter_dir_files(p):
                        if is_dir:
                            zf.writestr(arc, b"")
                            wrote_anything = True
                        else:
                            zf.write(absf, arc)
                            size += os.path.getsize(absf)
                            wrote_anything = True
                    if not wrote_anything:
                        zf.writestr(name + "/", b"")
                    entries.append(FileEntry(name=name, is_dir=True, size=size))
                    total += size
                else:
                    zf.write(p, name)
                    fsize = os.path.getsize(p)
                    entries.append(FileEntry(name=name, is_dir=False, size=fsize))
                    total += fsize
    except Exception:
        _safe_remove(zip_path)
        raise
    return zip_path, entries, total


def unpack_zip(zip_path: str, dest_dir: str) -> List[str]:
    """Extract ``zip_path`` into ``dest_dir`` and return top-level extracted paths.

    Guards against Zip-Slip (entries escaping ``dest_dir``).
    """
    os.makedirs(dest_dir, exist_ok=True)
    dest_abs = os.path.abspath(dest_dir)
    top_level = []
    seen = set()

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            target = os.path.abspath(os.path.join(dest_dir, name))
            if not (target == dest_abs or target.startswith(dest_abs + os.sep)):
                raise PackagingError("Unsafe path in archive: %s" % name)
            # Track the first path component as a top-level item.
            first = name.replace("\\", "/").split("/", 1)[0]
            if first and first not in seen:
                seen.add(first)
                top_level.append(os.path.join(dest_dir, first))
        zf.extractall(dest_dir)

    return top_level


def _safe_remove(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
