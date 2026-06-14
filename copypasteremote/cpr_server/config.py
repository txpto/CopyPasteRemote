"""Server configuration.

Configuration is resolved from (lowest to highest priority):

1. built-in defaults
2. a JSON config file (``--config`` / ``CPR_SERVER_CONFIG`` env var)
3. ``CPR_*`` environment variables

Only the pieces an administrator realistically needs to change are exposed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


@dataclass
class ServerConfig:
    # Network ----------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8765
    # Public URL clients should use to reach this server (used when the admin CLI
    # generates ready-to-use client configs). Example: https://cpr.example.com:8765
    public_url: str = "https://CHANGE-ME.public.ip:8765"

    # Storage ----------------------------------------------------------------
    data_dir: str = "./data"
    max_payload_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB hard cap per payload
    # Clipboard payloads older than this are purged. 0 disables expiry.
    slot_ttl_seconds: int = 24 * 3600
    # Half-finished uploads older than this are garbage-collected.
    orphan_blob_ttl_seconds: int = 3600

    # Identity / crypto ------------------------------------------------------
    pool_id: str = "default"
    # Optional: storing the pool key here lets the admin CLI emit complete client
    # configs. Leave empty for a zero-knowledge server (distribute the key out of
    # band instead).
    pool_key_b64: str = ""

    # Auth -------------------------------------------------------------------
    # Admin key protecting the /api/admin/* REST endpoints. Generated on first run
    # if left blank (printed once to the log).
    admin_api_key: str = ""

    # TLS (optional; you may also terminate TLS at a reverse proxy / DD-WRT) ---
    tls_certfile: str = ""
    tls_keyfile: str = ""

    # Misc -------------------------------------------------------------------
    blob_chunk_size: int = 4 * 1024 * 1024  # 4 MiB suggested upload chunk
    ws_ping_interval: int = 25               # seconds
    log_level: str = "info"

    # Security hardening -----------------------------------------------------
    enable_docs: bool = True                 # expose /docs, /redoc, /openapi.json
    max_request_bytes: int = 16 * 1024 * 1024  # reject any single request body above this
    trust_proxy: bool = False                # honour X-Forwarded-For (only behind a trusted proxy)
    hsts: bool = True                        # send Strict-Transport-Security
    allow_cross_pull: bool = True            # may a machine pull mailboxes other than its own?
    auth_rate_max_failures: int = 15         # failed auths per window before lockout
    auth_rate_window_seconds: int = 60
    auth_rate_block_seconds: int = 300

    # Clipboard history -----------------------------------------------------
    history_max_entries: int = 25            # unpinned entries kept per mailbox
    history_ttl_seconds: int = 7 * 24 * 3600  # unpinned history expiry (0 disables)

    # Derived ----------------------------------------------------------------
    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "cpr.sqlite3")

    @property
    def blobs_dir(self) -> str:
        return os.path.join(self.data_dir, "blobs")

    # Loading ----------------------------------------------------------------
    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "ServerConfig":
        cfg = cls()

        path = config_path or os.environ.get("CPR_SERVER_CONFIG")
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                data: Dict[str, Any] = json.load(fh)
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)

        # Environment overrides (highest priority).
        cfg.host = os.environ.get("CPR_HOST", cfg.host)
        cfg.port = _env_int("CPR_PORT", cfg.port)
        cfg.public_url = os.environ.get("CPR_PUBLIC_URL", cfg.public_url)
        cfg.data_dir = os.environ.get("CPR_DATA_DIR", cfg.data_dir)
        cfg.max_payload_bytes = _env_int("CPR_MAX_PAYLOAD_BYTES", cfg.max_payload_bytes)
        cfg.slot_ttl_seconds = _env_int("CPR_SLOT_TTL_SECONDS", cfg.slot_ttl_seconds)
        cfg.pool_id = os.environ.get("CPR_POOL_ID", cfg.pool_id)
        cfg.pool_key_b64 = os.environ.get("CPR_POOL_KEY", cfg.pool_key_b64)
        cfg.admin_api_key = os.environ.get("CPR_ADMIN_API_KEY", cfg.admin_api_key)
        cfg.tls_certfile = os.environ.get("CPR_TLS_CERTFILE", cfg.tls_certfile)
        cfg.tls_keyfile = os.environ.get("CPR_TLS_KEYFILE", cfg.tls_keyfile)
        cfg.log_level = os.environ.get("CPR_LOG_LEVEL", cfg.log_level)
        cfg.enable_docs = _env_bool("CPR_ENABLE_DOCS", cfg.enable_docs)
        cfg.max_request_bytes = _env_int("CPR_MAX_REQUEST_BYTES", cfg.max_request_bytes)
        cfg.trust_proxy = _env_bool("CPR_TRUST_PROXY", cfg.trust_proxy)
        cfg.hsts = _env_bool("CPR_HSTS", cfg.hsts)
        cfg.allow_cross_pull = _env_bool("CPR_ALLOW_CROSS_PULL", cfg.allow_cross_pull)
        return cfg

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def ensure_dirs(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.blobs_dir, exist_ok=True)
