# 01-setup-server.ps1  —  ejecutar como Administrador en el servidor (Windows).
# Prepara el servidor CopyPasteRemote: repo + venv + deps + claves + máquinas + firewall.
# Solo primera vez. Si el config ya existe, NO se sobrescribe (conserva las claves).
#
# Uso:
#   .\01-setup-server.ps1 -PublicHost "<HOST_PUBLICO>"

param(
    [Parameter(Mandatory=$true)] [string] $PublicHost,
    [int] $Port = 8765
)
$ErrorActionPreference = "Stop"

$Root    = "C:\CopyPasteRemote"
$Src     = "$Root\src"
$Pkg     = "$Src\copypasteremote"
$Venv    = "$Root\venv"
$VenvPy  = "$Venv\Scripts\python.exe"
$Data    = "$Root\data"
$Conf    = "$Root\server-config.json"
$Clients = "$Root\clients"
$RepoUrl = "https://github.com/txpto/CopyPasteRemote"

Write-Host "== CopyPasteRemote: configuración del servidor ==" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Root, $Clients | Out-Null

if (-not (Test-Path $Pkg)) { git clone $RepoUrl $Src } else { Write-Host "Repo ya presente." }

if (-not (Test-Path $VenvPy)) { python -m venv $Venv }
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r "$Pkg\requirements-server.txt"

if (-not (Get-NetFirewallRule -DisplayName "CopyPasteRemote $Port" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "CopyPasteRemote $Port" -Direction Inbound `
        -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
}

if (Test-Path $Conf) {
    Write-Host "El config ya existe; se omite init/add-machine (para conservar las claves)." -ForegroundColor Yellow
} else {
    $env:CPR_DATA_DIR = $Data   # hace que data_dir quede absoluto en el config guardado
    Push-Location $Pkg
    try {
        & $VenvPy -m cpr_server.admin_cli --config $Conf init --public-url "http://$PublicHost`:$Port"
        & $VenvPy -m cpr_server.admin_cli --config $Conf add-machine --slot 1 --name "client1" --client-config "$Clients\client1-config.json"
        & $VenvPy -m cpr_server.admin_cli --config $Conf add-machine --slot 2 --name "client2" --client-config "$Clients\client2-config.json"
        # Añade más con:  ... add-machine --slot N --name "<nombre>" --client-config "$Clients\<nombre>-config.json"
    } finally { Pop-Location }
    Write-Host "Configs de cliente escritos en $Clients" -ForegroundColor Green
}

Write-Host "`nAdmin API key:" -ForegroundColor Cyan
Push-Location $Pkg; & $VenvPy -m cpr_server.admin_cli --config $Conf show-admin-key; Pop-Location
Write-Host "`nSiguiente: 02-install-service.ps1 (y 03-enable-tls.ps1 para TLS)." -ForegroundColor Cyan
