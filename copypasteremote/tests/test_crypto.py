import io
import os

import pytest

from cpr_shared import crypto


def test_roundtrip_basic():
    key = crypto.generate_key()
    pt = b"hello world, copy paste remote!"
    blob = crypto.encrypt(key, pt)
    assert blob != pt
    assert crypto.decrypt(key, blob) == pt


def test_roundtrip_empty_and_large():
    key = crypto.generate_key()
    for pt in (b"", os.urandom(1), os.urandom(1024 * 1024 + 7)):
        assert crypto.decrypt(key, crypto.encrypt(key, pt)) == pt


def test_wrong_key_fails():
    k1, k2 = crypto.generate_key(), crypto.generate_key()
    blob = crypto.encrypt(k1, b"secret")
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(k2, blob)


def test_tamper_detection():
    key = crypto.generate_key()
    blob = bytearray(crypto.encrypt(key, b"important data"))
    blob[-1] ^= 0x01  # flip a bit in the tag
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(key, bytes(blob))


def test_aad_binding():
    key = crypto.generate_key()
    blob = crypto.encrypt(key, b"data", aad=b"ctx-1")
    assert crypto.decrypt(key, blob, aad=b"ctx-1") == b"data"
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(key, blob, aad=b"ctx-2")


def test_key_b64_roundtrip():
    key = crypto.generate_key()
    text = crypto.key_to_b64(key)
    assert crypto.key_from_b64(text) == key
    # Tolerant of missing padding.
    assert crypto.key_from_b64(text.rstrip("=")) == key


def test_passphrase_is_deterministic():
    a = crypto.key_from_passphrase("correct horse battery staple", "poolA")
    b = crypto.key_from_passphrase("correct horse battery staple", "poolA")
    c = crypto.key_from_passphrase("correct horse battery staple", "poolB")
    assert a == b
    assert a != c
    assert len(a) == 32


def test_fingerprint_stable_and_distinct():
    k1 = crypto.generate_key()
    k2 = crypto.generate_key()
    assert crypto.key_fingerprint(k1) == crypto.key_fingerprint(k1)
    assert crypto.key_fingerprint(k1) != crypto.key_fingerprint(k2)


def test_stream_roundtrip():
    key = crypto.generate_key()
    data = os.urandom(5 * 1024 * 1024 + 123)  # spans several chunks
    enc = io.BytesIO()
    crypto.encrypt_stream(key, io.BytesIO(data), enc, chunk_size=1024 * 1024)
    enc.seek(0)
    dec = io.BytesIO()
    crypto.decrypt_stream(key, enc, dec)
    assert dec.getvalue() == data
