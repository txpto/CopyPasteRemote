# Guía de despliegue

Autohospedar CopyPasteRemote: un **servidor** (orquestador) y los **clientes** que
necesites. Esta guía usa marcadores de posición — sustitúyelos por tus valores. Aquí no se
guardan claves, certificados ni secretos: cada secreto se genera en el momento del
despliegue, en tus propias máquinas.

> Marcadores: `<HOST_PUBLICO>` (IP pública o dominio del servidor), `<IP_LAN_SERVIDOR>`
> (dirección del servidor en su LAN), `<IP_LAN_ROUTER>`, `<IP_CLIENTE>`.

## Arquitectura

```
                Internet
                   │
            <HOST_PUBLICO>
                   │
            ┌──────────────┐
            │  Router/NAT   │   reenvía TCP 8765 → <IP_LAN_SERVIDOR>
            └──────┬───────┘
                   │ LAN del servidor
            ┌──────────────┐
            │  SERVIDOR     │  run_server.py
            │               │  público : 0.0.0.0:8765   (API de sync + WebSocket)
            │               │  admin   : 127.0.0.1:8766 (dashboard, solo loopback)
            └──────────────┘

   clientes (cualquier red, solo conexiones salientes):
     cliente #1  → slot 1
     cliente #2  → slot 2
```

- **Un único puerto público: TCP 8765.** La API REST y el WebSocket lo comparten.
- **El dashboard y `/api/admin/*` NO están en el puerto público.** Se sirven en
  `127.0.0.1:8766` y solo son accesibles desde la propia máquina del servidor
  (`http://127.0.0.1:8766/dashboard`). Configurable con `admin_host`/`admin_port`
  (entorno `CPR_ADMIN_HOST`/`CPR_ADMIN_PORT`).
- **Los clientes nunca necesitan abrir un puerto** — solo hacen conexiones salientes.

## Modelo de seguridad (resumen)

- Los contenidos del portapapeles se cifran **de extremo a extremo con AES-256-GCM** usando
  una *pool key* compartida de 256 bits. El servidor solo almacena texto cifrado.
- Las máquinas se autentican con un token bearer por máquina (`Bearer <slot>.<token>`); los
  tokens se guardan hasheados. Los endpoints de admin usan una cabecera `X-Admin-Key` aparte.
- Los fallos de autenticación tienen límite de tasa por IP. Los payloads tienen tope de
  tamaño. Las ACL por buzón y el aislamiento por *pool* restringen quién puede enviar/recibir.
- **Activa TLS** antes de exponer el puerto público a Internet (sin él, los tokens y la
  metadata viajan en claro; los payloads siguen cifrados E2E, pero el canal no).
- El servidor puede funcionar en modo **zero-knowledge**: mantén `pool_key_b64` fuera de la
  configuración del servidor para que un compromiso del servidor no pueda descifrar nada. La
  pool key solo se necesita de forma transitoria para emitir los configs de cliente (ver
  `04-harden-remove-poolkey.ps1`).

## Requisitos previos

- **Servidor**: Python 3.10+ y Git. Los ejemplos de Windows usan [NSSM](https://nssm.cc/)
  para el servicio. (En Linux, una unidad systemd sirve igual.)
- **Clientes (Windows)**: Python 3.10+ — o **Python 3.8.10** en Windows 7 x64 (la última
  versión compatible; las dependencias del cliente están fijadas para él).

## Pasos

### 1. Servidor

```powershell
# como Administrador
.\server\01-setup-server.ps1 -PublicHost "<HOST_PUBLICO>"   # repo + venv + deps + claves + máquinas + firewall
.\server\02-install-service.ps1                             # instalar como servicio de Windows (NSSM)
.\server\03-enable-tls.ps1   -PublicHost "<HOST_PUBLICO>"   # opcional pero recomendado: TLS autofirmado
# ...registra tus máquinas, copia los configs de cliente generados (y cert.pem si usas TLS)...
.\server\04-harden-remove-poolkey.ps1                       # opcional: quitar la pool key (zero-knowledge)
```

`01-setup-server.ps1` registra dos máquinas y escribe ficheros de configuración de cliente
listos para usar (uno por máquina). Copia cada uno a su cliente. Con TLS, copia también
`cert.pem`.

### 2. Router / NAT

Reenvía **TCP 8765 → `<IP_LAN_SERVIDOR>`:8765**. **No** reenvíes el puerto de admin (8766):
se queda en loopback. Verifica desde fuera: `Test-NetConnection <HOST_PUBLICO> -Port 8765`.

> ¿Prefieres no exponer el puerto? Pon el servidor detrás de una **VPN/WireGuard** y olvídate
> del NAT. Si lo expones y tus clientes tienen IP fija, **filtra por IP origen** el reenvío.

### 3. Clientes

Windows 10/11:
```powershell
.\client\setup-client.ps1 -PkgDir "<ruta>\copypasteremote" `
  -ConfigSource "<ruta>\client-config.json" -CaCert "<ruta>\cert.pem"   # omite -CaCert si no usas TLS
```
Windows 7 x64 (instala antes Python 3.8.10):
```bat
client\setup-client-win7.bat "<ruta>\client-config.json" "<ruta>\cert.pem"   REM 2º arg opcional
```
Después, arranca el cliente de bandeja (como Administrador, para que funcionen los hotkeys
globales): `python run_client.py`.

**Arranque automático al iniciar sesión (autostart):**
```powershell
# Windows 10/11 — tarea de logon elevada (recomendado para los hotkeys globales):
.\client\autostart-client.ps1 -PkgDir "<ruta>\copypasteremote" -Elevated
#   ...o un acceso directo en la carpeta Inicio (sin elevación): omite -Elevated.
```
```bat
REM Windows 7 (ejecútalo desde un CMD elevado):
client\autostart-client-win7.bat
```
Ambos registran una tarea de logon `CopyPasteRemote Client` que ejecuta `pythonw.exe` (sin
consola). Quítala con `schtasks /Delete /TN "CopyPasteRemote Client" /F`.

### 4. Verificación

- En la máquina del servidor, abre `http://127.0.0.1:8766/dashboard` (con la admin key) —
  tus clientes deberían aparecer **online**.
- Copia en un cliente, envía con `Ctrl+Alt+<slot>`, recoge en el destino con
  `Ctrl+Shift+<slot>`.

Consulta los scripts en `server/` y `client/` para los comandos exactos.
