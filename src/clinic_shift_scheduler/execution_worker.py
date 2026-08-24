"""Headless worker used by the desktop shell to run a complete schedule."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

from .app_config import load_scheduler_config
from .application import (
    ScheduleApplicationCallbacks,
    ScheduleApplicationError,
    request_from_app_config,
    run_schedule_application,
)
from .events import (
    CancellationToken,
    ExecutionPhase,
    PreservationToken,
    ProgressEvent,
    ProgressEventKind,
)
from .execution_protocol import (
    completion_message,
    encode_execution_message,
    failure_message,
    preserved_completion_message,
    progress_message,
)


class _ProtocolWriter:
    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, payload: bytes) -> None:
        with self._lock:
            self._stream.write(payload)
            self._stream.flush()


def run_worker(
    *,
    config_path: Path,
    input_path: Path,
    output_directory: Path,
    intermediate_directory: Path,
    cancel_file: Path | None,
    stdout: BinaryIO,
    preserve_file: Path | None = None,
) -> int:
    writer = _ProtocolWriter(stdout)
    cancellation = CancellationToken()
    preservation = PreservationToken()
    monitor_stop, monitor = _start_control_monitor(
        cancel_file,
        preserve_file,
        cancellation,
        preservation,
    )
    writer.write(
        encode_execution_message("started", input_path=str(input_path))
    )
    try:
        config = load_scheduler_config(config_path)
        request = replace(
            request_from_app_config(
                config,
                input_directory=input_path.parent,
                output_directory=output_directory,
                intermediate_directory=intermediate_directory,
            ),
            input_path=input_path,
        )

        def emit(event: ProgressEvent) -> None:
            writer.write(progress_message(event))

        def emit_diagnostic(event: ProgressEvent) -> None:
            writer.write(progress_message(_gui_diagnostic_event(event)))

        result = run_schedule_application(
            request,
            ScheduleApplicationCallbacks(
                progress=emit,
                diagnostic_progress=emit_diagnostic,
                cancellation=cancellation,
                preservation=preservation,
            ),
        )
    except ScheduleApplicationError as error:
        writer.write(
            failure_message(
                kind=error.kind.value,
                message=str(error),
                issues=error.issues,
            )
        )
        return 2 if error.kind.value == "CANCELLED" else 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        writer.write(
            failure_message(kind="CONFIG_ERROR", message=str(error))
        )
        return 1
    except Exception as error:  # Keep the GUI informed on unexpected failures.
        writer.write(
            failure_message(kind="UNEXPECTED_ERROR", message=str(error))
        )
        return 1

    else:
        if result.output.preservation_info is None:
            writer.write(completion_message(result))
        else:
            writer.write(preserved_completion_message(result))
        return 0
    finally:
        monitor_stop.set()
        if monitor is not None:
            monitor.join(timeout=1.0)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--intermediate-directory", required=True, type=Path)
    parser.add_argument("--cancel-file", type=Path)
    parser.add_argument("--preserve-file", type=Path)
    options = parser.parse_args(arguments)
    return run_worker(
        config_path=options.config.resolve(),
        input_path=options.input.resolve(),
        output_directory=options.output_directory.resolve(),
        intermediate_directory=options.intermediate_directory.resolve(),
        cancel_file=(
            None if options.cancel_file is None else options.cancel_file.resolve()
        ),
        stdout=sys.stdout.buffer,
        preserve_file=(
            None
            if options.preserve_file is None
            else options.preserve_file.resolve()
        ),
    )


def _start_control_monitor(
    cancel_file: Path | None,
    preserve_file: Path | None,
    cancellation: CancellationToken,
    preservation: PreservationToken,
) -> tuple[threading.Event, threading.Thread | None]:
    stop = threading.Event()
    if cancel_file is None and preserve_file is None:
        return stop, None

    def monitor() -> None:
        while not stop.wait(0.05):
            if cancel_file is not None and cancel_file.exists():
                cancellation.cancel()
                return
            if preserve_file is not None and preserve_file.exists():
                preservation.request()
                return

    thread = threading.Thread(
        target=monitor,
        name="schedule-worker-cancel-monitor",
        daemon=True,
    )
    thread.start()
    return stop, thread


def _start_cancel_monitor(
    cancel_file: Path | None,
    cancellation: CancellationToken,
) -> tuple[threading.Event, threading.Thread | None]:
    """Backward-compatible test seam for the original single control."""

    return _start_control_monitor(
        cancel_file,
        None,
        cancellation,
        PreservationToken(),
    )


def _gui_diagnostic_event(event: ProgressEvent) -> ProgressEvent:
    """Add the GUI-specific candidate-stop affordance to its progress text."""

    if (
        event.phase is ExecutionPhase.CANDIDATE_SEARCH
        and event.kind is ProgressEventKind.STEP_STARTED
    ):
        return replace(
            event,
            message=f'{event.message}；按「終止候選處理」可終止（不影響先前已完成的排班輸出）',
        )
    return event
