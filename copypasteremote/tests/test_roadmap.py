"""Tests for roadmap features: multi-pool, per-mailbox ACLs, clipboard history."""

import base64

import pytest
from fastapi.testclient import TestClient

from cpr_shared import crypto, protocol
from cpr_server.config import ServerConfig
from cpr_server.main import create_app

ADMIN = "admin-key-very-long-enough-1234567890"


def make_client(tmp_path, **overrides):
    key = crypto.generate_key()
    config = ServerConfig(
        data_dir=str(tmp_path / "data"),
        admin_api_key=ADMIN,
        pool_key_b64=crypto.key_to_b64(key),
        **overrides,
    )
    return TestClient(create_app(config)), key


def add(client, slot, name, pool="default"):
    r = client.post(
        "/api/admin/machines",
        headers={"X-Admin-Key": ADMIN},
        json={"slot": slot, "name": name, "pool": pool},
    )
    assert r.status_code == 200, r.text
    return r.json()["bearer"]


def push_text(client, bearer, target, key, text="hi"):
    data = text.encode()
    cipher = crypto.encrypt(key, data)
    env = protocol.Envelope(
        kind=protocol.KIND_TEXT, size=len(data), sha256=crypto.sha256_hex(data),
        inline=True, data_b64=base64.b64encode(cipher).decode(),
    )
    return client.post("/api/clip/%d" % target, headers={"Authorization": "Bearer " + bearer},
                       json=env.to_dict())


# ----------------------------------------------------------------- multi-pool
def test_pool_isolation(tmp_path):
    client, key = make_client(tmp_path)
    with client:
        a = add(client, 1, "A", pool="alpha")
        add(client, 2, "B", pool="alpha")
        add(client, 3, "C", pool="beta")

        # Pool view only shows same-pool peers.
        pool = client.get("/api/pool", headers={"Authorization": "Bearer " + a}).json()
        assert pool["pool"] == "alpha"
        assert {m["slot"] for m in pool["machines"]} == {1, 2}

        # Cannot push across pools.
        r = push_text(client, a, 3, key)
        assert r.status_code == 403
        # Can push within pool.
        assert push_text(client, a, 2, key).status_code == 200


def test_set_pool_endpoint(tmp_path):
    client, key = make_client(tmp_path)
    with client:
        a = add(client, 1, "A", pool="alpha")
        add(client, 2, "B", pool="beta")
        # Move slot 2 into alpha.
        r = client.post("/api/admin/machines/2/pool", headers={"X-Admin-Key": ADMIN},
                        json={"pool": "alpha"})
        assert r.status_code == 200
        assert push_text(client, a, 2, key).status_code == 200


# ----------------------------------------------------------------------- ACL
def test_push_acl(tmp_path):
    client, key = make_client(tmp_path)
    with client:
        a1 = add(client, 1, "one")
        a3 = add(client, 3, "three")
        add(client, 2, "two")
        # Only slot 3 may push to mailbox 2.
        r = client.post("/api/admin/machines/2/acl", headers={"X-Admin-Key": ADMIN},
                        json={"acl_push": [3]})
        assert r.status_code == 200
        assert push_text(client, a1, 2, key).status_code == 403
        assert push_text(client, a3, 2, key).status_code == 200


def test_pull_acl(tmp_path):
    client, key = make_client(tmp_path)
    with client:
        a1 = add(client, 1, "one")
        a2 = add(client, 2, "two")
        a3 = add(client, 3, "three")
        push_text(client, a1, 2, key)  # content in mailbox 2
        # Only slot 3 may read mailbox 2 (besides its owner, slot 2).
        client.post("/api/admin/machines/2/acl", headers={"X-Admin-Key": ADMIN},
                    json={"acl_pull": [3]})
        assert client.get("/api/clip/2", headers={"Authorization": "Bearer " + a1}).status_code == 403
        assert client.get("/api/clip/2", headers={"Authorization": "Bearer " + a3}).status_code == 200
        # Owner can always read its own.
        assert client.get("/api/clip/2", headers={"Authorization": "Bearer " + a2}).status_code == 200


# ------------------------------------------------------------------- history
def test_history_records_and_pin(tmp_path):
    client, key = make_client(tmp_path, history_max_entries=10)
    with client:
        a1 = add(client, 1, "one")
        b2 = add(client, 2, "two")
        for t in ("uno", "dos", "tres"):
            push_text(client, a1, 2, key, text=t)

        hist = client.get("/api/clip/2/history", headers={"Authorization": "Bearer " + b2}).json()
        entries = hist["entries"]
        assert len(entries) == 3
        # Newest first.
        assert entries[0]["from_id"] == 1

        # Fetch a specific (older) entry and decrypt it.
        older = entries[-1]
        r = client.get("/api/clip/2/history/%d" % older["id"],
                       headers={"Authorization": "Bearer " + b2})
        assert r.status_code == 200
        env = protocol.Envelope.from_dict(r.json())
        assert crypto.decrypt(key, base64.b64decode(env.data_b64)) == b"uno"

        # Pin it.
        r = client.post("/api/clip/2/history/%d/pin" % older["id"],
                        headers={"Authorization": "Bearer " + b2}, json={"pinned": True})
        assert r.status_code == 200 and r.json()["pinned"] is True


def test_history_trim_keeps_pinned(tmp_path):
    client, key = make_client(tmp_path, history_max_entries=2)
    with client:
        a1 = add(client, 1, "one")
        b2 = add(client, 2, "two")
        push_text(client, a1, 2, key, text="first")
        first = client.get("/api/clip/2/history", headers={"Authorization": "Bearer " + b2}).json()["entries"][0]
        # Pin the first item, then push 3 more (exceeding max_entries=2).
        client.post("/api/clip/2/history/%d/pin" % first["id"],
                    headers={"Authorization": "Bearer " + b2}, json={"pinned": True})
        for t in ("a", "b", "c"):
            push_text(client, a1, 2, key, text=t)
        entries = client.get("/api/clip/2/history",
                             headers={"Authorization": "Bearer " + b2}).json()["entries"]
        ids_pinned = [e for e in entries if e["pinned"]]
        assert len(ids_pinned) == 1  # the pinned 'first' survived the trim
        # Total = pinned(1) + last unpinned kept (2).
        assert len(entries) <= 3
