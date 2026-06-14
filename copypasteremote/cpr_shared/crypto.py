"""Authenticated symmetric encryption shared by client and server.

The whole pool shares one 256-bit *pool key*.  Clipboard payloads are encrypted
with AES-256-GCM before they ever leave a machine, so the orchestrator only ever
stores ciphertext (defence in depth on top of TLS).

Two crypto backends are supported so the client keeps working on Windows 7 / old
Python builds where one library or the other may be easier to install:

* ``cryptography`` (preferred, used on the server)
* ``pycryptodome`` (fallback, very easy to install on Windows 7 x64)

Both backends produce and consume the **exact same bytes**, so a payload encrypted
on one machine can always be decrypted on another regardless of which backend each
side happens to use.

Wire format of an encrypted blob::

    +---------+-------------------+--------------------------------+
    | 1 byte  | 12 bytes          | N bytes                        |
    | version | random GCM nonce  | ciphertext || 16-byte GCM tag  |
    +---------+-------------------+--------------------------------+

The key-derivation helper (passphrase -> 32-byte key) uses :func:`hashlib.pbkdf2_hmac`
from the standard library, so it is byte-for-byte identical everywhere and needs no
third-party dependency at all.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Optional, Tuple

_VERSION = 1
_NONCE_LEN = 12
_TAG_LEN = 16
_KEY_LEN = 32  # AES-256

# Fixed parameters for passphrase based key derivation.  Changing these breaks
# compatibility with previously generated keys, so treat them as constants.
_PBKDF2_ITERATIONS = 200_000
_PBKDF2_SALT_PREFIX = b"CopyPasteRemote::pool::"


class CryptoError(Exception):
    """Raised when encryption or (more importantly) decryption/authentication fails."""


# --------------------------------------------------------------------------- #
# Backend selection
# --------------------------------------------------------------------------- #
_BACKEND = None
try:  # Preferred backend.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _CgAESGCM

    _BACKEND = "cryptography"
except Exception:  # pragma: no cover - exercised on machines without cryptography
    try:
        from Crypto.Cipher import AES as _PyCAES  # type: ignore

        _BACKEND = "pycryptodome"
    except Exception:  # pragma: no cover - no crypto backend at all
        _BACKEND = None


def backend_name() -> str:
    """Return the name of the active crypto backend (for diagnostics)."""
    return _BACKEND or "none"


def _require_backend() -> None:
    if _BACKEND is None:  # pragma: no cover
        raise CryptoError(
            "No crypto backend available. Install 'cryptography' or 'pycryptodome'."
        )


# --------------------------------------------------------------------------- #
# Key helpers
# --------------------------------------------------------------------------- #
def generate_key() -> bytes:
    """Return a fresh random 32-byte pool key."""
    return os.urandom(_KEY_LEN)


def key_to_b64(key: bytes) -> str:
    """Encode a raw key as URL-safe base64 (the form stored in config files)."""
    if len(key) != _KEY_LEN:
        raise CryptoError("Pool key must be exactly 32 bytes")
    return base64.urlsafe_b64encode(key).decode("ascii")


def key_from_b64(text: str) -> bytes:
    """Decode a base64 pool key, accepting both standard and URL-safe alphabets."""
    text = text.strip()
    # Be tolerant about padding and alphabet so hand-edited config files still work.
    padded = text + "=" * (-len(text) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            raw = decoder(padded)
        except Exception:
            continue
        if len(raw) == _KEY_LEN:
            return raw
    raise CryptoError("Invalid pool key: must decode to 32 bytes of base64")


def key_from_passphrase(passphrase: str, pool_id: str = "default") -> bytes:
    """Derive a deterministic 32-byte key from a human passphrase.

    Uses PBKDF2-HMAC-SHA256 with a salt bound to ``pool_id`` so two different
    pools never end up with the same key from the same passphrase.
    """
    if not passphrase:
        raise CryptoError("Passphrase must not be empty")
    salt = _PBKDF2_SALT_PREFIX + pool_id.encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=_KEY_LEN
    )


def key_fingerprint(key: bytes) -> str:
    """Short, non-secret identifier of a key, used to detect key mismatches.

    It is a truncated SHA-256 of a domain-separated digest of the key; it does
    not reveal the key itself but lets two machines confirm they share one.
    """
    digest = hashlib.sha256(b"CPR-key-fingerprint\x00" + key).digest()
    return base64.urlsafe_b64encode(digest[:6]).decode("ascii").rstrip("=")


# --------------------------------------------------------------------------- #
# Encrypt / decrypt
# --------------------------------------------------------------------------- #
def _normalise_aad(aad: Optional[bytes]) -> bytes:
    return b"" if aad is None else aad


def encrypt(key: bytes, plaintext: bytes, aad: Optional[bytes] = None) -> bytes:
    """Encrypt ``plaintext`` with AES-256-GCM, returning a versioned blob."""
    _require_backend()
    if len(key) != _KEY_LEN:
        raise CryptoError("Pool key must be exactly 32 bytes")
    aad_b = _normalise_aad(aad)
    nonce = os.urandom(_NONCE_LEN)

    if _BACKEND == "cryptography":
        body_and_tag = _CgAESGCM(key).encrypt(nonce, plaintext, aad_b)
    else:  # pycryptodome
        cipher = _PyCAES.new(key, _PyCAES.MODE_GCM, nonce=nonce)
        cipher.update(aad_b)
        body, tag = cipher.encrypt_and_digest(plaintext)
        body_and_tag = body + tag

    return bytes([_VERSION]) + nonce + body_and_tag


def decrypt(key: bytes, blob: bytes, aad: Optional[bytes] = None) -> bytes:
    """Decrypt and authenticate a blob produced by :func:`encrypt`."""
    _require_backend()
    if len(key) != _KEY_LEN:
        raise CryptoError("Pool key must be exactly 32 bytes")
    if len(blob) < 1 + _NONCE_LEN + _TAG_LEN:
        raise CryptoError("Ciphertext too short / corrupted")
    if blob[0] != _VERSION:
        raise CryptoError("Unsupported ciphertext version %d" % blob[0])

    aad_b = _normalise_aad(aad)
    nonce = blob[1 : 1 + _NONCE_LEN]
    body_and_tag = blob[1 + _NONCE_LEN :]

    try:
        if _BACKEND == "cryptography":
            return _CgAESGCM(key).decrypt(nonce, body_and_tag, aad_b)
        else:  # pycryptodome
            body, tag = body_and_tag[:-_TAG_LEN], body_and_tag[-_TAG_LEN:]
            cipher = _PyCAES.new(key, _PyCAES.MODE_GCM, nonce=nonce)
            cipher.update(aad_b)
            return cipher.decrypt_and_verify(body, tag)
    except Exception as exc:  # noqa: BLE001 - normalise all backend errors
        raise CryptoError("Decryption/authentication failed: %s" % exc) from exc


# --------------------------------------------------------------------------- #
# Streaming helpers for large file blobs (encrypt/decrypt in fixed-size chunks)
# --------------------------------------------------------------------------- #
#
# Each chunk is encrypted independently and length-prefixed, so very large file
# payloads can be streamed to disk without ever holding the whole plaintext in
# memory.  The chunk index is bound in as associated data to prevent reordering.
#
_CHUNK_MAGIC = b"CPRS"  # CopyPasteRemote Stream
_DEFAULT_CHUNK = 1024 * 1024  # 1 MiB plaintext per chunk


def encrypt_stream(key: bytes, src, dst, chunk_size: int = _DEFAULT_CHUNK) -> int:
    """Encrypt a binary stream ``src`` into ``dst``. Returns plaintext bytes read.

    Layout: ``magic(4) || u32 chunk_size`` header, then repeated
    ``u32 blob_len || blob`` records, terminated by a ``u32 0`` record.
    """
    _require_backend()
    total = 0
    index = 0
    dst.write(_CHUNK_MAGIC)
    dst.write(_u32(chunk_size))
    while True:
        plain = src.read(chunk_size)
        if not plain:
            break
        total += len(plain)
        blob = encrypt(key, plain, aad=_u32(index))
        dst.write(_u32(len(blob)))
        dst.write(blob)
        index += 1
    dst.write(_u32(0))  # terminator
    return total


def decrypt_stream(key: bytes, src, dst) -> int:
    """Reverse :func:`encrypt_stream`. Returns plaintext bytes written."""
    _require_backend()
    magic = src.read(4)
    if magic != _CHUNK_MAGIC:
        raise CryptoError("Bad stream magic; not a CPR encrypted stream")
    _ = _read_u32(src)  # declared chunk size (informational)
    total = 0
    index = 0
    while True:
        blob_len = _read_u32(src)
        if blob_len == 0:
            break
        blob = _read_exact(src, blob_len)
        plain = decrypt(key, blob, aad=_u32(index))
        dst.write(plain)
        total += len(plain)
        index += 1
    return total


# --------------------------------------------------------------------------- #
# Small binary helpers
# --------------------------------------------------------------------------- #
def _u32(value: int) -> bytes:
    return int(value).to_bytes(4, "big")


def _read_u32(stream) -> int:
    return int.from_bytes(_read_exact(stream, 4), "big")


def _read_exact(stream, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise CryptoError("Unexpected end of encrypted stream")
        buf.extend(chunk)
    return bytes(buf)


def constant_time_equals(a: bytes, b: bytes) -> bool:
    """Wrapper around :func:`hmac.compare_digest` for token comparisons."""
    return hmac.compare_digest(a, b)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_token(token: str) -> str:
    """Hash an auth token for storage (we never store tokens in the clear)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
