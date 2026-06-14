# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the CopyPasteRemote Windows client.
# Build (ideally on Windows 7 x64 with Python 3.8) from the repository root:
#
#     pip install -r requirements-client.txt pyinstaller
#     pyinstaller scripts/client/cpr_client.spec
#
# Produces dist/CopyPasteRemote.exe (a single windowed executable, no console).

import os

block_cipher = None

# Repository root (this spec lives in scripts/client/).
REPO = os.path.abspath(os.path.join(os.getcwd()))

a = Analysis(
    [os.path.join(REPO, "run_client.py")],
    pathex=[REPO],
    binaries=[],
    datas=[],
    hiddenimports=[
        # pystray picks its backend dynamically.
        "pystray._win32",
        "PIL.Image",
        "PIL.ImageDraw",
        # pywin32 bits used at runtime.
        "win32clipboard",
        "win32con",
        "win32api",
        "win32gui",
        "win32timezone",
        # transport / hotkeys backends.
        "websocket",
        "keyboard",
        "requests",
        # crypto backend (whichever is installed).
        "Crypto.Cipher.AES",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="CopyPasteRemote",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,   # windowed app (no console window)
    icon=None,
)
