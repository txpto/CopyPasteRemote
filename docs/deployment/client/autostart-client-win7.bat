@echo off
REM autostart-client-win7.bat  --  Windows 7 x64. Start the tray client at logon.
REM Registers a logon Scheduled Task with highest privileges (recommended so global
REM hotkeys work). Uses pythonw.exe so no console window appears.
REM
REM Usage:  autostart-client-win7.bat
REM Remove: schtasks /Delete /TN "CopyPasteRemote Client" /F

setlocal
set "PYW=C:\CopyPasteRemote-client\venv\Scripts\pythonw.exe"
set "SCRIPT=C:\CopyPasteRemote-client\src\copypasteremote\run_client.py"
set "NAME=CopyPasteRemote Client"

if not exist "%PYW%" (
  echo ERROR: %PYW% not found. Run setup-client-win7.bat first.
  exit /b 1
)

schtasks /Create /TN "%NAME%" /TR "\"%PYW%\" \"%SCRIPT%\"" /SC ONLOGON /RL HIGHEST /F
if errorlevel 1 (
  echo Failed to create the task. Try running this from an elevated CMD.
  exit /b 1
)
echo Scheduled task "%NAME%" created: runs at logon, elevated.
echo (Alternative without elevation: put a shortcut to pythonw + run_client.py in shell:startup.)
endlocal
