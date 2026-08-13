"""Console presentation adapter for the typed scheduling application service."""

from __future__ import annotations

import sys
import threading
import unicodedata
from time import perf_counter
from typing import TextIO

from .application import (
    ScheduleApplicationCallbacks,
    ScheduleApplicationError,
    ScheduleApplicationRequest,
    run_schedule_application,
)
from .events import ExecutionPhase, ProgressEvent, ProgressEventKind
from .optimization_contracts import (
    EquivalentSolutionDiagnosticResult,
    EquivalentSolutionDiagnosticStatus,
)
from .time_formatting import format_seconds, format_seconds_with_minutes


def _terminal_width(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 1
        for character in text
    )


class ConsoleProgressPrinter:
    """Print heartbeat messages in place on interactive terminals."""

    def __init__(
        self,
        label: str,
        stream: TextIO | None = None,
        *,
        step_started_suffix: str | None = None,
    ) -> None:
        self._label = label
        self._stream = stream or sys.stdout
        self._step_started_suffix = step_started_suffix
        self._interactive = self._stream.isatty()
        self._active_width = 0
        self._lock = threading.Lock()

    def _clear_active_line(self) -> None:
        if self._active_width:
            self._stream.write("\r" + " " * self._active_width + "\r")
            self._active_width = 0

    def __call__(self, event: ProgressEvent) -> None:
        message = event.message
        if (
            self._step_started_suffix
            and event.phase is ExecutionPhase.CANDIDATE_SEARCH
            and event.kind is ProgressEventKind.STEP_STARTED
        ):
            message = f"{message}；{self._step_started_suffix}"
        rendered = f"{self._label} {message}"
        is_heartbeat = event.kind in {
            ProgressEventKind.HEARTBEAT,
            ProgressEventKind.CANDIDATE_COUNT,
        }
        with self._lock:
            if self._interactive and is_heartbeat:
                width = _terminal_width(rendered)
                padded_width = max(width, self._active_width)
                self._stream.write(
                    "\r" + rendered + " " * (padded_width - width)
                )
                self._active_width = padded_width
                self._stream.flush()
                return
            self._clear_active_line()
            print(rendered, file=self._stream, flush=True)

    def finish(self) -> None:
        with self._lock:
            self._clear_active_line()
            self._stream.flush()


def equivalent_diagnostic_message(
    diagnostic: EquivalentSolutionDiagnosticResult,
) -> str:
    """Render one completed candidate-search diagnostic."""

    count = diagnostic.alternative_count
    if diagnostic.status is EquivalentSolutionDiagnosticStatus.EXACT_COUNT:
        return f"已證明正式班表以外另有 {count} 份同品質候選班表。"
    if diagnostic.status is EquivalentSolutionDiagnosticStatus.AT_LEAST_LIMIT:
        return (
            f"已找到至少 {count} 份同品質候選班表；已達搜尋上限，"
            "未證明是否還有更多候選。"
        )
    prefix = (
        "目前尚未找到其他同品質候選班表"
        if count == 0
        else f"已找到至少 {count} 份同品質候選班表"
    )
    if diagnostic.status is EquivalentSolutionDiagnosticStatus.INTERRUPTED:
        return f"{prefix}；診斷已由使用者中止，未證明是否還有更多候選。"
    return f"{prefix}；搜尋時間不足，未證明是否還有更多候選。"


def run_schedule_request_with_console(
    request: ScheduleApplicationRequest,
) -> int:
    """Run one request and present progress, failures, and summary to console."""

    command_started = perf_counter()
    schedule_progress = ConsoleProgressPrinter("[排班]")
    diagnostic_progress = ConsoleProgressPrinter(
        "[候選處理]",
        step_started_suffix="按 Ctrl+C 可只終止候選處理",
    )
    try:
        result = run_schedule_application(
            request,
            ScheduleApplicationCallbacks(
                progress=schedule_progress,
                diagnostic_progress=diagnostic_progress,
            ),
        )
    except ScheduleApplicationError as error:
        schedule_progress.finish()
        diagnostic_progress.finish()
        print(f"[排班] 執行失敗：{error}", file=sys.stderr)
        for issue in error.issues:
            print(
                f"[排班] {issue.phase.value}/{issue.code} "
                f"{issue.path}：{issue.message}",
                file=sys.stderr,
            )
        print(
            "[排班] 失敗前總執行時間："
            f"{format_seconds(perf_counter() - command_started)}",
            file=sys.stderr,
        )
        return 1

    schedule_progress.finish()
    diagnostic_progress.finish()
    if result.equivalent_solution_diagnostic is not None:
        print(
            "[候選處理] 診斷時間："
            f"{format_seconds(result.equivalent_solution_diagnostic_seconds)}"
        )
        print(
            "[候選處理] 結果："
            + equivalent_diagnostic_message(
                result.equivalent_solution_diagnostic
            )
        )
    if result.candidate_exports:
        print(
            "[候選處理] 已輸出 "
            f"{len(result.candidate_exports)} 份候選班表至："
            f"{result.candidate_output_directory}"
        )
        print(
            "[候選處理] 候選輸出時間："
            f"{format_seconds(result.candidate_export_seconds)}"
        )
    print(
        "[執行] 總耗時（含完整排班與候選處理）："
        f"{format_seconds_with_minutes(result.total_execution_seconds)}"
    )
    return 0
