# Deployment guide

Self-hosting CopyPasteRemote: one **server** (orchestrator) and any number of
**clients**. This guide uses placeholders — replace them with your own values.
No keys, certificates or secrets are stored here; every secret is generated at
deploy time on your own machines.

> Placeholders: `<PUBLIC_HOST>` (public IP or domain of the server), `<SERVER_LAN_IP>`
> (the server's address on its LAN), `<ROUTER_LAN_IP>`, `<CLIENT_IP>`.

## Architecture

```
                Internet
                   │
            <PUBLIC_HOST>
                   │
            ┌──────────────┐
            │  Router/NAT   │   forward TCP 8765 → <SERVER_LAN_IP>
            └──────┬───────┘
                   │ server LAN
            ┌──────────────┐
            │  SERVER       │  run_server.py
            │               │  public  : 0.0.0.0:8765   (sync API + WebSocket)
            │               │  admin   : 127.0.0.1:8766 (dashboard, loopback only)
            └──────────────┘

   clients (any network, only outbound connections):
     client #1  → slot 1
     client #2  → slot 2
```

- **Single public port: TCP 8765.** The REST API and the WebSocket share it.
- **The dashboard and `/api/admin/*` are NOT on the public port.** They are served on
  `127.0.0.1:8766` and are only reachable from the server box itself
  (`http://127.0.0.1:8766/dashboard`). Configurable via `admin_host`/`admin_port`
  (env `CPR_ADMIN_HOST`/`CPR_ADMIN_PORT`).
- **Clients never need an open port** — they only make outbound connections.

## Security model (summary)

- Clipboard payloads are encrypted **end-to-end with AES-256-GCM** using a shared
  256-bit *pool key*. The server only ever stores ciphertext.
- Machines authenticate with a per-machine bearer token (`Bearer <slot>.<token>`);
  tokens are stored hashed. Admin endpoints use a separate `X-Admin-Key`.
- Failed auth is rate-limited per IP. Payloads are size-capped. Per-mailbox ACLs and
  pool isolation restrict who can push/pull where.
- **Enable TLS** before exposing the public port to the Internet (without it, tokens and
  metadata travel in clear; the payloads stay E2E-encrypted, but the channel does not).
- The server can run **zero-knowledge**: keep `pool_key_b64` out of the server config so
  a server compromise cannot decrypt anything. The pool key is only needed transiently to
  emit client configs (see `04-harden-remove-poolkey.ps1`).

## Prerequisites

- **Server**: Python 3.10+ and Git. Windows examples use [NSSM](https://nssm.cc/) for the
  service. (Linux: a systemd unit works equally well.)
- **Clients (Windows)**: Python 3.10+ — or **Python 3.8.10** on Windows 7 x64 (the last
  version supporting it; the client dependencies are pinned for it).

## Steps

### 1. Server

```powershell
# as Administrator
.\server\01-setup-server.ps1 -PublicHost "<PUBLIC_HOST>"   # repo + venv + deps + keys + machines + firewall
.\server\02-install-service.ps1                            # install as a Windows service (NSSM)
.\server\03-enable-tls.ps1   -PublicHost "<PUBLIC_HOST>"   # optional but recommended: self-signed TLS
# ...register your machines, copy out the generated client configs (and cert.pem if TLS)...
.\server\04-harden-remove-poolkey.ps1                      # optional: drop the pool key (zero-knowledge)
```

`01-setup-server.ps1` registers two machines and writes ready-to-use client config files
(one per machine). Copy each to its client. With TLS, also copy `cert.pem`.

### 2. Router / NAT

Forward **TCP 8765 → `<SERVER_LAN_IP>`:8765**. Do **not** forward the admin port (8766):
it stays on loopback. Verify from outside: `Test-NetConnection <PUBLIC_HOST> -Port 8765`.

> Prefer not exposing the port at all? Put the server behind a **VPN/WireGuard** and skip
> the NAT entirely. If you do expose it and your clients have static IPs, restrict the
> forward by source IP.

### 3. Clients

Windows 10/11:
```powershell
.\client\setup-client.ps1 -PkgDir "<path-to>\copypasteremote" `
  -ConfigSource "<path>\client-config.json" -CaCert "<path>\cert.pem"   # omit -CaCert if no TLS
```
Windows 7 x64 (install Python 3.8.10 first):
```bat
client\setup-client-win7.bat "<path>\client-config.json" "<path>\cert.pem"   REM 2nd arg optional
```
Then run the tray client (as Administrator, so global hotkeys work):
`python run_client.py`.

### 4. Verify

- On the server box, open `http://127.0.0.1:8766/dashboard` (with the admin key) — your
  clients should appear **online**.
- Copy on one client, push with `Ctrl+Alt+<slot>`, pull on the target with
  `Ctrl+Shift+<slot>`.

See the scripts in `server/` and `client/` for the exact commands.
