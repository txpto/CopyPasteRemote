# setup-client.ps1  —  cliente Windows 10/11.
# Crea un venv, instala las dependencias del cliente, coloca el config y lo prueba.
# Si pasas -CaCert (el cert.pem del servidor), se activa la verificación TLS contra él.
#
# Uso:
#   .\setup-client.ps1 -PkgDir "<ruta>\copypasteremote" `
#       -ConfigSource "<ruta>\client-config.json" [-CaCert "<ruta>\cert.pem"]

param(
    [Parameter(Mandatory=$true)] [string] $PkgDir,        # carpeta que contiene run_client.py
    [Parameter(Mandatory=$true)] [string] $ConfigSource,  # config de cliente emitido por el servidor
    [string] $CaCert                                      # cert.pem del servidor (opcional, para TLS)
)
$ErrorActionPreference = "Stop"

$Venv    = "$env:LOCALAPPDATA\CopyPasteRemote\venv"
$VenvPy  = "$Venv\Scripts\python.exe"
$CfgDir  = "$env:APPDATA\CopyPasteRemote"
$CfgPath = "$CfgDir\config.json"

if (-not (Test-Path "$PkgDir\run_client.py")) { throw "No se encuentra run_client.py en $PkgDir" }
if (-not (Test-Path $ConfigSource)) { throw "No se encuentra el config: $ConfigSource" }

if (-not (Test-Path $VenvPy)) { python -m venv $Venv }
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r "$PkgDir\requirements-client.txt"

New-Item -ItemType Directory -Force -Path $CfgDir | Out-Null
Copy-Item $ConfigSource $CfgPath -Force
Write-Host "Config -> $CfgPath" -ForegroundColor Green

if ($CaCert) {
    if (-not (Test-Path $CaCert)) { throw "No se encuentra el cert: $CaCert" }
    $CertDst = "$CfgDir\cpr-cert.pem"
    Copy-Item $CaCert $CertDst -Force
    $cfg = Get-Content $CfgPath -Raw | ConvertFrom-Json
    $cfg.ca_cert = $CertDst
    $cfg.verify_tls = $true
    [System.IO.File]::WriteAllText($CfgPath, ($cfg | ConvertTo-Json -Depth 12), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "TLS: ca_cert -> $CertDst , verify_tls = true" -ForegroundColor Green
}

Push-Location $PkgDir; & $VenvPy run_client.py --check; Pop-Location

Write-Host "`nSi el check fue OK, arranca el cliente de bandeja COMO ADMINISTRADOR (hotkeys globales):" -ForegroundColor Yellow
Write-Host "  cd `"$PkgDir`"; & `"$VenvPy`" run_client.py"
