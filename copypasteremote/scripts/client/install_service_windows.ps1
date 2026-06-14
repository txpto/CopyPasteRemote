<#
.SYNOPSIS
    Install the CopyPasteRemote CLIENT as an auto-starting Windows Service.

.DESCRIPTION
    The client needs the interactive desktop (clipboard, hotkeys, tray), so this
    installs a LocalSystem *launcher* service (cpr_client.winservice) that starts
    the real client GUI inside the active user session and relaunches it on logon.

    > Simpler alternative that also auto-starts: the per-user logon Scheduled Task
    > in install_task.ps1. Prefer that unless you specifically need a service.

    Run from the project root (copypasteremote/) in an ELEVATED prompt.

.PARAMETER ServicePython
    Python interpreter with pywin32 installed (hosts the service). Default "python".

.PARAMETER ExePath
    Path to a packaged CopyPasteRemote.exe to launch. Use this OR -RepoPath.

.PARAMETER RepoPath
    Project root containing run_client.py (used with -ClientPythonw).

.PARAMETER ClientPythonw
    pythonw.exe used to run run_client.py (with -RepoPath). Default "pythonw".

.EXAMPLE
    .\install_service_windows.ps1 -ServicePython C:\Python38\python.exe `
        -ExePath C:\CopyPasteRemote\CopyPasteRemote.exe

.EXAMPLE
    .\install_service_windows.ps1 -ServicePython C:\Python38\python.exe `
        -RepoPath C:\CopyPasteRemote -ClientPythonw C:\Python38\pythonw.exe
#>
param(
    [string]$ServicePython = "python",
    [string]$ExePath,
    [string]$RepoPath,
    [string]$ClientPythonw = "pythonw"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path .).Path

if ($ExePath) {
    if (-not (Test-Path $ExePath)) { throw "ExePath not found: $ExePath" }
    $cmd = "`"$ExePath`""
    $cwd = Split-Path $ExePath
}
elseif ($RepoPath) {
    $script = Join-Path $RepoPath "run_client.py"
    if (-not (Test-Path $script)) { throw "run_client.py not found in $RepoPath" }
    $cmd = "`"$ClientPythonw`" `"$script`""
    $cwd = $RepoPath
}
else {
    throw "Provide either -ExePath or -RepoPath."
}

[Environment]::SetEnvironmentVariable("CPR_CLIENT_CMD", $cmd, "Machine")
[Environment]::SetEnvironmentVariable("CPR_CLIENT_CWD", $cwd, "Machine")
$env:CPR_CLIENT_CMD = $cmd
$env:CPR_CLIENT_CWD = $cwd
Write-Host "Set CPR_CLIENT_CMD=$cmd"
Write-Host "Set CPR_CLIENT_CWD=$cwd"

Write-Host "Installing launcher service (ensure: $ServicePython -m pip install pywin32)..."
& $ServicePython -m cpr_client.winservice --startup auto install
& $ServicePython -m cpr_client.winservice start
Write-Host "Installed and started CopyPasteRemoteClient launcher (auto-start at boot/logon)."
Write-Host "Verify with:  sc.exe query CopyPasteRemoteClient"
