# autostart-client.ps1  —  Windows 10/11. Arranca el cliente de bandeja al iniciar sesión.
#
# Dos modos:
#   (por defecto)  crea un acceso directo en la carpeta Inicio (SIN elevación)
#   -Elevated      registra una tarea programada al logon con privilegios elevados
#                  (recomendado: los hotkeys globales de la librería 'keyboard' suelen
#                   necesitar permisos de administrador)
#
# Uso:
#   .\autostart-client.ps1 -PkgDir "<ruta>\copypasteremote"            # acceso directo
#   .\autostart-client.ps1 -PkgDir "<ruta>\copypasteremote" -Elevated  # tarea elevada

param(
    [Parameter(Mandatory=$true)] [string] $PkgDir,
    [switch] $Elevated
)
$ErrorActionPreference = "Stop"

$PyW    = "$env:LOCALAPPDATA\CopyPasteRemote\venv\Scripts\pythonw.exe"
$Script = "$PkgDir\run_client.py"
$Name   = "CopyPasteRemote Client"

if (-not (Test-Path $PyW))    { throw "No se encuentra pythonw en $PyW (ejecuta antes setup-client.ps1)." }
if (-not (Test-Path $Script)) { throw "No se encuentra run_client.py en $Script." }

if ($Elevated) {
    $tr = '"{0}" "{1}"' -f $PyW, $Script
    schtasks /Create /TN $Name /TR $tr /SC ONLOGON /RL HIGHEST /F | Out-Null
    Write-Host "Tarea '$Name' creada: arranca al logon, elevada." -ForegroundColor Green
    Write-Host "Quitar con:  schtasks /Delete /TN `"$Name`" /F"
} else {
    $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) "$Name.lnk"
    $ws  = New-Object -ComObject WScript.Shell
    $sc  = $ws.CreateShortcut($lnk)
    $sc.TargetPath       = $PyW
    $sc.Arguments        = '"{0}"' -f $Script
    $sc.WorkingDirectory = $PkgDir
    $sc.WindowStyle      = 7          # minimizado / sin consola
    $sc.Description      = "Cliente de bandeja CopyPasteRemote"
    $sc.Save()
    Write-Host "Acceso directo creado: $lnk" -ForegroundColor Green
    Write-Host "Arranca SIN admin. Si los hotkeys globales no funcionan, relanza con -Elevated."
    Write-Host "Quitar borrando ese .lnk."
}
