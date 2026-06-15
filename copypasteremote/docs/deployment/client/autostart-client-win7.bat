@echo off
REM autostart-client-win7.bat  --  Windows 7 x64. Arranca el cliente al iniciar sesion.
REM Registra una tarea programada al logon con privilegios elevados (recomendado para que
REM funcionen los hotkeys globales). Usa pythonw.exe para que no aparezca consola.
REM
REM Uso:    autostart-client-win7.bat   (ejecutar desde un CMD elevado)
REM Quitar: schtasks /Delete /TN "CopyPasteRemote Client" /F

setlocal
set "PYW=C:\CopyPasteRemote\venv\Scripts\pythonw.exe"
set "SCRIPT=C:\CopyPasteRemote\src\copypasteremote\run_client.py"
set "NAME=CopyPasteRemote Client"

if not exist "%PYW%" (
  echo ERROR: no existe %PYW% . Ejecuta antes setup-client-win7.bat.
  exit /b 1
)

schtasks /Create /TN "%NAME%" /TR "\"%PYW%\" \"%SCRIPT%\"" /SC ONLOGON /RL HIGHEST /F
if errorlevel 1 (
  echo Fallo al crear la tarea. Ejecuta este .bat desde un CMD como administrador.
  exit /b 1
)
echo Tarea "%NAME%" creada: arranca al logon, elevada.
echo (Alternativa sin elevacion: pon un acceso directo a pythonw + run_client.py en shell:startup.)
endlocal
