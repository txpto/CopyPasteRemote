# CopyPasteRemote — Especificaciones técnicas del proyecto

> Documento de especificación funcional y técnica. Versión 1.0.

## 1. Resumen ejecutivo

**CopyPasteRemote** permite **copiar y pegar entre ordenadores** aunque estén en
**redes distintas**, en cualquier ubicación física, con el único requisito de que
todas las máquinas tengan **salida a Internet** hacia un servidor central
("director de orquesta").

El portapapeles compartido funciona con **texto, archivos y carpetas**, igual que
el copiar/pegar nativo de Windows, y está pensado inicialmente para clientes
**Windows 7, 10, 11, Server 2016 y Server 2022 (x64)**.

Cada máquina tiene un **buzón** (mailbox) numerado. El usuario:

- **Envía** el contenido de su portapapeles al buzón de otra máquina con un atajo
  de teclado (por defecto `Ctrl+Shift+F<N>`, donde `N` es el número de la máquina destino).
- **Pega** el contenido recibido en una máquina con otro atajo
  (por defecto `Ctrl+Shift+N` para el buzón `N`, o `Ctrl+Shift+0` para *mi* buzón).

> Los atajos son **configurables**; los valores anteriores son los predeterminados,
> elegidos para no pisar el `Ctrl+C`/`Ctrl+V` nativos.

## 2. Objetivos y alcance

### 2.1 Objetivos

1. Copiar/pegar **texto** entre máquinas en redes distintas.
2. Copiar/pegar **archivos y carpetas** (con su estructura) entre máquinas.
3. Funcionar **sin VPN** ni configuración de red en los clientes: solo salida HTTPS.
4. **Cifrado de extremo a extremo** del contenido del portapapeles (el servidor
   nunca ve el contenido en claro).
5. Operativa por **atajos de teclado globales** y por **menú en la bandeja del sistema**.
6. **Compatibilidad con Windows 7 x64** (Python 3.8).
7. Alta previa de máquinas en un **"pool"** gestionado por el servidor.

> **Nota (post-1.0):** la hoja de ruta ya está implementada — además de Windows hay
> **clientes Linux/macOS**, **historial con fijado**, **multi-pool y ACLs por buzón**,
> **asistente gráfico**, **modo "seguir"** (auto-aplicar entrante) y **sincronización
> bidireccional continua** (`sync_enabled`). Ver
> [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) §8.

### 2.2 Fuera de alcance

- Sincronización de objetos OLE complejos o formatos propietarios de aplicaciones.
- Federación entre varios servidores orquestadores.

## 3. Actores y casos de uso

| Actor | Descripción |
|-------|-------------|
| **Administrador** | Despliega el servidor, da de alta máquinas en el pool, reparte credenciales. |
| **Usuario** | Trabaja en una o varias máquinas Windows y usa los atajos para copiar/pegar. |
| **Orquestador** | El servidor central (VM en cloud privado) que autentica, almacena y notifica. |

### 3.1 Casos de uso principales

- **UC1 — Enviar portapapeles a otra máquina.** El usuario copia algo (`Ctrl+C`)
  y pulsa `Ctrl+Shift+F2`; el contenido viaja cifrado al buzón de la máquina 2.
- **UC2 — Pegar contenido recibido.** En la máquina 2, el usuario pulsa
  `Ctrl+Shift+2` (o `Ctrl+Shift+0`); el contenido se descifra, se coloca en el
  portapapeles local y se pega en la aplicación activa.
- **UC3 — Copiar archivos/carpetas.** Igual que UC1/UC2 pero con archivos
  seleccionados en el Explorador; en destino aparecen como archivos reales listos
  para pegar en cualquier carpeta.
- **UC4 — Alta de máquina.** El administrador registra una máquina (`slot`, nombre)
  y obtiene un fichero de configuración listo para el cliente.
- **UC5 — Ver el pool.** Desde la bandeja, el usuario ve qué máquinas hay y cuáles
  están conectadas.

## 4. Modelo conceptual: buzones / slots

- Cada máquina registrada tiene un **identificador entero `slot` (1..255)**.
- El `slot` **es** el número de buzón. "Enviar al slot 2" = "dejar mi portapapeles
  en el buzón de la máquina 2".
- Cada buzón guarda **un único** contenido (el último que se le envió).
- Una máquina lee normalmente **su propio** buzón, pero puede leer cualquiera
  (los miembros del pool comparten la clave y se consideran de confianza mutua).

```
   Máquina 1  ──Ctrl+Shift+F2──►  [ Buzón 2 ]  ◄──Ctrl+Shift+2──  Máquina 2
   (origen)      (push)        (servidor)         (pull+paste)   (destino)
```

