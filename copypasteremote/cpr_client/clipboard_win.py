"""Windows clipboard backend (text, files/folders, images, HTML).

This is the only client module that talks to Win32 directly.  Native imports are
done lazily inside :class:`WindowsClipboard` so the package still imports on
non-Windows machines (handy for tests/tooling); instantiating it off-Windows
raises a clear error.

Notes on file copy/paste
------------------------
The Windows clipboard does **not** carry file *contents* - copying files in
Explorer puts a ``CF_HDROP`` list of *paths* on the clipboard.  So:

* reading  -> we get the paths, then the packaging layer reads the real bytes;
* writing  -> after we extract received files to a temp folder, we build a fresh
  ``CF_HDROP`` pointing at those temp paths, so a normal Ctrl+V drops the files
  into Explorer exactly like a native paste.
"""

from __future__ import annotations

import ctypes
import io
import logging
import struct
import time
from typing import List, Optional

from cpr_shared import protocol

from .agent import ClipboardBackend
from .clipdata import ClipData

log = logging.getLogger("cpr.client.clipboard")

# Registered (non-standard) clipboard format names.
_CF_HTML_NAME = "HTML Format"
_CF_FILENAMEW = "FileNameW"


class ClipboardUnavailable(Exception):
    pass


def _require_windows():
    import os

    if os.name != "nt":
        raise ClipboardUnavailable("The Windows clipboard backend only runs on Windows")


class WindowsClipboard(ClipboardBackend):
    def __init__(self):
        _require_windows()
        # Import native deps lazily so this module imports anywhere.
        import win32clipboard  # noqa: F401
        import win32con  # noqa: F401

        self._win32clipboard = win32clipboard
        self._win32con = win32con
        self._cf_html = win32clipboard.RegisterClipboardFormat(_CF_HTML_NAME)

    # ------------------------------------------------------------------ open
    def _open(self, retries: int = 10, delay: float = 0.05):
        last = None
        for _ in range(retries):
            try:
                self._win32clipboard.OpenClipboard()
                return
            except Exception as exc:  # clipboard busy
                last = exc
                time.sleep(delay)
        raise ClipboardUnavailable("Could not open clipboard: %s" % last)

    def _close(self):
        try:
            self._win32clipboard.CloseClipboard()
        except Exception:
            pass

    # ------------------------------------------------------------------ read
    def read(self) -> Optional[ClipData]:
        wc = self._win32clipboard
        win32con = self._win32con
        self._open()
        try:
            available = set(_enum_formats(wc))

            # 1) Files / folders take priority (matches Explorer behaviour).
            if win32con.CF_HDROP in available:
                try:
                    paths = list(wc.GetClipboardData(win32con.CF_HDROP))
                    if paths:
                        return ClipData.files_data([str(p) for p in paths])
                except Exception as exc:  # noqa: BLE001
                    log.debug("CF_HDROP read failed: %s", exc)

            # 2) Bitmap image.
            if win32con.CF_DIB in available:
                try:
                    dib = wc.GetClipboardData(win32con.CF_DIB)
                    png, w, h = _dib_to_png(dib)
                    if png:
                        return ClipData.image_data(png, w, h)
                except Exception as exc:  # noqa: BLE001
                    log.debug("CF_DIB read failed: %s", exc)

            # 3) HTML (rich text) with a plain-text fallback.
            if self._cf_html in available and win32con.CF_UNICODETEXT in available:
                try:
                    raw = wc.GetClipboardData(self._cf_html)
                    html = _parse_cf_html(raw)
                    text = wc.GetClipboardData(win32con.CF_UNICODETEXT)
                    if html:
                        return ClipData.html_data(html, text)
                except Exception as exc:  # noqa: BLE001
                    log.debug("HTML read failed: %s", exc)

            # 4) Plain text.
            if win32con.CF_UNICODETEXT in available:
                text = wc.GetClipboardData(win32con.CF_UNICODETEXT)
                if text:
                    return ClipData.text_data(text)

            return None
        finally:
            self._close()

    # ----------------------------------------------------------------- write
    def write(self, clip: ClipData) -> None:
        wc = self._win32clipboard
        win32con = self._win32con
        self._open()
        try:
            wc.EmptyClipboard()
            if clip.kind == protocol.KIND_TEXT:
                wc.SetClipboardData(win32con.CF_UNICODETEXT, clip.text or "")

            elif clip.kind == protocol.KIND_HTML:
                # Set both rich + plain so any target app can consume it.
                if clip.text is not None:
                    wc.SetClipboardData(win32con.CF_UNICODETEXT, clip.text or "")
                try:
                    cf_html_bytes = _build_cf_html(clip.html or "")
                    _set_bytes(wc, self._cf_html, cf_html_bytes)
                except Exception as exc:  # noqa: BLE001
                    log.debug("HTML write failed, kept plain text: %s", exc)

            elif clip.kind == protocol.KIND_IMAGE:
                try:
                    dib = _png_to_dib(clip.image_png or b"")
                    _set_bytes(wc, win32con.CF_DIB, dib)
                except Exception as exc:  # noqa: BLE001
                    log.debug("Image write failed: %s", exc)

            elif clip.kind == protocol.KIND_FILES:
                paths = clip.paths or []
                drop = _build_dropfiles(paths)
                _set_bytes(wc, win32con.CF_HDROP, drop)

            else:
                raise ValueError("Unsupported clip kind for write: %s" % clip.kind)
        finally:
            self._close()

    # ------------------------------------------------------- input simulation
    def simulate_copy(self) -> None:
        _send_ctrl_key("c")

    def simulate_paste(self) -> None:
        _send_ctrl_key("v")


