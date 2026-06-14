"""Director server and admin CLI for CopyPasteRemote."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


from .protocol import PACKAGE_FILES, PACKAGE_TEXT, SUPPORTED_PACKAGE_TYPES, new_token, sha256_file

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pools (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    last_seen INTEGER,
    FOREIGN KEY(pool_id) REFERENCES pools(id)
);
CREATE TABLE IF NOT EXISTS enrollment_codes (
    code TEXT PRIMARY KEY,
    pool_id INTEGER NOT NULL,
    machine_name TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    FOREIGN KEY(pool_id) REFERENCES pools(id)
);
CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id INTEGER NOT NULL,
    slot TEXT NOT NULL,
    source_machine_id INTEGER NOT NULL,
    package_type TEXT NOT NULL,
    text_value TEXT,
    blob_path TEXT,
    blob_sha256 TEXT,
    original_name TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    FOREIGN KEY(pool_id) REFERENCES pools(id),
    FOREIGN KEY(source_machine_id) REFERENCES machines(id)
);
CREATE INDEX IF NOT EXISTS idx_packages_pool_slot_created ON packages(pool_id, slot, created_at DESC);
"""


def connect_db(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(data_dir / "director.sqlite3"))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(data_dir: Path, admin_token: Optional[str] = None) -> None:
    conn = connect_db(data_dir)
    try:
        conn.executescript(SCHEMA)
        if admin_token:
            conn.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES('admin_token', ?)",
                (admin_token,),
            )
        conn.commit()
    finally:
        conn.close()


