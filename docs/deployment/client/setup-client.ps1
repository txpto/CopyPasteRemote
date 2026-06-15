# setup-client.ps1  —  Windows 10/11 client.
# Creates a venv, installs the client deps, drops the config in place and tests it.
# If you pass -CaCert (the server's cert.pem), TLS verification is enabled against it.
#
# Usage:
#   .\setup-client.ps1 -PkgDir "<path>\copypasteremote" `
#       -ConfigSource "<path>\client-config.json" [-CaCert "<path>\cert.pem"]

param(
    [Parameter(Mandatory=$true)] [string] $PkgDir,        # folder containing run_client.py
    [Parameter(Mandatory=$true)] [string] $ConfigSource,  # client config emitted by the server
    [string] $CaCert                                      # server cert.pem (optional, for TLS)
)
$ErrorActionPreference = "Stop"

$Venv    = "$env:LOCALAPPDATA\CopyPasteRemote\venv"
$VenvPy  = "$Venv\Scripts\python.exe"
$CfgDir  = "$env:APPDATA\CopyPasteRemote"
$CfgPath = "$CfgDir\config.json"

if (-not (Test-Path "$PkgDir\run_client.py")) { throw "run_client.py not found under $PkgDir" }
if (-not (Test-Path $ConfigSource)) { throw "Config not found: $ConfigSource" }

if (-not (Test-Path $VenvPy)) { python -m venv $Venv }
& $VenvPy -m pip install --upgrade pip
& $VenvPy -m pip install -r "$PkgDir\requirements-client.txt"

New-Item -ItemType Directory -Force -Path $CfgDir | Out-Null
Copy-Item $ConfigSource $CfgPath -Force
Write-Host "Config -> $CfgPath" -ForegroundColor Green

if ($CaCert) {
    if (-not (Test-Path $CaCert)) { throw "Cert not found: $CaCert" }
    $CertDst = "$CfgDir\cpr-cert.pem"
    Copy-Item $CaCert $CertDst -Force
    $cfg = Get-Content $CfgPath -Raw | ConvertFrom-Json
    $cfg.ca_cert = $CertDst
    $cfg.verify_tls = $true
    $cfg | ConvertTo-Json -Depth 12 | Set-Content $CfgPath -Encoding utf8
    Write-Host "TLS: ca_cert -> $CertDst , verify_tls = true" -ForegroundColor Green
}

Push-Location $PkgDir; & $VenvPy run_client.py --check; Pop-Location

Write-Host "`nIf the check passed, run the tray client AS ADMINISTRATOR (for global hotkeys):" -ForegroundColor Yellow
Write-Host "  cd `"$PkgDir`"; & `"$VenvPy`" run_client.py"