# --------------------------------------------------------------------------- #
# Win32 helpers
# --------------------------------------------------------------------------- #
def _enum_formats(wc) -> List[int]:
    formats = []
    fmt = 0
    while True:
        fmt = wc.EnumClipboardFormats(fmt)
        if fmt == 0:
            break
        formats.append(fmt)
    return formats


def _set_bytes(wc, fmt: int, data: bytes) -> None:
    """Place raw bytes onto the clipboard under ``fmt`` via a moveable HGLOBAL."""
    kernel32 = ctypes.windll.kernel32
    GMEM_MOVEABLE = 0x0002
    size = len(data)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        raise MemoryError("GlobalAlloc failed")
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        raise MemoryError("GlobalLock failed")
    try:
        ctypes.memmove(ptr, data, size)
    finally:
        kernel32.GlobalUnlock(handle)
    # On success the system owns the memory; do not free it.
    wc.SetClipboardData(fmt, handle)


def _build_dropfiles(paths: List[str]) -> bytes:
    """Build a CF_HDROP (DROPFILES + double-null-terminated wide path list)."""
    # DROPFILES: pFiles(DWORD)=offset to list(20), pt.x, pt.y, fNC, fWide=1
    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)
    body = "".join(p + "\x00" for p in paths) + "\x00"
    return header + body.encode("utf-16-le")


def _send_ctrl_key(letter: str) -> None:
    """Send Ctrl+<letter> using the keyboard module (falls back to keybd_event)."""
    try:
        import keyboard

        keyboard.send("ctrl+%s" % letter)
        return
    except Exception:
        pass
    # Fallback: raw keybd_event.
    user32 = ctypes.windll.user32
    VK_CONTROL = 0x11
    KEYEVENTF_KEYUP = 0x0002
    vk = ord(letter.upper())
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# --------------------------------------------------------------------------- #
# Image (DIB <-> PNG) via Pillow
# --------------------------------------------------------------------------- #
def _dib_to_png(dib: bytes):
    """Convert a CF_DIB byte string to PNG bytes; returns (png, width, height)."""
    from PIL import Image

    # Parse just enough of BITMAPINFOHEADER to compute the pixel-data offset.
    if len(dib) < 40:
        return None, 0, 0
    header_size, width, height, planes, bitcount = struct.unpack("<IiiHH", dib[:16])
    compression, _img_size, _xppm, _yppm, clr_used, _clr_imp = struct.unpack(
        "<IIiiII", dib[16:40]
    )
    if clr_used == 0 and bitcount <= 8:
        clr_used = 1 << bitcount
    palette_bytes = clr_used * 4
    bitfields = 12 if compression == 3 else 0  # BI_BITFIELDS
    pixel_offset = 14 + header_size + bitfields + palette_bytes

    file_size = 14 + len(dib)
    bmp_header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, pixel_offset)
    bmp = bmp_header + dib
    img = Image.open(io.BytesIO(bmp))
    img.load()
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue(), img.width, img.height


def _png_to_dib(png: bytes) -> bytes:
    """Convert PNG bytes to a CF_DIB byte string (BMP minus the 14-byte header)."""
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="BMP")
    bmp = out.getvalue()
    # Strip the 14-byte BITMAPFILEHEADER -> the rest is the DIB.
    return bmp[14:]


# --------------------------------------------------------------------------- #
# HTML clipboard format (CF_HTML) build/parse
# --------------------------------------------------------------------------- #
_CF_HTML_TEMPLATE = (
    "Version:0.9\r\n"
    "StartHTML:%09d\r\n"
    "EndHTML:%09d\r\n"
    "StartFragment:%09d\r\n"
    "EndFragment:%09d\r\n"
)


def _build_cf_html(fragment_html: str) -> bytes:
    """Wrap an HTML fragment in the CF_HTML format with correct byte offsets."""
    pre = "<html><body><!--StartFragment-->"
    post = "<!--EndFragment--></body></html>"
    # Compute offsets in bytes (UTF-8). The header has a fixed length because the
    # numbers are zero-padded to 9 digits.
    header_len = len(_CF_HTML_TEMPLATE % (0, 0, 0, 0))
    start_html = header_len
    start_fragment = start_html + len(pre.encode("utf-8"))
    end_fragment = start_fragment + len(fragment_html.encode("utf-8"))
    end_html = end_fragment + len(post.encode("utf-8"))
    header = _CF_HTML_TEMPLATE % (start_html, end_html, start_fragment, end_fragment)
    return (header + pre + fragment_html + post).encode("utf-8")


def _parse_cf_html(raw) -> Optional[str]:
    """Extract the fragment between StartFragment/EndFragment markers."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)
    start = text.find("<!--StartFragment-->")
    end = text.find("<!--EndFragment-->")
    if start != -1 and end != -1:
        return text[start + len("<!--StartFragment-->"): end]
    # Fall back to the StartFragment offset header if comments are absent.
    return None
