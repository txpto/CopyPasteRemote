<#
.SYNOPSIS
    Install the CopyPasteRemote ORCHESTRATOR as an auto-starting Windows Service.

.DESCRIPTION
    Two backends:
      * pywin32 (default): registers cpr_server.winservice as a service.
      * NSSM (-UseNSSM): wraps run_server.py with the Non-Sucking Service Manager.

    Run from the project root (the copypasteremote/ folder) in an ELEVATED prompt.

.PARAMETER PythonExe
    Python interpreter that has the server deps + pywin32 installed. Default "python".

.PARAMETER ConfigPath
    Path to server-config.json. Stored as the machine env var CPR_SERVER_CONFIG.

.PARAMETER UseNSSM
    Use NSSM instead of pywin32.

.PARAMETER NssmPath
    Path to nssm.exe (with -UseNSSM).

.EXAMPLE
    .\install_service_windows.ps1 -PythonExe C:\Python311\python.exe -ConfigPath C:\cpr\server-config.json
#>
param(
    [string]$PythonExe = "python",
    [string]$ConfigPath = "$(Resolve-Path .)\server-config.json",
    [switch]$UseNSSM,
    [string]$NssmPath = "nssm.exe"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path .).Path

if ($ConfigPath) {
    [Environment]::SetEnvironmentVariable("CPR_SERVER_CONFIG", $ConfigPath, "Machine")
    $env:CPR_SERVER_CONFIG = $ConfigPath
    Write-Host "Set machine env CPR_SERVER_CONFIG=$ConfigPath"
}

if ($UseNSSM) {
    & $NssmPath install CopyPasteRemoteServer $PythonExe "$root\run_server.py"
    & $NssmPath set CopyPasteRemoteServer AppDirectory $root
    & $NssmPath set CopyPasteRemoteServer Start SERVICE_AUTO_START
    & $NssmPath set CopyPasteRemoteServer AppEnvironmentExtra "CPR_SERVER_CONFIG=$ConfigPath"
    & $NssmPath start CopyPasteRemoteServer
    Write-Host "Installed CopyPasteRemoteServer via NSSM (auto-start)."
}
else {
    Write-Host "Installing pywin32 service (ensure: $PythonExe -m pip install pywin32)..."
    & $PythonExe -m cpr_server.winservice --startup auto install
    & $PythonExe -m cpr_server.winservice start
    Write-Host "Installed and started CopyPasteRemoteServer (auto-start)."
}
Write-Host "Verify with:  sc.exe query CopyPasteRemoteServer   and  curl http://localhost:8765/api/health"
