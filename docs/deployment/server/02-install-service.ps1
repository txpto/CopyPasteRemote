# 02-install-service.ps1  —  run as Administrator on the server (Windows).
# Installs run_server.py as a Windows service via NSSM (https://nssm.cc/).
# Put nssm.exe in PATH or next to this script.

$ErrorActionPreference = "Stop"

$Root    = "C:\CopyPasteRemote"
$Pkg     = "$Root\src\copypasteremote"
$VenvPy  = "$Root\venv\Scripts\python.exe"
$Conf    = "$Root\server-config.json"
$Logs    = "$Root\logs"
$SvcName = "CopyPasteRemoteServer"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

$Nssm = (Get-Command nssm.exe -ErrorAction SilentlyContinue).Source
if (-not $Nssm) { $Nssm = Join-Path $PSScriptRoot "nssm.exe" }
if (-not (Test-Path $Nssm)) { throw "nssm.exe not found. Download it from https://nssm.cc/." }

if (Get-Service $SvcName -ErrorAction SilentlyContinue) {
    & $Nssm stop $SvcName
    & $Nssm remove $SvcName confirm
}

& $Nssm install $SvcName $VenvPy "run_server.py --config `"$Conf`""
& $Nssm set $SvcName AppDirectory $Pkg            # so cpr_server/cpr_shared are importable
& $Nssm set $SvcName DisplayName "CopyPasteRemote Server"
& $Nssm set $SvcName Start SERVICE_AUTO_START
& $Nssm set $SvcName AppStdout "$Logs\server.log"
& $Nssm set $SvcName AppStderr "$Logs\server.err.log"
& $Nssm set $SvcName AppRotateFiles 1
& $Nssm set $SvcName AppExit Default Restart
& $Nssm set $SvcName AppRestartDelay 5000

& $Nssm start $SvcName
Start-Sleep -Seconds 2
Get-Service $SvcName
Write-Host "Check: Get-Content $Logs\server.log -Tail 20 ; Test-NetConnection 127.0.0.1 -Port 8765" -ForegroundColor Green
