"""Client configuration: load/save JSON, sensible defaults, hotkey maps.

The file lives at ``%APPDATA%\\CopyPasteRemote\\config.json`` on Windows
(``~/.config/copypasteremote/config.json`` elsewhere) unless overridden.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


APP_DIR_NAME = "CopyPasteRemote"


def default_config_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_DIR_NAME)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "copypasteremote")


def default_config_path() -> str:
    return os.path.join(default_config_dir(), "config.json")


def _default_push_hotkeys() -> Dict[str, str]:
    # "Send my clipboard to mailbox N"
    return {str(n): "ctrl+alt+%d" % n for n in range(1, 10)}


def _default_pull_hotkeys() -> Dict[str, str]:
    # "Fetch mailbox N into my clipboard (and paste)"
    return {str(n): "ctrl+shift+%d" % n for n in range(1, 10)}


@dataclass
class ClientConfig:
    # Connection -------------------------------------------------------------
    server_url: str = "https://CHANGE-ME:8765"
    machine_id: int = 0
    machine_name: str = ""
    token: str = ""
    pool_id: str = "default"
    pool_key: str = ""                # base64 32-byte pool key
    verify_tls: bool = True
    ca_cert: str = ""                 # path to a CA bundle / self-signed cert to trust

    # Behaviour --------------------------------------------------------------
    auto_paste: bool = True           # simulate Ctrl+V after pulling
    copy_before_send: bool = True     # simulate Ctrl+C before pushing (grab selection)
    notifications: bool = True        # tray balloon notifications
    prefetch: bool = True             # pre-download content when notified over WS
    reconnect_seconds: int = 5        # WS reconnect backoff base

    # Hotkeys ----------------------------------------------------------------
    pull_own_hotkey: str = "ctrl+alt+v"
    push_hotkeys: Dict[str, str] = field(default_factory=_default_push_hotkeys)
    pull_hotkeys: Dict[str, str] = field(default_factory=_default_pull_hotkeys)

    # Misc -------------------------------------------------------------------
    temp_dir: str = ""                # where to materialise received files (blank = system temp)
    log_level: str = "info"
    log_file: str = ""                # blank = console only

    # Loading / saving -------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[str] = None) -> "ClientConfig":
        path = path or os.environ.get("CPR_CLIENT_CONFIG") or default_config_path()
        cfg = cls()
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            cfg.apply(data)
        cfg._path = path  # type: ignore[attr-defined]
        return cfg

    def apply(self, data: Dict[str, Any]) -> None:
        for key, value in data.items():
            if hasattr(self, key) and not key.startswith("_"):
                setattr(self, key, value)

    def save(self, path: Optional[str] = None) -> str:
        path = path or getattr(self, "_path", None) or default_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    # Validation -------------------------------------------------------------
    def validate(self) -> None:
        problems = []
        if not self.server_url or "CHANGE-ME" in self.server_url:
            problems.append("server_url is not set")
        if not (1 <= int(self.machine_id) <= 255):
            problems.append("machine_id must be 1..255")
        if not self.token:
            problems.append("token is empty")
        if not self.pool_key:
            problems.append("pool_key is empty")
        if problems:
            raise ValueError("Invalid client config: " + "; ".join(problems))

    @property
    def config_path(self) -> str:
        return getattr(self, "_path", default_config_path())
