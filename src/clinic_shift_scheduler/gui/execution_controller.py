"""QProcess adapter that keeps the GUI isolated from the scheduling engine."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from ..execution_protocol import ExecutionMessageDecoder, worker_command


class ExecutionController(QObject):
    """Own one headless worker process and translate its JSON-lines events."""

    started = Signal()
    message_received = Signal(dict)
    stderr_received = Signal(str)
    finished = Signal(int)

    def __init__(self, application_root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.application_root = application_root.resolve()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )
        self.process.started.connect(self.started.emit)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self._decoder = _worker_stdout_decoder()
        self._terminal_message_received = False
        self._cancel_requested = False
        self._preserve_requested = False
        self._generation = 0
        self._finished_emitted = False
        self._cancel_file: Path | None = None
        self._preserve_file: Path | None = None

    @property
    def is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start(
        self,
        *,
        config_path: Path,
        input_path: Path,
        output_directory: Path,
        intermediate_directory: Path,
    ) -> None:
        if self.is_running:
            raise RuntimeError("a scheduling worker is already running")
        program, arguments = worker_command(
            self.application_root,
            frozen=bool(getattr(sys, "frozen", False)),
            python_executable=Path(sys.executable),
        )
        arguments.extend(
            (
                f"--config={config_path.resolve()}",
                f"--input={input_path.resolve()}",
                f"--output-directory={output_directory.resolve()}",
                f"--intermediate-directory={intermediate_directory.resolve()}",
            )
        )
        self._decoder = _worker_stdout_decoder()
        self._terminal_message_received = False
        self._cancel_requested = False
        self._preserve_requested = False
        self._generation += 1
        self._finished_emitted = False
        control_directory = intermediate_directory.parent / "worker-control"
        control_directory.mkdir(parents=True, exist_ok=True)
        self._cancel_file = control_directory / f"{uuid4().hex}.cancel"
        self._preserve_file = control_directory / f"{uuid4().hex}.preserve"
        self.process.setWorkingDirectory(str(self.application_root))
        arguments.append(f"--cancel-file={self._cancel_file.resolve()}")
        arguments.append(f"--preserve-file={self._preserve_file.resolve()}")
        self.process.start(program, arguments)

    def cancel(self) -> None:
        if (
            not self.is_running
            or self._cancel_requested
            or self._preserve_requested
        ):
            return
        self._cancel_requested = True
        if self._cancel_file is not None:
            try:
                self._cancel_file.write_text("cancel\n", encoding="utf-8")
            except OSError:
                self.process.terminate()
        generation = self._generation
        QTimer.singleShot(
            10000,
            lambda: self._force_stop_if_same_run(generation),
        )

    def preserve_current_best(self) -> bool:
        """Request graceful stop while retaining the best legal schedule."""

        if (
            not self.is_running
            or self._cancel_requested
            or self._preserve_requested
            or self._preserve_file is None
        ):
            return False
        try:
            self._preserve_file.write_text("preserve\n", encoding="utf-8")
        except OSError:
            return False
        self._preserve_requested = True
        return True

    def stop_for_shutdown(self) -> None:
        if not self.is_running:
            return
        if self._preserve_requested:
            self.process.kill()
        else:
            self.cancel()
        if not self.process.waitForFinished(3000):
            self.process.kill()
            self.process.waitForFinished(3000)

    def _read_stdout(self) -> None:
        try:
            messages = self._decoder.feed(
                bytes(self.process.readAllStandardOutput())
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            self._emit_protocol_failure(
                "背景排班程序回傳了無法辨識的資料："
                f"{error}"
            )
            return
        for message in messages:
            if message["type"] in {"completed", "preserved", "failed"}:
                self._terminal_message_received = True
            self.message_received.emit(message)

    def _read_stderr(self) -> None:
        rendered = bytes(self.process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )
        meaningful = "\n".join(
            line
            for line in rendered.splitlines()
            if line.strip() and not _is_ortools_dll_load_noise(line)
        )
        if meaningful:
            self.stderr_received.emit(meaningful)

    def _process_finished(
        self,
        exit_code: int,
        _status: QProcess.ExitStatus,
    ) -> None:
        self._read_stdout()
        self._read_stderr()
        self._remove_control_files()
        if not self._terminal_message_received:
            if self._cancel_requested:
                kind = "CANCELLED"
                message = "排班已取消。"
            elif self._preserve_requested:
                kind = "PRESERVATION_FAILED"
                message = "未能完成目前最佳班表的驗證與輸出。"
            else:
                kind = "WORKER_EXITED"
                message = f"排班程序提前結束（exit code {exit_code}）。"
            self.message_received.emit(
                {
                    "protocol": "clinic-shift-scheduler.execution-v1",
                    "type": "failed",
                    "kind": kind,
                    "message": message,
                    "issues": [],
                }
            )
        self._emit_finished_once(exit_code)

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._remove_control_files()
            self._emit_protocol_failure(
                f"無法啟動排班程序：{self.process.errorString()}"
            )
            self._emit_finished_once(-1)

    def _emit_protocol_failure(self, message: str) -> None:
        if self._terminal_message_received:
            return
        self._terminal_message_received = True
        self.message_received.emit(
            {
                "protocol": "clinic-shift-scheduler.execution-v1",
                "type": "failed",
                "kind": "WORKER_PROTOCOL_ERROR",
                "message": message,
                "issues": [],
            }
        )

    def _force_stop_if_same_run(self, generation: int) -> None:
        if (
            self.is_running
            and self._cancel_requested
            and self._generation == generation
        ):
            self.process.kill()

    def _emit_finished_once(self, exit_code: int) -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self.finished.emit(exit_code)

    def _remove_control_files(self) -> None:
        if self._cancel_file is not None:
            self._cancel_file.unlink(missing_ok=True)
            self._cancel_file = None
        if self._preserve_file is not None:
            self._preserve_file.unlink(missing_ok=True)
            self._preserve_file = None


def _is_ortools_dll_load_noise(line: str) -> bool:
    return bool(
        re.fullmatch(
            r"load .*[\\/]ortools[\\/]\.libs[\\/][^\\/]+\.dll\.\.\.",
            line.strip(),
            flags=re.IGNORECASE,
        )
    )


def _worker_stdout_decoder() -> ExecutionMessageDecoder:
    """Keep Windows native-loader chatter outside the JSON-lines channel."""

    return ExecutionMessageDecoder(ignored_line=_is_ortools_dll_load_noise)
