"""Cross-platform clipboard backend for Linux and macOS.

It shells out to the standard clipboard utilities so it needs no compiled
dependencies:

* **macOS**: ``pbcopy`` / ``pbpaste`` for text, ``osascript`` for files.
* **Linux**: ``wl-copy`` / ``wl-paste`` (Wayland) or ``xclip`` / ``xsel`` (X11);
  files travel as ``text/uri-list``.

Text is fully supported on both. Files/folders work via ``text/uri-list`` on
Linux and AppleScript on macOS. Images are best-effort on Linux; if a capability
is unavailable the backend degrades gracefully (text still works).

The URI<->path helpers are pure functions and are unit-tested.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from typing import List, Optional
from urllib.parse import quote, unquote, urlparse

from cpr_shared import protocol

from .agent import ClipboardBackend
from .clipdata import ClipData

log = logging.getLogger("cpr.client.clipboard.posix")


class ClipboardUnavailable(Exception):
    pass


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------- #
def paths_to_uri_list(paths: List[str]) -> bytes:
    """Encode local paths as a CRLF-separated text/uri-list payload."""
    lines = []
    for p in paths:
        ap = os.path.abspath(p)
        lines.append("file://" + quote(ap))
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def uri_list_to_paths(data: bytes) -> List[str]:
    """Decode a text/uri-list payload into local file paths (ignores comments)."""
    text = data.decode("utf-8", errors="replace")
    paths = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = urlparse(line)
        if parsed.scheme and parsed.scheme != "file":
            continue
        paths.append(unquote(parsed.path) if parsed.scheme == "file" else unquote(line))
    return paths


# --------------------------------------------------------------------------- #
# Backend
# --------------------------------------------------------------------------- #
def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _run(cmd: List[str], data: Optional[bytes] = None) -> "tuple[int, bytes]":
    proc = subprocess.run(
        cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    return proc.returncode, proc.stdout or b""


class PosixClipboard(ClipboardBackend):
    def __init__(self):
        self.is_mac = platform.system() == "Darwin"
        if self.is_mac:
            if not _have("pbcopy"):
                raise ClipboardUnavailable("pbcopy/pbpaste not found")
            self.linux_tool = None
        else:
            self.linux_tool = self._pick_linux_tool()
            if self.linux_tool is None:
                raise ClipboardUnavailable(
                    "No clipboard tool found. Install wl-clipboard (Wayland) or xclip/xsel (X11)."
                )

    def _pick_linux_tool(self) -> Optional[str]:
        if os.environ.get("WAYLAND_DISPLAY") and _have("wl-copy") and _have("wl-paste"):
            return "wl"
        if _have("xclip"):
            return "xclip"
        if _have("xsel"):
            return "xsel"
        if _have("wl-copy") and _have("wl-paste"):
            return "wl"
        return None

    # ------------------------------------------------------------------ read
    def read(self) -> Optional[ClipData]:
        # 1) Files first (matches desktop behaviour).
        paths = self._read_files()
        if paths:
            return ClipData.files_data(paths)
        # 2) Text.
        text = self._read_text()
        if text:
            return ClipData.text_data(text)
        return None

    def _read_text(self) -> Optional[str]:
        if self.is_mac:
            rc, out = _run(["pbpaste"])
        elif self.linux_tool == "wl":
            rc, out = _run(["wl-paste", "-n"])
        elif self.linux_tool == "xclip":
            rc, out = _run(["xclip", "-selection", "clipboard", "-o"])
        else:
            rc, out = _run(["xsel", "--clipboard", "--output"])
        if rc == 0 and out:
            return out.decode("utf-8", errors="replace")
        return None

    def _read_files(self) -> Optional[List[str]]:
        if self.is_mac:
            # Ask the pasteboard for file URLs via AppleScript.
            script = (
                'set out to ""\n'
                'try\n'
                '  set theFiles to the clipboard as «class furl»\n'
                'end try\n'
                'try\n'
                '  set p to POSIX path of (theFiles as alias)\n'
                '  set out to p\n'
                'end try\n'
                'return out'
            )
            rc, out = _run(["osascript", "-e", script])
            text = out.decode("utf-8", errors="replace").strip()
            return [text] if text else None
        # Linux: try text/uri-list.
        if self.linux_tool == "wl":
            rc, out = _run(["wl-paste", "--type", "text/uri-list"])
        elif self.linux_tool == "xclip":
            rc, out = _run(["xclip", "-selection", "clipboard", "-t", "text/uri-list", "-o"])
        else:
            return None  # xsel has no MIME targets
        if rc == 0 and out.strip():
            paths = [p for p in uri_list_to_paths(out) if os.path.exists(p)]
            return paths or None
        return None

    # ----------------------------------------------------------------- write
    def write(self, clip: ClipData) -> None:
        if clip.kind == protocol.KIND_TEXT:
            self._write_text(clip.text or "")
        elif clip.kind == protocol.KIND_HTML:
            self._write_text(clip.text or clip.html or "")
        elif clip.kind == protocol.KIND_FILES:
            self._write_files(clip.paths or [])
        elif clip.kind == protocol.KIND_IMAGE:
            self._write_image(clip.image_png or b"")
        else:
            raise ValueError("Unsupported clip kind: %s" % clip.kind)

    def _write_text(self, text: str) -> None:
        data = text.encode("utf-8")
        if self.is_mac:
            _run(["pbcopy"], data)
        elif self.linux_tool == "wl":
            _run(["wl-copy"], data)
        elif self.linux_tool == "xclip":
            _run(["xclip", "-selection", "clipboard", "-i"], data)
        else:
            _run(["xsel", "--clipboard", "--input"], data)

    def _write_files(self, paths: List[str]) -> None:
        if not paths:
            return
        if self.is_mac:
            quoted = ", ".join('POSIX file "%s"' % os.path.abspath(p) for p in paths)
            script = "set the clipboard to {%s}" % quoted
            _run(["osascript", "-e", script])
            return
        uri = paths_to_uri_list(paths)
        if self.linux_tool == "wl":
            _run(["wl-copy", "--type", "text/uri-list"], uri)
        elif self.linux_tool == "xclip":
            _run(["xclip", "-selection", "clipboard", "-t", "text/uri-list", "-i"], uri)
        else:
            # xsel cannot set a MIME target; fall back to newline-separated paths.
            self._write_text("\n".join(os.path.abspath(p) for p in paths))

    def _write_image(self, png: bytes) -> None:
        if not png:
            return
        if self.is_mac:
            log.debug("Image paste not implemented on macOS posix backend")
            return
        if self.linux_tool == "wl":
            _run(["wl-copy", "--type", "image/png"], png)
        elif self.linux_tool == "xclip":
            _run(["xclip", "-selection", "clipboard", "-t", "image/png", "-i"], png)

    # ------------------------------------------------------- input simulation
    def simulate_copy(self) -> None:
        self._send_combo("c")

    def simulate_paste(self) -> None:
        self._send_combo("v")

    def _send_combo(self, letter: str) -> None:
        try:
            import keyboard

            keyboard.send("ctrl+%s" % letter if not self.is_mac else "command+%s" % letter)
            return
        except Exception:
            pass
        if self.is_mac:
            key = "c" if letter == "c" else "v"
            _run(["osascript", "-e", 'tell application "System Events" to keystroke "%s" using command down' % key])
        elif _have("xdotool"):
            _run(["xdotool", "key", "--clearmodifiers", "ctrl+%s" % letter])
