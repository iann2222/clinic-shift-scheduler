# -*- mode: python ; coding: utf-8 -*-

import json
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


repository_root = Path(SPECPATH).resolve().parents[1]
packaging_config = json.loads(
    (repository_root / "packaging" / "config_packaging.json").read_text(
        encoding="utf-8"
    )
)
application = packaging_config["application"]
asset_directory = repository_root / packaging_config["build"]["asset_directory"]
font_directory = asset_directory / "fonts"

datas = collect_data_files(
    "clinic_shift_scheduler",
    includes=["schemas/*.json"],
)
datas += [
    (
        str(font_directory / "NotoSansTC-Regular.ttf"),
        "clinic_shift_scheduler/resources/fonts",
    ),
    (
        str(font_directory / "NotoSansTC-Bold.ttf"),
        "clinic_shift_scheduler/resources/fonts",
    ),
]

a = Analysis(
    [str(repository_root / application["entry_point"])],
    pathex=[str(repository_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[str(repository_root / "packaging" / "windows" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=application["name"],
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=bool(application["console"]),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="_internal",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=application["name"],
)