def get_setting(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def require_admin(conn: sqlite3.Connection, token: str) -> None:
    expected = get_setting(conn, "admin_token")
    if not expected or token != expected:
        raise SystemExit("invalid admin token")


def create_app(data_dir: Path, max_upload_bytes: int = 2 * 1024 * 1024 * 1024):
    from flask import Flask, abort, g, jsonify, request, send_file
    from werkzeug.utils import secure_filename

    app = Flask(__name__)
    app.config["DATA_DIR"] = data_dir
    app.config["MAX_CONTENT_LENGTH"] = max_upload_bytes

    @app.before_request
    def open_db() -> None:
        g.db = connect_db(app.config["DATA_DIR"])

    @app.teardown_request
    def close_db(_exc: Optional[BaseException]) -> None:
        db = getattr(g, "db", None)
        if db is not None:
            db.close()

    def auth_machine() -> sqlite3.Row:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            abort(401)
        token = auth.split(" ", 1)[1].strip()
        machine = g.db.execute(
            "SELECT machines.*, pools.name AS pool_name FROM machines JOIN pools ON pools.id = machines.pool_id WHERE token = ?",
            (token,),
        ).fetchone()
        if not machine:
            abort(403)
        g.db.execute("UPDATE machines SET last_seen = ? WHERE id = ?", (int(time.time()), machine["id"]))
        g.db.commit()
        return machine

    @app.get("/health")
    def health() -> Any:
        return jsonify({"ok": True, "service": "CopyPasteRemote Director"})

    @app.post("/api/enroll")
    def enroll() -> Any:
        payload = request.get_json(force=True)
        code = payload.get("code")
        now = int(time.time())
        row = g.db.execute(
            "SELECT * FROM enrollment_codes WHERE code = ? AND used_at IS NULL AND expires_at > ?",
            (code, now),
        ).fetchone()
        if not row:
            abort(403)
        token = new_token("machine")
        g.db.execute(
            "INSERT INTO machines(pool_id, name, token, created_at) VALUES(?, ?, ?, ?)",
            (row["pool_id"], row["machine_name"], token, now),
        )
        g.db.execute("UPDATE enrollment_codes SET used_at = ? WHERE code = ?", (now, code))
        pool = g.db.execute("SELECT name FROM pools WHERE id = ?", (row["pool_id"],)).fetchone()
        g.db.commit()
        return jsonify({"machine_name": row["machine_name"], "pool": pool["name"], "token": token})

    @app.post("/api/slots/<slot>/package")
    def upload_package(slot: str) -> Any:
        machine = auth_machine()
        package_type = request.form.get("package_type")
        if package_type not in SUPPORTED_PACKAGE_TYPES:
            abort(400, "unsupported package_type")
        now = int(time.time())
        expires_at = now + int(request.form.get("ttl_seconds", 7 * 24 * 3600))
        text_value = None
        blob_path = None
        blob_sha = None
        original_name = request.form.get("original_name")
        size_bytes = 0
        if package_type == PACKAGE_TEXT:
            text_value = request.form.get("text", "")
            size_bytes = len(text_value.encode("utf-8"))
        else:
            uploaded = request.files.get("blob")
            if not uploaded:
                abort(400, "missing blob")
            safe_slot = secure_filename(slot) or "slot"
            blob_dir = app.config["DATA_DIR"] / "blobs" / str(machine["pool_id"]) / safe_slot
            blob_dir.mkdir(parents=True, exist_ok=True)
            temp_path = blob_dir / (new_token("pkg") + ".zip")
            uploaded.save(str(temp_path))
            size_bytes = temp_path.stat().st_size
            blob_sha = sha256_file(temp_path)
            blob_path = str(temp_path.relative_to(app.config["DATA_DIR"]))
        cur = g.db.execute(
            """
            INSERT INTO packages(pool_id, slot, source_machine_id, package_type, text_value, blob_path,
                                 blob_sha256, original_name, size_bytes, created_at, expires_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (machine["pool_id"], slot, machine["id"], package_type, text_value, blob_path, blob_sha,
             original_name, size_bytes, now, expires_at),
        )
        g.db.commit()
        return jsonify({"package_id": cur.lastrowid, "slot": slot, "package_type": package_type, "size_bytes": size_bytes})

    def latest_package(machine: sqlite3.Row, slot: str) -> sqlite3.Row:
        row = g.db.execute(
            """
            SELECT packages.*, machines.name AS source_machine
            FROM packages JOIN machines ON machines.id = packages.source_machine_id
            WHERE packages.pool_id = ? AND packages.slot = ? AND (packages.expires_at IS NULL OR packages.expires_at > ?)
            ORDER BY packages.created_at DESC LIMIT 1
            """,
            (machine["pool_id"], slot, int(time.time())),
        ).fetchone()
        if not row:
            abort(404)
        return row

    @app.get("/api/slots/<slot>/package")
    def package_metadata(slot: str) -> Any:
        machine = auth_machine()
        row = latest_package(machine, slot)
        return jsonify(dict(row))

    @app.get("/api/slots/<slot>/package/blob")
    def package_blob(slot: str) -> Any:
        machine = auth_machine()
        row = latest_package(machine, slot)
        if row["package_type"] == PACKAGE_TEXT or not row["blob_path"]:
            abort(404)
        return send_file(app.config["DATA_DIR"] / row["blob_path"], as_attachment=True, download_name=row["original_name"] or "clipboard.zip")

    return app


def cmd_init(args: argparse.Namespace) -> None:
    init_db(Path(args.data_dir), args.admin_token)
    print("Director database initialized")


def cmd_create_pool(args: argparse.Namespace) -> None:
    conn = connect_db(Path(args.data_dir))
    try:
        require_admin(conn, args.admin_token)
        conn.execute("INSERT INTO pools(name, created_at) VALUES(?, ?)", (args.pool, int(time.time())))
        conn.commit()
        print("Pool created: %s" % args.pool)
    finally:
        conn.close()


def cmd_enroll_code(args: argparse.Namespace) -> None:
    conn = connect_db(Path(args.data_dir))
    try:
        require_admin(conn, args.admin_token)
        pool = conn.execute("SELECT id FROM pools WHERE name = ?", (args.pool,)).fetchone()
        if not pool:
            raise SystemExit("pool not found")
        code = new_token("enroll")
        conn.execute(
            "INSERT INTO enrollment_codes(code, pool_id, machine_name, expires_at) VALUES(?, ?, ?, ?)",
            (code, pool["id"], args.machine, int(time.time()) + args.ttl_seconds),
        )
        conn.commit()
        print(code)
    finally:
        conn.close()


def cmd_serve(args: argparse.Namespace) -> None:
    init_db(Path(args.data_dir))
    app = create_app(Path(args.data_dir), args.max_upload_bytes)
    app.run(host=args.host, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CopyPasteRemote Director")
    sub = parser.add_subparsers(required=True)
    init = sub.add_parser("init")
    init.add_argument("--data-dir", required=True)
    init.add_argument("--admin-token", required=True)
    init.set_defaults(func=cmd_init)
    pool = sub.add_parser("create-pool")
    pool.add_argument("--data-dir", required=True)
    pool.add_argument("--admin-token", required=True)
    pool.add_argument("--pool", required=True)
    pool.set_defaults(func=cmd_create_pool)
    code = sub.add_parser("enroll-code")
    code.add_argument("--data-dir", required=True)
    code.add_argument("--admin-token", required=True)
    code.add_argument("--pool", required=True)
    code.add_argument("--machine", required=True)
    code.add_argument("--ttl-seconds", type=int, default=3600)
    code.set_defaults(func=cmd_enroll_code)
    serve = sub.add_parser("serve")
    serve.add_argument("--data-dir", required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--max-upload-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    serve.set_defaults(func=cmd_serve)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
