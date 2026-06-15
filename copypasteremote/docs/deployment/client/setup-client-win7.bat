@echo off
REM setup-client-win7.bat  --  cliente Windows 7 x64.
REM Requisito previo: instalar Python 3.8.10 (64-bit) y marcar "Add to PATH".
REM   https://www.python.org/downloads/release/python-3810/  (instalador Windows x86-64)
REM Uso:
REM   setup-client-win7.bat "<ruta>\client-config.json" ["<ruta>\cert.pem"]
REM   (el 2o argumento, el cert del servidor, es opcional y activa la verificacion TLS)

setlocal
if "%~1"=="" (
  echo ERROR: pasa la ruta del JSON de configuracion del cliente.
  echo   setup-client-win7.bat "<ruta>\client-config.json" ["<ruta>\cert.pem"]
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

echo == Comprobando Python 3.8 ==
py -3.8 --version
if errorlevel 1 (
  echo ERROR: no se encuentra Python 3.8. Instalalo desde:
  echo   https://www.python.org/downloads/release/python-3810/
  exit /b 1
)

echo == Obteniendo el codigo ==
if not exist "%PKG%" (
  git --version >nul 2>&1
  if errorlevel 1 (
    echo No hay git. Descarga el ZIP del repo desde %REPO% , descomprimelo en
    echo   %SRC%  (de modo que exista %PKG%\run_client.py ) y vuelve a ejecutar.
    exit /b 1
  )
  git clone %REPO% "%SRC%"
)

echo == Creando venv e instalando dependencias (fijadas para Win7) ==
if not exist "%VENVPY%" py -3.8 -m venv "%VENV%"
"%VENVPY%" -m pip install --upgrade pip
"%VENVPY%" -m pip install -r "%PKG%\requirements-client.txt"

echo == Colocando el config del cliente ==
if not exist "%CFGDIR%" mkdir "%CFGDIR%"
copy /Y "%CFGSRC%" "%CFGDIR%\config.json"

if not "%CASRC%"=="" (
  echo == Activando TLS con el certificado del servidor ==
  copy /Y "%CASRC%" "%CFGDIR%\cpr-cert.pem"
  "%VENVPY%" -c "import json,sys; p=sys.argv[1]; d=json.load(open(p)); d['ca_cert']=sys.argv[2]; d['verify_tls']=True; json.dump(d,open(p,'w'),indent=2)" "%CFGDIR%\config.json" "%CFGDIR%\cpr-cert.pem"
)

echo == Probando la conexion con el servidor ==
pushd "%PKG%"
"%VENVPY%" run_client.py --check
popd

echo.
echo Si el check fue OK, arranca el cliente de bandeja (COMO ADMINISTRADOR para hotkeys globales):
echo   "%VENVPY%" "%PKG%\run_client.py"
endlocal
