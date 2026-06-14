"""Tests for continuous bidirectional clipboard sync."""

import base64
import threading
import time

import pytest

from cpr_shared import crypto, protocol
from cpr_client.agent import Agent, ClipboardBackend
from cpr_client.clipdata import ClipData
from cpr_client.config import ClientConfig
from cpr_client.sync import ClipboardMonitor
from cpr_client.transport import RestClient


class FakeClipboard(ClipboardBackend):
    def __init__(self):
        self.clip = None
        self.seq = 0

    def read(self):
        return self.clip

    def write(self, clip):
        self.clip = clip
        self.seq += 1

    def change_token(self):
        return self.seq


def _cfg(base, key, slot, token, **ov):
    cfg = ClientConfig(
        server_url=base, machine_id=slot, machine_name="m%d" % slot, token=token,
        pool_key=crypto.key_to_b64(key), verify_tls=False, copy_before_send=False,
        auto_paste=False,
    )
    for k, v in ov.items():
        setattr(cfg, k, v)
    return cfg


# ------------------------------------------------------------------- monitor
def test_monitor_fires_on_change():
    cb = FakeClipboard()
    ev = threading.Event()
    mon = ClipboardMonitor(cb, on_change=ev.set, interval=0.05)
    mon.start()
    try:
        time.sleep(0.12)
        cb.write(ClipData.text_data("hello"))  # bumps seq -> a change
        assert ev.wait(2.0), "monitor did not fire on change"
    finally:
        mon.stop()


def test_monitor_note_self_write_absorbs_change():
    cb = FakeClipboard()
    fired = []
    mon = ClipboardMonitor(cb, on_change=lambda: fired.append(1), interval=0.05)
    mon._last = mon._token()
    cb.write(ClipData.text_data("x"))   # our own write
    mon.note_self_write()               # absorb it
    assert mon._token() == mon._last    # no pending change -> would not fire


# ------------------------------------------------------------------ outgoing
def test_local_change_is_pushed_to_peer(live_server):
    base, key, tokens = live_server
    cbA = FakeClipboard()
    a = Agent(_cfg(base, key, 1, tokens[1], sync_enabled=True, sync_peers=[2]), cbA)
    cbA.clip = ClipData.text_data("sync me")
    a._on_local_clip_change()

    env = protocol.Envelope.from_dict(
        RestClient(base, 2, tokens[2], verify_tls=False).pull_envelope(2)
    )
    import io

    out = io.BytesIO()
    crypto.decrypt_stream(key, io.BytesIO(base64.b64decode(env.data_b64)), out)
    assert out.getvalue() == b"sync me"
    a.close()


def test_sync_targets_default_to_all_pool_peers(live_server):
    base, key, tokens = live_server
    cbA = FakeClipboard()
    a = Agent(_cfg(base, key, 1, tokens[1], sync_enabled=True), cbA)  # no explicit peers
    assert a._sync_targets() == [2]  # everyone in the pool except me
    a.close()


# ------------------------------------------------------------- echo-loop guard
def test_echo_is_suppressed(live_server):
    base, key, tokens = live_server
    cbA = FakeClipboard()
    a = Agent(_cfg(base, key, 1, tokens[1], sync_enabled=True, sync_peers=[2]), cbA)

    clip = ClipData.text_data("came from a peer")
    # Simulate that this content just arrived and was applied locally.
    a._apply(1, protocol.Envelope(kind=protocol.KIND_TEXT), clip, auto_paste=False)
    cbA.clip = clip

    # The monitor firing now must NOT re-broadcast it.
    a._on_local_clip_change()
    rest2 = RestClient(base, 2, tokens[2], verify_tls=False)
    with pytest.raises(Exception):
        rest2.pull_envelope(2)  # mailbox 2 stays empty (404)
    a.close()


def test_large_payload_skipped_when_capped(live_server):
    base, key, tokens = live_server
    cbA = FakeClipboard()
    a = Agent(_cfg(base, key, 1, tokens[1], sync_enabled=True, sync_peers=[2],
                   sync_max_bytes=10), cbA)
    cbA.clip = ClipData.text_data("this text is definitely longer than ten bytes")
    a._on_local_clip_change()
    with pytest.raises(Exception):
        RestClient(base, 2, tokens[2], verify_tls=False).pull_envelope(2)  # skipped -> empty
    a.close()
