from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from clinic_shift_scheduler.execution_protocol import (
    EXECUTION_PROTOCOL,
    ExecutionMessageDecoder,
    encode_execution_message,
    worker_command,
)
from clinic_shift_scheduler.events import (
    CancellationToken,
    ExecutionPhase,
    ProgressEvent,
    ProgressEventKind,
)
from clinic_shift_scheduler.execution_worker import (
    _gui_diagnostic_event,
    _start_cancel_monitor,
    run_worker,
)


class ExecutionWorkerTests(unittest.TestCase):
    def test_decoder_accepts_partial_utf8_json_lines(self) -> None:
        first = encode_execution_message("started", input_path="排班.json")
        second = encode_execution_message(
            "progress",
            phase="INPUT",
            kind="INFORMATION",
            message="讀取完成",
        )
        decoder = ExecutionMessageDecoder()

        self.assertEqual(decoder.feed(first[:7]), ())
        messages = decoder.feed(first[7:] + second)

        self.assertEqual([item["type"] for item in messages], ["started", "progress"])
        self.assertEqual(messages[0]["protocol"], EXECUTION_PROTOCOL)
        self.assertEqual(messages[0]["input_path"], "排班.json")

    def test_decoder_rejects_unknown_protocol(self) -> None:
        decoder = ExecutionMessageDecoder()
        with self.assertRaisesRegex(ValueError, "unsupported"):
            decoder.feed(b'{"protocol":"future","type":"started"}\n')

    def test_worker_command_uses_scheduler_executable_when_frozen(self) -> None:
        root = Path("C:/Clinic")
        program, arguments = worker_command(
            root,
            frozen=True,
            python_executable=Path("C:/Python/python.exe"),
        )
        self.assertEqual(program, str(root / "ClinicShiftScheduler.exe"))
        self.assertEqual(arguments, ["--gui-worker"])

    def test_worker_command_uses_source_entry_during_development(self) -> None:
        root = Path("D:/repo")
        python = Path("D:/conda/python.exe")
        program, arguments = worker_command(
            root,
            frozen=False,
            python_executable=python,
        )
        self.assertEqual(program, str(python))
        self.assertEqual(
            arguments,
            [str(root / "src" / "run_scheduler.py"), "--gui-worker"],
        )

    def test_worker_reports_config_failure_as_protocol_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.BytesIO()
            exit_code = run_worker(
                config_path=root / "missing-config.json",
                input_path=root / "input.json",
                output_directory=root / "output",
                intermediate_directory=root / "runtime" / "expanded-input",
                cancel_file=None,
                stdout=output,
            )

        messages = [
            json.loads(line)
            for line in output.getvalue().decode("utf-8").splitlines()
        ]
        self.assertEqual(exit_code, 1)
        self.assertEqual([item["type"] for item in messages], ["started", "failed"])
        self.assertEqual(messages[-1]["kind"], "CONFIG_ERROR")

    def test_cancel_file_sets_worker_cancellation_without_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cancel_file = Path(directory) / "worker.cancel"
            cancellation = CancellationToken()
            stop, monitor = _start_cancel_monitor(cancel_file, cancellation)
            self.addCleanup(stop.set)
            cancel_file.write_text("cancel\n", encoding="utf-8")
            deadline = time.monotonic() + 2.0
            while not cancellation.is_cancelled and time.monotonic() < deadline:
                time.sleep(0.01)
            stop.set()
            assert monitor is not None
            monitor.join(timeout=1.0)

        self.assertTrue(cancellation.is_cancelled)

    def test_gui_candidate_start_uses_button_specific_stop_hint(self) -> None:
        event = ProgressEvent(
            phase=ExecutionPhase.CANDIDATE_SEARCH,
            kind=ProgressEventKind.STEP_STARTED,
            message="開始搜尋同品質候選班表",
        )

        rendered = _gui_diagnostic_event(event)

        self.assertIn("按「終止候選處理」可終止", rendered.message)
        self.assertNotIn("Ctrl+C", rendered.message)


if __name__ == "__main__":
    unittest.main()
