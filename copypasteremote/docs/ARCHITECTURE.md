# CopyPasteRemote — Arquitectura

## 1. Vista de componentes

```
┌──────────────────────────────┐         ┌──────────────────────────────┐
│        Cliente (Win A)        │         │        Cliente (Win B)        │
│                               │         │                               │
│  Atajos ─► Agente ─► Cripto   │  HTTPS  │   Cripto ◄─ Agente ◄─ Atajos  │
│   Bandeja   │        │        │  + WSS  │     │        │       Bandeja  │
│  Portapapeles(Win32) │        │◄───────►│     │  Portapapeles(Win32)    │
└──────────────────────┼───────┘         └─────┼────────────────────────┘
                       │                        │
                       ▼                        ▼
              ┌──────────────────────────────────────────┐
              │        Orquestador (VM cloud privado)     │
              │  FastAPI: REST + WebSocket (presencia)    │
              │  Registro del pool (SQLite)               │
              │  Buzones (1 contenido cifrado por slot)   │
              │  Blobs de archivos en disco               │
              └──────────────────────────────────────────┘
```

- **`cpr_shared`**: criptografía y protocolo, idénticos en ambos lados.
- **`cpr_server`**: API, persistencia, presencia, mantenimiento, CLI admin.
- **`cpr_client`**: portapapeles, serialización, transporte, agente, atajos, bandeja.

## 2. Topología de red (DD-WRT + ESXi)

```
                 Internet
                    │
                    │  IP pública fija (WAN)
            ┌───────▼────────┐
            │     DD-WRT      │   Port-forward 8765/tcp ─► VM
            └───────┬────────┘   (o 443 si terminas TLS en el router)
                    │ LAN
            ┌───────▼─────────────────────────┐
            │   ESXi (cloud privado)          │
            │   ┌───────────────────────────┐ │
            │   │  VM Orquestador            │ │
            │   │  CopyPasteRemote server    │ │
            │   │  :8765 (HTTPS/WSS)         │ │
            │   └───────────────────────────┘ │
            └─────────────────────────────────┘

   Clientes (cualquier red con salida a Internet)
   Win A ───────────────► https://IP_PUBLICA:8765 ◄─────────────── Win B
```

- El **director de orquesta** es la VM con la IP pública del cloud privado, expuesta
  a través del DD-WRT mediante *port-forwarding*.
- Los clientes solo necesitan **salida HTTPS** hacia esa IP/puerto. No hace falta
  abrir puertos en las redes de los clientes ni VPN.

## 3. Secuencia — Enviar (push)

```
Usuario(Win A)        Agente A            Servidor            (Win B)
     │  Ctrl+Alt+2        │                   │                  │
     ├───────────────────►│                   │                  │
     │             (Ctrl+C auto)              │                  │
     │             lee portapapeles           │                  │
     │             serializa (ZIP si archivos)│                  │
     │             cifra (AES-256-GCM)        │                  │
     │                    │ ¿ciphertext≤64KiB?│                  │
     │                    │   sí → inline      │                  │
     │                    │   no → POST /blobs, PUT chunks, complete
     │                    ├──POST /api/clip/2 (Envelope)─────────►│
     │                    │                   │ guarda en buzón 2 │
     │                    │                   │ WS: "clip" ──────►│ (prefetch)
     │             notificación "Enviado"     │                  │
```

## 4. Secuencia — Pegar (pull)

```
Usuario(Win B)        Agente B            Servidor
     │  Ctrl+Shift+2      │                   │
     ├───────────────────►│                   │
     │            ¿prefetch en caché? ─ sí ─► usa caché
     │                    │ no → GET /api/clip/2
     │                    ├──────────────────►│ devuelve Envelope (+inline o blob_id)
     │                    │ inline → base64    │
     │                    │ blob   → GET /api/blobs/{id} (Range/reanudable)
     │             descifra (AES-256-GCM)     │
     │             verifica SHA-256           │
     │             si archivos: descomprime ZIP, construye CF_HDROP
     │             escribe portapapeles local │
     │             (Ctrl+V auto)              │
     │◄───────── contenido pegado ────────────┤
```

## 5. Modelo de datos (servidor)

```
machines(id PK, name, token_hash, enabled, created_at, last_seen)
slots(id PK = machine id, envelope_json, inline_blob, blob_id,
      kind, size, sha256, from_id, updated_at)
blobs(id PK, path, size, sha256, complete, created_at, ref_slot)
meta(key PK, value)         # admin_api_key, pool_key_fp, ...
```

- Un **buzón** (`slots`) referencia contenido **inline** (pequeño) o un **blob**
  (grande). Al sobrescribir un buzón se libera el blob anterior (GC).
- Los **blobs huérfanos** (subidas a medias) se purgan tras un tiempo.

## 6. Concurrencia

- **Servidor**: endpoints síncronos ejecutados en el *threadpool* de FastAPI;
  acceso a SQLite serializado con un cerrojo. El WebSocket es asíncrono.
- **Cliente**: el hook de teclado solo **encola**; un único *worker* ejecuta las
  operaciones de red de una en una (evita choques de portapapeles). El WebSocket y
  las acciones de bandeja corren en hilos propios.

## 7. Seguridad (capas)

1. **Transporte**: TLS (HTTPS/WSS).
2. **Autenticación**: `Bearer <slot>.<token>` por máquina (token *hasheado* en BD).
3. **Contenido**: AES-256-GCM con clave de pool; el servidor solo ve *ciphertext*.
4. **Integridad**: SHA-256 del contenido en claro verificado en destino; GCM autentica
   cada bloque.
5. **Ciclo de vida**: expiración de buzones (24 h por defecto) y GC de blobs.

## 8. Por qué el cliente NO es un servicio de Windows

El portapapeles, el envío de `Ctrl+V` y la bandeja del sistema requieren una
**sesión interactiva de usuario**. Un servicio en *sesión 0* no tiene acceso fiable a
ellos. Por eso el cliente se ejecuta al **iniciar sesión** (Tarea Programada o carpeta
de Inicio). El **servidor**, en cambio, sí es un servicio (systemd/Docker/NSSM).
