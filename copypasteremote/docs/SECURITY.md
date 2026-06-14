# CopyPasteRemote — Análisis de seguridad y endurecimiento

> Este documento analiza el nivel de seguridad de la arquitectura y describe los
> controles implementados, los riesgos residuales y un checklist de despliegue.
> **Contexto clave:** el orquestador (la VM con IP pública) está **expuesto a
> Internet**, por lo que se trata como un servicio hostil-facing.

## 1. Modelo de amenazas

### 1.1 Activos a proteger
- **Contenido del portapapeles** (texto, archivos, carpetas): puede ser sensible.
- **Clave de pool** (AES-256): descifra todo el contenido del pool.
- **Tokens de máquina** y **clave de administración**.
- **Disponibilidad** del orquestador.

### 1.2 Fronteras de confianza
```
[ Cliente Windows ]  --TLS-->  [ DD-WRT / Internet ]  -->  [ Orquestador (VM pública) ]
   confiable                       NO confiable                semi-confiable (ve cifrado)
```
- Los **miembros del mismo pool** se consideran **mutuamente confiables** (comparten
  la clave de pool). El aislamiento entre máquinas es por token, no por contenido.
- El **orquestador** es *semi-confiable*: se busca que vea solo *ciphertext*
  (conocimiento cero del contenido si la clave no se almacena en el servidor).
- **Internet** es hostil: cualquiera puede alcanzar los puertos publicados.

### 1.3 Adversarios considerados
- **Atacante de red** (MITM, sniffing): mitigado por TLS + cifrado de contenido.
- **Atacante de Internet no autenticado**: escaneos, fuerza bruta de tokens/clave
  admin, DoR/DoS, explotación de endpoints.
- **Servidor curioso/comprometido**: solo ve *ciphertext* (defensa en profundidad).
- **Cliente malicioso del pool**: fuera de alcance (modelo de confianza mutua), pero
  se limita el daño con tokens revocables y opción de restringir lecturas cruzadas.

## 2. Controles de seguridad implementados

### 2.1 Transporte
- **TLS (HTTPS/WSS)** recomendado y documentado (cert propio "fijado" o Let's Encrypt,
  o terminación en proxy/DD-WRT).
- Aviso de **postura de seguridad** en el arranque si se sirve sin TLS en bind público.

### 2.2 Autenticación y autorización
- **Token por máquina** `Bearer <slot>.<token>` (32 bytes aleatorios, ~256 bits).
  Se almacena solo el **hash SHA-256**; comparación en **tiempo constante**.
- **Clave de administración** para `/api/admin/*` y el dashboard (cabecera
  `X-Admin-Key`), comparación en tiempo constante; si no se define, se **genera**
  una aleatoria (no se registra en logs; se obtiene con `admin_cli show-admin-key`).
- **Tokens revocables y rotables** (`admin_cli rotate`, `enable --disable`).
- **WebSocket**: autenticación por **cabecera `Authorization`** (no en la URL), para
  que el token no acabe en logs de acceso/proxies.
- **Lecturas cruzadas opcionales**: `allow_cross_pull=false` restringe a cada máquina
  a leer **solo su propio buzón**.

### 2.3 Confidencialidad e integridad del contenido
- **AES-256-GCM** (autenticado) con **clave de pool** compartida; el servidor guarda
  solo *ciphertext* (conocimiento cero si la clave no se almacena en el servidor).
- Cifrado **por bloques** para archivos grandes, con el índice de bloque como
  *associated data* (impide reordenación).
- **Integridad**: SHA-256 del contenido en claro verificado en destino; GCM autentica
  cada bloque. Manipulación ⇒ fallo de descifrado.
- **Huella de clave** (`key_fp`) para detectar pools/claves incompatibles sin exponer
  la clave.

### 2.4 Endurecimiento del servicio (exposición a Internet)
- **Cabeceras de seguridad** en todas las respuestas: `X-Content-Type-Options:
  nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`, **HSTS**.
- **CSP estricta** para el dashboard con **nonce** por respuesta (sin `unsafe-inline`);
  CSP `default-src 'none'` para las respuestas de API.
- **Límite de tamaño de petición** (`max_request_bytes`) que rechaza cuerpos enormes
  **antes** de bufferizarlos (protección anti-DoS de memoria).
- **Rate limiting / lockout** por IP ante fallos de autenticación (máquina y admin).
- **Minimización de divulgación**: `/api/info` público devuelve solo app/versión/
  protocolo; la huella de clave y los límites van tras autenticación (`/api/pool`).
  Posibilidad de **ocultar `/docs`** (`enable_docs=false`).
- **Middleware ASGI puro**: no bufferiza el cuerpo ⇒ no degrada las descargas de
  archivos en streaming.

