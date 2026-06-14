<#
.SYNOPSIS
    Remove the CopyPasteRemote logon task.
#>
$ErrorActionPreference = "Stop"
$TaskName = "CopyPasteRemote"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
} else {
    Write-Host "Task '$TaskName' not found; nothing to do."
}
