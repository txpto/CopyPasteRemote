# autostart-client.ps1  —  Windows 10/11. Make the tray client start at logon.
#
# Two modes:
#   (default)   creates a shortcut in the Startup folder (runs WITHOUT elevation)
#   -Elevated   registers a logon Scheduled Task with highest privileges
#               (recommended: global hotkeys via the 'keyboard' lib usually need admin)
#
# Usage:
#   .\autostart-client.ps1 -PkgDir "<path>\copypasteremote"            # Startup shortcut
#   .\autostart-client.ps1 -PkgDir "<path>\copypasteremote" -Elevated  # elevated task

param(
    [Parameter(Mandatory=$true)] [string] $PkgDir,
    [switch] $Elevated
)
$ErrorActionPreference = "Stop"

$PyW    = "$env:LOCALAPPDATA\CopyPasteRemote\venv\Scripts\pythonw.exe"
$Script = "$PkgDir\run_client.py"
$Name   = "CopyPasteRemote Client"

if (-not (Test-Path $PyW))    { throw "pythonw not found at $PyW (run setup-client.ps1 first)." }
if (-not (Test-Path $Script)) { throw "run_client.py not found at $Script." }

if ($Elevated) {
    $tr = '"{0}" "{1}"' -f $PyW, $Script
    schtasks /Create /TN $Name /TR $tr /SC ONLOGON /RL HIGHEST /F | Out-Null
    Write-Host "Scheduled task '$Name' created: runs at logon, elevated." -ForegroundColor Green
    Write-Host "Remove with:  schtasks /Delete /TN `"$Name`" /F"
} else {
    $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) "$Name.lnk"
    $ws  = New-Object -ComObject WScript.Shell
    $sc  = $ws.CreateShortcut($lnk)
    $sc.TargetPath       = $PyW
    $sc.Arguments        = '"{0}"' -f $Script
    $sc.WorkingDirectory = $PkgDir
    $sc.WindowStyle      = 7          # minimized / no console
    $sc.Description      = "CopyPasteRemote tray client"
    $sc.Save()
    Write-Host "Startup shortcut created: $lnk" -ForegroundColor Green
    Write-Host "Runs WITHOUT admin. If global hotkeys don't work, re-run with -Elevated."
    Write-Host "Remove by deleting that .lnk."
}
