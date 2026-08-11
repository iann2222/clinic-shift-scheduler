"""Command-line interface for a complete clinic scheduling run."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .application import ScheduleApplicationRequest
from .app_config import (
    DEFAULT_CANDIDATE_EXPORT_COUNT,
    DEFAULT_CANDIDATE_EXPORT_FORMATS,
    DEFAULT_CANDIDATE_SEARCH_LIMIT,
    DEFAULT_DIAGNOSTIC_TIME_RATIO,
    DEFAULT_PROGRESS_UPDATE_SECONDS,
)
from .console_app import run_schedule_request_with_console
from .optimization import EquivalentSolutionDiagnosticConfig
from .runner import CandidateExportConfig


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
        default=DEFAULT_CANDIDATE_SEARCH_LIMIT,
        help=(
            "最多搜尋幾份正式班表以外的同品質候選"
            f"（預設：{DEFAULT_CANDIDATE_SEARCH_LIMIT}）"
        ),
    )
    parser.add_argument(
        "--equivalent-time-limit",
        type=float,
        default=None,
        help=(
            "候選班表診斷總秒數上限"
            "（預設：本次 CP-SAT 最佳化時間的 "
            f"{DEFAULT_DIAGNOSTIC_TIME_RATIO:g} 倍）"
        ),
    )
    parser.add_argument(
        "--equivalent-time-ratio",
        type=float,
        default=DEFAULT_DIAGNOSTIC_TIME_RATIO,
        help=(
            "未指定固定秒數時，候選診斷時間相對於最佳化時間的比例"
            f"（預設：{DEFAULT_DIAGNOSTIC_TIME_RATIO}）"
        ),
    )
    parser.add_argument(
        "--skip-equivalent-diagnostic",
        action="store_true",
        help="正式輸出完成後不搜尋同品質候選班表",
    )
    parser.add_argument(
        "--candidate-export-count",
        type=int,
        default=DEFAULT_CANDIDATE_EXPORT_COUNT,
        help=(
            "額外保存幾份找到的同品質候選班表"
            f"（預設：{DEFAULT_CANDIDATE_EXPORT_COUNT}）"
        ),
    )
    parser.add_argument(
        "--candidate-export-formats",
        nargs="+",
        choices=("json", "excel", "pdf"),
        default=DEFAULT_CANDIDATE_EXPORT_FORMATS,
        help=(
            "候選班表輸出格式（可複選；預設："
            + ", ".join(DEFAULT_CANDIDATE_EXPORT_FORMATS)
            + "）"
        ),
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=DEFAULT_PROGRESS_UPDATE_SECONDS,
        help=(
            "最佳化進度更新秒數"
            f"（預設：{DEFAULT_PROGRESS_UPDATE_SECONDS:g}）"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.skip_equivalent_diagnostic and args.candidate_export_count:
        parser.error("候選診斷停用時，候選輸出份數必須為 0")
    if args.candidate_export_count > args.equivalent_limit:
        parser.error("候選輸出份數不可超過候選搜尋上限")
    diagnostic_config = (
        None
        if args.skip_equivalent_diagnostic
        else EquivalentSolutionDiagnosticConfig(
            max_alternatives=args.equivalent_limit,
            max_time_seconds=args.equivalent_time_limit,
            scheduling_time_ratio=args.equivalent_time_ratio,
        )
    )
    return run_schedule_request_with_console(
        ScheduleApplicationRequest(
            input_path=args.input,
            output_directory=args.output_dir,
            intermediate_directory=args.intermediate_dir,
            overwrite=args.overwrite,
            diagnostic_config=diagnostic_config,
            candidate_export_config=CandidateExportConfig(
                max_candidates=args.candidate_export_count,
                formats=tuple(args.candidate_export_formats),
            ),
            progress_interval_seconds=args.progress_interval,
        )
    )
