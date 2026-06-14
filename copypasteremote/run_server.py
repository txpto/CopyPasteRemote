#!/usr/bin/env python3
"""Entry point for the CopyPasteRemote orchestrator.

Examples
--------
    python run_server.py
    python run_server.py --host 0.0.0.0 --port 8765
    python run_server.py --config server-config.json
    CPR_TLS_CERTFILE=cert.pem CPR_TLS_KEYFILE=key.pem python run_server.py
"""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from cpr_server.config import ServerConfig
from cpr_server.main import create_app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CopyPasteRemote orchestrator")
    parser.add_argument("--config", help="Path to a JSON config file")
    parser.add_argument("--host", help="Bind address (overrides config)")
    parser.add_argument("--port", type=int, help="Bind port (overrides config)")
    parser.add_argument("--log-level", help="uvicorn log level (debug/info/warning/error)")
    args = parser.parse_args(argv)

    config = ServerConfig.load(args.config)
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.log_level:
        config.log_level = args.log_level

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    app = create_app(config)

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

    logging.getLogger("cpr.server").info(
        "Listening on %s://%s:%d (public_url=%s)",
        scheme, config.host, config.port, config.public_url,
    )

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level,
        **ssl_kwargs,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
