"""Application-level orchestration for one complete scheduling run."""

from __future__ import annotations

# VS Code's "Run Python File" executes the open file as a standalone script.
# Redirect that convenience action to the single formal application entry point.
if __name__ == "__main__" and not __package__:
    import runpy
    import sys
    from pathlib import Path as _EntryPath

    _src_directory = _EntryPath(__file__).resolve().parents[1]
    sys.path.insert(0, str(_src_directory))
    runpy.run_path(str(_src_directory / "run_scheduler.py"), run_name="__main__")
    raise SystemExit(0)

import json
import os
import shutil
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any, TypeVar

from .app_config import SUPPORTED_CANDIDATE_EXPORT_FORMATS
from .authoring import WEEKLY_AUTHORING_VERSION, expand_weekly_template
from .exporters import (
    DEFAULT_OUTPUT_DIRECTORY,
    export_result_excel,
    export_result_json,
    export_schedule_pdf_from_excel,
)
from .feasibility import Assignment, FeasibilityStatus
from .models import NormalizedScheduleInput
from .output import ExecutionTiming, FormalScheduleOutput, finalize_schedule_output
from .precheck import PrecheckResult, run_prechecks
from .validation import validate_and_normalize
from .optimization import (
    EquivalentSolutionDiagnosticConfig,
    EquivalentSolutionDiagnosticResult,
    LexicographicResult,
    diagnose_equivalent_solutions,
    solve_lexicographic,
)
from .time_formatting import format_seconds, format_seconds_with_minutes


ProgressCallback = Callable[[str], None]
DEFAULT_INTERMEDIATE_DIRECTORY = Path("runtime/expanded-input")
CANDIDATE_OUTPUT_DIRECTORY_NAME = "候選班表"
T = TypeVar("T")


class ScheduleRunError(RuntimeError):
    """Raised when a complete run cannot produce a formal schedule."""


@dataclass(frozen=True, slots=True)
class CandidateExportConfig:
    """How many diagnosed candidates to persist and in which media."""

    max_candidates: int = 0
    formats: tuple[str, ...] = ("json",)

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_candidates, bool)
            or not isinstance(self.max_candidates, int)
            or self.max_candidates < 0
        ):
            raise ValueError("candidate export count must be a non-negative integer")
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("candidate export formats cannot contain duplicates")
        unsupported = sorted(
            set(self.formats) - SUPPORTED_CANDIDATE_EXPORT_FORMATS
        )
        if unsupported:
            raise ValueError(
                "unsupported candidate export formats: " + ", ".join(unsupported)
            )
        if self.max_candidates and not self.formats:
            raise ValueError("candidate export formats cannot be empty")


@dataclass(frozen=True, slots=True)
class CandidateScheduleExport:
    index: int
    json_path: Path | None
    excel_path: Path | None
    pdf_path: Path | None


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
    formal_output_seconds: float
    equivalent_solution_diagnostic: EquivalentSolutionDiagnosticResult | None
    equivalent_solution_diagnostic_seconds: float
    candidate_output_directory: Path
    candidate_exports: tuple[CandidateScheduleExport, ...]
    candidate_export_seconds: float
    total_execution_seconds: float


