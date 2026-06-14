"""Shared test fixtures, and making the repo root importable."""

import os
import socket
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def live_server(tmp_path):
    """A real uvicorn server with slots 1 and 2 registered.

    Yields ``(base_url, pool_key, {slot: token})``.
    """
    import requests
    import uvicorn

    from cpr_shared import crypto
    from cpr_server.config import ServerConfig
    from cpr_server.main import create_app

    key = crypto.generate_key()
    port = _free_port()
    config = ServerConfig(
        host="127.0.0.1",
        port=port,
        data_dir=str(tmp_path / "srv"),
        admin_api_key="admin-key",
        pool_key_b64=crypto.key_to_b64(key),
        public_url="http://127.0.0.1:%d" % port,
    )
    app = create_app(config)
    uvconfig = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(uvconfig)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()

    base = "http://127.0.0.1:%d" % port
    for _ in range(200):
        try:
            if srv.started and requests.get(base + "/api/health", timeout=1).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.05)

    tokens = {}
    for slot, name in ((1, "PC-Casa"), (2, "PC-Oficina")):
        r = requests.post(
            base + "/api/admin/machines",
            headers={"X-Admin-Key": "admin-key"},
            json={"slot": slot, "name": name},
            timeout=5,
        )
        assert r.status_code == 200, r.text
        tokens[slot] = r.json()["token"]

    yield base, key, tokens

    srv.should_exit = True
    thread.join(timeout=5)
