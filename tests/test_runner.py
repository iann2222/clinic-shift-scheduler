from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from clinic_shift_scheduler import (
    FeasibilityStatus,
    RESULT_CONTRACT_VERSION,
    run_schedule_file,
)
from clinic_shift_scheduler.cli import main
import run_scheduler

from tests.fixtures import minimal_valid_input


class ScheduleRunnerTests(unittest.TestCase):
    def test_primary_script_uses_configured_file_from_root_input(self) -> None:
        with patch.object(run_scheduler, "run_cli", return_value=0) as run_cli:
            exit_code = run_scheduler.main()

        self.assertEqual(exit_code, 0)
        arguments = run_cli.call_args.args[0]
        self.assertEqual(
            Path(arguments[0]),
            run_scheduler.PROJECT_ROOT
            / "input"
            / run_scheduler.INPUT_FILENAME,
        )
        self.assertEqual(
            Path(arguments[2]),
            run_scheduler.PROJECT_ROOT / "output",
        )
        intermediate_index = arguments.index("--intermediate-dir") + 1
        self.assertEqual(
            Path(arguments[intermediate_index]),
            run_scheduler.PROJECT_ROOT / "runtime" / "expanded-input",
        )
        self.assertIn("--overwrite", arguments)

    def test_complete_run_exports_files_and_records_execution_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "input.json"
            payload = minimal_valid_input()
            payload["authoring_version"] = "weekly-v1"
            payload["period"] = {
                "start_date": "2024-10-01",
                "end_date": "2024-10-01",
                "holidays": ["2024-10-01"],
            }
            payload.pop("demands")
            payload["weekly_demands"] = [
                {
                    "weekdays": ["tuesday"],
                    "is_open": True,
                    "staffing": {
                        "morning": {"reception": 1, "assistant": 1},
                        "afternoon": {"reception": 1, "assistant": 1},
                        "evening": {"reception": 0, "assistant": 1},
                    },
                },
                {
                    "weekdays": [
                        "monday",
                        "wednesday",
                        "thursday",
                        "friday",
                        "saturday",
                        "sunday",
                    ],
                    "is_open": False,
                },
            ]
            payload["date_overrides"] = []
            input_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            messages: list[str] = []
            intermediate_directory = root / "runtime" / "expanded-input"
            intermediate_directory.mkdir(parents=True)
            (intermediate_directory / "obsolete.json").write_text(
                "{}",
                encoding="utf-8",
            )

            result = run_schedule_file(
                input_path,
                output_directory=root / "output",
                intermediate_directory=intermediate_directory,
                progress=messages.append,
            )

            self.assertIs(result.output.status, FeasibilityStatus.OPTIMAL)
            self.assertTrue(result.precheck.status.value == "CONTINUE")
            self.assertTrue(result.json_path.is_file())
            self.assertTrue(result.excel_path.is_file())
            self.assertTrue(result.pdf_path.is_file())
            self.assertTrue(result.intermediate_input_path.is_file())
            self.assertFalse((intermediate_directory / "obsolete.json").exists())
            intermediate = json.loads(
                result.intermediate_input_path.read_text(encoding="utf-8")
            )
            self.assertNotIn("authoring_version", intermediate)
            self.assertNotIn("weekly_demands", intermediate)
            self.assertEqual(len(intermediate["demands"]), 6)
            self.assertGreaterEqual(result.total_execution_seconds, 0)
            self.assertGreaterEqual(result.json_export_seconds, 0)
            self.assertGreaterEqual(result.excel_export_seconds, 0)
            self.assertGreaterEqual(result.pdf_export_seconds, 0)
            self.assertTrue(any("最佳化" in message for message in messages))

            timing = result.output.execution_timing
            self.assertIsNotNone(timing)
            assert timing is not None
            self.assertGreaterEqual(timing.input_loading_seconds, 0)
            self.assertGreaterEqual(timing.validation_normalization_seconds, 0)
            self.assertGreaterEqual(timing.precheck_seconds, 0)
            self.assertGreaterEqual(timing.optimization_seconds, 0)
            self.assertGreaterEqual(
                timing.result_validation_and_build_seconds,
                0,
            )
            self.assertGreaterEqual(timing.scheduling_pipeline_seconds, 0)

            document = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(document["contract"]["version"], "1.7")
            self.assertEqual(RESULT_CONTRACT_VERSION, "1.7")
            self.assertAlmostEqual(
                document["execution_timing"]["optimization_seconds"],
                timing.optimization_seconds,
            )

            workbook = load_workbook(result.excel_path, read_only=True)
            try:
                sheet = workbook["求解與驗證資訊"]
                values = {
                    sheet.cell(row, 1).value: sheet.cell(row, 2).value
                    for row in range(1, sheet.max_row + 1)
                }
                self.assertAlmostEqual(
                    values["CP-SAT 最佳化（秒）"],
                    timing.optimization_seconds,
                )
                self.assertAlmostEqual(
                    values["排班管線總時間（秒）"],
                    timing.scheduling_pipeline_seconds,
                )
            finally:
                workbook.close()

            stdout = StringIO()
            with patch(
                "clinic_shift_scheduler.cli.run_schedule_file",
                return_value=result,
            ), redirect_stdout(stdout):
                exit_code = main([str(input_path)])
            self.assertEqual(exit_code, 0)
            printed = stdout.getvalue()
            self.assertIn("完成：OPTIMAL + validation PASS", printed)
            self.assertIn("CP-SAT 最佳化", printed)
            self.assertIn("從讀檔到全部輸出", printed)


if __name__ == "__main__":
    unittest.main()
