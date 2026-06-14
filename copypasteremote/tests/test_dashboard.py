import base64

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
        admin_api_key="dash-admin",
        pool_key_b64=crypto.key_to_b64(key),
    )
    app = create_app(config)
    with TestClient(app) as client:
        yield client, key


def _admin(client, path, **kw):
    return client.get(path, headers={"X-Admin-Key": "dash-admin"}, **kw)


def _add(client, slot, name):
    r = client.post(
        "/api/admin/machines",
        headers={"X-Admin-Key": "dash-admin"},
        json={"slot": slot, "name": name},
    )
    return r.json()["bearer"]


def test_dashboard_html_served(env):
    client, _ = env
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "CopyPasteRemote" in r.text
    assert "/api/admin/overview" in r.text  # the page wires to the data endpoint


def test_overview_requires_admin(env):
    client, _ = env
    assert client.get("/api/admin/overview").status_code == 403


def test_overview_reports_machines_and_content(env):
    client, key = env
    b1 = _add(client, 1, "PC-Casa")
    _add(client, 2, "PC-Oficina")

    # Push a clip 1 -> mailbox 2 so the overview shows origin/destination.
    text = "hola dashboard".encode("utf-8")
    cipher = crypto.encrypt(key, text)
    env_obj = protocol.Envelope(
        kind=protocol.KIND_TEXT,
        size=len(text),
        sha256=crypto.sha256_hex(text),
        inline=True,
        data_b64=base64.b64encode(cipher).decode(),
    )
    client.post("/api/clip/2", headers={"Authorization": "Bearer " + b1}, json=env_obj.to_dict())

    ov = _admin(client, "/api/admin/overview").json()
    assert ov["server"]["machine_count"] == 2
    assert ov["server"]["clip_count"] == 1
    assert ov["server"]["version"]
    boxes = {m["slot"]: m for m in ov["mailboxes"]}
    assert boxes[2]["from_id"] == 1
    assert boxes[2]["dest_name"] == "PC-Oficina"
    assert boxes[2]["kind"] == protocol.KIND_TEXT


def test_activity_feed_records_push_and_pull(env):
    client, key = env
    b1 = _add(client, 1, "PC-Casa")
    b2 = _add(client, 2, "PC-Oficina")
    cipher = crypto.encrypt(key, b"x")
    env_obj = protocol.Envelope(
        kind=protocol.KIND_TEXT, inline=True, data_b64=base64.b64encode(cipher).decode()
    )
    client.post("/api/clip/2", headers={"Authorization": "Bearer " + b1}, json=env_obj.to_dict())
    client.get("/api/clip/2", headers={"Authorization": "Bearer " + b2})

    act = _admin(client, "/api/admin/activity").json()
    types = [e["type"] for e in act["events"]]
    assert "push" in types
    assert "pull" in types
    push_ev = [e for e in act["events"] if e["type"] == "push"][0]
    assert push_ev["from_id"] == 1 and push_ev["slot"] == 2
    assert act["last_seq"] >= 2
