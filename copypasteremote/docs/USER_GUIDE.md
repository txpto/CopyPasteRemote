# CopyPasteRemote — Manual de uso

CopyPasteRemote añade un **portapapeles compartido** entre tus ordenadores. Cada
máquina tiene un **buzón** numerado (su `slot`). Envías el portapapeles al buzón de
otra máquina y lo recoges allí.

## 1. Conceptos en 30 segundos

- **Enviar (push)**: coge lo que tengas copiado y lo deja en el buzón de la máquina
  destino. Atajo por defecto: **`Ctrl+Alt+N`** (N = número de la máquina destino).
- **Pegar (pull)**: recoge lo que haya en un buzón, lo pone en tu portapapeles y lo
  pega. Atajos por defecto:
  - **`Ctrl+Shift+N`** → pega lo del buzón **N**.
  - **`Ctrl+Alt+V`** → pega lo de **mi** buzón (el de esta máquina).

> Recuerda los números con el comando `--check` o desde el menú de la bandeja, que
> lista las máquinas y su `slot`.

## 2. Flujos de trabajo

### 2.1 Enviar texto de la máquina 1 a la 2

1. En la **máquina 1**, selecciona el texto.
2. Pulsa **`Ctrl+Alt+2`**. (Por defecto, el cliente hace `Ctrl+C` por ti antes de
   enviar; si lo desactivas, copia tú primero con `Ctrl+C`.)
3. Ve a la **máquina 2** y pulsa **`Ctrl+Shift+2`** (o `Ctrl+Alt+V`). El texto se pega.

### 2.2 Enviar archivos o carpetas

1. En el **Explorador** de la máquina origen, selecciona archivos y/o carpetas y
   cópialos (`Ctrl+C`).
2. Pulsa **`Ctrl+Alt+N`** (máquina destino).
3. En la máquina destino, abre la carpeta donde quieras dejarlos y pulsa
   **`Ctrl+Shift+N`**. Los archivos se pegan como si fueran locales, con su estructura.

> Los archivos grandes se transfieren por partes y se verifican con SHA-256. Verás el
> progreso en los avisos de la bandeja.

### 2.3 Usar el menú de la bandeja (sin atajos)

Haz clic en el icono de CopyPasteRemote (junto al reloj):

- **Send clipboard to →** elige una máquina para **enviar**.
- **Paste from →** elige un buzón del que **pegar**.
- **Paste my mailbox** → pega lo de tu propio buzón.
- **Refresh pool** → actualiza la lista de máquinas.
- **Open config folder** → abre la carpeta de configuración.
- **Quit** → cierra el cliente.

El icono está **verde** cuando hay conexión con el servidor y **gris** cuando no.

## 3. Notificaciones

Cuando alguien deja contenido en **tu** buzón, recibes un aviso ("Clipboard ready")
con el tipo de contenido y la máquina origen. Con `prefetch` activado (por defecto),
el contenido se **descarga por adelantado** para que el pegado sea instantáneo.

## 4. Personalización (config.json)

Edita `%APPDATA%\CopyPasteRemote\config.json` (o usa **Open config folder**). Tras
cambiarlo, reinicia el cliente.

| Opción | Por defecto | Descripción |
|--------|-------------|-------------|
| `auto_paste` | `true` | Pegar automáticamente (`Ctrl+V`) tras recoger un buzón. |
| `copy_before_send` | `true` | Hacer `Ctrl+C` automático antes de enviar. |
| `notifications` | `true` | Mostrar avisos en la bandeja. |
| `prefetch` | `true` | Pre-descargar el contenido al recibir aviso. |
| `pull_own_hotkey` | `ctrl+alt+v` | Atajo para pegar de mi buzón. |
| `push_hotkeys` | `ctrl+alt+1..9` | Mapa `slot → atajo` para enviar. |
| `pull_hotkeys` | `ctrl+shift+1..9` | Mapa `slot → atajo` para pegar de un buzón. |
| `verify_tls` | `true` | Verificar el certificado del servidor. |
| `ca_cert` | `""` | Ruta a un certificado/CA a confiar (autofirmado). |
| `temp_dir` | `""` | Carpeta para materializar archivos recibidos (vacío = temporal del sistema). |
| `log_level` | `info` | `debug` para diagnóstico. |
| `log_file` | `""` | Ruta a un fichero de log (vacío = solo consola). |

### 4.1 Sintaxis de atajos

Se usan nombres de la librería `keyboard`: combina con `+`. Ejemplos válidos:
`ctrl+alt+1`, `ctrl+shift+f1`, `ctrl+alt+shift+c`, `win+v` (evítalo, lo usa Windows).

Ejemplo: cambiar el envío a la máquina 2 a `Ctrl+Alt+F2` y añadir un buzón 4:

