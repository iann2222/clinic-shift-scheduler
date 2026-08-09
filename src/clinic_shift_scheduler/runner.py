"""Application-level orchestration for one complete scheduling run."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any

from .authoring import WEEKLY_AUTHORING_VERSION, expand_weekly_template
from .exporters import (
    DEFAULT_OUTPUT_DIRECTORY,
    export_result_excel,
    export_result_json,
    export_schedule_pdf_from_excel,
)
from .feasibility import FeasibilityStatus
from .output import ExecutionTiming, FormalScheduleOutput, finalize_schedule_output
from .precheck import PrecheckResult, run_prechecks
from .validation import validate_and_normalize
from .optimization import solve_lexicographic


ProgressCallback = Callable[[str], None]
DEFAULT_INTERMEDIATE_DIRECTORY = Path("runtime/expanded-input")


class ScheduleRunError(RuntimeError):
    """Raised when a complete run cannot produce a formal schedule."""


@dataclass(frozen=True, slots=True)
class ScheduleRunResult:
    """Formal outputs and wall-clock timings from one end-to-end run."""

    output: FormalScheduleOutput
    precheck: PrecheckResult
    intermediate_input_path: Path
    json_path: Path
    excel_path: Path
    pdf_path: Path
    json_export_seconds: float
    excel_export_seconds: float
    pdf_export_seconds: float
    total_execution_seconds: float


def _notify(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _load_payload(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("input JSON root must be an object")
    return payload


def _write_intermediate_input(
    payload: Mapping[str, Any],
    directory: str | Path,
    month: str,
) -> Path:
    """Clear and atomically recreate the dedicated solver-input directory."""

    target_directory = Path(directory)
    if target_directory.name != "expanded-input":
        raise ScheduleRunError(
            "intermediate directory must be a dedicated 'expanded-input' folder"
        )
    target_directory.mkdir(parents=True, exist_ok=True)
    for child in target_directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            raise ScheduleRunError(
                "intermediate input directory may contain generated files only: "
                f"{child}"
            )
        child.unlink()

    target = target_directory / f"排班輸入_{month}.canonical-v1.json"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{target.stem}.",
            suffix=".tmp",
            dir=target_directory,
            delete=False,
        ) as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            temporary = Path(stream.name)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target


def run_schedule_file(
    input_path: str | Path,
    *,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    intermediate_directory: str | Path = DEFAULT_INTERMEDIATE_DIRECTORY,
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
) -> ScheduleRunResult:
    """Run input loading through validated JSON, Excel, and PDF exports."""

    started = perf_counter()
    source = Path(input_path)

    _notify(progress, f"讀取輸入：{source}")
    step_started = perf_counter()
    payload = _load_payload(source)
    input_loading_seconds = perf_counter() - step_started

    _notify(progress, "展開、驗證並正規化輸入")
    step_started = perf_counter()
    if payload.get("authoring_version") == WEEKLY_AUTHORING_VERSION:
        canonical_payload = expand_weekly_template(payload)
    else:
        canonical_payload = dict(payload)
    data = validate_and_normalize(canonical_payload)
    month = data.source.period.start_date.strftime("%Y-%m")
    intermediate_input_path = _write_intermediate_input(
        canonical_payload,
        intermediate_directory,
        month,
    )
    _notify(progress, f"逐日中間輸入：{intermediate_input_path}")
    validation_normalization_seconds = perf_counter() - step_started

    _notify(progress, "執行前置可行性檢查")
    step_started = perf_counter()
    precheck = run_prechecks(data)
    precheck_seconds = perf_counter() - step_started
    if precheck.is_infeasible:
        details = "; ".join(item.message for item in precheck.diagnostics)
        raise ScheduleRunError(f"{precheck.status.value}: {details}")

    _notify(progress, "執行嚴格分階段最佳化")
    step_started = perf_counter()
    solver_result = solve_lexicographic(data)
    optimization_seconds = perf_counter() - step_started

    _notify(progress, "執行獨立結果驗證並建立正式結果")
    step_started = perf_counter()
    output = finalize_schedule_output(data, solver_result)
    result_validation_and_build_seconds = perf_counter() - step_started
    scheduling_pipeline_seconds = perf_counter() - started
    execution_timing = ExecutionTiming(
        input_loading_seconds=input_loading_seconds,
        validation_normalization_seconds=validation_normalization_seconds,
        precheck_seconds=precheck_seconds,
        optimization_seconds=optimization_seconds,
        result_validation_and_build_seconds=(
            result_validation_and_build_seconds
        ),
        scheduling_pipeline_seconds=scheduling_pipeline_seconds,
    )
    output = replace(output, execution_timing=execution_timing)

    report = output.validation_report
    if (
        output.status is not FeasibilityStatus.OPTIMAL
        or report is None
        or not report.is_valid
    ):
        validation = "NONE" if report is None else report.status.value
        raise ScheduleRunError(
            f"formal output unavailable: status={output.status.value}, "
            f"validation={validation}"
        )

    _notify(progress, "輸出正式 JSON")
    step_started = perf_counter()
    json_path = export_result_json(
        data,
        output,
        output_directory=output_directory,
        overwrite=overwrite,
    )
    json_export_seconds = perf_counter() - step_started

    _notify(progress, "輸出正式 Excel")
    step_started = perf_counter()
    excel_path = export_result_excel(
        data,
        output,
        output_directory=output_directory,
        overwrite=overwrite,
    )
    excel_export_seconds = perf_counter() - step_started

    _notify(progress, "由 Excel 月班表產生 PDF")
    step_started = perf_counter()
    pdf_path = export_schedule_pdf_from_excel(
        excel_path,
        overwrite=overwrite,
    )
    pdf_export_seconds = perf_counter() - step_started

    return ScheduleRunResult(
        output=output,
        precheck=precheck,
        intermediate_input_path=intermediate_input_path,
        json_path=json_path,
        excel_path=excel_path,
        pdf_path=pdf_path,
        json_export_seconds=json_export_seconds,
        excel_export_seconds=excel_export_seconds,
        pdf_export_seconds=pdf_export_seconds,
        total_execution_seconds=perf_counter() - started,
    )
