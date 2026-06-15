# 03-enable-tls.ps1  —  run as Administrator on the server (Windows).
# Generates a self-signed cert (SAN = public host + loopback), enables TLS in the
# server config (public_url -> https) and restarts the service.
#
# Usage:
#   .\03-enable-tls.ps1 -PublicHost "<PUBLIC_IP_OR_DOMAIN>"
#
# For a real domain, prefer a Let's Encrypt certificate instead of self-signed.

param(
    [Parameter(Mandatory=$true)] [string] $PublicHost,
    [int] $Port = 8765
)
$ErrorActionPreference = "Stop"

$Root    = "C:\CopyPasteRemote"
$VenvPy  = "$Root\venv\Scripts\python.exe"
$Conf    = "$Root\server-config.json"
$Certs   = "$Root\certs"
$SvcName = "CopyPasteRemoteServer"

if (-not (Test-Path $Conf)) { throw "$Conf not found. Run 01-setup-server.ps1 first." }

& $VenvPy "$PSScriptRoot\gen_selfsigned_cert.py" $Certs $PublicHost "127.0.0.1" "localhost"

$cfg = Get-Content $Conf -Raw | ConvertFrom-Json
$cfg.tls_certfile = "$Certs\cert.pem"
$cfg.tls_keyfile  = "$Certs\key.pem"
$cfg.public_url   = "https://$PublicHost`:$Port"
$cfg | ConvertTo-Json -Depth 12 | Set-Content $Conf -Encoding utf8
Write-Host "TLS ON, public_url = https://$PublicHost`:$Port" -ForegroundColor Green

if (Get-Service $SvcName -ErrorAction SilentlyContinue) {
    Restart-Service $SvcName -Force; Start-Sleep -Seconds 2; Get-Service $SvcName
}

Write-Host "`nClients: copy $Certs\cert.pem to each client and pass it to the setup script" -ForegroundColor Cyan
Write-Host "(it sets ca_cert + verify_tls=true). New client configs will use the https URL."
