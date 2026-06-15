#!/usr/bin/env python3
"""Entry point for the CopyPasteRemote orchestrator.

The server runs TWO listeners in a single process (one event loop, one shared
SQLite store):

* the **public** listener (``host``/``port``, default ``0.0.0.0:8765``) serves the
  clipboard sync API and the WebSocket. The admin surface (``/dashboard``,
  ``/api/admin/*`` and the API docs) is hidden here.
* the **admin** listener (``admin_host``/``admin_port``, default
  ``127.0.0.1:8766``) serves the dashboard and admin API. It binds to loopback by
  default, so the dashboard is only reachable from the server box itself at
  ``http://127.0.0.1:8766/dashboard``.

Examples
--------
    python run_server.py
    python run_server.py --host 0.0.0.0 --port 8765
    python run_server.py --config server-config.json
    CPR_TLS_CERTFILE=cert.pem CPR_TLS_KEYFILE=key.pem python run_server.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import uvicorn

from cpr_server.config import ServerConfig
from cpr_server.main import create_app, lifespan


class _AdminSurfaceGate:
    """ASGI wrapper that hides the admin surface on the public listener.

    Requests to the dashboard, the ``/api/admin/*`` endpoints or the API docs get a
    flat 404 — so even though both listeners share the same application, those paths
    are only reachable through the loopback admin listener.
    """

    _BLOCKED = ("/dashboard", "/api/admin", "/docs", "/redoc", "/openapi.json")

    def __init__(self, app):
        self.app = app

    def _is_blocked(self, path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in self._BLOCKED)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self._is_blocked(scope.get("path", "")):
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": b'{"detail":"Not Found"}'})
            return
        if scope["type"] == "websocket" and self._is_blocked(scope.get("path", "")):
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


async def _serve(config: ServerConfig, ssl_kwargs: dict) -> None:
    app = create_app(config)

    public = uvicorn.Server(uvicorn.Config(
        _AdminSurfaceGate(app),
        host=config.host,
        port=config.port,
        log_level=config.log_level,
        lifespan="off",          # lifespan is driven once, manually, below
        **ssl_kwargs,
    ))
    admin = uvicorn.Server(uvicorn.Config(
        app,
        host=config.admin_host,
        port=config.admin_port,
        log_level=config.log_level,
        lifespan="off",
    ))
    # We own the process lifecycle (KeyboardInterrupt -> asyncio.run cancels the
    # gather); don't let either server hijack the signal handlers.
    public.install_signal_handlers = lambda: None  # type: ignore[assignment]
    admin.install_signal_handlers = lambda: None    # type: ignore[assignment]

    async with lifespan(app):
        await asyncio.gather(public.serve(), admin.serve())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CopyPasteRemote orchestrator")
    parser.add_argument("--config", help="Path to a JSON config file")
    parser.add_argument("--host", help="Public bind address (overrides config)")
    parser.add_argument("--port", type=int, help="Public bind port (overrides config)")
    parser.add_argument("--admin-host", help="Admin/dashboard bind address (overrides config)")
    parser.add_argument("--admin-port", type=int, help="Admin/dashboard bind port (overrides config)")
    parser.add_argument("--log-level", help="uvicorn log level (debug/info/warning/error)")
    args = parser.parse_args(argv)

    config = ServerConfig.load(args.config)
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.admin_host:
        config.admin_host = args.admin_host
    if args.admin_port:
        config.admin_port = args.admin_port
    if args.log_level:
        config.log_level = args.log_level

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    ssl_kwargs = {}
    if config.tls_certfile and config.tls_keyfile:
        ssl_kwargs = {"ssl_certfile": config.tls_certfile, "ssl_keyfile": config.tls_keyfile}
        scheme = "https"
    else:
        scheme = "http"
        logging.getLogger("cpr.server").warning(
            "TLS is OFF. Run behind a TLS-terminating proxy or set tls_certfile/tls_keyfile "
            "before exposing this to the Internet."
        )

    log = logging.getLogger("cpr.server")
    log.info("Public  API : %s://%s:%d  (public_url=%s)",
             scheme, config.host, config.port, config.public_url)
    log.info("Admin/dash  : http://%s:%d/dashboard  (loopback only)",
             config.admin_host, config.admin_port)

    try:
        asyncio.run(_serve(config, ssl_kwargs))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
