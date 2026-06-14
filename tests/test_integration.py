"""End-to-end test: a real uvicorn server + two client agents.

Exercises the full path (serialize -> encrypt -> upload/inline -> store ->
download -> decrypt -> deserialize) for text and for files/folders, including the
large-payload blob path. The only thing stubbed is the Windows clipboard itself.
"""

import os

import pytest

from cpr_shared import crypto, protocol

from cpr_client.agent import Agent, ClipboardBackend
from cpr_client.clipdata import ClipData
from cpr_client.config import ClientConfig


class FakeClipboard(ClipboardBackend):
    def __init__(self):
        self.clip = None
        self.copies = 0
        self.pastes = 0

    def read(self):
        return self.clip

    def write(self, clip):
        self.clip = clip

    def simulate_copy(self):
        self.copies += 1

    def simulate_paste(self):
        self.pastes += 1


@pytest.fixture()
def server(live_server):
    # Thin alias so the tests below read naturally; startup lives in conftest.
    return live_server


def _client(base, key, slot, token, **overrides):
    cfg = ClientConfig(
        server_url=base,
        machine_id=slot,
        machine_name="m%d" % slot,
        token=token,
        pool_key=crypto.key_to_b64(key),
        verify_tls=False,
        auto_paste=True,
        copy_before_send=True,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def test_text_push_pull(server):
    base, key, tokens = server
    cb1, cb2 = FakeClipboard(), FakeClipboard()
    a1 = Agent(_client(base, key, 1, tokens[1]), cb1)
    a2 = Agent(_client(base, key, 2, tokens[2]), cb2)

    cb1.clip = ClipData.text_data("Texto de prueba con acentos: ñ á é ☺")
    a1.push(2)

    assert cb1.copies == 1  # copy_before_send happened
    clip = a2.pull(2)
    assert clip.kind == protocol.KIND_TEXT
    assert cb2.clip.text == "Texto de prueba con acentos: ñ á é ☺"
    assert cb2.pastes == 1  # auto_paste happened
    a1.close()
    a2.close()


def test_text_inline_path_is_used_for_small(server):
    base, key, tokens = server
    cb1, cb2 = FakeClipboard(), FakeClipboard()
    a1 = Agent(_client(base, key, 1, tokens[1]), cb1)
    a2 = Agent(_client(base, key, 2, tokens[2]), cb2)
    cb1.clip = ClipData.text_data("small")
    env = a1.push(2)
    assert env.inline is True  # small -> inline
    assert env.blob_id is None
    a2.pull(2)
    assert cb2.clip.text == "small"
    a1.close(); a2.close()


def test_large_text_uses_blob(server):
    base, key, tokens = server
    cb1, cb2 = FakeClipboard(), FakeClipboard()
    a1 = Agent(_client(base, key, 1, tokens[1]), cb1)
    a2 = Agent(_client(base, key, 2, tokens[2]), cb2)
    big = "A" * (200 * 1024)  # > 64 KiB inline threshold after encryption
    cb1.clip = ClipData.text_data(big)
    env = a1.push(2)
    assert env.inline is False
    assert env.blob_id is not None
    a2.pull(2)
    assert cb2.clip.text == big
    a1.close(); a2.close()


def test_files_and_folders_roundtrip(server, tmp_path):
    base, key, tokens = server
    # Build a source tree on machine 1.
    src = tmp_path / "src"
    (src / "folder" / "sub").mkdir(parents=True)
    (src / "folder" / "a.txt").write_text("hello A", encoding="utf-8")
    (src / "folder" / "sub" / "b.txt").write_text("hello B" * 1000, encoding="utf-8")
    (src / "single.bin").write_bytes(os.urandom(1024))

    paths = [str(src / "folder"), str(src / "single.bin")]

    cb1, cb2 = FakeClipboard(), FakeClipboard()
    a1 = Agent(_client(base, key, 1, tokens[1]), cb1)
    a2 = Agent(_client(base, key, 2, tokens[2]), cb2)

    cb1.clip = ClipData.files_data(paths)
    env = a1.push(2)
    assert env.kind == protocol.KIND_FILES
    assert {e.name for e in env.files} == {"folder", "single.bin"}

    a2.pull(2)
    out_paths = cb2.clip.paths
    names = {os.path.basename(p) for p in out_paths}
    assert names == {"folder", "single.bin"}

    # Verify the extracted content matches.
    out_by_name = {os.path.basename(p): p for p in out_paths}
    with open(os.path.join(out_by_name["folder"], "a.txt"), encoding="utf-8") as fh:
        assert fh.read() == "hello A"
    with open(os.path.join(out_by_name["folder"], "sub", "b.txt"), encoding="utf-8") as fh:
        assert fh.read() == "hello B" * 1000
    assert os.path.isdir(out_by_name["folder"])
    assert os.path.isfile(out_by_name["single.bin"])
    a1.close(); a2.close()


def test_large_file_blob_path(server, tmp_path):
    base, key, tokens = server
    big = tmp_path / "big.bin"
    big.write_bytes(os.urandom(3 * 1024 * 1024))  # 3 MiB -> definitely a blob

    cb1, cb2 = FakeClipboard(), FakeClipboard()
    a1 = Agent(_client(base, key, 1, tokens[1]), cb1)
    a2 = Agent(_client(base, key, 2, tokens[2]), cb2)
    cb1.clip = ClipData.files_data([str(big)])
    env = a1.push(2)
    assert env.inline is False and env.blob_id

    a2.pull(2)
    out = cb2.clip.paths[0]
    assert os.path.getsize(out) == 3 * 1024 * 1024
    with open(out, "rb") as fh, open(str(big), "rb") as orig:
        assert fh.read() == orig.read()
    a1.close(); a2.close()


def test_wrong_pool_key_fails_integrity(server):
    base, key, tokens = server
    cb1 = FakeClipboard()
    other_key = crypto.generate_key()
    a1 = Agent(_client(base, key, 1, tokens[1]), cb1)
    # Machine 2 has a different pool key -> cannot decrypt.
    cb2 = FakeClipboard()
    a2 = Agent(_client(base, other_key, 2, tokens[2]), cb2)
    cb1.clip = ClipData.text_data("secret")
    a1.push(2)
    with pytest.raises(Exception):
        a2.pull(2)
    a1.close(); a2.close()
