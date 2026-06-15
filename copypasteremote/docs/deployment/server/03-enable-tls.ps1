# 03-enable-tls.ps1  —  ejecutar como Administrador en el servidor (Windows).
# Genera un certificado autofirmado (SAN = host público + loopback), activa TLS en la
# configuración del servidor (public_url -> https) y reinicia el servicio.
#
# Uso:
#   .\03-enable-tls.ps1 -PublicHost "<HOST_PUBLICO>"
#
# Para un dominio real, mejor un certificado de Let's Encrypt en lugar de autofirmado.

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

if (-not (Test-Path $Conf)) { throw "No se encuentra $Conf . Ejecuta antes 01-setup-server.ps1." }

& $VenvPy "$PSScriptRoot\gen_selfsigned_cert.py" $Certs $PublicHost "127.0.0.1" "localhost"

$cfg = Get-Content $Conf -Raw | ConvertFrom-Json
$cfg.tls_certfile = "$Certs\cert.pem"
$cfg.tls_keyfile  = "$Certs\key.pem"
$cfg.public_url   = "https://$PublicHost`:$Port"
[System.IO.File]::WriteAllText($Conf, ($cfg | ConvertTo-Json -Depth 12), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "TLS ON, public_url = https://$PublicHost`:$Port" -ForegroundColor Green

if (Get-Service $SvcName -ErrorAction SilentlyContinue) {
    Restart-Service $SvcName -Force; Start-Sleep -Seconds 2; Get-Service $SvcName
}

Write-Host "`nClientes: copia $Certs\cert.pem a cada cliente y pásalo al script de setup" -ForegroundColor Cyan
Write-Host "(fija ca_cert + verify_tls=true). Los nuevos configs de cliente usarán la URL https."
