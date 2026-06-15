# 01-setup-server.ps1  —  run as Administrator on the server (Windows).
# Prepares the CopyPasteRemote server: repo + venv + deps + keys + machines + firewall.
# First run only. If the config already exists it is NOT overwritten (keeps the keys).
#
# Usage:
#   .\01-setup-server.ps1 -PublicHost "<PUBLIC_IP_OR_DOMAIN>"

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

Write-Host "== CopyPasteRemote: server setup ==" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Root, $Clients | Out-Null

if (-not (Test-Path $Pkg)) { git clone $RepoUrl $Src } else { Write-Host "Repo already present." }

if (-not (Test-Path $VenvPy)) { python -m venv $Venv }
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r "$Pkg\requirements-server.txt"

if (-not (Get-NetFirewallRule -DisplayName "CopyPasteRemote $Port" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "CopyPasteRemote $Port" -Direction Inbound `
        -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
}

if (Test-Path $Conf) {
    Write-Host "Config exists; skipping init/add-machine (so keys are preserved)." -ForegroundColor Yellow
} else {
    $env:CPR_DATA_DIR = $Data   # makes data_dir absolute in the saved config
    Push-Location $Pkg
    try {
        & $VenvPy -m cpr_server.admin_cli --config $Conf init --public-url "http://$PublicHost`:$Port"
        & $VenvPy -m cpr_server.admin_cli --config $Conf add-machine --slot 1 --name "client1" --client-config "$Clients\client1-config.json"
        & $VenvPy -m cpr_server.admin_cli --config $Conf add-machine --slot 2 --name "client2" --client-config "$Clients\client2-config.json"
        # Add more with:  ... add-machine --slot N --name "<name>" --client-config "$Clients\<name>-config.json"
    } finally { Pop-Location }
    Write-Host "Client configs written under $Clients" -ForegroundColor Green
}

Write-Host "`nAdmin API key:" -ForegroundColor Cyan
Push-Location $Pkg; & $VenvPy -m cpr_server.admin_cli --config $Conf show-admin-key; Pop-Location
Write-Host "`nNext: 02-install-service.ps1 (and 03-enable-tls.ps1 for TLS)." -ForegroundColor Cyan
