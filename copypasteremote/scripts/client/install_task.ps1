<#
.SYNOPSIS
    Install CopyPasteRemote to start automatically when the user logs in.

.DESCRIPTION
    The client must run in the interactive user session (it needs the clipboard,
    keyboard and tray), so we register a per-user Scheduled Task that runs at logon
    instead of a Windows service.

.PARAMETER ExePath
    Path to CopyPasteRemote.exe (a PyInstaller build). Use this OR -PythonExe.

.PARAMETER PythonExe
    Path to pythonw.exe to run the script form. Defaults to "pythonw".

.PARAMETER RepoPath
    Path to the repository (where run_client.py lives), used with -PythonExe.

.PARAMETER Highest
    Run with highest privileges so paste works into elevated/UAC apps.

.EXAMPLE
    # Packaged exe:
    .\install_task.ps1 -ExePath "C:\CopyPasteRemote\CopyPasteRemote.exe"

.EXAMPLE
    # From source with Python:
    .\install_task.ps1 -PythonExe "C:\Python38\pythonw.exe" -RepoPath "C:\CopyPasteRemote"
#>
param(
    [string]$ExePath,
    [string]$PythonExe = "pythonw",
    [string]$RepoPath,
    [switch]$Highest
)

$ErrorActionPreference = "Stop"
$TaskName = "CopyPasteRemote"

if ($ExePath) {
    if (-not (Test-Path $ExePath)) { throw "ExePath not found: $ExePath" }
    $action = New-ScheduledTaskAction -Execute $ExePath
}
elseif ($RepoPath) {
    $script = Join-Path $RepoPath "run_client.py"
    if (-not (Test-Path $script)) { throw "run_client.py not found in $RepoPath" }
    $action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$script`"" -WorkingDirectory $RepoPath
}
else {
    throw "Provide either -ExePath or -RepoPath."
}

$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$level    = if ($Highest) { "Highest" } else { "Limited" }
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel $level

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "CopyPasteRemote shared-clipboard client (runs at logon)." | Out-Null

Write-Host "Installed scheduled task '$TaskName' (runs at logon, RunLevel=$level)."
Write-Host "Start it now with:  Start-ScheduledTask -TaskName $TaskName"