def _notify(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _resolve_diagnostic_config(
    config: EquivalentSolutionDiagnosticConfig,
    optimization_seconds: float,
) -> EquivalentSolutionDiagnosticConfig:
    if config.max_time_seconds is not None:
        return config
    return replace(
        config,
        max_time_seconds=max(
            optimization_seconds * config.scheduling_time_ratio,
            0.001,
        ),
    )


def _run_with_elapsed_heartbeat(
    operation: Callable[[], T],
    progress: ProgressCallback | None,
    *,
    interval_seconds: float = 5.0,
) -> tuple[T, float]:
    """Run a blocking operation while periodically reporting elapsed time."""

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than 0")
    started = perf_counter()
    stop = threading.Event()
    heartbeat: threading.Thread | None = None
    if progress is not None:

        def report_elapsed() -> None:
            while not stop.wait(interval_seconds):
                elapsed = perf_counter() - started
                _notify(
                    progress,
                    "嚴格分階段最佳化進行中："
                    f"已耗時 {elapsed:.0f} 秒",
                )

        heartbeat = threading.Thread(
            target=report_elapsed,
            name="schedule-optimization-heartbeat",
            daemon=True,
        )
        heartbeat.start()

    try:
        result = operation()
    finally:
        stop.set()
        if heartbeat is not None:
            heartbeat.join(timeout=interval_seconds)

    elapsed = perf_counter() - started
    _notify(
        progress,
        f"嚴格分階段最佳化完成：共耗時 {format_seconds(elapsed)}",
    )
    return result, elapsed


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


def _reset_candidate_output_directory(output_directory: str | Path) -> Path:
    """Recreate the dedicated generated-candidate directory."""

    output_root = Path(output_directory).resolve()
    target = (output_root / CANDIDATE_OUTPUT_DIRECTORY_NAME).resolve()
    if target.parent != output_root or target.name != CANDIDATE_OUTPUT_DIRECTORY_NAME:
        raise ScheduleRunError("invalid candidate output directory")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _export_candidate_schedules(
    data: NormalizedScheduleInput,
    solver_result: LexicographicResult,
    assignments_by_index: tuple[tuple[int, tuple[Assignment, ...]], ...],
    output_directory: Path,
    formats: tuple[str, ...],
    execution_timing: ExecutionTiming,
) -> tuple[CandidateScheduleExport, ...]:
    exports: list[CandidateScheduleExport] = []
    month = data.source.period.start_date.strftime("%Y-%m")
    for index, assignments in assignments_by_index:
        candidate_result = replace(solver_result, assignments=assignments)
        candidate_output = finalize_schedule_output(data, candidate_result)
        candidate_output = replace(
            candidate_output,
            execution_timing=execution_timing,
        )
        report = candidate_output.validation_report
        if (
            candidate_output.status is not FeasibilityStatus.OPTIMAL
            or report is None
            or not report.is_valid
        ):
            validation = "NONE" if report is None else report.status.value
            raise ScheduleRunError(
                "candidate output failed independent validation: "
                f"index={index}, status={candidate_output.status.value}, "
                f"validation={validation}"
            )

        stem = f"候選班表_{index:03d}_{month}.result-v1"
        json_path = None
        excel_path = None
        pdf_path = None
        if "json" in formats:
            json_path = export_result_json(
                data,
                candidate_output,
                output_directory=output_directory,
                overwrite=True,
                filename_stem=stem,
            )
        generated_excel: Path | None = None
        if "excel" in formats or "pdf" in formats:
            generated_excel = export_result_excel(
                data,
                candidate_output,
                output_directory=output_directory,
                overwrite=True,
                filename_stem=stem,
            )
            if "excel" in formats:
                excel_path = generated_excel
        if "pdf" in formats:
            assert generated_excel is not None
            pdf_path = export_schedule_pdf_from_excel(
                generated_excel,
                overwrite=True,
            )
        if generated_excel is not None and "excel" not in formats:
            generated_excel.unlink()
        exports.append(
            CandidateScheduleExport(
                index=index,
                json_path=json_path,
                excel_path=excel_path,
                pdf_path=pdf_path,
            )
        )
    return tuple(exports)


def run_schedule_file(
    input_path: str | Path,
    *,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    intermediate_directory: str | Path = DEFAULT_INTERMEDIATE_DIRECTORY,
    overwrite: bool = False,
    equivalent_solution_diagnostic_config: (
        EquivalentSolutionDiagnosticConfig | None
    ) = None,
    candidate_export_config: CandidateExportConfig | None = None,
    progress_interval_seconds: float = 5.0,
    progress: ProgressCallback | None = None,
    diagnostic_progress: ProgressCallback | None = None,
) -> ScheduleRunResult:
    """Run input loading through validated JSON, Excel, and PDF exports."""

    resolved_candidate_export = candidate_export_config or CandidateExportConfig()
    if (
        equivalent_solution_diagnostic_config is None
        and resolved_candidate_export.max_candidates
    ):
        raise ValueError("candidate export requires equivalent-solution diagnosis")
    if (
        equivalent_solution_diagnostic_config is not None
        and resolved_candidate_export.max_candidates
        > equivalent_solution_diagnostic_config.max_alternatives
    ):
        raise ValueError("candidate export count cannot exceed diagnostic search limit")
    if progress_interval_seconds <= 0:
        raise ValueError("progress_interval_seconds must be greater than 0")

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
    solver_result, optimization_seconds = _run_with_elapsed_heartbeat(
        lambda: solve_lexicographic(data, precheck_result=precheck),
        progress,
        interval_seconds=progress_interval_seconds,
    )

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

    _notify(
        progress,
        "輸出正式檔案：JSON 保存完整結果，Excel 供查看與使用，"
        "PDF 由 Excel 月班表產生",
    )
    step_started = perf_counter()
    json_path = export_result_json(
        data,
        output,
        output_directory=output_directory,
        overwrite=overwrite,
    )
    json_export_seconds = perf_counter() - step_started

    step_started = perf_counter()
    excel_path = export_result_excel(
        data,
        output,
        output_directory=output_directory,
        overwrite=overwrite,
    )
    excel_export_seconds = perf_counter() - step_started

    step_started = perf_counter()
    pdf_path = export_schedule_pdf_from_excel(
        excel_path,
        overwrite=overwrite,
    )
    pdf_export_seconds = perf_counter() - step_started

    formal_output_seconds = perf_counter() - started
    file_export_seconds = (
        json_export_seconds + excel_export_seconds + pdf_export_seconds
    )
    _notify(
        progress,
        "\n".join(
            (
                "完成：OPTIMAL + validation PASS",
                "執行時間紀錄：",
                f"  輸入讀取：{format_seconds(input_loading_seconds)}",
                (
                    "  驗證與正規化："
                    f"{format_seconds(validation_normalization_seconds)}"
                ),
                f"  前置可行性檢查：{format_seconds(precheck_seconds)}",
                f"  CP-SAT 最佳化：{format_seconds(optimization_seconds)}",
                (
                    "  獨立驗證與結果建立："
                    f"{format_seconds(result_validation_and_build_seconds)}"
                ),
                (
                    "  輸出檔案（含 JSON、Excel、PDF）："
                    f"{format_seconds(file_export_seconds)}"
                ),
                (
                    "[排班耗時] 完整排班時間（從讀檔到正式輸出）："
                    f"{format_seconds_with_minutes(formal_output_seconds)}"
                ),
                "輸出檔案：",
                f"  中間輸入：{intermediate_input_path}",
                f"  {json_path}",
                f"  {excel_path}",
                f"  {pdf_path}",
            )
        ),
    )

    equivalent_solution_diagnostic = None
    equivalent_solution_diagnostic_seconds = 0.0
    candidate_export_seconds = 0.0
    candidate_exports: tuple[CandidateScheduleExport, ...] = ()
    candidate_output_directory = _reset_candidate_output_directory(
        output_directory
    )
    if equivalent_solution_diagnostic_config is not None:
        resolved_diagnostic_config = _resolve_diagnostic_config(
            equivalent_solution_diagnostic_config,
            optimization_seconds,
        )
        candidate_progress = diagnostic_progress or progress
        _notify(
            candidate_progress,
            "開始搜尋同品質候選班表"
            f"（時間上限 {format_seconds(resolved_diagnostic_config.max_time_seconds)}），"
            "按 Ctrl+C 可只中止此診斷",
        )
        step_started = perf_counter()
        captured_candidates: list[tuple[int, tuple[Assignment, ...]]] = []

        def report_alternative(count: int) -> None:
            _notify(
                candidate_progress,
                f"已找到 {count} 份同品質候選班表",
            )

        def capture_candidate(
            index: int,
            assignments: tuple[Assignment, ...],
        ) -> None:
            if len(captured_candidates) < resolved_candidate_export.max_candidates:
                captured_candidates.append((index, assignments))

        equivalent_solution_diagnostic = diagnose_equivalent_solutions(
            solver_result,
            resolved_diagnostic_config,
            progress=report_alternative,
            candidate_found=capture_candidate,
        )
        equivalent_solution_diagnostic_seconds = perf_counter() - step_started

        if captured_candidates:
            _notify(
                candidate_progress,
                f"輸出 {len(captured_candidates)} 份同品質候選班表",
            )
            step_started = perf_counter()
            candidate_exports = _export_candidate_schedules(
                data,
                solver_result,
                tuple(captured_candidates),
                candidate_output_directory,
                resolved_candidate_export.formats,
                execution_timing,
            )
            candidate_export_seconds = perf_counter() - step_started
            _notify(
                candidate_progress,
                f"候選班表輸出完成：{candidate_output_directory}",
            )

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
        formal_output_seconds=formal_output_seconds,
        equivalent_solution_diagnostic=equivalent_solution_diagnostic,
        equivalent_solution_diagnostic_seconds=(
            equivalent_solution_diagnostic_seconds
        ),
        candidate_output_directory=candidate_output_directory,
        candidate_exports=candidate_exports,
        candidate_export_seconds=candidate_export_seconds,
        total_execution_seconds=perf_counter() - started,
    )
