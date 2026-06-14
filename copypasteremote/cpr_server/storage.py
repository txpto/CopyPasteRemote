"""Persistence layer: SQLite for metadata, flat files for large blobs.

All public methods are thread-safe (guarded by a single lock).  Throughput for a
clipboard tool is tiny, so a global lock keeps the code simple and correct while
FastAPI runs the sync endpoints in its thread pool.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from cpr_shared import crypto

_SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    token_hash  TEXT    NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  REAL    NOT NULL,
    last_seen   REAL
);

CREATE TABLE IF NOT EXISTS slots (
    id            INTEGER PRIMARY KEY,   -- == owner machine id (the mailbox)
    envelope_json TEXT,
    inline_blob   BLOB,                  -- ciphertext when carried inline
    blob_id       TEXT,                  -- reference into blobs table otherwise
    kind          TEXT,
    size          INTEGER,
    sha256        TEXT,
    from_id       INTEGER,
    updated_at    REAL
);

CREATE TABLE IF NOT EXISTS blobs (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    size        INTEGER NOT NULL DEFAULT 0,
    sha256      TEXT,
    complete    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    ref_slot    INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class StorageError(Exception):
    pass


class Storage:
    def __init__(self, db_path: str, blobs_dir: str):
        self.db_path = db_path
        self.blobs_dir = blobs_dir
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        os.makedirs(blobs_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ----------------------------------------------------------------- meta
    def get_meta(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._conn.commit()

    # ------------------------------------------------------------- machines
    def add_machine(self, slot: int, name: str, token: Optional[str] = None) -> str:
        """Register a machine and return its (clear-text) auth token.

        The token is returned exactly once; only its hash is stored.
        """
        token = token or secrets.token_urlsafe(32)
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM machines WHERE id=?", (slot,)
            ).fetchone()
            if existing:
                raise StorageError("Slot %d is already registered" % slot)
            self._conn.execute(
                "INSERT INTO machines(id, name, token_hash, enabled, created_at) "
                "VALUES(?, ?, ?, 1, ?)",
                (slot, name, crypto.hash_token(token), time.time()),
            )
            self._conn.commit()
        return token

    def rotate_token(self, slot: int) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            cur = self._conn.execute(
                "UPDATE machines SET token_hash=? WHERE id=?",
                (crypto.hash_token(token), slot),
            )
            if cur.rowcount == 0:
                raise StorageError("No such machine: slot %d" % slot)
            self._conn.commit()
        return token

    def set_machine_name(self, slot: int, name: str) -> None:
        with self._lock:
            cur = self._conn.execute("UPDATE machines SET name=? WHERE id=?", (name, slot))
            if cur.rowcount == 0:
                raise StorageError("No such machine: slot %d" % slot)
            self._conn.commit()

    def set_enabled(self, slot: int, enabled: bool) -> None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE machines SET enabled=? WHERE id=?", (1 if enabled else 0, slot)
            )
            if cur.rowcount == 0:
                raise StorageError("No such machine: slot %d" % slot)
            self._conn.commit()

    def delete_machine(self, slot: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM machines WHERE id=?", (slot,))
            self._conn.execute("DELETE FROM slots WHERE id=?", (slot,))
            self._conn.commit()

    def get_machine(self, slot: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM machines WHERE id=?", (slot,)).fetchone()
            return dict(row) if row else None

    def list_machines(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM machines ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def verify_token(self, slot: int, token: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT token_hash, enabled FROM machines WHERE id=?", (slot,)
            ).fetchone()
        if not row or not row["enabled"]:
            return False
        return crypto.constant_time_equals(
            row["token_hash"].encode(), crypto.hash_token(token).encode()
        )

    def touch_machine(self, slot: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE machines SET last_seen=? WHERE id=?", (time.time(), slot)
            )
            self._conn.commit()

    # ---------------------------------------------------------------- slots
    def set_slot(
        self,
        slot: int,
        envelope_json: str,
        kind: str,
        size: int,
        sha256: str,
        from_id: Optional[int],
        inline_blob: Optional[bytes] = None,
        blob_id: Optional[str] = None,
    ) -> None:
        now = time.time()
        with self._lock:
            old = self._conn.execute(
                "SELECT blob_id FROM slots WHERE id=?", (slot,)
            ).fetchone()
            old_blob = old["blob_id"] if old else None

            self._conn.execute(
                "INSERT INTO slots(id, envelope_json, inline_blob, blob_id, kind, size, "
                "sha256, from_id, updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET envelope_json=excluded.envelope_json, "
                "inline_blob=excluded.inline_blob, blob_id=excluded.blob_id, "
                "kind=excluded.kind, size=excluded.size, sha256=excluded.sha256, "
                "from_id=excluded.from_id, updated_at=excluded.updated_at",
                (slot, envelope_json, inline_blob, blob_id, kind, size, sha256, from_id, now),
            )
            if blob_id:
                self._conn.execute(
                    "UPDATE blobs SET ref_slot=? WHERE id=?", (slot, blob_id)
                )
            self._conn.commit()

            # The slot no longer points at the previous blob -> reclaim it.
            if old_blob and old_blob != blob_id:
                self._delete_blob_locked(old_blob)

    def get_slot(self, slot: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM slots WHERE id=?", (slot,)).fetchone()
            return dict(row) if row else None

    def clear_slot(self, slot: int) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT blob_id FROM slots WHERE id=?", (slot,)
            ).fetchone()
            self._conn.execute("DELETE FROM slots WHERE id=?", (slot,))
            self._conn.commit()
            if row and row["blob_id"]:
                self._delete_blob_locked(row["blob_id"])

    # ---------------------------------------------------------------- blobs
    def create_blob(self) -> str:
        blob_id = secrets.token_hex(16)
        path = os.path.join(self.blobs_dir, blob_id + ".bin")
        with self._lock:
            self._conn.execute(
                "INSERT INTO blobs(id, path, size, complete, created_at) VALUES(?,?,0,0,?)",
                (blob_id, path, time.time()),
            )
            self._conn.commit()
        # Touch the file so appends find it.
        open(path, "wb").close()
        return blob_id

    def get_blob(self, blob_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM blobs WHERE id=?", (blob_id,)).fetchone()
            return dict(row) if row else None

    def append_blob(self, blob_id: str, offset: int, data: bytes) -> int:
        """Append a chunk at ``offset``; returns the new total size.

        Chunks must arrive in order (offset must equal the current size).  This
        keeps the writer simple and lets a client resume after a drop by querying
        the current size first.
        """
        info = self.get_blob(blob_id)
        if not info:
            raise StorageError("No such blob: %s" % blob_id)
        if info["complete"]:
            raise StorageError("Blob already finalised: %s" % blob_id)
        path = info["path"]
        current = os.path.getsize(path) if os.path.exists(path) else 0
        if offset != current:
            raise StorageError(
                "Out-of-order chunk for %s: expected offset %d, got %d"
                % (blob_id, current, offset)
            )
        with open(path, "ab") as fh:
            fh.write(data)
        new_size = current + len(data)
        with self._lock:
            self._conn.execute("UPDATE blobs SET size=? WHERE id=?", (new_size, blob_id))
            self._conn.commit()
        return new_size

    def complete_blob(self, blob_id: str, expected_sha256: Optional[str] = None) -> Dict[str, Any]:
        info = self.get_blob(blob_id)
        if not info:
            raise StorageError("No such blob: %s" % blob_id)
        path = info["path"]
        actual = _sha256_file(path)
        if expected_sha256 and actual != expected_sha256:
            raise StorageError("Blob checksum mismatch for %s" % blob_id)
        with self._lock:
            self._conn.execute(
                "UPDATE blobs SET complete=1, sha256=?, size=? WHERE id=?",
                (actual, os.path.getsize(path), blob_id),
            )
            self._conn.commit()
        return self.get_blob(blob_id)  # type: ignore[return-value]

    def _delete_blob_locked(self, blob_id: str) -> None:
        row = self._conn.execute("SELECT path FROM blobs WHERE id=?", (blob_id,)).fetchone()
        if row:
            try:
                if os.path.exists(row["path"]):
                    os.remove(row["path"])
            except OSError:
                pass
            self._conn.execute("DELETE FROM blobs WHERE id=?", (blob_id,))
            self._conn.commit()

    def delete_blob(self, blob_id: str) -> None:
        with self._lock:
            self._delete_blob_locked(blob_id)

    # ----------------------------------------------------------- maintenance
    def expire_slots(self, ttl_seconds: int) -> int:
        """Purge clipboard payloads older than ttl. Returns count removed."""
        if ttl_seconds <= 0:
            return 0
        cutoff = time.time() - ttl_seconds
        removed = 0
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM slots WHERE updated_at < ?", (cutoff,)
            ).fetchall()
        for r in rows:
            self.clear_slot(r["id"])
            removed += 1
        return removed

    def gc_orphan_blobs(self, ttl_seconds: int) -> int:
        """Delete blobs that were never attached to a slot and are old/abandoned."""
        cutoff = time.time() - ttl_seconds
        removed = 0
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM blobs WHERE ref_slot IS NULL AND created_at < ?",
                (cutoff,),
            ).fetchall()
            ids = [r["id"] for r in rows]
        for blob_id in ids:
            self.delete_blob(blob_id)
            removed += 1
        return removed


def _sha256_file(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
