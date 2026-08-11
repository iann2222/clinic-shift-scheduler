"""Keep a user-owned frozen console visible after an application run."""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable
from ctypes import wintypes


NO_PAUSE_ENVIRONMENT_VARIABLE = "CLINIC_SCHEDULER_NO_PAUSE"


def _windows_console_process_count() -> int | None:
    """Return processes attached to this Windows console, if available."""

    try:
        process_ids = (wintypes.DWORD * 2)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(process_ids, 2)
    except (AttributeError, OSError):
        return None
    return int(count) if count else None


def should_pause_after_run(
    *,
    frozen: bool | None = None,
    platform_name: str | None = None,
    console_process_count: int | None = None,
    no_pause: bool | None = None,
) -> bool:
    """Return whether a double-clicked frozen console should wait for input."""

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    current_platform = os.name if platform_name is None else platform_name
    pause_disabled = (
        os.environ.get(NO_PAUSE_ENVIRONMENT_VARIABLE) == "1"
        if no_pause is None
        else no_pause
    )
    if not is_frozen or current_platform != "nt" or pause_disabled:
        return False
    process_count = (
        _windows_console_process_count()
        if console_process_count is None
        else console_process_count
    )
    return process_count == 1


def pause_after_run_if_needed(
    *,
    input_function: Callable[[str], str] = input,
) -> None:
    """Wait for Enter only when the executable owns its Windows console."""

    if not should_pause_after_run():
        return
    try:
        input_function("\n[執行] 排班程序已結束，按 Enter 關閉視窗...")
    except (EOFError, KeyboardInterrupt):
        pass
