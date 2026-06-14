"""Network transport: REST over HTTPS + a WebSocket presence channel.

Uses ``requests`` (sync, simple, robust on old Windows) and ``websocket-client``.
The blob helpers stream to/from disk so multi-gigabyte file payloads never sit
fully in memory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import ssl
import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse, urlunparse

import requests

from cpr_shared import protocol

log = logging.getLogger("cpr.client.transport")


class TransportError(Exception):
    pass


class RestClient:
    def __init__(
        self,
        base_url: str,
        slot: int,
        token: str,
        verify_tls: bool = True,
        ca_cert: str = "",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.slot = slot
        self.token = token
        self.timeout = timeout
        self._verify: Any = ca_cert if (verify_tls and ca_cert) else verify_tls
        self._session = requests.Session()
        self._session.headers.update({"Authorization": "Bearer %d.%s" % (slot, token)})

    # -- low level ----------------------------------------------------------
    def _url(self, path: str) -> str:
        return self.base_url + path

    def _request(self, method: str, path: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        kw.setdefault("verify", self._verify)
        try:
            resp = self._session.request(method, self._url(path), **kw)
        except requests.RequestException as exc:
            raise TransportError("Network error: %s" % exc) from exc
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise TransportError("HTTP %d: %s" % (resp.status_code, detail))
        return resp

    # -- high level ---------------------------------------------------------
    def info(self) -> Dict[str, Any]:
        return self._request("GET", "/api/info").json()

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/api/health").json()

    def get_pool(self) -> Dict[str, Any]:
        return self._request("GET", "/api/pool").json()

    def push_envelope(self, slot: int, envelope: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/api/clip/%d" % slot, json=envelope).json()

    def pull_envelope(self, slot: int, meta_only: bool = False) -> Dict[str, Any]:
        params = {"meta_only": "true"} if meta_only else None
        return self._request("GET", "/api/clip/%d" % slot, params=params).json()

    def clear(self, slot: int) -> None:
        self._request("DELETE", "/api/clip/%d" % slot)

    # -- history ------------------------------------------------------------
    def get_history(self, slot: int, limit: int = 50) -> Dict[str, Any]:
        return self._request(
            "GET", "/api/clip/%d/history" % slot, params={"limit": limit}
        ).json()

    def get_history_entry(self, slot: int, history_id: int) -> Dict[str, Any]:
        return self._request("GET", "/api/clip/%d/history/%d" % (slot, history_id)).json()

    def pin_history(self, slot: int, history_id: int, pinned: bool = True) -> Dict[str, Any]:
        return self._request(
            "POST", "/api/clip/%d/history/%d/pin" % (slot, history_id), json={"pinned": pinned}
        ).json()

    # -- blobs --------------------------------------------------------------
    def upload_blob(
        self,
        stream,
        chunk_size: int = 4 * 1024 * 1024,
        progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Upload a binary stream as a blob; returns its blob_id.

        Computes the SHA-256 while streaming and finalises with it so the server
        can verify integrity.
        """
        created = self._request("POST", "/api/blobs").json()
        blob_id = created["blob_id"]
        server_chunk = int(created.get("chunk_size", chunk_size)) or chunk_size
        chunk_size = min(chunk_size, server_chunk) or server_chunk

        hasher = hashlib.sha256()
        offset = 0
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
            self._request(
                "PUT",
                "/api/blobs/%s" % blob_id,
                params={"offset": offset},
                data=chunk,
                headers={"Content-Type": "application/octet-stream"},
            )
            offset += len(chunk)
            if progress:
                progress(offset)
        self._request(
            "POST",
            "/api/blobs/%s/complete" % blob_id,
            json={"sha256": hasher.hexdigest()},
        )
        return blob_id

    def download_blob(
        self,
        blob_id: str,
        dest_path: str,
        progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Stream a blob to ``dest_path``, resuming if a partial file exists."""
        resume_from = 0
        if os.path.exists(dest_path):
            resume_from = os.path.getsize(dest_path)
        headers = {}
        mode = "wb"
        if resume_from:
            headers["Range"] = "bytes=%d-" % resume_from
            mode = "ab"
        resp = self._session.get(
            self._url("/api/blobs/%s" % blob_id),
            headers=headers,
            stream=True,
            verify=self._verify,
            timeout=self.timeout,
        )
        if resp.status_code not in (200, 206):
            raise TransportError("HTTP %d downloading blob" % resp.status_code)
        if resume_from and resp.status_code == 200:
            # Server ignored the range; restart from scratch.
            mode = "wb"
            resume_from = 0
        written = resume_from
        with open(dest_path, mode) as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written)
        return dest_path


def to_ws_url(base_url: str) -> str:
    """WebSocket URL WITHOUT credentials (auth goes in the Authorization header,
    so the token never lands in URLs/proxy/access logs)."""
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = (parsed.path or "") + "/api/ws"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


class WsClient:
    """Background WebSocket client with auto-reconnect.

    Callbacks (all optional) are invoked from the WS thread:
      * on_hello(machines)            - initial pool snapshot
      * on_presence(slot, online)     - a peer changed state
      * on_clip(slot, info)           - new content arrived in your mailbox
      * on_state(connected: bool)     - connection up/down
    """

    def __init__(
        self,
        base_url: str,
        slot: int,
        token: str,
        verify_tls: bool = True,
        ca_cert: str = "",
        reconnect_seconds: int = 5,
    ):
        self.url = to_ws_url(base_url)
        self._auth_header = "Authorization: Bearer %d.%s" % (slot, token)
        self.slot = slot
        self.verify_tls = verify_tls
        self.ca_cert = ca_cert
        self.reconnect_seconds = max(1, reconnect_seconds)
        self.on_hello: Optional[Callable[[list], None]] = None
        self.on_presence: Optional[Callable[[int, bool], None]] = None
        self.on_clip: Optional[Callable[[int, dict], None]] = None
        self.on_state: Optional[Callable[[bool], None]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ws = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="cpr-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    def _sslopt(self):
        if not self.verify_tls:
            return {"cert_reqs": ssl.CERT_NONE}
        if self.ca_cert:
            return {"ca_certs": self.ca_cert}
        return None

    def _run_loop(self) -> None:
        import websocket  # websocket-client; imported lazily

        backoff = self.reconnect_seconds
        while not self._stop.is_set():
            try:
                self._ws = websocket.WebSocketApp(
                    self.url,
                    header=[self._auth_header],  # token in header, not in the URL
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_close=self._on_close,
                    on_error=self._on_error,
                )
                self._ws.run_forever(
                    sslopt=self._sslopt(), ping_interval=30, ping_timeout=10
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("WS run error: %s", exc)
            if self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)  # exponential backoff, capped
        if self.on_state:
            self.on_state(False)

    # -- websocket-client callbacks ----------------------------------------
    def _on_open(self, _ws):
        log.info("WebSocket connected")
        if self.on_state:
            self.on_state(True)

    def _on_close(self, _ws, *_args):
        log.info("WebSocket closed")
        if self.on_state:
            self.on_state(False)

    def _on_error(self, _ws, error):
        log.debug("WebSocket error: %s", error)

    def _on_message(self, _ws, message):
        try:
            msg = json.loads(message)
        except Exception:
            return
        mtype = msg.get("type")
        if mtype == protocol.WS_HELLO and self.on_hello:
            self.on_hello(msg.get("machines", []))
        elif mtype == protocol.WS_PRESENCE and self.on_presence:
            self.on_presence(msg.get("slot"), bool(msg.get("online")))
        elif mtype == protocol.WS_CLIP_AVAILABLE and self.on_clip:
            self.on_clip(msg.get("slot"), msg)