## 5. Requisitos funcionales

| ID | Requisito |
|----|-----------|
| RF1 | Enviar el portapapeles local al buzón de una máquina destino mediante atajo. |
| RF2 | Recuperar el contenido de un buzón al portapapeles local mediante atajo. |
| RF3 | Soportar **texto Unicode**. |
| RF4 | Soportar **archivos y carpetas** preservando nombres y estructura. |
| RF5 | (Extra) Soportar **imágenes** de mapa de bits y **texto enriquecido (HTML)**. |
| RF6 | Pegar automáticamente tras recuperar (configurable). |
| RF7 | Capturar la selección con `Ctrl+C` automático antes de enviar (configurable). |
| RF8 | Alta/baja de máquinas en el pool por parte del administrador. |
| RF9 | Mostrar estado de conexión y miembros del pool en la bandeja. |
| RF10 | Notificar (aviso emergente) cuando llega contenido al buzón propio. |
| RF11 | Atajos de teclado totalmente configurables. |
| RF12 | Funcionar tras reinicios y reconexiones de red automáticamente. |
| RF13 | **Dashboard de administración** web: máquinas conectadas, contenido compartido (origen/destino), actividad y estado de los servicios. |
| RF14 | **Auto-arranque como servicio de Windows** del servidor y del cliente (este último mediante servicio lanzador en la sesión interactiva). |

## 6. Requisitos no funcionales

| ID | Requisito |
|----|-----------|
| RNF1 | **Compatibilidad**: cliente funcional en Windows 7/10/11 y Server 2016/2022 x64. |
| RNF2 | **Python 3.8** en el cliente (último que soporta Windows 7). |
| RNF3 | **Seguridad**: TLS en tránsito + cifrado AES-256-GCM del contenido. |
| RNF4 | **Autenticación** por máquina con token revocable. |
| RNF5 | **Rendimiento**: transferencia por *streaming* y *chunks* para archivos grandes (GB). |
| RNF6 | **Robustez**: reintentos, reanudación de descargas, verificación de integridad SHA-256. |
| RNF7 | **Operabilidad**: instalación documentada, ejecución desatendida al iniciar sesión. |
| RNF8 | **Privacidad**: el servidor almacena solo *ciphertext*; expiración automática del contenido. |
| RNF9 | **Mantenibilidad**: código modular, pruebas automatizadas del núcleo. |

## 7. Arquitectura (resumen)

Modelo **cliente/servidor con almacenamiento intermedio** (*store-and-forward*):

- **Orquestador (servidor)**: API REST (HTTPS) + canal **WebSocket** de presencia y
  notificaciones. Mantiene el registro del pool (SQLite), un buzón por máquina y los
  *blobs* de archivos en disco. Es el **director de orquesta** (la IP pública del
  cloud privado, tras el DD-WRT).
- **Cliente (agente Windows)**: captura/restaura el portapapeles, cifra/descifra,
  gestiona atajos globales y bandeja del sistema, y habla con el servidor.
- **Librería compartida** (`cpr_shared`): criptografía y definición de protocolo,
  idénticas en ambos lados.

Ver detalle en [`ARCHITECTURE.md`](ARCHITECTURE.md).

## 8. Protocolo y formato de datos

### 8.1 "Sobre" (Envelope)

Cada contenido del portapapeles se describe con un *Envelope* (JSON) que viaja por
la API. El contenido binario va **siempre cifrado** (AES-256-GCM) y viaja:

- **inline** (base64 dentro del JSON) si el *ciphertext* ≤ 64 KiB, o
- como **blob** subido previamente por *chunks* si es mayor.

Campos principales del Envelope:

| Campo | Significado |
|-------|-------------|
| `kind` | `text` \| `files` \| `image` \| `html` \| `empty` |
| `size` | Tamaño lógico en claro (bytes). |
| `enc_size` | Tamaño del *ciphertext*. |
| `sha256` | Hash del contenido en claro (verificación de integridad). |
| `key_fp` | Huella de la clave de pool (detecta claves incompatibles). |
| `files[]` | Manifiesto de archivos/carpetas de nivel superior (para `kind=files`). |
| `inline` / `data_b64` / `blob_id` | Modo y referencia del contenido cifrado. |
| `from_id` / `from_name` | Máquina origen (la rellena el servidor de forma autenticada). |

### 8.2 Cifrado

- Algoritmo: **AES-256-GCM** (autenticado). Formato: `versión(1) ‖ nonce(12) ‖ ciphertext‖tag`.
- Archivos grandes: cifrado **por bloques** (1 MiB) con el índice de bloque como
  *associated data* (evita reordenación).
