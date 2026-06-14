import base64

import pytest
from fastapi.testclient import TestClient

from cpr_shared import crypto, protocol
from cpr_server.config import ServerConfig
from cpr_server.main import create_app


def make_client(tmp_path, **overrides):
    key = crypto.generate_key()
    config = ServerConfig(
        data_dir=str(tmp_path / "data"),
        admin_api_key="admin-key-very-long-enough-1234567890",
        pool_key_b64=crypto.key_to_b64(key),
        **overrides,
    )
    return TestClient(create_app(config)), key


def _add(client, slot, name):
    r = client.post(
        "/api/admin/machines",
        headers={"X-Admin-Key": "admin-key-very-long-enough-1234567890"},
        json={"slot": slot, "name": name},
    )
    return r.json()["bearer"]


def test_security_headers_present(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        r = client.get("/api/health")
        h = r.headers
        assert h.get("X-Content-Type-Options") == "nosniff"
        assert h.get("X-Frame-Options") == "DENY"
        assert h.get("Referrer-Policy") == "no-referrer"
        assert "default-src 'none'" in h.get("Content-Security-Policy", "")
        assert "Strict-Transport-Security" in h


def test_dashboard_uses_nonce_csp(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        r = client.get("/dashboard")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "nonce-" in csp
        assert "unsafe-inline" not in csp
        # The inline tags must carry the same nonce as the header.
        import re

        nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
        assert ('<script nonce="%s">' % nonce) in r.text
        assert ('<style nonce="%s">' % nonce) in r.text


def test_body_size_limit_rejects_large(tmp_path):
    client, _ = make_client(tmp_path, max_request_bytes=200)
    with client:
        big = {"blob": "A" * 500}
        r = client.post(
            "/api/clip/1",
            headers={"Authorization": "Bearer 1.whatever"},
            json=big,
        )
        assert r.status_code == 413  # rejected before auth/routing


def test_auth_rate_limit_locks_out(tmp_path):
    client, _ = make_client(tmp_path, auth_rate_max_failures=3)
    with client:
        # 3 bad admin attempts -> 403, then locked out -> 429.
        for _ in range(3):
            assert client.get("/api/admin/machines", headers={"X-Admin-Key": "nope"}).status_code == 403
        r = client.get("/api/admin/machines", headers={"X-Admin-Key": "nope"})
        assert r.status_code == 429
        assert "Retry-After" in r.headers


def test_cross_pull_can_be_disabled(tmp_path):
    client, key = make_client(tmp_path, allow_cross_pull=False)
    with client:
        b1 = _add(client, 1, "PC-Casa")
        b2 = _add(client, 2, "PC-Oficina")
        cipher = crypto.encrypt(key, b"hola")
        env = protocol.Envelope(
            kind=protocol.KIND_TEXT, inline=True, data_b64=base64.b64encode(cipher).decode()
        )
        client.post("/api/clip/2", headers={"Authorization": "Bearer " + b1}, json=env.to_dict())

        # Machine 1 may NOT read mailbox 2 when cross-pull is disabled.
        r = client.get("/api/clip/2", headers={"Authorization": "Bearer " + b1})
        assert r.status_code == 403
        # Machine 2 may read its own mailbox.
        r = client.get("/api/clip/2", headers={"Authorization": "Bearer " + b2})
        assert r.status_code == 200


def test_info_is_minimal_public(tmp_path):
    client, _ = make_client(tmp_path)
    with client:
        info = client.get("/api/info").json()
        for leaky in ("pool_key_fp", "max_payload_bytes", "crypto_backend", "pool_id"):
            assert leaky not in info