```json
"push_hotkeys": { "1": "ctrl+alt+1", "2": "ctrl+alt+f2", "4": "ctrl+alt+4" },
"pull_hotkeys": { "1": "ctrl+shift+1", "2": "ctrl+shift+f2", "4": "ctrl+shift+4" }
```

## 5. Funciones avanzadas

### 5.1 Historial y "fijar"
Cada buzón guarda los **últimos elementos** recibidos (no solo el último). Desde la
bandeja, **History (my mailbox)** lista los recientes; selecciona uno para recuperarlo
al portapapeles. Puedes **fijar** (📌) elementos para que **no caduquen**.

### 5.2 Modo "seguir" (sincronización automática)
Activa `"auto_apply_incoming": true` en tu `config.json` para que **lo que llegue a tu
buzón se ponga automáticamente en tu portapapeles** (sin pulsar atajo). Útil para
"seguir" lo que otra máquina te envía. No pega solo; solo deja el contenido listo.

### 5.3 Asistente gráfico de configuración
Ejecuta `run_client.py --wizard` (o el `.exe --wizard`) para rellenar la configuración
con un formulario y **probar la conexión** antes de guardar. Si arrancas el cliente sin
configuración válida, el asistente se ofrece automáticamente.

### 5.4 Clientes Linux y macOS
Además de Windows, el cliente funciona en **Linux** (instala `wl-clipboard` en Wayland o
`xclip`/`xsel` en X11) y **macOS** (usa `pbcopy`/`pbpaste`/`osascript` ya incluidos).
Texto en ambos; archivos/carpetas en Linux vía `text/uri-list` y en macOS vía AppleScript.

### 5.5 Múltiples pools
Las máquinas pueden agruparse en **pools**: solo ves y compartes con máquinas de **tu
mismo pool**. El administrador lo gestiona con `add-machine --pool`, `set-pool` y, para
permisos finos por buzón, `set-acl` (quién puede enviarte/leerte).

## 6. Buenas prácticas

- Numera las máquinas de forma estable (el `slot` no debería cambiar).
- Si compartes datos sensibles, recuerda que **otros miembros del pool** pueden leer
  cualquier buzón (comparten la clave). Usa **pools separados** o **ACLs** para aislar.
- El contenido de los buzones **caduca** (24 h por defecto): no lo uses como almacén.
  Usa **fijar** para conservar elementos del historial.

## 7. Solución de problemas

| Síntoma | Causa probable / solución |
|---------|---------------------------|
| Icono **gris** (sin conexión) | Revisa `server_url`, el port-forward del DD-WRT y el firewall. Ejecuta `--check`. |
| `--check` da error TLS | Certificado no confiable: pon `ca_cert` (autofirmado) o instala la CA. Para pruebas, `verify_tls: false` (no recomendado). |
| `Pool key fingerprint ... MISMATCH` | La `pool_key` del cliente no coincide con la del pool. Pide al admin la correcta. |
| Pulso el atajo y no pasa nada | Otro programa usa ese atajo, o el cliente no corre con privilegios suficientes. Cambia el atajo o instala la tarea con `-Highest`. |
| No pega en una app **como administrador** | Ejecuta el cliente con privilegios equivalentes (tarea con `-Highest`). |
| "Nothing to copy" al enviar | El portapapeles estaba vacío. Copia algo (`Ctrl+C`) o deja `copy_before_send: true`. |
| Los archivos no aparecen al pegar | Asegúrate de pegar en una ventana del **Explorador**/carpeta. Mira los avisos de progreso. |
| Texto con acentos raros | No debería ocurrir (UTF-8). Si pasa, reporta el caso con `log_level: debug`. |
| Quiero ver detalles | Pon `log_level: debug` y `log_file` a una ruta; reproduce el problema y revisa el log. |

### 7.1 Diagnóstico rápido

```powershell
CopyPasteRemote.exe --check          # o: python run_client.py --check
```
Muestra: versión del servidor, coincidencia de clave de pool y el pool con el estado
en línea de cada máquina.

## 8. Preguntas frecuentes

**¿Necesito VPN?** No. Solo salida HTTPS hacia el servidor.

**¿Ve el servidor mi contenido?** No: viaja cifrado (AES-256-GCM) con la clave del
pool; el servidor almacena solo datos cifrados.

**¿Puedo pegar en varias máquinas a la vez?** Envía a cada buzón (`Ctrl+Alt+N`) y
pega en cada una. Cada buzón guarda su último contenido.

**¿Funciona con Windows 7?** Sí, con Python 3.8.10 x64 y las dependencias fijadas.

**¿Y con imágenes o texto con formato?** De forma "mejor esfuerzo": si la conversión
no es posible, se transfiere como texto plano.

**¿Cómo cambio mis atajos?** Edita `push_hotkeys` / `pull_hotkeys` en `config.json`
y reinicia el cliente.
