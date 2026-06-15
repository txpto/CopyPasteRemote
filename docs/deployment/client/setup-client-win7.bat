@echo off
REM setup-client-win7.bat  --  Windows 7 x64 client.
REM Prereq: install Python 3.8.10 (64-bit) and tick "Add to PATH".
REM   https://www.python.org/downloads/release/python-3810/  (Windows x86-64 installer)
REM Usage:
REM   setup-client-win7.bat "<path>\client-config.json" ["<path>\cert.pem"]
REM   (2nd arg, the server cert, is optional and enables TLS verification)

setlocal
if "%~1"=="" (
  echo ERROR: pass the path to the client config JSON.
  echo   setup-client-win7.bat "<path>\client-config.json" ["<path>\cert.pem"]
  exit /b 1
)
set "CFGSRC=%~1"
set "CASRC=%~2"

set "ROOT=C:\CopyPasteRemote-client"
set "SRC=%ROOT%\src"
set "PKG=%SRC%\copypasteremote"
set "VENV=%ROOT%\venv"
set "VENVPY=%VENV%\Scripts\python.exe"
set "REPO=https://github.com/txpto/CopyPasteRemote"
set "CFGDIR=%APPDATA%\CopyPasteRemote"

if not exist "%ROOT%" mkdir "%ROOT%"

echo == Checking Python 3.8 ==
py -3.8 --version
if errorlevel 1 (
  echo ERROR: Python 3.8 not found. Install it from:
  echo   https://www.python.org/downloads/release/python-3810/
  exit /b 1
)

echo == Fetching the code ==
if not exist "%PKG%" (
  git --version >nul 2>&1
  if errorlevel 1 (
    echo No git. Download the repo ZIP from %REPO% , unzip into
    echo   %SRC%  (so that %PKG%\run_client.py exists ) and re-run.
    exit /b 1
  )
  git clone %REPO% "%SRC%"
)

echo == Creating venv and installing deps (pinned for Win7) ==
if not exist "%VENVPY%" py -3.8 -m venv "%VENV%"
"%VENVPY%" -m pip install --upgrade pip
"%VENVPY%" -m pip install -r "%PKG%\requirements-client.txt"

echo == Placing the client config ==
if not exist "%CFGDIR%" mkdir "%CFGDIR%"
copy /Y "%CFGSRC%" "%CFGDIR%\config.json"

if not "%CASRC%"=="" (
  echo == Enabling TLS with the server certificate ==
  copy /Y "%CASRC%" "%CFGDIR%\cpr-cert.pem"
  "%VENVPY%" -c "import json,sys; p=sys.argv[1]; d=json.load(open(p)); d['ca_cert']=sys.argv[2]; d['verify_tls']=True; json.dump(d,open(p,'w'),indent=2)" "%CFGDIR%\config.json" "%CFGDIR%\cpr-cert.pem"
)

echo == Testing the connection ==
pushd "%PKG%"
"%VENVPY%" run_client.py --check
popd

echo.
echo If the check passed, run the tray client (AS ADMINISTRATOR for global hotkeys):
echo   "%VENVPY%" "%PKG%\run_client.py"
endlocal
