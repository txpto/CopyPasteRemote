# CopyPasteRemote — Plan de implementación (Python)

> Plan técnico de construcción. El estado refleja lo entregado en la versión 1.0.

## 1. Estrategia general

- **Lenguaje**: Python 3.8 (cliente, por compatibilidad con Windows 7) y 3.8+ (servidor).
- **Una sola base de código** con tres paquetes: `cpr_shared`, `cpr_server`, `cpr_client`.
- **Núcleo desacoplado de Windows**: la lógica (cifrado, serialización, empaquetado,
  transporte, agente) se prueba en cualquier SO; solo 3 módulos tocan Win32 y se
  importan de forma perezosa.
- **Pruebas primero en lo testeable**: criptografía, protocolo, empaquetado, servidor
  (con `TestClient`) e **integración extremo a extremo** (servidor real + 2 agentes con
  portapapeles simulado).

## 2. Pila tecnológica

| Componente | Tecnología | Motivo |
|------------|-----------|--------|
| Servidor HTTP/WS | **FastAPI + Uvicorn** | REST + WebSocket + validación, simple y robusto. |
| Persistencia | **SQLite** (stdlib) + ficheros para *blobs* | Cero dependencias extra, suficiente para la escala. |
| Criptografía | **AES-256-GCM** vía `cryptography` o `pycryptodome` | Doble *backend* compatible byte a byte; `pycryptodome` instala fácil en Win7. |
| Cliente HTTP | **requests** (+ `urllib3<2`) | Síncrono, estable en Windows antiguo. |
| Cliente WS | **websocket-client** | Hilo en segundo plano con reconexión. |
| Portapapeles | **pywin32** (+ `ctypes`) | Acceso a `CF_UNICODETEXT`, `CF_HDROP`, `CF_DIB`, HTML. |
| Atajos globales | **keyboard** | Combinaciones/acordes configurables, Python puro. |
| Bandeja | **pystray + Pillow** | Icono y menú multiplataforma, compatible Win7. |
| Empaquetado cliente | **PyInstaller** | `.exe` autónomo para Windows. |

## 3. Estructura del repositorio

```
CopyPasteRemote/
├── cpr_shared/            # Librería común (idéntica en cliente y servidor)
│   ├── version.py         # Versión de app y de protocolo
│   ├── crypto.py          # AES-256-GCM (doble backend) + KDF + huellas
│   └── protocol.py        # Envelope, tipos, mensajes WS (solo stdlib)
├── cpr_server/            # Orquestador
│   ├── config.py          # Config por env + JSON
│   ├── storage.py         # SQLite (máquinas, slots) + blobs en disco
│   ├── auth.py            # Bearer por máquina + clave admin
│   ├── presence.py        # Hub WebSocket (presencia/notificaciones)
│   ├── activity.py        # Registro de actividad (para el dashboard)
│   ├── dashboard.py       # UI web de administración (HTML/JS autónomo)
│   ├── winservice.py      # Servicio de Windows del servidor (pywin32)
│   ├── main.py            # App FastAPI (REST + WS + dashboard + mantenimiento)
│   └── admin_cli.py       # Alta/baja de máquinas, generación de configs
├── cpr_client/            # Agente Windows
│   ├── config.py          # Config del cliente + atajos por defecto
│   ├── packaging.py       # ZIP de archivos/carpetas (multiplataforma)
│   ├── clipdata.py        # Estructura ClipData (neutra)
│   ├── serializer.py      # ClipData ⇄ (Envelope + plaintext)
│   ├── transport.py       # REST + WS (blobs por chunks, reanudación)
│   ├── agent.py           # Motor push/pull (cifrado, integridad, prefetch)
│   ├── clipboard_win.py   # Backend Win32 (texto/archivos/imagen/HTML)
│   ├── hotkeys.py         # Atajos globales + worker serializado
│   ├── tray.py            # Icono y menú de bandeja
│   ├── winservice.py      # Servicio lanzador de Windows (corre la GUI en la sesión)
│   └── main.py            # Punto de entrada (tray / headless / check / setup)
├── run_server.py          # Lanzador del servidor
├── run_client.py          # Lanzador del cliente
├── tests/                 # Pytest (unit + integración E2E)
├── scripts/               # Despliegue (systemd, Docker, tarea programada, build exe)
├── docs/                  # Especificación, plan, arquitectura, manuales
├── requirements-server.txt
└── requirements-client.txt
```

## 4. Fases y entregables

### Fase 0 — Andamiaje y librería compartida  ✅
- `version.py`, `crypto.py` (AES-GCM, KDF, streaming, huellas), `protocol.py` (Envelope).
- **Pruebas**: `test_crypto.py`, `test_protocol.py`.

### Fase 1 — Orquestador (servidor)  ✅
- Config, almacenamiento SQLite + blobs, autenticación, hub de presencia.
- API REST completa + WebSocket + bucle de mantenimiento (expiración/GC).
- CLI de administración (`init`, `add-machine`, `list`, `rotate`, `enable`, `remove`).
- **Pruebas**: `test_server.py` (TestClient): salud, auth, pool, push/pull inline,
  blobs (subida/descarga/rango), límites y errores.

### Fase 2 — Núcleo del cliente (sin Windows)  ✅
- `packaging` (ZIP), `clipdata`, `serializer`, `transport` (REST+WS+blobs), `agent`.
- Decisión **inline vs blob**, integridad SHA-256, *prefetch* por WebSocket.
- **Pruebas**: `test_packaging.py`, `test_integration.py` (servidor real + 2 agentes:
  texto, texto grande, archivos/carpetas, archivo grande, clave incorrecta).