### 2.5 Robustez y ciclo de vida de datos
- **Expiración** automática de buzones (24 h por defecto) y **GC** de blobs huérfanos.
- **Protección anti *Zip-Slip*** al descomprimir archivos recibidos.
- **Reanudación** de descargas y verificación de checksum en subidas.
- IDs de blob generados por el servidor (sin *path traversal*; se resuelven por BD).

## 3. Riesgos residuales y recomendaciones

| Riesgo residual | Estado / recomendación |
|-----------------|------------------------|
| **Confianza intra-pool** | Un miembro puede leer/escribir buzones de otros. Usa `allow_cross_pull=false` y pools separados para aislar grupos. |
| **El servidor podría almacenar la clave** (para generar configs) | Para conocimiento cero, **no** pongas `pool_key_b64` en el servidor; distribúyela solo a clientes. |
| **TLS desactivado** | Nunca expongas sin TLS. El servidor avisa en el arranque. |
| **Fuerza bruta de clave admin** | Mitigada con rate limiting; usa una clave **larga y aleatoria**. Restringe el puerto en el DD-WRT a IPs conocidas si es posible. |
| **DoS volumétrico** | Hay límites de tamaño y rate limiting de auth, pero no de ancho de banda. Considera un proxy (Cloudflare/Nginx) o reglas de firewall. |
| **Rate limiting en memoria** | Se reinicia al reiniciar el proceso y es por instancia. Suficiente para un único nodo; para HA usa un proxy con rate limiting. |
| **Pegado automático en apps elevadas (UAC)** | El cliente debe correr con privilegios equivalentes; documentado. |
| **Compromiso de un cliente** | Rota su token (`admin_cli rotate`) y deshabilítalo; considera rotar la clave de pool. |

## 4. Checklist de despliegue seguro (producción, expuesto a Internet)

- [ ] **TLS activado** (`tls_certfile`/`tls_keyfile`) o terminado en un proxy de confianza.
- [ ] **Clave de administración** larga y aleatoria (`>= 24` caracteres) en `admin_api_key`.
- [ ] **`enable_docs=false`** si no necesitas `/docs` públicamente.
- [ ] **Clave de pool** generada aleatoriamente; valora **no** almacenarla en el servidor.
- [ ] **`server-config.json` con permisos `600`** (la CLI ya lo hace) y backups cifrados.
- [ ] **Port-forwarding mínimo** en el DD-WRT (solo el puerto necesario; restringe IPs si puedes).
- [ ] **`trust_proxy`** solo si hay un proxy de confianza por delante (si no, déjalo `false`).
- [ ] **Firewall del SO** de la VM permitiendo solo el puerto del servicio.
- [ ] **Actualizaciones** del SO de la VM y de las dependencias del servidor.
- [ ] **Monitorización** del dashboard y de los logs (avisos `SECURITY:` en el arranque).
- [ ] **Rotación periódica** de tokens; revocación inmediata de máquinas dadas de baja.
- [ ] Considera **fail2ban** sobre los logs del proxy para bloqueos a nivel de red.

### Ejemplo de config endurecida (`server-config.json`)
```json
{
  "host": "0.0.0.0",
  "port": 8765,
  "public_url": "https://tu-dominio-o-ip:8765",
  "tls_certfile": "/etc/cpr/cert.pem",
  "tls_keyfile": "/etc/cpr/key.pem",
  "enable_docs": false,
  "trust_proxy": false,
  "hsts": true,
  "allow_cross_pull": false,
  "max_request_bytes": 16777216,
  "slot_ttl_seconds": 86400,
  "auth_rate_max_failures": 10,
  "auth_rate_window_seconds": 60,
  "auth_rate_block_seconds": 600
}
```

## 5. Respuesta a incidentes
- **Token de máquina filtrado** → `admin_cli rotate --slot N` (invalida el anterior).
- **Máquina perdida/robada** → `admin_cli enable --slot N --disable` y rota su token.
- **Sospecha sobre la clave de pool** → genera una nueva, redistribúyela a los clientes
  (el contenido antiguo deja de ser descifrable; los buzones caducan solos).
- **Clave de administración filtrada** → cámbiala en la config y reinicia el servicio.

## 6. Resumen del nivel de seguridad

La arquitectura aplica **defensa en profundidad**: TLS en tránsito + cifrado
autenticado del contenido (servidor de conocimiento cero opcional) + autenticación
por token con rate limiting + endurecimiento HTTP (cabeceras, CSP, límites) +
minimización de divulgación. Es **adecuada para exposición directa a Internet**
siempre que se cumpla el checklist (sobre todo **TLS** y una **clave de
administración fuerte**). El riesgo dominante restante es la **confianza mutua
dentro del pool**, mitigable con `allow_cross_pull=false` y separación de pools.
