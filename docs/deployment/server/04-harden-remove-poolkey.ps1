# 04-harden-remove-poolkey.ps1  —  run as Administrator on the server (Windows).
# Hardening: removes the pool key from server-config.json to return to "zero-knowledge"
# mode (a server compromise can no longer decrypt anything).
#
# Run this ONLY AFTER you have emitted the client configs (01-setup-server.ps1), because
# add-machine needs the pool key to write them. To emit more configs later, restore the
# pool key temporarily.

$ErrorActionPreference = "Stop"

$Root    = "C:\CopyPasteRemote"
$Conf    = "$Root\server-config.json"
$SvcName = "CopyPasteRemoteServer"

if (-not (Test-Path $Conf)) { throw "$Conf not found." }

$cfg = Get-Content $Conf -Raw | ConvertFrom-Json
if (-not $cfg.pool_key_b64) {
    Write-Host "Pool key already empty in the config. Nothing to do." -ForegroundColor Yellow
} else {
    $cfg.pool_key_b64 | Set-Content "$Root\POOL_KEY_BACKUP.txt" -Encoding ascii
    $cfg.pool_key_b64 = ""
    $cfg | ConvertTo-Json -Depth 12 | Set-Content $Conf -Encoding utf8
    Write-Host "pool_key_b64 removed from the config." -ForegroundColor Green
    Write-Host "Backup at $Root\POOL_KEY_BACKUP.txt -> store it OFFLINE, then delete it from the VM." -ForegroundColor Yellow
}

if (Get-Service $SvcName -ErrorAction SilentlyContinue) {
    Restart-Service $SvcName -Force; Start-Sleep -Seconds 2; Get-Service $SvcName
}