### Fase 3 — Integración Windows  ✅ (código completo; verificación manual en Windows)
- `clipboard_win` (Win32: `CF_UNICODETEXT`, `CF_HDROP` con `DROPFILES`, `CF_DIB`, HTML).
- `hotkeys` (atajos globales con cola de trabajo) y `tray` (bandeja + notificaciones).
- `main` del cliente: modos *tray*, *headless*, `--check`, `--setup`.

### Fase 4 — Empaquetado y despliegue  ✅
- `requirements-*.txt` con versiones fijadas para Win7.
- `scripts/`: unidad **systemd** y **Docker** para el servidor; **Tarea Programada**
  (PowerShell) y **PyInstaller** (`.spec` + `.bat`) para el cliente.
- Generación de certificado autofirmado de ejemplo.

### Fase 5 — Documentación  ✅
- `SPECIFICATION.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`,
  `INSTALL.md` (servidor + cliente + DD-WRT/ESXi), `USER_GUIDE.md`.

### Fase 6 — Dashboard y servicios de Windows  ✅
- **Dashboard** web (`dashboard.py` + `activity.py` + endpoints `/api/admin/overview`
  y `/api/admin/activity`): máquinas conectadas, contenido compartido (origen →
  destino), actividad y estado del servicio. **Pruebas**: `test_dashboard.py`.
- **Servicios de Windows**: `cpr_server.winservice` (orquestador como servicio
  auto-arrancable) y `cpr_client.winservice` (servicio lanzador que arranca la GUI
  del cliente en la sesión interactiva). Instaladores PowerShell en `scripts/`.

## 5. Decisiones de diseño clave

1. **Push/pull explícito** (no sincronización automática): coincide con el modelo
   mental "envío al buzón N / pego del buzón N" y evita fugas accidentales.
2. **Cifrado en cliente** con clave de pool: el servidor es (opcionalmente) de
   *conocimiento cero* respecto al contenido.
3. **Doble backend criptográfico con formato idéntico**: desacopla la
   compatibilidad de Win7 de la elección de librería.
4. **Streaming + chunks + reanudación**: soporta archivos de varios GB sin agotar memoria.
5. **`slot` = nº de máquina = nº de buzón**: simplicidad y mapeo directo a atajos.
6. **El cliente corre en sesión de usuario** (no como servicio en sesión 0): es
   imprescindible para acceder al portapapeles, enviar `Ctrl+V` y mostrar bandeja.
7. **Backend de portapapeles inyectable**: permite pruebas E2E sin Windows.

## 6. Estrategia de pruebas

| Nivel | Qué cubre | Dónde |
|-------|-----------|-------|
| Unidad | Cripto (roundtrip, manipulación, AAD, streaming), protocolo, empaquetado (incl. *Zip-Slip*). | `test_crypto/protocol/packaging` |
| Servicio | Endpoints REST con `TestClient`, auth, blobs, rangos, errores. | `test_server` |
| Integración | Servidor Uvicorn real + 2 agentes: texto/archivos/grandes/clave incorrecta. | `test_integration` |
| Manual (Windows) | Atajos, `CF_HDROP`, pegado real, bandeja, arranque al inicio. | `INSTALL.md` §verificación |

Ejecutar: `pip install -r requirements-server.txt requests websocket-client pytest && pytest -q`.

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|-----------|
| Dependencias que rompen Win7 | Versiones fijadas + doble backend cripto + `urllib3<2`. |
| Certificados Let's Encrypt en Win7 | Documentar CA raíz ISRG X1 o usar certificado propio "fijado". |
| Portapapeles ocupado por otra app | Reintentos al abrir el portapapeles. |
| Pegado en apps elevadas (UAC) | Documentar ejecución del cliente con privilegios equivalentes. |
| Archivos enormes | Límite configurable + streaming + reanudación de descargas. |
| Pérdida de credenciales | Rotación de tokens (`admin_cli rotate`) y revocación (`enable --disable`). |

## 8. Hoja de ruta — implementada ✅

Todos los puntos previstos post-1.0 están implementados:

- ✅ **Clientes Linux/macOS**: backend `clipboard_posix` (texto en ambos; archivos
  vía `text/uri-list` en Linux y AppleScript en macOS; imagen best-effort). Selección
  automática de backend por SO en `cpr_client.main`.
- ✅ **Historial de portapapeles y "fijar"**: tabla `history` (últimos N por buzón +
  fijados que no expiran), endpoints `GET /api/clip/{slot}/history`,
  `GET .../history/{id}`, `POST .../history/{id}/pin`; GC de blobs por referencias;
  submenú "History" en la bandeja. **Pruebas**: `test_roadmap.py`.
- ✅ **Multi-pool y ACLs por buzón**: columna `pool` (las máquinas solo ven su pool;
  push/pull y presencia restringidos al pool) y `acl_push`/`acl_pull` por buzón;
  CLI `add-machine --pool`, `set-pool`, `set-acl`. **Pruebas**: `test_roadmap.py`.
- ✅ **Asistente gráfico de alta**: `cpr_client.wizard` (Tkinter) con prueba de
  conexión; `run_client.py --wizard` y auto-oferta cuando la config es inválida.
- ✅ **Sincronización automática (modo "seguir")**: `auto_apply_incoming` aplica al
  portapapeles local el contenido que llega a tu buzón, vía notificación WebSocket.
- ✅ **Sincronización bidireccional continua**: monitor del portapapeles local
  (`sync.py`; nº de secuencia en Windows, firma de contenido en Linux/macOS) que
  **auto-empuja** los cambios a los peers (`sync_enabled`/`sync_peers`), con
  **prevención de bucles** (firma + "self-write") y cap de tamaño; conmutable desde la
  bandeja. **Pruebas**: `test_sync.py`.

### Posibles ampliaciones futuras
- Historial con vista previa de contenido en el dashboard.
- ACLs con grupos/roles y federación entre servidores.
