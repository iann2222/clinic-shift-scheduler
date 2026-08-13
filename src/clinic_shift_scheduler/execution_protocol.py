"""JSON-lines protocol shared by the scheduler worker and desktop shell."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .events import DiagnosticIssue, ProgressEvent


EXECUTION_PROTOCOL = "clinic-shift-scheduler.execution-v1"


def encode_execution_message(
    message_type: str,
    **payload: Any,
) -> bytes:
    message = {
        "protocol": EXECUTION_PROTOCOL,
        "type": message_type,
        **payload,
    }
    return (
        json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def progress_message(event: ProgressEvent) -> bytes:
    return encode_execution_message(
        "progress",
        phase=event.phase.value,
        kind=event.kind.value,
        message=event.message,
        elapsed_seconds=event.elapsed_seconds,
        current=event.current,
        total=event.total,
        details=dict(event.details),
    )


def failure_message(
    *,
    kind: str,
    message: str,
    issues: tuple[DiagnosticIssue, ...] = (),
) -> bytes:
    return encode_execution_message(
        "failed",
        kind=kind,
        message=message,
        issues=[issue.to_dict() for issue in issues],
    )


def completion_message(result: Any) -> bytes:
    output = result.output
    validation = output.validation_report
    overall = output.overall_statistics
    return encode_execution_message(
        "completed",
        status=output.status.value,
        validation=(
            None if validation is None else validation.status.value
        ),
        objective_vector=(
            {} if overall is None else dict(overall.objective_vector)
        ),
        paths={
            "json": str(result.json_path),
            "excel": str(result.excel_path),
            "pdf": str(result.pdf_path),
            "candidate_directory": str(result.candidate_output_directory),
        },
        candidate_diagnostic=(
            None
            if result.equivalent_solution_diagnostic is None
            else {
                "status": result.equivalent_solution_diagnostic.status.value,
                "alternative_count": (
                    result.equivalent_solution_diagnostic.alternative_count
                ),
            }
        ),
        candidate_export_count=len(result.candidate_exports),
        timings={
            "formal_output_seconds": result.formal_output_seconds,
            "candidate_processing_seconds": (
                result.equivalent_solution_diagnostic_seconds
                + result.candidate_export_seconds
            ),
            "total_execution_seconds": result.total_execution_seconds,
        },
    )


class ExecutionMessageDecoder:
    """Incrementally decode UTF-8 JSON lines produced by one worker."""

    def __init__(
        self,
        *,
        ignored_line: Callable[[str], bool] | None = None,
    ) -> None:
        self._buffer = bytearray()
        self._ignored_line = ignored_line

    def feed(self, chunk: bytes) -> tuple[dict[str, Any], ...]:
        self._buffer.extend(chunk)
        messages: list[dict[str, Any]] = []
        while b"\n" in self._buffer:
            raw_line, _, remainder = self._buffer.partition(b"\n")
            self._buffer = bytearray(remainder)
            if not raw_line.strip():
                continue
            rendered_line = raw_line.decode("utf-8")
            if self._ignored_line is not None and self._ignored_line(
                rendered_line
            ):
                continue
            decoded = json.loads(rendered_line)
            if not isinstance(decoded, Mapping):
                raise ValueError("execution message must be a JSON object")
            if decoded.get("protocol") != EXECUTION_PROTOCOL:
                raise ValueError("unsupported execution protocol")
            if not isinstance(decoded.get("type"), str):
                raise ValueError("execution message type is required")
            messages.append(dict(decoded))
        return tuple(messages)


def worker_command(
    application_root: Path,
    *,
    frozen: bool,
    python_executable: Path,
) -> tuple[str, list[str]]:
    """Build the same worker invocation for source and frozen executions."""

    if frozen:
        return str(application_root / "ClinicShiftScheduler.exe"), [
            "--gui-worker"
        ]
    return str(python_executable), [
        str(application_root / "src" / "run_scheduler.py"),
        "--gui-worker",
    ]
