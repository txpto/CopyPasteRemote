# CopyPasteRemote

CopyPasteRemote is a Python 3.8-compatible project for a Windows virtual clipboard pool coordinated by a relay server hosted on your private-cloud VM behind DD-WRT/ESXi. It lets registered Windows machines exchange clipboard text, files, folders, and many application-specific clipboard formats over the internet, regardless of whether they are on the same LAN.

> Target clients: Windows 7 x64, Windows 10/11, Windows Server 2016/2022. Use Python 3.8.x on Windows 7.

## Architecture

```text
Windows PC A ──HTTPS──┐
Windows PC B ──HTTPS──┼── CopyPasteRemote Director VM ── local SQLite + blob store
Windows PC C ──HTTPS──┘
```

The Director VM is the single rendezvous point. Clients never need inbound ports; they authenticate to the Director, upload clipboard packages, and download packages produced by other machines in the same pool.

### Main concepts

* **Pool**: trusted group of machines sharing a virtual clipboard.
* **Machine enrollment**: an administrator creates an enrollment code on the Director; the Windows client redeems it once and receives a persistent machine token.
* **Clipboard package**: versioned payload containing text, a zipped file/folder selection, or a generic multi-format clipboard snapshot plus metadata.
* **Slots**: numbered remote clipboards. For example, slot `1` can represent machine/source 1, slot `2` another source, or simply named buffers.

## Technical specification

### Functional requirements

1. Register Windows machines in a named pool before they can exchange clipboard contents.
2. Capture native Windows clipboard content for:
   * Unicode text.
   * Files and folders copied in Explorer (`CF_HDROP`).
   * Generic serializable clipboard formats such as HTML, RTF, PNG/app-specific binary payloads, and other registered formats when Windows exposes them as bytes or strings.
3. Transfer clipboard packages through a public HTTPS endpoint on the Director VM.
4. Restore clipboard content on another Windows client so normal `Ctrl+V` works in target applications.
5. Keep all client connections outbound to support NAT, different networks, and mobile users.
6. Support configurable hotkeys; defaults are intentionally simple:
   * `ctrl+alt+1` / `ctrl+alt+2` / ...: upload local clipboard to that slot.
   * `ctrl+shift+1` / `ctrl+shift+2` / ...: download slot to local Windows clipboard.
7. Provide a command-line fallback for environments where global hotkeys are restricted.

### Non-functional requirements

* Python runtime: Python 3.8 on clients for Windows 7 compatibility.
* Transport: HTTPS strongly recommended; HTTP only for local lab testing.
* Authentication: bearer machine tokens and one-time enrollment codes.
* Storage: SQLite metadata and filesystem blob storage on the Director.
* Maximum upload size: configurable, default 2 GiB.
* Retention: configurable cleanup of expired clipboard packages.
* Auditing: server logs uploads, downloads, enrollment, and machine names.

### Security model

* The Director authorizes every request with a per-machine token.
* Enrollment codes are one-time and expire.
* Pools isolate machines; a token from one pool cannot read another pool.
* Deploy behind TLS on DD-WRT/ESXi using Nginx/Caddy/Traefik or direct TLS termination.
* For highly sensitive use, add end-to-end encryption before production rollout. The current implementation protects traffic in transit with TLS and protects access with tokens, but the Director can read stored plaintext text payloads and zip blobs.

### Network plan for ESXi/DD-WRT

1. Create a Linux VM on ESXi for the Director.
2. Give it a stable private IP, for example `192.168.10.20`.
3. On DD-WRT, forward public TCP `443` to the reverse proxy on the VM.
4. Put the Director service on `127.0.0.1:8080` or `0.0.0.0:8080` inside the VM.
5. Terminate TLS at a reverse proxy and proxy to `http://127.0.0.1:8080`.
6. Clients use `https://your-public-name.example.com` as `server_url`.

## Implementation plan

### Phase 1 - Core protocol and Director

