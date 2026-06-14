@echo off
REM Build the CopyPasteRemote client .exe with PyInstaller.
REM Run from the repository ROOT on a Windows machine:
REM     scripts\client\build_exe.bat
REM
REM For a Windows 7-compatible binary, build on Windows 7 x64 with Python 3.8.10.

setlocal
echo === Installing build dependencies ===
python -m pip install --upgrade pip
python -m pip install -r requirements-client.txt pyinstaller || goto :error

echo === Building executable ===
pyinstaller --noconfirm --clean scripts\client\cpr_client.spec || goto :error

echo.
echo Done. The executable is at: dist\CopyPasteRemote.exe
echo Copy it to the target machine together with its config.json.
goto :eof

:error
echo.
echo BUILD FAILED. See the output above.
exit /b 1
