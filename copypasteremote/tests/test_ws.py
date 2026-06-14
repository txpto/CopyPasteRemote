"""WebSocket presence + clip-notification channel against a live server."""

import base64
import threading

from cpr_shared import crypto, protocol
from cpr_client.transport import RestClient, WsClient


def _push_text(base, key, slot_from, token_from, target_slot, text):
    rest = RestClient(base, slot_from, token_from, verify_tls=False)
    data = text.encode("utf-8")
    cipher = crypto.encrypt(key, data)
    env = protocol.Envelope(
        kind=protocol.KIND_TEXT,
        size=len(data),
        enc_size=len(cipher),
        sha256=crypto.sha256_hex(data),
        key_fp=crypto.key_fingerprint(key),
        inline=True,
        data_b64=base64.b64encode(cipher).decode(),
    )
    rest.push_envelope(target_slot, env.to_dict())


def test_ws_hello_and_clip_notification(live_server):
    base, key, tokens = live_server

    hello = threading.Event()
    clip = threading.Event()
    received = {}

    ws2 = WsClient(base, 2, tokens[2], verify_tls=False)
    ws2.on_hello = lambda machines: (received.update(hello=machines), hello.set())
    ws2.on_clip = lambda slot, info: (received.update(clip=(slot, info)), clip.set())
    ws2.start()
    try:
        assert hello.wait(timeout=10), "did not receive WS hello"
        assert any(m["slot"] == 2 for m in received["hello"])

        # Machine 1 pushes into mailbox 2 -> server should notify slot 2.
        _push_text(base, key, 1, tokens[1], 2, "hola ws")
        assert clip.wait(timeout=10), "did not receive clip notification"
        slot, info = received["clip"]
        assert slot == 2
        assert info.get("from_id") == 1
        assert info.get("summary")
    finally:
        ws2.stop()


def test_ws_presence(live_server):
    base, key, tokens = live_server

    presence = threading.Event()
    seen = {}

    ws2 = WsClient(base, 2, tokens[2], verify_tls=False)
    ws2.on_presence = lambda slot, online: (seen.update(last=(slot, online)), presence.set())
    ws2.start()
    try:
        # Give ws2 a moment to be registered, then connect ws1 -> ws2 sees presence.
        import time

        time.sleep(1.0)
        ws1 = WsClient(base, 1, tokens[1], verify_tls=False)
        ws1.start()
        try:
            assert presence.wait(timeout=10), "did not receive presence event"
            slot, online = seen["last"]
            assert slot == 1 and online is True
        finally:
            ws1.stop()
    finally:
        ws2.stop()
