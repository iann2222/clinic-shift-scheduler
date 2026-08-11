"""Command-line interface for a complete clinic scheduling run."""

from __future__ import annotations

import argparse
import sys
import threading
import unicodedata
from pathlib import Path
from time import perf_counter
from typing import Sequence, TextIO

from .errors import InputValidationError
from .optimization import (
    EquivalentSolutionDiagnosticConfig,
    EquivalentSolutionDiagnosticResult,
    EquivalentSolutionDiagnosticStatus,
)
from .runner import CandidateExportConfig, ScheduleRunError, run_schedule_file
from .time_formatting import format_seconds, format_seconds_with_minutes


_OPTIMIZATION_HEARTBEAT_PREFIX = "嚴格分階段最佳化進行中："
_CANDIDATE_COUNT_PROGRESS_PREFIX = "已找到 "


def _terminal_width(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 1
        for character in text
    )


class _ConsoleProgressPrinter:
    """Print heartbeat messages in place on interactive terminals."""

    def __init__(self, label: str, stream: TextIO | None = None) -> None:
        self._label = label
        self._stream = stream or sys.stdout
        self._interactive = self._stream.isatty()
        self._active_width = 0
        self._lock = threading.Lock()

    def _clear_active_line(self) -> None:
        if self._active_width:
            self._stream.write("\r" + " " * self._active_width + "\r")
            self._active_width = 0

    def __call__(self, message: str) -> None:
        rendered = f"{self._label} {message}"
        is_heartbeat = message.startswith(
            (_OPTIMIZATION_HEARTBEAT_PREFIX, _CANDIDATE_COUNT_PROGRESS_PREFIX)
        )
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clinic-shift-scheduler",
        description=(
            "從 JSON 輸入完成驗證、前置檢查、最佳化、獨立驗證及正式輸出。"
        ),
    )
    parser.add_argument("input", type=Path, help="weekly-v1 或 canonical v1 JSON")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="輸出資料夾（預設：output）",
    )
    parser.add_argument(
        "--intermediate-dir",
        type=Path,
        default=Path("runtime/expanded-input"),
        help="逐日 canonical 中間輸入資料夾（預設：runtime/expanded-input）",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允許覆寫同月份既有的正式輸出",
    )
    parser.add_argument(
        "--equivalent-limit",
        type=int,
        default=100,
        help="最多搜尋幾份正式班表以外的同品質候選（預設：100）",
    )
    parser.add_argument(
        "--equivalent-time-limit",
        type=float,
        default=None,
        help=(
            "候選班表診斷總秒數上限"
            "（預設：本次 CP-SAT 最佳化時間的 1/5）"
        ),
    )
    parser.add_argument(
        "--equivalent-time-ratio",
        type=float,
        default=0.2,
        help="未指定固定秒數時，候選診斷時間相對於最佳化時間的比例（預設：0.2）",
    )
    parser.add_argument(
        "--skip-equivalent-diagnostic",
        action="store_true",
        help="正式輸出完成後不搜尋同品質候選班表",
    )
    parser.add_argument(
        "--candidate-export-count",
        type=int,
        default=0,
        help="額外保存幾份找到的同品質候選班表（預設：0）",
    )
    parser.add_argument(
        "--candidate-export-formats",
        nargs="+",
        choices=("json", "excel", "pdf"),
        default=("json",),
        help="候選班表輸出格式（可複選；預設：json）",
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=5.0,
        help="最佳化進度更新秒數（預設：5）",
    )
    return parser


def _equivalent_diagnostic_message(
    diagnostic: EquivalentSolutionDiagnosticResult,
) -> str:
    count = diagnostic.alternative_count
    if diagnostic.status is EquivalentSolutionDiagnosticStatus.EXACT_COUNT:
        return f"已證明正式班表以外另有 {count} 份同品質候選班表。"
    if diagnostic.status is EquivalentSolutionDiagnosticStatus.AT_LEAST_LIMIT:
        return (
            f"已找到至少 {count} 份同品質候選班表；已達搜尋上限，"
            "未證明是否還有更多候選。"
        )
    if count == 0:
        prefix = "目前尚未找到其他同品質候選班表"
    else:
        prefix = f"已找到至少 {count} 份同品質候選班表"
    if diagnostic.status is EquivalentSolutionDiagnosticStatus.INTERRUPTED:
        return f"{prefix}；診斷已由使用者中止，未證明是否還有更多候選。"
    return f"{prefix}；搜尋時間不足，未證明是否還有更多候選。"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.skip_equivalent_diagnostic and args.candidate_export_count:
        parser.error("候選診斷停用時，候選輸出份數必須為 0")
    if args.candidate_export_count > args.equivalent_limit:
        parser.error("候選輸出份數不可超過候選搜尋上限")
    command_started = perf_counter()
    schedule_progress = _ConsoleProgressPrinter("[排班]")
    diagnostic_progress = _ConsoleProgressPrinter("[候選處理]")
    try:
        diagnostic_config = (
            None
            if args.skip_equivalent_diagnostic
            else EquivalentSolutionDiagnosticConfig(
                max_alternatives=args.equivalent_limit,
                max_time_seconds=args.equivalent_time_limit,
                scheduling_time_ratio=args.equivalent_time_ratio,
            )
        )
        result = run_schedule_file(
            args.input,
            output_directory=args.output_dir,
            intermediate_directory=args.intermediate_dir,
            overwrite=args.overwrite,
            equivalent_solution_diagnostic_config=diagnostic_config,
            candidate_export_config=CandidateExportConfig(
                max_candidates=args.candidate_export_count,
                formats=tuple(args.candidate_export_formats),
            ),
            progress_interval_seconds=args.progress_interval,
            progress=schedule_progress,
            diagnostic_progress=diagnostic_progress,
        )
    except (InputValidationError, ScheduleRunError, OSError, ValueError) as error:
        schedule_progress.finish()
        diagnostic_progress.finish()
        print(f"[排班] 執行失敗：{error}", file=sys.stderr)
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
            + _equivalent_diagnostic_message(
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
