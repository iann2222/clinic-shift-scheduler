"""Typed application service shared by CLI, config entry points, and future UI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from .app_config import (
    DEFAULT_DIAGNOSTIC_TIME_RATIO,
    DEFAULT_PROGRESS_UPDATE_SECONDS,
    SchedulerAppConfig,
)
from .authoring_application import (
    AuthoringApplication,
    AuthoringFileExistsError,
    AuthoringSession,
    AuthoringValidationResult,
    default_month_filename,
)
from .application_contracts import (
    DEFAULT_INTERMEDIATE_DIRECTORY,
    CandidateExportConfig,
    ProvisionalExportConfig,
)
from .errors import InputValidationError
from .events import (
    CancellationToken,
    DiagnosticIssue,
    ExecutionPhase,
    ProgressCallback,
    PreservationToken,
)
from .optimization_contracts import EquivalentSolutionDiagnosticConfig

if TYPE_CHECKING:
    from .runner import PreservedScheduleRunResult, ScheduleRunResult


class ScheduleApplicationFailureKind(StrEnum):
    INPUT_INVALID = "INPUT_INVALID"
    REQUEST_INVALID = "REQUEST_INVALID"
    FILE_ERROR = "FILE_ERROR"
    OUTPUT_FAILED = "OUTPUT_FAILED"
    SCHEDULE_FAILED = "SCHEDULE_FAILED"
    CANCELLED = "CANCELLED"


class ScheduleApplicationError(RuntimeError):
    """A categorized application failure suitable for CLI or GUI handling."""

    def __init__(
        self,
        kind: ScheduleApplicationFailureKind,
        message: str,
        *,
        cause: Exception,
        issues: tuple[DiagnosticIssue, ...] = (),
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.cause = cause
        self.issues = issues


@dataclass(frozen=True, slots=True)
class ScheduleApplicationRequest:
    """All non-presentation inputs for one complete scheduling run."""

    input_path: Path
    output_directory: Path = Path("output")
    intermediate_directory: Path = DEFAULT_INTERMEDIATE_DIRECTORY
    overwrite: bool = False
    diagnostic_config: EquivalentSolutionDiagnosticConfig | None = None
    candidate_export_config: CandidateExportConfig = field(
        default_factory=CandidateExportConfig
    )
    provisional_export_config: ProvisionalExportConfig = field(
        default_factory=ProvisionalExportConfig
    )
    progress_interval_seconds: float = DEFAULT_PROGRESS_UPDATE_SECONDS


@dataclass(frozen=True, slots=True)
class ScheduleApplicationCallbacks:
    """Presentation callbacks supplied by a CLI or future graphical UI."""

    progress: ProgressCallback | None = None
    diagnostic_progress: ProgressCallback | None = None
    cancellation: CancellationToken | None = None
    preservation: PreservationToken | None = None


def request_from_app_config(
    config: SchedulerAppConfig,
    *,
    input_directory: str | Path,
    output_directory: str | Path,
    intermediate_directory: str | Path,
) -> ScheduleApplicationRequest:
    """Translate validated user config without passing through argparse."""

    diagnostic: EquivalentSolutionDiagnosticConfig | None = None
    if config.candidate_diagnostic.enabled:
        time = config.candidate_diagnostic.time
        diagnostic = EquivalentSolutionDiagnosticConfig(
            max_alternatives=config.candidate_diagnostic.search_limit,
            max_time_seconds=time.fixed_seconds,
            scheduling_time_ratio=(
                time.scheduling_time_ratio
                if time.scheduling_time_ratio is not None
                else DEFAULT_DIAGNOSTIC_TIME_RATIO
            ),
        )
    return ScheduleApplicationRequest(
        input_path=Path(input_directory) / config.input_file,
        output_directory=Path(output_directory),
        intermediate_directory=Path(intermediate_directory),
        overwrite=config.overwrite,
        diagnostic_config=diagnostic,
        candidate_export_config=CandidateExportConfig(
            max_candidates=config.candidate_diagnostic.export_count,
            formats=config.candidate_diagnostic.export_formats,
        ),
        provisional_export_config=ProvisionalExportConfig(
            formats=config.preservation_output.export_formats,
        ),
        progress_interval_seconds=config.progress_update_seconds,
    )


def run_schedule_application(
    request: ScheduleApplicationRequest,
    callbacks: ScheduleApplicationCallbacks | None = None,
) -> ScheduleRunResult | PreservedScheduleRunResult:
    """Execute the shared scheduling workflow without presentation concerns."""

    from .exporters import FormalExportError
    from .runner import ScheduleRunError, run_schedule_file

    callbacks = callbacks or ScheduleApplicationCallbacks()
    try:
        return run_schedule_file(
            request.input_path,
            output_directory=request.output_directory,
            intermediate_directory=request.intermediate_directory,
            overwrite=request.overwrite,
            equivalent_solution_diagnostic_config=request.diagnostic_config,
            candidate_export_config=request.candidate_export_config,
            provisional_export_config=request.provisional_export_config,
            progress_interval_seconds=request.progress_interval_seconds,
            progress=callbacks.progress,
            diagnostic_progress=callbacks.diagnostic_progress,
            cancellation=callbacks.cancellation,
            preservation=callbacks.preservation,
        )
    except (
        InputValidationError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:
        issues = (
            error.issues
            if isinstance(error, InputValidationError)
            else (
                DiagnosticIssue(
                    code="invalid_input_file",
                    path=str(request.input_path),
                    message=str(error),
                    phase=ExecutionPhase.INPUT,
                ),
            )
        )
        raise ScheduleApplicationError(
            ScheduleApplicationFailureKind.INPUT_INVALID,
            str(error),
            cause=error,
            issues=tuple(issues),
        ) from error
    except ScheduleRunError as error:
        issues = error.issues or (
            DiagnosticIssue(
                code=(
                    "operation_cancelled"
                    if error.cancelled
                    else "schedule_failed"
                ),
                path="$",
                message=str(error),
                phase=ExecutionPhase.APPLICATION,
            ),
        )
        raise ScheduleApplicationError(
            (
                ScheduleApplicationFailureKind.CANCELLED
                if error.cancelled
                else ScheduleApplicationFailureKind.SCHEDULE_FAILED
            ),
            str(error),
            cause=error,
            issues=issues,
        ) from error
    except FormalExportError as error:
        raise ScheduleApplicationError(
            ScheduleApplicationFailureKind.OUTPUT_FAILED,
            str(error),
            cause=error,
            issues=(
                DiagnosticIssue(
                    code="formal_output_failed",
                    path="$",
                    message=str(error),
                    phase=ExecutionPhase.OUTPUT,
                ),
            ),
        ) from error
    except OSError as error:
        raise ScheduleApplicationError(
            ScheduleApplicationFailureKind.FILE_ERROR,
            str(error),
            cause=error,
            issues=(
                DiagnosticIssue(
                    code="file_error",
                    path="$",
                    message=str(error),
                    phase=ExecutionPhase.APPLICATION,
                ),
            ),
        ) from error
    except ValueError as error:
        raise ScheduleApplicationError(
            ScheduleApplicationFailureKind.REQUEST_INVALID,
            str(error),
            cause=error,
            issues=(
                DiagnosticIssue(
                    code="invalid_request",
                    path="$",
                    message=str(error),
                    phase=ExecutionPhase.APPLICATION,
                ),
            ),
        ) from error
