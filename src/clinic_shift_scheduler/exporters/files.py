"""Output directory, naming, and overwrite policy shared by exporters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..feasibility import FeasibilityStatus
from ..models import NormalizedScheduleInput
from ..output import FormalScheduleOutput
from ..result_validation import ResultValidationStatus


DEFAULT_OUTPUT_DIRECTORY = Path("output")


class FormalExportError(ValueError):
    """Raised when a non-final or invalid result is requested as formal output."""


class ExportFileExistsError(FileExistsError):
    """Raised when an exporter would overwrite an existing result implicitly."""


@dataclass(frozen=True, slots=True)
class OutputPaths:
    directory: Path
    stem: str
    json: Path
    excel: Path
    pdf: Path


def schedule_month(data: NormalizedScheduleInput) -> str:
    """Return the filename/report month derived from the scheduling start date."""

    return data.source.period.start_date.strftime("%Y-%m")


def build_output_paths(
    data: NormalizedScheduleInput,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    *,
    stem: str | None = None,
) -> OutputPaths:
    directory = Path(output_directory)
    resolved_stem = stem or f"排班結果_{schedule_month(data)}.result-v1"
    return OutputPaths(
        directory=directory,
        stem=resolved_stem,
        json=directory / f"{resolved_stem}.json",
        excel=directory / f"{resolved_stem}.xlsx",
        pdf=directory / f"{resolved_stem}.pdf",
    )


def require_formal_result(output: FormalScheduleOutput) -> None:
    report = output.validation_report
    if (
        output.status is not FeasibilityStatus.OPTIMAL
        or not output.has_formal_schedule
        or report is None
        or report.status is not ResultValidationStatus.PASS
    ):
        raise FormalExportError(
            "formal files require OPTIMAL status, PASS validation, and a schedule"
        )


def prepare_target(path: Path, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise ExportFileExistsError(
            f"refusing to overwrite existing output file: {path}"
        )
