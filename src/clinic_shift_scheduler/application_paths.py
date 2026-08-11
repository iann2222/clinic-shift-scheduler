"""Resolve writable application paths in source and frozen executions."""

from __future__ import annotations

import sys
from pathlib import Path


def application_root(
    entry_file: str | Path,
    *,
    frozen: bool | None = None,
    executable: str | Path | None = None,
) -> Path:
    """Return the directory that owns config, input, output, and runtime.

    Source executions use the repository root above ``src``. PyInstaller
    executions use the directory containing the user-visible executable.
    Explicit arguments keep this boundary deterministic in tests.
    """

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        executable_path = Path(executable or sys.executable)
        return executable_path.resolve().parent
    return Path(entry_file).resolve().parent.parent