- Clave de **pool** de 256 bits compartida por todas las máquinas; el servidor
  guarda solo la **huella** (no la clave) salvo que se opte por que genere las
  configuraciones de cliente.
- Doble *backend* criptográfico (`cryptography` o `pycryptodome`) con **formato de
  bytes idéntico**, para máxima compatibilidad en Windows 7.

### 8.3 Transferencia de archivos

El portapapeles de Windows solo lleva **referencias** a archivos (`CF_HDROP`), no
su contenido. CopyPasteRemote:

1. Lee las rutas de `CF_HDROP`.
2. Empaqueta los archivos/carpetas en un **ZIP** (preservando estructura, incluidas
   carpetas vacías).
3. Cifra y transfiere el ZIP.
4. En destino lo **descomprime** en una carpeta temporal y construye un `CF_HDROP`
   nuevo apuntando a esas rutas, de modo que un `Ctrl+V` normal pega los archivos.

## 9. API REST (resumen)

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| GET | `/api/health` | — | Estado del servicio. |
| GET | `/api/info` | — | Versión, protocolo, huella de clave, límites. |
| GET | `/api/pool` | Máquina | Lista de máquinas y su estado en línea. |
| POST | `/api/clip/{slot}` | Máquina | Enviar contenido al buzón `slot`. |
| GET | `/api/clip/{slot}` | Máquina | Recuperar el contenido del buzón `slot`. |
| DELETE | `/api/clip/{slot}` | Máquina | Vaciar el buzón `slot`. |
| POST | `/api/blobs` | Máquina | Crear un blob para subida por *chunks*. |
| PUT | `/api/blobs/{id}?offset=` | Máquina | Subir un *chunk* (reanudable). |
| POST | `/api/blobs/{id}/complete` | Máquina | Finalizar y verificar (SHA-256). |
| GET | `/api/blobs/{id}` | Máquina | Descargar (soporta `Range`). |
| WS | `/api/ws?auth=slot.token` | Máquina | Presencia y notificaciones en tiempo real. |
| GET/POST/DELETE | `/api/admin/machines...` | Admin | Gestión del pool. |

Autenticación de máquina: cabecera `Authorization: Bearer <slot>.<token>`.
Autenticación de administración: cabecera `X-Admin-Key: <clave>`.

## 10. Seguridad

- **TLS obligatorio** en exposición a Internet (certificado propio o Let's Encrypt;
  o terminación TLS en proxy/DD-WRT).
- **Tokens por máquina** (se guardan solo *hasheados*; revocables y rotables).
- **Cifrado de contenido** independiente de TLS (defensa en profundidad: el
  servidor almacena solo *ciphertext*).
- **Expiración** automática del contenido de los buzones (24 h por defecto).
- **Verificación de integridad** SHA-256 en cada transferencia.
- **Protección anti *Zip-Slip*** al descomprimir archivos recibidos.
- Modelo de confianza: los miembros de un mismo pool comparten clave y se confían
  mutuamente; el aislamiento entre máquinas es por token, no por contenido.

## 11. Compatibilidad Windows 7

- **Python 3.8.10 x64** (último con instalador para Windows 7).
- Dependencias **fijadas** a versiones con ruedas (`wheels`) compatibles
  (ver `requirements-client.txt`).
- TLS con `urllib3 < 2` para compatibilidad con el almacén de certificados antiguo.
- Para certificados Let's Encrypt en Windows 7, puede requerirse instalar la CA raíz
  **ISRG Root X1**, o bien usar un certificado propio "fijado" (`ca_cert`).

## 12. Limitaciones conocidas

- Un buzón guarda solo el último contenido; un envío sobrescribe al anterior.
- El pegado automático envía `Ctrl+V` a la ventana en primer plano; en aplicaciones
  con elevación (UAC) puede no llegar si el cliente no está elevado.
- Imágenes y HTML son "mejor esfuerzo": si la conversión falla, se degrada a texto.
- El tamaño máximo por contenido es configurable (2 GiB por defecto).

## 13. Criterios de aceptación

1. Texto copiado en la máquina A aparece, idéntico, al pegar en la máquina B.
2. Una carpeta con subcarpetas y archivos se transfiere y pega con su estructura intacta.
3. Un archivo de varios cientos de MB se transfiere por *chunks* y se verifica su SHA-256.
4. Con clave de pool incorrecta, el contenido **no** se puede descifrar (falla controlada).
5. El cliente se reconecta solo tras una caída de red.
6. El servidor purga el contenido caducado sin intervención.
