import base64
import io

import pytest
from fastapi.testclient import TestClient

from cpr_shared import crypto, protocol
from cpr_server.config import ServerConfig
from cpr_server.main import create_app


@pytest.fixture()
def env(tmp_path):
    key = crypto.generate_key()
    config = ServerConfig(
        data_dir=str(tmp_path / "data"),
        admin_api_key="test-admin-key",
        pool_key_b64=crypto.key_to_b64(key),
        public_url="https://example.test:8765",
    )
    app = create_app(config)
    with TestClient(app) as client:
        yield client, key


def _add_machine(client, slot, name):
    r = client.post(
        "/api/admin/machines",
        headers={"X-Admin-Key": "test-admin-key"},
        json={"slot": slot, "name": name},
    )
    assert r.status_code == 200, r.text
    return r.json()["bearer"]


def test_health_and_info(env):
    client, _ = env
    assert client.get("/api/health").json()["status"] == "ok"
    info = client.get("/api/info").json()
    assert info["app"] == "CopyPasteRemote"
    assert info["version"]
    # pool_key_fp is no longer disclosed publicly; it lives behind auth in /api/pool.
    assert "pool_key_fp" not in info
    bearer = _add_machine(client, 1, "PC-Casa")
    pool = client.get("/api/pool", headers={"Authorization": "Bearer " + bearer}).json()
    assert pool["pool_key_fp"]


def test_admin_requires_key(env):
    client, _ = env
    r = client.get("/api/admin/machines")
    assert r.status_code == 403


def test_register_and_pool(env):
    client, _ = env
    b1 = _add_machine(client, 1, "PC-Casa")
    _add_machine(client, 2, "PC-Oficina")
    r = client.get("/api/pool", headers={"Authorization": "Bearer " + b1})
    assert r.status_code == 200
    data = r.json()
    assert data["you"] == 1
    slots = {m["slot"]: m for m in data["machines"]}
    assert slots[1]["name"] == "PC-Casa"
    assert slots[2]["name"] == "PC-Oficina"


def test_duplicate_slot_rejected(env):
    client, _ = env
    _add_machine(client, 5, "A")
    r = client.post(
        "/api/admin/machines",
        headers={"X-Admin-Key": "test-admin-key"},
        json={"slot": 5, "name": "B"},
    )
    assert r.status_code == 409


def test_bad_token_rejected(env):
    client, _ = env
    _add_machine(client, 1, "PC-Casa")
    r = client.get("/api/pool", headers={"Authorization": "Bearer 1.wrongtoken"})
    assert r.status_code == 401


def test_push_pull_inline_text(env):
    client, key = env
    b1 = _add_machine(client, 1, "PC-Casa")
    b2 = _add_machine(client, 2, "PC-Oficina")

    text = "Hola desde la máquina 1 → portapapeles de la 2".encode("utf-8")
    cipher = crypto.encrypt(key, text)
    env_obj = protocol.Envelope(
        kind=protocol.KIND_TEXT,
        size=len(text),
        enc_size=len(cipher),
        sha256=crypto.sha256_hex(text),
        key_fp=crypto.key_fingerprint(key),
        inline=True,
        data_b64=base64.b64encode(cipher).decode(),
    )
    # Machine 1 pushes into mailbox 2.
    r = client.post(
        "/api/clip/2",
        headers={"Authorization": "Bearer " + b1},
        json=env_obj.to_dict(),
    )
    assert r.status_code == 200, r.text

    # Machine 2 pulls its own mailbox.
    r = client.get("/api/clip/2", headers={"Authorization": "Bearer " + b2})
    assert r.status_code == 200, r.text
    pulled = protocol.Envelope.from_dict(r.json())
    assert pulled.kind == protocol.KIND_TEXT
    assert pulled.from_id == 1
    got_cipher = base64.b64decode(pulled.data_b64)
    assert crypto.decrypt(key, got_cipher) == text


def test_push_to_unregistered_slot_404(env):
    client, key = env
    b1 = _add_machine(client, 1, "PC-Casa")
    env_obj = protocol.Envelope(kind=protocol.KIND_TEXT, inline=True, data_b64="AAAA")
    r = client.post(
        "/api/clip/9", headers={"Authorization": "Bearer " + b1}, json=env_obj.to_dict()
    )
    assert r.status_code == 404


def test_pull_empty_mailbox_404(env):
    client, _ = env
    b1 = _add_machine(client, 1, "PC-Casa")
    r = client.get("/api/clip/1", headers={"Authorization": "Bearer " + b1})
    assert r.status_code == 404


def test_blob_upload_download_roundtrip(env):
    client, key = env
    b1 = _add_machine(client, 1, "PC-Casa")
    _add_machine(client, 2, "PC-Oficina")
    h = {"Authorization": "Bearer " + b1}

    payload = crypto.encrypt(key, b"X" * (300 * 1024))  # > inline threshold
    # 1) create blob
    blob_id = client.post("/api/blobs", headers=h).json()["blob_id"]
    # 2) upload in two chunks
    half = len(payload) // 2
    r = client.put(
        "/api/blobs/%s?offset=0" % blob_id, headers=h, content=payload[:half]
    )
    assert r.status_code == 200, r.text
    r = client.put(
        "/api/blobs/%s?offset=%d" % (blob_id, half), headers=h, content=payload[half:]
    )
    assert r.status_code == 200, r.text
    # 3) complete with checksum
    sha = crypto.sha256_hex(payload)
    r = client.post(
        "/api/blobs/%s/complete" % blob_id, headers=h, json={"sha256": sha}
    )
    assert r.status_code == 200, r.text

    # 4) reference it from an envelope pushed to slot 2
    env_obj = protocol.Envelope(
        kind=protocol.KIND_FILES,
        size=300 * 1024,
        enc_size=len(payload),
        sha256=sha,
        key_fp=crypto.key_fingerprint(key),
        inline=False,
        blob_id=blob_id,
        files=[protocol.FileEntry(name="big.bin", is_dir=False, size=300 * 1024)],
    )
    r = client.post("/api/clip/2", headers=h, json=env_obj.to_dict())
    assert r.status_code == 200, r.text

    # 5) download the blob and verify bytes
    r = client.get("/api/blobs/%s" % blob_id, headers=h)
    assert r.status_code == 200
    assert r.content == payload

    # 6) range request
    r = client.get("/api/blobs/%s" % blob_id, headers={**h, "Range": "bytes=10-19"})
    assert r.status_code == 206
    assert r.content == payload[10:20]


def test_out_of_order_chunk_rejected(env):
    client, _ = env
    b1 = _add_machine(client, 1, "PC-Casa")
    h = {"Authorization": "Bearer " + b1}
    blob_id = client.post("/api/blobs", headers=h).json()["blob_id"]
    r = client.put("/api/blobs/%s?offset=100" % blob_id, headers=h, content=b"x")
    assert r.status_code == 409


def test_clear_slot(env):
    client, key = env
    b1 = _add_machine(client, 1, "PC-Casa")
    cipher = crypto.encrypt(key, b"data")
    env_obj = protocol.Envelope(
        kind=protocol.KIND_TEXT, inline=True, data_b64=base64.b64encode(cipher).decode()
    )
    client.post("/api/clip/1", headers={"Authorization": "Bearer " + b1}, json=env_obj.to_dict())
    assert client.get("/api/clip/1", headers={"Authorization": "Bearer " + b1}).status_code == 200
    client.delete("/api/clip/1", headers={"Authorization": "Bearer " + b1})
    assert client.get("/api/clip/1", headers={"Authorization": "Bearer " + b1}).status_code == 404
