from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from time import sleep
from unittest.mock import patch

from openpyxl import load_workbook

from clinic_shift_scheduler import (
    EquivalentSolutionDiagnosticConfig,
    EquivalentSolutionDiagnosticStatus,
    FeasibilityStatus,
    RESULT_CONTRACT_VERSION,
    run_schedule_file,
)
import clinic_shift_scheduler.cli as cli_module
from clinic_shift_scheduler.cli import main
import clinic_shift_scheduler.runner as runner_module
import run_scheduler

from tests.fixtures import minimal_valid_input


class ScheduleRunnerTests(unittest.TestCase):
    def test_interactive_console_overwrites_heartbeat_line(self) -> None:
        class InteractiveBuffer(StringIO):
            def isatty(self) -> bool:
                return True

        stream = InteractiveBuffer()
        printer = cli_module._ConsoleProgressPrinter("[排班]", stream)

        printer("嚴格分階段最佳化進行中：已耗時 10 秒")
        printer("嚴格分階段最佳化進行中：已耗時 20 秒")
        heartbeat_output = stream.getvalue()
        self.assertNotIn("\n", heartbeat_output)
        self.assertEqual(heartbeat_output.count("\r"), 2)

        printer("嚴格分階段最佳化完成：共耗時 20.123 秒")
        final_output = stream.getvalue()
        self.assertIn("\r", final_output)
        self.assertTrue(final_output.endswith("20.123 秒\n"))

    def test_noninteractive_console_keeps_heartbeat_lines(self) -> None:
        stream = StringIO()
        printer = cli_module._ConsoleProgressPrinter("[排班]", stream)

        printer("嚴格分階段最佳化進行中：已耗時 10 秒")
        printer("嚴格分階段最佳化進行中：已耗時 20 秒")

        self.assertEqual(stream.getvalue().count("\n"), 2)
        self.assertNotIn("\r", stream.getvalue())

    def test_elapsed_heartbeat_reports_progress_and_completion(self) -> None:
        messages: list[str] = []

        def operation() -> str:
            sleep(0.035)
            return "done"

        result, elapsed = runner_module._run_with_elapsed_heartbeat(
            operation,
            messages.append,
            interval_seconds=0.01,
        )

        self.assertEqual(result, "done")
        self.assertGreaterEqual(elapsed, 0.03)
        self.assertTrue(any("進行中" in message for message in messages))
        self.assertIn("最佳化完成", messages[-1])

    def test_default_diagnostic_time_is_one_fifth_of_optimization(self) -> None:
        automatic = runner_module._resolve_diagnostic_config(
            EquivalentSolutionDiagnosticConfig(),
            125.0,
        )
        explicit = runner_module._resolve_diagnostic_config(
            EquivalentSolutionDiagnosticConfig(max_time_seconds=7.5),
            125.0,
        )

        self.assertEqual(automatic.max_time_seconds, 25.0)
        self.assertEqual(explicit.max_time_seconds, 7.5)

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
                equivalent_solution_diagnostic_config=(
                    EquivalentSolutionDiagnosticConfig(
                        max_alternatives=1,
                        max_time_seconds=30,
                    )
                ),
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
            self.assertGreaterEqual(result.formal_output_seconds, 0)
            self.assertIsNotNone(result.equivalent_solution_diagnostic)
            assert result.equivalent_solution_diagnostic is not None
            self.assertIn(
                result.equivalent_solution_diagnostic.status,
                (
                    EquivalentSolutionDiagnosticStatus.EXACT_COUNT,
                    EquivalentSolutionDiagnosticStatus.AT_LEAST_LIMIT,
                ),
            )
            self.assertGreaterEqual(
                result.equivalent_solution_diagnostic_seconds,
                0,
            )
            self.assertTrue(any("最佳化" in message for message in messages))
            self.assertTrue(any("最佳化完成" in message for message in messages))
            self.assertTrue(
                any(
                    "完成：OPTIMAL + validation PASS" in message
                    for message in messages
                )
            )
            self.assertTrue(any("輸出檔案" in message for message in messages))
            self.assertTrue(
                any(str(result.json_path) in message for message in messages)
            )

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

            def fake_run(*_args, **kwargs):
                config = kwargs["equivalent_solution_diagnostic_config"]
                self.assertIsNone(config.max_time_seconds)
                kwargs["progress"](
                    "完成：OPTIMAL + validation PASS\n"
                    "  CP-SAT 最佳化：1.000 秒\n"
                    "  從讀檔到正式輸出：2.000 秒\n"
                    "  輸出檔案：output/result.json"
                )
                kwargs["diagnostic_progress"](
                    "開始搜尋同品質候選班表"
                )
                return result

            with patch(
                "clinic_shift_scheduler.cli.run_schedule_file",
                side_effect=fake_run,
            ), redirect_stdout(stdout):
                exit_code = main([str(input_path)])
            self.assertEqual(exit_code, 0)
            printed = stdout.getvalue()
            self.assertIn("完成：OPTIMAL + validation PASS", printed)
            self.assertIn("CP-SAT 最佳化", printed)
            self.assertIn("從讀檔到正式輸出", printed)
            self.assertIn("[候選診斷] 開始搜尋", printed)
            self.assertNotIn("[排班] 開始搜尋", printed)


if __name__ == "__main__":
    unittest.main()
