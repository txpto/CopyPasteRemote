# CopyPasteRemote — Manual de instalación

Este manual cubre la instalación del **orquestador (servidor)** en tu VM del cloud
privado (tras el DD-WRT) y la del **cliente** en cada máquina Windows.

> Convención: los comandos del servidor empiezan por `#` o `$`; los del cliente
> Windows van en `PowerShell` o `CMD`.

---

## Parte A — Orquestador (servidor)

### A.1 Requisitos

- VM Linux (recomendado) o Windows con **Python 3.8+** y salida a Internet.
- Acceso a la configuración del **DD-WRT** (port-forwarding) y, opcionalmente, a la
  consola del **ESXi** para la VM.
- Un puerto público (por defecto `8765/tcp`).

### A.2 Descarga e instalación de dependencias

```bash
# En la VM
sudo useradd -r -m -d /opt/copypasteremote cpr     # usuario de servicio (opcional)
sudo -iu cpr
git clone <URL-de-tu-repo> /opt/copypasteremote
cd /opt/copypasteremote
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-server.txt
```

### A.3 Inicialización (config + clave de pool)

```bash
# Genera server-config.json con una clave de pool aleatoria y una clave de admin
python -m cpr_server.admin_cli --config server-config.json init \
    --public-url https://TU_IP_PUBLICA:8765 --pool-id default
```

Esto crea `server-config.json` (contiene la **clave de pool**, la **clave de admin**
y la base de datos en `./data`). **Guárdalo con permisos restringidos** (`chmod 600`).

> Alternativa "conocimiento cero": si no quieres que el servidor conozca la clave de
> pool, genera la clave aparte y **no** la pongas en `server-config.json`; añádela
> manualmente solo en los clientes. En ese caso tendrás que rellenar `pool_key` a mano
> en cada `config.json` de cliente.

### A.4 TLS (muy recomendado)

Tienes tres opciones:

1. **Certificado propio (autofirmado) "fijado" en los clientes**
   ```bash
   bash scripts/server/gen_selfsigned_cert.sh TU_IP_PUBLICA
   # Edita server-config.json: "tls_certfile": "cert.pem", "tls_keyfile": "key.pem"
   ```
   Copia `cert.pem` a cada cliente y pon `ca_cert` apuntando a él (ver Parte B).

2. **Let's Encrypt** (si tienes un dominio apuntando a la IP pública): usa `certbot`
   y apunta `tls_certfile`/`tls_keyfile` a los ficheros emitidos.
   > En **Windows 7** puede ser necesario instalar la CA raíz **ISRG Root X1**.

3. **Terminación TLS en un proxy inverso** (Caddy/Nginx/Traefik) o en el propio
   **DD-WRT**; en ese caso el servidor puede ir en HTTP en la LAN.

### A.5 Apertura de puerto en el DD-WRT

En el DD-WRT: **NAT / QoS → Port Forwarding** y añade:

| Application | Port from | Protocol | IP Address (VM) | Port to |
|-------------|-----------|----------|------------------|---------|
| CPR | 8765 | TCP | `IP_LAN_de_la_VM` | 8765 |

Si terminas TLS en el router en el 443, reenvía `443 → 8765` y pon `public_url`
con `https://TU_IP:443` (o sin puerto).

> ESXi: asegúrate de que la VM tiene IP fija en la LAN (reserva DHCP o IP estática) y
> de que el firewall del SO permite el puerto.

### A.6 Arranque

**Manual (prueba):**
```bash
. .venv/bin/activate
CPR_SERVER_CONFIG=server-config.json python run_server.py
# Comprueba: curl -k https://TU_IP_PUBLICA:8765/api/health
```

**Como servicio systemd (producción):**
```bash
sudo cp scripts/server/copypasteremote.service /etc/systemd/system/
# Ajusta rutas/usuario dentro del .service si difieren
sudo systemctl daemon-reload
sudo systemctl enable --now copypasteremote
sudo systemctl status copypasteremote
```

**Con Docker (alternativa):**
```bash
docker compose -f scripts/server/docker-compose.yml up -d
```

### A.7 Alta de máquinas en el pool

Cada máquina necesita un **slot** (número 1..255 = su buzón) y un **nombre**. La CLI
puede generar el `config.json` del cliente ya listo:

```bash
python -m cpr_server.admin_cli --config server-config.json add-machine \
    --slot 1 --name "PC-Casa"    --client-config clients/pc-casa.json
python -m cpr_server.admin_cli --config server-config.json add-machine \
    --slot 2 --name "PC-Oficina" --client-config clients/pc-oficina.json

python -m cpr_server.admin_cli --config server-config.json list
```

Otros comandos útiles:
```bash
python -m cpr_server.admin_cli --config server-config.json rotate  --slot 2   # nuevo token
python -m cpr_server.admin_cli --config server-config.json enable  --slot 2 --disable
python -m cpr_server.admin_cli --config server-config.json remove  --slot 2
python -m cpr_server.admin_cli --config server-config.json show-admin-key
```

Copia cada `clients/<máquina>.json` a su PC Windows (ver Parte B). Contiene
`server_url`, `machine_id`, `token` y `pool_key`: **trátalo como secreto**.

