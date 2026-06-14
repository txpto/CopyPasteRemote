"""Shared protocol helpers for CopyPasteRemote."""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

PACKAGE_TEXT = "text"
PACKAGE_FILES = "files"
SUPPORTED_PACKAGE_TYPES = {PACKAGE_TEXT, PACKAGE_FILES}


def new_token(prefix: str) -> str:
    """Return a URL-safe random token with a readable prefix."""
    return "%s_%s" % (prefix, secrets.token_urlsafe(32))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
