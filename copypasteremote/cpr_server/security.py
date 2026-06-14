"""Security hardening helpers: ASGI middleware + auth rate limiting.

The middlewares are written as **pure ASGI** (not Starlette's BaseHTTPMiddleware)
on purpose: BaseHTTPMiddleware buffers the response body, which would defeat the
streaming blob downloads. These wrappers only touch headers / the request start,
so multi-gigabyte transfers stay streamed.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Iterable, Optional, Tuple

from fastapi import HTTPException, Request, status


def _config_value(scope, attr: str, default):
    """Read a setting from the running app's config (per-app, request-time)."""
    app = scope.get("app")
    if app is not None:
        cfg = getattr(getattr(app, "state", None), "config", None)
        if cfg is not None:
            return getattr(cfg, attr, default)
    return default


# --------------------------------------------------------------------------- #
# Security headers (added to every response)
# --------------------------------------------------------------------------- #
class SecurityHeadersMiddleware:
    """Add hardening headers without buffering the body.

    A strict default Content-Security-Policy is applied to API/JSON responses;
    routes that need their own CSP (the dashboard) set it themselves and we leave
    it untouched. Swagger UI paths get a permissive CSP so /docs keeps working.
    """

    def __init__(self, app, hsts: bool = True):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        hsts = _config_value(scope, "hsts", self.hsts)
        path = scope.get("path", "")
        is_docs = path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json"

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {k.lower() for k, _ in headers}

                def add(name: str, value: str):
                    if name.lower().encode() not in present:
                        headers.append((name.encode(), value.encode()))

                add("X-Content-Type-Options", "nosniff")
                add("X-Frame-Options", "DENY")
                add("Referrer-Policy", "no-referrer")
                add("Cross-Origin-Opener-Policy", "same-origin")
                add("Cross-Origin-Resource-Policy", "same-origin")
                add("X-Permitted-Cross-Domain-Policies", "none")
                if hsts:
                    add("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
                if is_docs:
                    add(
                        "Content-Security-Policy",
                        "default-src 'self'; img-src 'self' data: https:; "
                        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
                    )
                else:
                    # Leave a route-provided CSP (dashboard) in place; otherwise lock down.
                    add("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            await send(message)

        await self.app(scope, receive, send_wrapper)


# --------------------------------------------------------------------------- #
# Request body size limit (reject oversized bodies before buffering them)
# --------------------------------------------------------------------------- #
class BodySizeLimitMiddleware:
    """Reject requests whose Content-Length exceeds ``max_bytes`` with 413.

    Large *payloads* still go through (they are uploaded as many bounded chunks
    via PUT /api/blobs); this only caps the size of any single request body.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            max_bytes = _config_value(scope, "max_request_bytes", self.max_bytes)
            for key, value in scope.get("headers", []):
                if key == b"content-length":
                    try:
                        if int(value) > max_bytes:
                            return await self._reject(send)
                    except ValueError:
                        pass
                    break
        await self.app(scope, receive, send)

    async def _reject(self, send):
        body = b'{"detail":"Request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,  # Content Too Large
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


# --------------------------------------------------------------------------- #
# Auth rate limiting / lockout (in-memory, per client IP)
# --------------------------------------------------------------------------- #
class AuthRateLimiter:
    """Throttle repeated authentication failures from the same IP.

    After ``max_failures`` failures within ``window`` seconds the IP is blocked
    for ``block`` seconds. Successful auth clears the counter.
    """

    def __init__(self, max_failures: int = 15, window: int = 60, block: int = 300):
        self.max_failures = max_failures
        self.window = window
        self.block = block
        self._fails: Dict[str, Deque[float]] = {}
        self._blocked: Dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, ip: str) -> None:
        now = time.time()
        with self._lock:
            until = self._blocked.get(ip)
            if until is not None:
                if now < until:
                    retry = int(until - now) + 1
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Too many failed attempts; locked out",
                        headers={"Retry-After": str(retry)},
                    )
                # Block expired.
                del self._blocked[ip]
                self._fails.pop(ip, None)

    def record_failure(self, ip: str) -> None:
        now = time.time()
        with self._lock:
            dq = self._fails.setdefault(ip, deque())
            dq.append(now)
            while dq and dq[0] < now - self.window:
                dq.popleft()
            if len(dq) >= self.max_failures:
                self._blocked[ip] = now + self.block
                dq.clear()

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)
            self._blocked.pop(ip, None)


def security_posture_warnings(config) -> "list[str]":
    """Return human-readable warnings about risky settings for an exposed server.

    Intended to be logged at startup; especially relevant when the host has a
    public IP and is reachable from the Internet.
    """
    warnings = []
    public_bind = config.host in ("0.0.0.0", "::", "")
    tls_on = bool(config.tls_certfile and config.tls_keyfile)

    if public_bind and not tls_on and not config.trust_proxy:
        warnings.append(
            "TLS is OFF and the server binds to all interfaces. Enable TLS "
            "(tls_certfile/tls_keyfile) or put it behind a TLS-terminating proxy "
            "before exposing it to the Internet."
        )
    if config.trust_proxy and not tls_on:
        warnings.append(
            "trust_proxy is enabled: only use this behind a proxy you control, "
            "otherwise clients can spoof X-Forwarded-For."
        )
    if config.enable_docs and public_bind:
        warnings.append(
            "Interactive API docs (/docs) are enabled on a public bind. Consider "
            "enable_docs=false in production to reduce information disclosure."
        )
    if config.admin_api_key and len(config.admin_api_key) < 24:
        warnings.append(
            "admin_api_key looks short; use a long random value (>= 24 chars)."
        )
    if not config.pool_key_b64:
        warnings.append(
            "No pool key configured on the server (clients must carry it). That is "
            "fine for a zero-knowledge setup; ignore if intentional."
        )
    return warnings


def client_ip(request: Request, trust_proxy: bool = False) -> str:
    """Best-effort client IP, honouring X-Forwarded-For only when trusted."""
    if trust_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    if request.client:
        return request.client.host
    return "unknown"
