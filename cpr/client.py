"""Windows client CLI and hotkey daemon for CopyPasteRemote."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from . import winclip
from .protocol import PACKAGE_CLIPBOARD, PACKAGE_FILES, PACKAGE_TEXT

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "CopyPasteRemote"
CONFIG_PATH = APP_DIR / "config.json"
CACHE_DIR = APP_DIR / "cache"


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit("client is not enrolled; run enroll first")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: Dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")


def session(config: Dict[str, Any]) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({"Authorization": "Bearer %s" % config["token"]})
    return sess


def server_url(config: Dict[str, Any], path: str) -> str:
    return config["server_url"].rstrip("/") + path


def cmd_enroll(args: argparse.Namespace) -> None:
    response = requests.post(args.server_url.rstrip("/") + "/api/enroll", json={"code": args.code}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    config = {
        "server_url": args.server_url.rstrip("/"),
        "token": payload["token"],
        "machine_name": payload["machine_name"],
        "pool": payload["pool"],
        "hotkeys": {
            "copy_prefix": "ctrl+alt",
            "paste_prefix": "ctrl+shift",
            "slots": ["1", "2", "3", "4"],
        },
    }
    save_config(config)
    print("Enrolled %s in pool %s" % (payload["machine_name"], payload["pool"]))


def upload_slot(slot: str) -> None:
    config = load_config()
    content = winclip.read_clipboard()
    sess = session(config)
    upload_file = None
    if content["type"] == PACKAGE_TEXT:
        files = None
        data = {"package_type": PACKAGE_TEXT, "text": content.get("text", "")}
    else:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if content["type"] == PACKAGE_FILES:
            upload_file = CACHE_DIR / ("upload_%s.zip" % next(tempfile._get_candidate_names()))
            winclip.make_zip_from_paths(content["paths"], upload_file)  # type: ignore[arg-type]
            data = {"package_type": PACKAGE_FILES, "original_name": "clipboard.zip"}
            filename = "clipboard.zip"
            mime_type = "application/zip"
        else:
            upload_file = CACHE_DIR / ("clipboard_%s.json" % next(tempfile._get_candidate_names()))
            winclip.write_clipboard_snapshot_file(content, upload_file)
            data = {"package_type": PACKAGE_CLIPBOARD, "original_name": "clipboard.json"}
            filename = "clipboard.json"
            mime_type = "application/json"
        files = {"blob": (filename, upload_file.open("rb"), mime_type)}
    try:
        response = sess.post(server_url(config, "/api/slots/%s/package" % slot), data=data, files=files, timeout=300)
        response.raise_for_status()
        print("Uploaded slot %s: %s" % (slot, response.json()))
    finally:
        if files:
            files["blob"][1].close()  # type: ignore[index,union-attr]


def download_slot(slot: str) -> None:
    config = load_config()
    sess = session(config)
    meta = sess.get(server_url(config, "/api/slots/%s/package" % slot), timeout=30)
    meta.raise_for_status()
    package = meta.json()
    if package["package_type"] == PACKAGE_TEXT:
        winclip.write_text(package.get("text_value", ""))
        print("Downloaded text from slot %s to local clipboard" % slot)
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    blob = sess.get(server_url(config, "/api/slots/%s/package/blob" % slot), timeout=300)
    blob.raise_for_status()
    zip_path = CACHE_DIR / ("download_%s.zip" % package["id"])
    zip_path.write_bytes(blob.content)
    if package["package_type"] == PACKAGE_FILES:
        paths = winclip.extract_zip_for_clipboard(zip_path, CACHE_DIR)
        winclip.write_file_drop(paths)
        print("Downloaded files from slot %s to local clipboard" % slot)
    elif package["package_type"] == PACKAGE_CLIPBOARD:
        winclip.write_clipboard_snapshot(zip_path)
        print("Downloaded generic clipboard snapshot from slot %s to local clipboard" % slot)
    else:
        raise RuntimeError("unsupported remote package type: %s" % package["package_type"])
    winclip.clean_cache(CACHE_DIR)


def cmd_copy(args: argparse.Namespace) -> None:
    upload_slot(args.slot)


def cmd_paste(args: argparse.Namespace) -> None:
    download_slot(args.slot)


def cmd_hotkeys(_args: argparse.Namespace) -> None:
    import keyboard  # type: ignore

    config = load_config()
    hotkeys = config.get("hotkeys", {})
    copy_prefix = hotkeys.get("copy_prefix", "ctrl+alt")
    paste_prefix = hotkeys.get("paste_prefix", "ctrl+shift")
    slots = hotkeys.get("slots", ["1", "2", "3", "4"])
    for slot in slots:
        keyboard.add_hotkey("%s+%s" % (copy_prefix, slot), lambda s=slot: upload_slot(s))
        keyboard.add_hotkey("%s+%s" % (paste_prefix, slot), lambda s=slot: download_slot(s))
        print("Registered copy %s+%s and paste %s+%s" % (copy_prefix, slot, paste_prefix, slot))
    print("CopyPasteRemote hotkey daemon running. Press Ctrl+C to exit.")
    keyboard.wait()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CopyPasteRemote Windows client")
    sub = parser.add_subparsers(required=True)
    enroll = sub.add_parser("enroll")
    enroll.add_argument("--server-url", required=True)
    enroll.add_argument("--code", required=True)
    enroll.set_defaults(func=cmd_enroll)
    copy = sub.add_parser("copy")
    copy.add_argument("--slot", required=True)
    copy.set_defaults(func=cmd_copy)
    paste = sub.add_parser("paste")
    paste.add_argument("--slot", required=True)
    paste.set_defaults(func=cmd_paste)
    hotkeys = sub.add_parser("hotkeys")
    hotkeys.set_defaults(func=cmd_hotkeys)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
