"""Authentication helpers for the FastAPI app.

Machines authenticate with ``Authorization: Bearer <slot>.<token>`` where the
``slot`` prefix tells us which machine row to check the token against.  Admin
endpoints use a separate ``X-Admin-Key`` header.
"""

from __future__ import annotations

from typing import Optional, Tuple

from fastapi import Header, HTTPException, status

from cpr_shared import crypto


def parse_bearer(authorization: Optional[str]) -> Tuple[int, str]:
    """Parse a ``Bearer <slot>.<token>`` header into (slot, token)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw = authorization.split(" ", 1)[1].strip()
    if "." not in raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")
    slot_str, token = raw.split(".", 1)
    try:
        slot = int(slot_str)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")
    return slot, token


def make_bearer(slot: int, token: str) -> str:
    """Build the bearer value a client should send (the inverse of parse_bearer)."""
    return "%d.%s" % (slot, token)


class AuthContext:
    """Resolved identity attached to an authenticated request."""

    def __init__(self, slot: int, name: str):
        self.slot = slot
        self.name = name


def require_admin_key(provided: Optional[str], configured: str) -> None:
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API not configured (no admin_api_key set)",
        )
    if not provided or not crypto.constant_time_equals(provided.encode(), configured.encode()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin key")