* Build REST API with Flask.
* Persist pools, machines, enrollment codes, and clipboard package metadata in SQLite.
* Store binary blobs under `data/blobs/<pool>/<slot>/<package_id>.zip`.
* Add admin CLI for creating pools and one-time enrollment codes.
* Add package upload, package metadata, and package download endpoints.

### Phase 2 - Windows client

* Add enrollment command that saves machine credentials in `%APPDATA%\\CopyPasteRemote\\config.json`.
* Add upload/download commands for slots.
* Capture text via `pywin32` clipboard APIs.
* Capture Explorer file/folder selections via `CF_HDROP`, zip them, and upload.
* Capture generic serializable clipboard formats as a JSON snapshot so rich content can be moved when both machines have compatible applications.
* Preserve empty directories inside transferred folder trees.
* Restore text to `CF_UNICODETEXT`.
* Restore files/folders by downloading zip to a local cache, extracting it, and setting `CF_HDROP` so Explorer/app paste works like native Windows file copy.
* Restore generic registered clipboard formats by re-registering format names and putting their byte/string payloads back on the Windows clipboard.

### Phase 3 - Hotkeys and service mode

* Add a foreground tray/console daemon using the `keyboard` package.
* Register configurable hotkeys mapped to upload/download slot actions.
* Log status and errors to `%APPDATA%\\CopyPasteRemote\\client.log`.

### Phase 4 - Hardening

* Add TLS-only deployment.
* Add retention cleanup job.
* Add optional end-to-end encryption with pool passphrase and AES-GCM.
* Add MSI/EXE packaging with PyInstaller pinned to Python 3.8-compatible versions.

## Installation

### Director VM

```powershell
# Linux shell shown; PowerShell also works with equivalent commands
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-server.txt
python -m cpr.server init --data-dir ./data --admin-token CHANGE_THIS_LONG_RANDOM_TOKEN
python -m cpr.server create-pool --data-dir ./data --admin-token CHANGE_THIS_LONG_RANDOM_TOKEN --pool oficina
python -m cpr.server enroll-code --data-dir ./data --admin-token CHANGE_THIS_LONG_RANDOM_TOKEN --pool oficina --machine PC-01
python -m cpr.server serve --data-dir ./data --host 0.0.0.0 --port 8080
```

Put the service behind HTTPS. Example Nginx location:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    client_max_body_size 2048m;
}
```

### Windows client

Install Python 3.8.x x64. Then:

```powershell
py -3.8 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-client.txt
python -m cpr.client enroll --server-url https://your-public-name.example.com --code ENROLLMENT_CODE_FROM_SERVER
```

Run hotkey daemon:

```powershell
python -m cpr.client hotkeys
```

Optional command-line operations:

```powershell
python -m cpr.client copy --slot 1
python -m cpr.client paste --slot 1
```

## Usage manual

1. Copy text, files, folders, images, rich text, or application content normally on PC A using Windows Explorer or an application.
2. Press `Ctrl+Alt+1` on PC A to upload the current local clipboard to virtual slot 1.
3. Go to PC B.
4. Press `Ctrl+Shift+1` on PC B to download slot 1 into the local Windows clipboard.
5. Press normal `Ctrl+V` in the destination app/folder. For generic/rich clipboard formats, use the same or a compatible application on the target PC.

Repeat with slot 2, 3, etc. Slots are shared buffers, not hard-coded machine IDs, so you can choose the workflow that best fits your team. The implementation prioritizes native Windows behavior for text and files/folders and adds a best-effort generic snapshot layer for rich/application formats; formats backed by process-local handles, device contexts, or unsupported Windows handles may still need app-specific plugins.

## Repository layout

* `cpr/server.py`: Director API and admin CLI.
* `cpr/client.py`: Windows client CLI and hotkey daemon.
* `cpr/winclip.py`: Windows clipboard integration for text and file/folder selections.
* `cpr/protocol.py`: shared protocol constants and helpers.
* `requirements-server.txt`: Director dependencies.
* `requirements-client.txt`: Windows client dependencies.
