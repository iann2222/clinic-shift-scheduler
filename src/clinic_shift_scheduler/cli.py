"""Command-line interface for a complete clinic scheduling run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter
from typing import Sequence

from .errors import InputValidationError
from .runner import ScheduleRunError, run_schedule_file


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
    return parser


def _seconds(value: float) -> str:
    return f"{value:.3f} 秒"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command_started = perf_counter()
    try:
        result = run_schedule_file(
            args.input,
            output_directory=args.output_dir,
            intermediate_directory=args.intermediate_dir,
            overwrite=args.overwrite,
            progress=lambda message: print(f"[排班] {message}", flush=True),
        )
    except (InputValidationError, ScheduleRunError, OSError, ValueError) as error:
        print(f"[排班] 執行失敗：{error}", file=sys.stderr)
        print(
            f"[排班] 失敗前總執行時間：{_seconds(perf_counter() - command_started)}",
            file=sys.stderr,
        )
        return 1

    timing = result.output.execution_timing
    assert timing is not None
    print("[排班] 完成：OPTIMAL + validation PASS")
    print("[排班] 執行時間紀錄：")
    print(f"  輸入讀取：{_seconds(timing.input_loading_seconds)}")
    print(
        "  驗證與正規化："
        f"{_seconds(timing.validation_normalization_seconds)}"
    )
    print(f"  前置可行性檢查：{_seconds(timing.precheck_seconds)}")
    print(f"  CP-SAT 最佳化：{_seconds(timing.optimization_seconds)}")
    print(
        "  獨立驗證與結果建立："
        f"{_seconds(timing.result_validation_and_build_seconds)}"
    )
    print(f"  正式 JSON：{_seconds(result.json_export_seconds)}")
    print(f"  正式 Excel：{_seconds(result.excel_export_seconds)}")
    print(f"  月班表 PDF：{_seconds(result.pdf_export_seconds)}")
    print(f"  排班管線：{_seconds(timing.scheduling_pipeline_seconds)}")
    print(f"  從讀檔到全部輸出：{_seconds(result.total_execution_seconds)}")
    print("[排班] 輸出檔案：")
    print(f"  中間輸入：{result.intermediate_input_path}")
    print(f"  {result.json_path}")
    print(f"  {result.excel_path}")
    print(f"  {result.pdf_path}")
    return 0
