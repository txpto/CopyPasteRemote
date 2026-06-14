"""The client engine: ties clipboard <-> crypto <-> transport together.

``Agent.push(slot)`` captures the local clipboard, encrypts it and drops it into a
remote mailbox.  ``Agent.pull(slot)`` fetches a mailbox, decrypts it, restores it
to the local clipboard and (optionally) pastes.

The clipboard is accessed through a small :class:`ClipboardBackend` interface so
the whole engine is testable on any OS with a fake backend.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import tempfile
import threading
import time
from typing import List, Optional

from cpr_shared import crypto, protocol
from cpr_shared.protocol import Envelope

from . import serializer
from .clipdata import ClipData
from .config import ClientConfig
from .transport import RestClient, WsClient

log = logging.getLogger("cpr.client.agent")


# --------------------------------------------------------------------------- #
# Clipboard backend interface
# --------------------------------------------------------------------------- #
class ClipboardBackend:
    """Abstract local-clipboard access. The Windows implementation lives in
    :mod:`cpr_client.clipboard_win`."""

    def read(self) -> Optional[ClipData]:  # pragma: no cover - interface
        raise NotImplementedError

    def write(self, clip: ClipData) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def simulate_copy(self) -> None:
        """Optionally press Ctrl+C to capture the current selection."""

    def simulate_paste(self) -> None:
        """Optionally press Ctrl+V to paste what we just put on the clipboard."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class _HashingReader:
    """Wrap a binary stream and SHA-256 everything that is read through it."""

    def __init__(self, fh):
        self._fh = fh
        self._h = hashlib.sha256()

    def read(self, n: int = -1) -> bytes:
        data = self._fh.read(n)
        if data:
            self._h.update(data)
        return data

    def hexdigest(self) -> str:
        return self._h.hexdigest()

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class AgentError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #
class Agent:
    def __init__(self, config: ClientConfig, clipboard: ClipboardBackend, events=None):
        config.validate()
        self.config = config
        self.clipboard = clipboard
        self.events = events or AgentEvents()
        self.key = crypto.key_from_b64(config.pool_key)
        self.rest = RestClient(
            base_url=config.server_url,
            slot=int(config.machine_id),
            token=config.token,
            verify_tls=config.verify_tls,
            ca_cert=config.ca_cert,
        )
        self.ws: Optional[WsClient] = None
        self.temp_dir = self._init_temp_dir()
        self._materialised: List[tuple] = []  # (path, created_at)
        self._lock = threading.Lock()
        self._prefetched = {}  # slot -> (envelope, plaintext path/bytes)

    def _init_temp_dir(self) -> str:
        base = self.config.temp_dir or os.path.join(tempfile.gettempdir(), "CopyPasteRemote")
        os.makedirs(base, exist_ok=True)
        return base

    # -- lifecycle ----------------------------------------------------------
    def connect_ws(self) -> None:
        self.ws = WsClient(
            base_url=self.config.server_url,
            slot=int(self.config.machine_id),
            token=self.config.token,
            verify_tls=self.config.verify_tls,
            ca_cert=self.config.ca_cert,
            reconnect_seconds=self.config.reconnect_seconds,
        )
        self.ws.on_hello = self.events.on_hello
        self.ws.on_presence = self.events.on_presence
        self.ws.on_state = self.events.on_connection
        self.ws.on_clip = self._on_clip_notification
        self.ws.start()

    def close(self) -> None:
        if self.ws:
            self.ws.stop()
        self.cleanup_all_temp()

    def check_server(self) -> dict:
        info = self.rest.info()
        ours = crypto.key_fingerprint(self.key)
        theirs = info.get("pool_key_fp")
        if theirs and theirs != ours:
            log.warning(
                "Pool key fingerprint mismatch (server=%s, local=%s); peers will "
                "not be able to decrypt your clips.", theirs, ours
            )
        return info

    # -- push ---------------------------------------------------------------
    def push(self, slot: int) -> Envelope:
        """Capture the local clipboard and send it to mailbox ``slot``."""
        if self.config.copy_before_send:
            try:
                self.clipboard.simulate_copy()
                time.sleep(0.12)  # let the foreground app populate the clipboard
            except Exception as exc:  # noqa: BLE001
                log.debug("simulate_copy failed: %s", exc)

        clip = self.clipboard.read()
        if clip is None or clip.kind == protocol.KIND_EMPTY:
            self.events.on_error("Nothing to copy (clipboard is empty)")
            raise AgentError("Clipboard is empty")

        ser = serializer.serialize(clip, self.key, self.temp_dir)
        env = ser.envelope

        ct_fd, ct_path = tempfile.mkstemp(suffix=".enc", prefix="cpr_ct_", dir=self.temp_dir)
        os.close(ct_fd)
        try:
            reader = _HashingReader(ser.source.open())
            with open(ct_path, "wb") as out:
                crypto.encrypt_stream(self.key, reader, out)
            reader.close()
            env.sha256 = reader.hexdigest()
            env.enc_size = os.path.getsize(ct_path)

            if env.enc_size <= protocol.INLINE_THRESHOLD:
                with open(ct_path, "rb") as fh:
                    env.inline = True
                    env.data_b64 = base64.b64encode(fh.read()).decode("ascii")
                    env.blob_id = None
            else:
                with open(ct_path, "rb") as fh:
                    blob_id = self.rest.upload_blob(
                        fh,
                        chunk_size=4 * 1024 * 1024,
                        progress=lambda done: self.events.on_progress("upload", done, env.enc_size),
                    )
                env.inline = False
                env.blob_id = blob_id
                env.data_b64 = None

            self.rest.push_envelope(slot, env.to_dict())
            self.events.on_pushed(slot, env)
            log.info("Pushed %s to slot %d", env.human_summary(), slot)
            return env
        finally:
            serializer.FileSource(ct_path).cleanup()
            ser.source.cleanup()

    # -- pull ---------------------------------------------------------------
    def pull(self, slot: int, auto_paste: Optional[bool] = None) -> ClipData:
        """Fetch mailbox ``slot`` into the local clipboard (and optionally paste)."""
        prefetched = self._prefetched.pop(slot, None)
        if prefetched and prefetched[0] is not None:
            env, clip = prefetched
        else:
            env_dict = self.rest.pull_envelope(slot)
            env = Envelope.from_dict(env_dict)
            clip = self._materialise(env)

        if env.key_fp and env.key_fp != crypto.key_fingerprint(self.key):
            self.events.on_error("Decryption key mismatch; cannot read this clip")
            raise AgentError("Pool key mismatch")

        self.clipboard.write(clip)
        do_paste = self.config.auto_paste if auto_paste is None else auto_paste
        if do_paste:
            time.sleep(0.05)
            try:
                self.clipboard.simulate_paste()
            except Exception as exc:  # noqa: BLE001
                log.debug("simulate_paste failed: %s", exc)

        self.events.on_pulled(slot, env)
        log.info("Pulled %s from slot %d", env.human_summary(), slot)
        self._gc_temp()
        return clip

    def pull_own(self, auto_paste: Optional[bool] = None) -> ClipData:
        return self.pull(int(self.config.machine_id), auto_paste=auto_paste)

    def _materialise(self, env: Envelope) -> ClipData:
        """Decrypt an envelope's payload and turn it into ClipData."""
        is_files = env.kind == protocol.KIND_FILES

        # Obtain the ciphertext as a readable stream.
        if env.inline:
            if not env.data_b64:
                raise AgentError("Server returned an inline clip without data")
            ct_stream = io.BytesIO(base64.b64decode(env.data_b64))
            ct_path = None
        else:
            if not env.blob_id:
                raise AgentError("Server returned a clip without inline data or blob")
            ct_fd, ct_path = tempfile.mkstemp(suffix=".enc", prefix="cpr_dl_", dir=self.temp_dir)
            os.close(ct_fd)
            self.rest.download_blob(
                env.blob_id,
                ct_path,
                progress=lambda done: self.events.on_progress("download", done, env.enc_size),
            )
            ct_stream = open(ct_path, "rb")

        try:
            if is_files:
                pt_fd, pt_path = tempfile.mkstemp(suffix=".zip", prefix="cpr_pt_", dir=self.temp_dir)
                with os.fdopen(pt_fd, "wb") as out:
                    crypto.decrypt_stream(self.key, ct_stream, out)
                if env.sha256 and _sha256_file(pt_path) != env.sha256:
                    serializer.FileSource(pt_path).cleanup()
                    raise AgentError("Integrity check failed (files)")
                result = serializer.deserialize(env, path=pt_path, temp_dir=self.temp_dir)
            else:
                buf = io.BytesIO()
                crypto.decrypt_stream(self.key, ct_stream, buf)
                data = buf.getvalue()
                if env.sha256 and hashlib.sha256(data).hexdigest() != env.sha256:
                    raise AgentError("Integrity check failed")
                result = serializer.deserialize(env, data=data, temp_dir=self.temp_dir)
        finally:
            try:
                ct_stream.close()
            except Exception:
                pass
            if ct_path:
                serializer.FileSource(ct_path).cleanup()

        for path in result.materialised:
            self._materialised.append((path, time.time()))
        return result.clip

    # -- prefetch via WS ----------------------------------------------------
    def _on_clip_notification(self, slot: int, info: dict) -> None:
        self.events.on_clip_available(slot, info)
        if self.config.prefetch and slot == int(self.config.machine_id):
            try:
                env_dict = self.rest.pull_envelope(slot)
                env = Envelope.from_dict(env_dict)
                clip = self._materialise(env)
                self._prefetched[slot] = (env, clip)
                log.debug("Prefetched clip for slot %d", slot)
            except Exception as exc:  # noqa: BLE001
                log.debug("Prefetch failed: %s", exc)

    # -- pool ---------------------------------------------------------------
    def get_pool(self) -> dict:
        return self.rest.get_pool()

    def clear(self, slot: int) -> None:
        self.rest.clear(slot)

    # -- temp file housekeeping --------------------------------------------
    def _gc_temp(self, max_age_seconds: int = 3600) -> None:
        cutoff = time.time() - max_age_seconds
        keep = []
        for path, created in self._materialised:
            if created < cutoff:
                _rmtree_safe(path)
            else:
                keep.append((path, created))
        self._materialised = keep

    def cleanup_all_temp(self) -> None:
        for path, _ in self._materialised:
            _rmtree_safe(path)
        self._materialised = []


def _rmtree_safe(path: str) -> None:
    import shutil

    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Event callbacks (overridden by the UI / tray)
# --------------------------------------------------------------------------- #
class AgentEvents:
    """Default no-op event sink. The tray/UI subclasses this."""

    def on_hello(self, machines: list) -> None: ...
    def on_presence(self, slot: int, online: bool) -> None: ...
    def on_connection(self, connected: bool) -> None: ...
    def on_clip_available(self, slot: int, info: dict) -> None: ...
    def on_pushed(self, slot: int, env: Envelope) -> None: ...
    def on_pulled(self, slot: int, env: Envelope) -> None: ...
    def on_progress(self, direction: str, done: int, total: int) -> None: ...
    def on_error(self, message: str) -> None:
        log.error(message)
