# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from importlib.util import find_spec

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH)

flet_datas = collect_data_files("flet")
flet_binaries, flet_hidden = [], []
if find_spec("flet_desktop") is not None:
    desktop_datas, desktop_binaries, desktop_hidden = collect_all("flet_desktop")
else:
    desktop_datas, desktop_binaries, desktop_hidden = [], [], []

hiddenimports = sorted(set(
    flet_hidden
    + desktop_hidden
    + collect_submodules("mutagen")
    + [
        "aiohttp",
        "aiofiles",
        "yarl",
        "sqlite3",
        "pystray",
        "PIL",
    ]
))

datas = flet_datas + desktop_datas + [
    (str(ROOT / "config.example.json"), "."),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
]

binaries = flet_binaries + desktop_binaries

analysis = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tests"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ARSM-Suite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(ROOT / "packaging" / "windows_version_info.txt"),
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ARSM-Suite",
)
