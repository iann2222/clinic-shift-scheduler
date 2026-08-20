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
application["version"] = (
    (repository_root / "packaging" / "version.txt")
    .read_text(encoding="utf-8")
    .strip()
)
asset_directory = repository_root / packaging_config["build"]["asset_directory"]
font_directory = asset_directory / "fonts"
packaging_only_excludes = [
    "colorama",
    "iniconfig",
    "packaging",
    "pluggy",
    "pygments",
    "pytest",
    "setuptools",
    "wheel",
]

datas = collect_data_files(
    "clinic_shift_scheduler",
    includes=["schemas/*.json", "gui/styles/*.qss"],
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

scheduler_analysis = Analysis(
    [str(repository_root / application["entry_point"])],
    pathex=[str(repository_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[str(repository_root / "packaging" / "windows" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=packaging_only_excludes,
    noarchive=False,
    optimize=0,
)
scheduler_pyz = PYZ(scheduler_analysis.pure)

scheduler_exe = EXE(
    scheduler_pyz,
    scheduler_analysis.scripts,
    [],
    exclude_binaries=True,
    name=application["executable_name"],
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
editor = packaging_config["editor"]
editor_analysis = Analysis(
    [str(repository_root / editor["entry_point"])],
    pathex=[str(repository_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[str(repository_root / "packaging" / "windows" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=packaging_only_excludes,
    noarchive=False,
    optimize=0,
)
editor_pyz = PYZ(editor_analysis.pure)
editor_exe = EXE(
    editor_pyz,
    editor_analysis.scripts,
    [],
    exclude_binaries=True,
    name=editor["name"],
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=bool(editor["console"]),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="_internal",
)
coll = COLLECT(
    scheduler_exe,
    editor_exe,
    scheduler_analysis.binaries,
    scheduler_analysis.datas,
    editor_analysis.binaries,
    editor_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=application["name"],
)
