"""FastAPI application: the CopyPasteRemote orchestrator.

Run it with ``python run_server.py`` (see that file for TLS / host / port wiring)
or ``uvicorn cpr_server.main:app``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from cpr_shared import crypto, protocol
from cpr_shared.version import __version__, PROTOCOL_VERSION

from . import auth as authmod
from .config import ServerConfig
from .presence import PresenceHub
from .storage import Storage, StorageError

log = logging.getLogger("cpr.server")

# Populated in the lifespan handler.
CONFIG: ServerConfig
STORE: Storage
HUB = PresenceHub()


# --------------------------------------------------------------------------- #
# Lifespan: init storage, admin key, background maintenance
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    global CONFIG, STORE
    CONFIG = app.state.config
    CONFIG.ensure_dirs()
    STORE = Storage(CONFIG.db_path, CONFIG.blobs_dir)
    app.state.store = STORE

    # Ensure there is an admin key; persist a generated one so it is stable.
    if not CONFIG.admin_api_key:
        stored = STORE.get_meta("admin_api_key")
        if stored:
            CONFIG.admin_api_key = stored
        else:
            CONFIG.admin_api_key = secrets.token_urlsafe(32)
            STORE.set_meta("admin_api_key", CONFIG.admin_api_key)
            log.warning("Generated a new admin API key: %s", CONFIG.admin_api_key)

    # Record the pool key fingerprint (if a key is configured) so clients can
    # detect a mismatch without us ever storing the key when not needed.
    if CONFIG.pool_key_b64:
        try:
            fp = crypto.key_fingerprint(crypto.key_from_b64(CONFIG.pool_key_b64))
            STORE.set_meta("pool_key_fp", fp)
        except crypto.CryptoError:
            log.error("Configured pool_key_b64 is invalid; ignoring it")

    maintenance_task = asyncio.create_task(_maintenance_loop())
    log.info("CopyPasteRemote server %s ready (crypto backend: %s)",
             __version__, crypto.backend_name())
    try:
        yield
    finally:
        maintenance_task.cancel()
        try:
            await maintenance_task
        except asyncio.CancelledError:
            pass
        STORE.close()


async def _maintenance_loop() -> None:
    """Periodically expire stale clipboard payloads and orphan uploads."""
    while True:
        try:
            await asyncio.sleep(300)  # every 5 minutes
            removed = STORE.expire_slots(CONFIG.slot_ttl_seconds)
            orphans = STORE.gc_orphan_blobs(CONFIG.orphan_blob_ttl_seconds)
            if removed or orphans:
                log.info("Maintenance: purged %d slots, %d orphan blobs", removed, orphans)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Maintenance loop error: %s", exc)


# Single application instance. All route decorators below attach to it; tests and
# run_server.py call create_app() to (re)point it at a specific config before use.
app = FastAPI(
    title="CopyPasteRemote Orchestrator",
    version=__version__,
    lifespan=lifespan,
)
app.state.config = ServerConfig.load()


def create_app(config: Optional[ServerConfig] = None) -> FastAPI:
    """Return the application, optionally overriding its configuration.

    There is intentionally a single ``app`` object (so the route decorators have
    something to bind to at import time); this just swaps in the config that the
    lifespan handler will use on startup.
    """
    if config is not None:
        app.state.config = config
    return app


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
def auth_machine(authorization: Optional[str] = Header(None)) -> authmod.AuthContext:
    slot, token = authmod.parse_bearer(authorization)
    if not STORE.verify_token(slot, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials for slot %d" % slot,
            headers={"WWW-Authenticate": "Bearer"},
        )
    STORE.touch_machine(slot)
    machine = STORE.get_machine(slot)
    return authmod.AuthContext(slot=slot, name=machine["name"] if machine else "")


def auth_admin(x_admin_key: Optional[str] = Header(None)) -> None:
    authmod.require_admin_key(x_admin_key, CONFIG.admin_api_key)


# --------------------------------------------------------------------------- #
# Public / health endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {"status": "ok", "time": time.time()}


@app.get("/api/info")
def info():
    return {
        "app": "CopyPasteRemote",
        "version": __version__,
        "protocol": PROTOCOL_VERSION,
        "pool_id": CONFIG.pool_id,
        "pool_key_fp": STORE.get_meta("pool_key_fp"),
        "crypto_backend": crypto.backend_name(),
        "inline_threshold": protocol.INLINE_THRESHOLD,
        "max_payload_bytes": CONFIG.max_payload_bytes,
        "blob_chunk_size": CONFIG.blob_chunk_size,
    }


@app.get("/", response_class=PlainTextResponse)
def root():
    return (
        "CopyPasteRemote orchestrator %s is running.\n"
        "See /docs for the API and the project README for setup.\n" % __version__
    )


# --------------------------------------------------------------------------- #
# Pool
# --------------------------------------------------------------------------- #
@app.get("/api/pool")
async def get_pool(ctx: authmod.AuthContext = Depends(auth_machine)):
    online = set(await HUB.online_slots())
    machines = []
    for m in STORE.list_machines():
        slot = m["id"]
        has_clip = STORE.get_slot(slot) is not None
        machines.append(
            {
                "slot": slot,
                "name": m["name"],
                "enabled": bool(m["enabled"]),
                "online": slot in online,
                "last_seen": m["last_seen"],
                "has_clip": has_clip,
                "is_me": slot == ctx.slot,
            }
        )
    return {"you": ctx.slot, "machines": machines}


# --------------------------------------------------------------------------- #
# Clipboard push / pull
# --------------------------------------------------------------------------- #
@app.post("/api/clip/{slot}")
async def push_clip(
    slot: int, request: Request, ctx: authmod.AuthContext = Depends(auth_machine)
):
    if not protocol.valid_slot(slot):
        raise HTTPException(status_code=400, detail="Invalid slot")
    if STORE.get_machine(slot) is None:
        raise HTTPException(status_code=404, detail="Target slot %d is not registered" % slot)

    body = await request.json()
    env = protocol.Envelope.from_dict(body)
    env.from_id = ctx.slot
    env.from_name = ctx.name

    # Enforce size limits early.
    if env.size > CONFIG.max_payload_bytes:
        raise HTTPException(status_code=413, detail="Payload too large")

    inline_bytes = None
    blob_id = None
    if env.inline:
        if not env.data_b64:
            raise HTTPException(status_code=400, detail="inline envelope missing data_b64")
        import base64

        inline_bytes = base64.b64decode(env.data_b64)
        # Do not also keep the (large) base64 string inside the stored JSON.
        env.data_b64 = None
    else:
        if not env.blob_id:
            raise HTTPException(status_code=400, detail="non-inline envelope missing blob_id")
        blob = STORE.get_blob(env.blob_id)
        if not blob or not blob["complete"]:
            raise HTTPException(status_code=400, detail="referenced blob is missing/incomplete")
        blob_id = env.blob_id

    STORE.set_slot(
        slot=slot,
        envelope_json=env.to_json(),
        kind=env.kind,
        size=env.size,
        sha256=env.sha256,
        from_id=ctx.slot,
        inline_blob=inline_bytes,
        blob_id=blob_id,
    )

    # Notify the mailbox owner so it can pre-fetch for an instant paste.
    await HUB.notify_clip_available(
        slot,
        {
            "kind": env.kind,
            "size": env.size,
            "from_id": ctx.slot,
            "from_name": ctx.name,
            "summary": env.human_summary(),
        },
    )
    return {"ok": True, "slot": slot, "kind": env.kind, "size": env.size}


@app.get("/api/clip/{slot}")
def pull_clip(
    slot: int,
    meta_only: bool = False,
    ctx: authmod.AuthContext = Depends(auth_machine),
):
    if not protocol.valid_slot(slot):
        raise HTTPException(status_code=400, detail="Invalid slot")
    row = STORE.get_slot(slot)
    if not row:
        raise HTTPException(status_code=404, detail="Mailbox %d is empty" % slot)

    env = protocol.Envelope.from_json(row["envelope_json"])
    if meta_only:
        env.data_b64 = None
        return env.to_dict()

    if row["inline_blob"] is not None:
        import base64

        env.inline = True
        env.data_b64 = base64.b64encode(row["inline_blob"]).decode("ascii")
        env.blob_id = None
    else:
        env.inline = False
        env.data_b64 = None
        env.blob_id = row["blob_id"]
    return env.to_dict()


@app.delete("/api/clip/{slot}")
def clear_clip(slot: int, ctx: authmod.AuthContext = Depends(auth_machine)):
    if not protocol.valid_slot(slot):
        raise HTTPException(status_code=400, detail="Invalid slot")
    STORE.clear_slot(slot)
    return {"ok": True, "slot": slot}


# --------------------------------------------------------------------------- #
# Blob upload / download (for large file payloads)
# --------------------------------------------------------------------------- #
@app.post("/api/blobs")
def create_blob(ctx: authmod.AuthContext = Depends(auth_machine)):
    blob_id = STORE.create_blob()
    return {"blob_id": blob_id, "chunk_size": CONFIG.blob_chunk_size}


@app.put("/api/blobs/{blob_id}")
async def append_blob(
    blob_id: str,
    request: Request,
    offset: int = 0,
    ctx: authmod.AuthContext = Depends(auth_machine),
):
    data = await request.body()
    info = STORE.get_blob(blob_id)
    if not info:
        raise HTTPException(status_code=404, detail="No such blob")
    if info["size"] + len(data) > CONFIG.max_payload_bytes:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        new_size = STORE.append_blob(blob_id, offset, data)
    except StorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"blob_id": blob_id, "size": new_size}


@app.get("/api/blobs/{blob_id}/status")
def blob_status(blob_id: str, ctx: authmod.AuthContext = Depends(auth_machine)):
    info = STORE.get_blob(blob_id)
    if not info:
        raise HTTPException(status_code=404, detail="No such blob")
    return {
        "blob_id": blob_id,
        "size": info["size"],
        "complete": bool(info["complete"]),
        "sha256": info["sha256"],
    }


@app.post("/api/blobs/{blob_id}/complete")
async def complete_blob(
    blob_id: str, request: Request, ctx: authmod.AuthContext = Depends(auth_machine)
):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    expected = body.get("sha256") if isinstance(body, dict) else None
    try:
        info = STORE.complete_blob(blob_id, expected)
    except StorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"blob_id": blob_id, "size": info["size"], "sha256": info["sha256"]}


@app.get("/api/blobs/{blob_id}")
def download_blob(
    blob_id: str,
    request: Request,
    ctx: authmod.AuthContext = Depends(auth_machine),
):
    info = STORE.get_blob(blob_id)
    if not info or not info["complete"]:
        raise HTTPException(status_code=404, detail="No such (completed) blob")
    path = info["path"]
    total = os.path.getsize(path)

    # Optional HTTP Range support so a dropped download can resume.
    range_header = request.headers.get("range")
    start, end = 0, total - 1
    status_code = 200
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "application/octet-stream",
        "X-Blob-Sha256": info["sha256"] or "",
    }
    if range_header and range_header.startswith("bytes="):
        try:
            rng = range_header.split("=", 1)[1]
            s, e = rng.split("-", 1)
            start = int(s) if s else 0
            end = int(e) if e else total - 1
            end = min(end, total - 1)
            if start > end or start >= total:
                raise ValueError
            status_code = 206
            headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, total)
        except ValueError:
            raise HTTPException(status_code=416, detail="Invalid range")

    length = end - start + 1
    headers["Content-Length"] = str(length)

    def file_iter():
        remaining = length
        with open(path, "rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(file_iter(), status_code=status_code, headers=headers)


# --------------------------------------------------------------------------- #
# WebSocket presence channel
# --------------------------------------------------------------------------- #
@app.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket):
    # Authenticate from query (?auth=slot.token) or Authorization header.
    auth_value = ws.query_params.get("auth")
    if not auth_value:
        header = ws.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            auth_value = header.split(" ", 1)[1]
    if not auth_value or "." not in auth_value:
        await ws.close(code=4401)
        return
    slot_str, token = auth_value.split(".", 1)
    try:
        slot = int(slot_str)
    except ValueError:
        await ws.close(code=4401)
        return
    if not STORE.verify_token(slot, token):
        await ws.close(code=4401)
        return

    await ws.accept()
    STORE.touch_machine(slot)
    came_online = await HUB.connect(slot, ws)
    if came_online:
        await HUB.announce_presence(slot, True)

    # Greet with a pool snapshot so the client UI is immediately populated.
    online = set(await HUB.online_slots())
    machines = [
        {
            "slot": m["id"],
            "name": m["name"],
            "online": m["id"] in online,
            "enabled": bool(m["enabled"]),
        }
        for m in STORE.list_machines()
    ]
    await ws.send_text(
        protocol.ws_message(protocol.WS_HELLO, you=slot, machines=machines, version=__version__)
    )

    try:
        while True:
            raw = await ws.receive_text()
            if not raw:
                continue
            try:
                import json

                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == protocol.WS_PING:
                await ws.send_text(protocol.ws_message(protocol.WS_PONG))
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.debug("WS error for slot %d: %s", slot, exc)
    finally:
        now_offline = await HUB.disconnect(slot, ws)
        if now_offline:
            await HUB.announce_presence(slot, False)


# --------------------------------------------------------------------------- #
# Admin REST API (protected by X-Admin-Key)
# --------------------------------------------------------------------------- #
@app.get("/api/admin/machines")
def admin_list_machines(_: None = Depends(auth_admin)):
    machines = []
    for m in STORE.list_machines():
        machines.append(
            {
                "slot": m["id"],
                "name": m["name"],
                "enabled": bool(m["enabled"]),
                "created_at": m["created_at"],
                "last_seen": m["last_seen"],
            }
        )
    return {"machines": machines}


@app.post("/api/admin/machines")
async def admin_add_machine(request: Request, _: None = Depends(auth_admin)):
    body = await request.json()
    slot = body.get("slot")
    name = body.get("name")
    if not protocol.valid_slot(slot):
        raise HTTPException(status_code=400, detail="slot must be 1..255")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        token = STORE.add_machine(int(slot), str(name))
    except StorageError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "slot": slot,
        "name": name,
        "token": token,
        "bearer": authmod.make_bearer(int(slot), token),
    }


@app.post("/api/admin/machines/{slot}/rotate")
def admin_rotate(slot: int, _: None = Depends(auth_admin)):
    try:
        token = STORE.rotate_token(slot)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"slot": slot, "token": token, "bearer": authmod.make_bearer(slot, token)}


@app.post("/api/admin/machines/{slot}/enabled")
async def admin_set_enabled(slot: int, request: Request, _: None = Depends(auth_admin)):
    body = await request.json()
    enabled = bool(body.get("enabled", True))
    try:
        STORE.set_enabled(slot, enabled)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"slot": slot, "enabled": enabled}


@app.delete("/api/admin/machines/{slot}")
def admin_delete(slot: int, _: None = Depends(auth_admin)):
    STORE.delete_machine(slot)
    return {"ok": True, "slot": slot}


# Friendly JSON for uncaught storage errors.
@app.exception_handler(StorageError)
async def _storage_error_handler(_request: Request, exc: StorageError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})