---

## Parte B — Cliente (Windows)

Hay dos formas: **(B1) ejecutable** (recomendado para usuarios) o **(B2) desde
código con Python**. Para **Windows 7** lee primero la sección B.4.

### B1 — Instalación con ejecutable (.exe)

1. Obtén `CopyPasteRemote.exe` (construido con PyInstaller; ver B.3) y cópialo, por
   ejemplo, a `C:\CopyPasteRemote\`.
2. Copia el `config.json` generado por el administrador a:
   ```
   %APPDATA%\CopyPasteRemote\config.json
   ```
   (Crea la carpeta si no existe. Es `C:\Users\<tu_usuario>\AppData\Roaming\CopyPasteRemote`.)
3. Si usas certificado autofirmado, copia `cert.pem` a esa carpeta y añade en el
   `config.json`: `"ca_cert": "C:\\Users\\<tu>\\AppData\\Roaming\\CopyPasteRemote\\cert.pem"`.
4. Verifica la conexión:
   ```
   C:\CopyPasteRemote\CopyPasteRemote.exe --check
   ```
5. Instala el arranque automático al iniciar sesión:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\client\install_task.ps1 `
       -ExePath "C:\CopyPasteRemote\CopyPasteRemote.exe"
   Start-ScheduledTask -TaskName CopyPasteRemote
   ```
   Añade `-Highest` si necesitas pegar en aplicaciones que se ejecutan **como
   administrador**.

### B2 — Instalación desde código (Python)

1. Instala **Python 3.8.10 x64** (Win7) o 3.8+ (Win10/11/Server). Marca "Add to PATH".
2. Instala dependencias:
   ```powershell
   cd C:\CopyPasteRemote
   python -m pip install -r requirements-client.txt
   ```
3. Crea/instala la configuración:
   ```powershell
   python run_client.py --setup       # crea una plantilla y abre la carpeta
   # ...sustituye la plantilla por el config.json del administrador...
   python run_client.py --check       # prueba la conexión y muestra el pool
   ```
4. Ejecuta:
   ```powershell
   python run_client.py               # app con icono de bandeja
   # o, sin consola visible:
   pythonw run_client.py
   ```
5. Arranque automático al iniciar sesión:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\client\install_task.ps1 `
       -PythonExe "C:\Python38\pythonw.exe" -RepoPath "C:\CopyPasteRemote"
   ```

### B3 — Construir el ejecutable (.exe)

En una máquina Windows (para Win7, hazlo **en** Windows 7 x64 con Python 3.8.10):
```cmd
cd C:\CopyPasteRemote
scripts\client\build_exe.bat
REM Resultado: dist\CopyPasteRemote.exe
```

### B4 — Notas específicas de Windows 7 x64

- Usa **Python 3.8.10** (último con instalador para Windows 7).
- Las versiones de `requirements-client.txt` están **fijadas** para Win7. No las subas
  sin comprobar compatibilidad.
- TLS: el cliente usa `urllib3 < 2`. Para certificados Let's Encrypt, instala la CA
  **ISRG Root X1** o usa un certificado propio "fijado" con `ca_cert`.
- Asegúrate de tener instalado el **Visual C++ 2015–2019 Redistributable (x64)** si
  alguna rueda lo requiere.

### B5 — Estructura del `config.json` del cliente

```json
{
  "server_url": "https://TU_IP_PUBLICA:8765",
  "machine_id": 1,
  "machine_name": "PC-Casa",
  "token": "<secreto>",
  "pool_id": "default",
  "pool_key": "<clave-de-pool-base64>",
  "verify_tls": true,
  "ca_cert": "",
  "auto_paste": true,
  "copy_before_send": true,
  "notifications": true,
  "pull_own_hotkey": "ctrl+alt+v",
  "push_hotkeys": { "1": "ctrl+alt+1", "2": "ctrl+alt+2", "3": "ctrl+alt+3" },
  "pull_hotkeys": { "1": "ctrl+shift+1", "2": "ctrl+shift+2", "3": "ctrl+shift+3" }
}
```

Los campos de comportamiento y atajos son **opcionales** (si faltan, se usan los
valores por defecto). Ver [`USER_GUIDE.md`](USER_GUIDE.md) para personalizarlos.

---

## Parte C — Verificación de extremo a extremo

1. En **dos** máquinas del pool, ejecuta `--check`: ambas deben ver el pool y la
   huella de clave debe marcar `[OK]`.
2. Arranca el cliente en ambas. El icono de bandeja debe ponerse en verde (conectado).
3. En la máquina 1: copia un texto (`Ctrl+C`) y pulsa `Ctrl+Alt+2`.
4. En la máquina 2: pulsa `Ctrl+Shift+2` (o `Ctrl+Alt+V`). Debe pegarse el texto.
5. Repite con **archivos/carpetas** seleccionados en el Explorador.
6. Prueba un **archivo grande** (cientos de MB) para validar la transferencia por
   *chunks*.

Si algo falla, revisa la sección **Solución de problemas** del manual de uso.
