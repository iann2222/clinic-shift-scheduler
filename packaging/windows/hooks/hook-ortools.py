"""Collect the native CP-SAT runtime shipped inside the OR-Tools wheel."""

from PyInstaller.utils.hooks import (
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


binaries = collect_dynamic_libs("ortools")
hiddenimports = collect_submodules("ortools.sat.python")
datas = copy_metadata("ortools")
