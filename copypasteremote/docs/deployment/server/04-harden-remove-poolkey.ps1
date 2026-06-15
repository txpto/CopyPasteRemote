# 04-harden-remove-poolkey.ps1  —  ejecutar como Administrador en el servidor (Windows).
# Endurecimiento: quita la pool key de server-config.json para volver al modo
# "zero-knowledge" (un compromiso del servidor ya no podrá descifrar nada).
#
# Ejecútalo SOLO DESPUÉS de haber emitido los configs de cliente (01-setup-server.ps1),
# porque add-machine necesita la pool key para escribirlos. Para emitir más configs más
# adelante, repón la pool key temporalmente.

$ErrorActionPreference = "Stop"

$Root    = "C:\CopyPasteRemote"
$Conf    = "$Root\server-config.json"
$SvcName = "CopyPasteRemoteServer"

if (-not (Test-Path $Conf)) { throw "No se encuentra $Conf ." }

$cfg = Get-Content $Conf -Raw | ConvertFrom-Json
if (-not $cfg.pool_key_b64) {
    Write-Host "La pool key ya está vacía en el config. Nada que hacer." -ForegroundColor Yellow
} else {
    $cfg.pool_key_b64 | Set-Content "$Root\POOL_KEY_BACKUP.txt" -Encoding ascii
    $cfg.pool_key_b64 = ""
    [System.IO.File]::WriteAllText($Conf, ($cfg | ConvertTo-Json -Depth 12), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "pool_key_b64 eliminada del config." -ForegroundColor Green
    Write-Host "Respaldo en $Root\POOL_KEY_BACKUP.txt -> guárdalo OFFLINE y luego bórralo de la VM." -ForegroundColor Yellow
}

if (Get-Service $SvcName -ErrorAction SilentlyContinue) {
    Restart-Service $SvcName -Force; Start-Sleep -Seconds 2; Get-Service $SvcName
}
