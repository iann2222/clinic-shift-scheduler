from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import clinic_shift_scheduler.application as application
from clinic_shift_scheduler.app_config import (
    CandidateDiagnosticSettings,
    DiagnosticTimeSettings,
    SchedulerAppConfig,
)
from clinic_shift_scheduler.application import (
    ScheduleApplicationCallbacks,
    ScheduleApplicationError,
    ScheduleApplicationFailureKind,
    ScheduleApplicationRequest,
    request_from_app_config,
    run_schedule_application,
)


class ScheduleApplicationTests(unittest.TestCase):
    def test_user_config_maps_directly_to_typed_request(self) -> None:
        config = SchedulerAppConfig(
            input_file="schedule.json",
            overwrite=True,
            progress_update_seconds=7,
            candidate_diagnostic=CandidateDiagnosticSettings(
                search_limit=12,
                time=DiagnosticTimeSettings(
                    mode="定值",
                    fixed_seconds=30,
                    scheduling_time_ratio=None,
                ),
                export_count=2,
                export_formats=("json", "excel"),
            ),
        )

        request = request_from_app_config(
            config,
            input_directory="input",
            output_directory="output",
            intermediate_directory="runtime/expanded-input",
        )

        self.assertEqual(request.input_path, Path("input/schedule.json"))
        self.assertTrue(request.overwrite)
        self.assertEqual(request.progress_interval_seconds, 7)
        self.assertEqual(request.candidate_export_config.max_candidates, 2)
        self.assertEqual(
            request.candidate_export_config.formats,
            ("json", "excel"),
        )
        self.assertIsNotNone(request.diagnostic_config)
        assert request.diagnostic_config is not None
        self.assertEqual(request.diagnostic_config.max_alternatives, 12)
        self.assertEqual(request.diagnostic_config.max_time_seconds, 30)

    def test_disabled_candidate_search_maps_to_no_diagnostic(self) -> None:
        config = SchedulerAppConfig(
            input_file="schedule.json",
            candidate_diagnostic=CandidateDiagnosticSettings(
                enabled=False,
                export_count=0,
            ),
        )

        request = request_from_app_config(
            config,
            input_directory="input",
            output_directory="output",
            intermediate_directory="runtime/expanded-input",
        )

        self.assertIsNone(request.diagnostic_config)

    def test_application_service_forwards_request_and_callbacks(self) -> None:
        request = ScheduleApplicationRequest(input_path=Path("input.json"))
        progress = Mock()
        diagnostic_progress = Mock()
        callbacks = ScheduleApplicationCallbacks(
            progress=progress,
            diagnostic_progress=diagnostic_progress,
        )
        expected = Mock()

        with patch.object(
            application,
            "run_schedule_file",
            return_value=expected,
        ) as run_file:
            actual = run_schedule_application(request, callbacks)

        self.assertIs(actual, expected)
        run_file.assert_called_once_with(
            request.input_path,
            output_directory=request.output_directory,
            intermediate_directory=request.intermediate_directory,
            overwrite=request.overwrite,
            equivalent_solution_diagnostic_config=request.diagnostic_config,
            candidate_export_config=request.candidate_export_config,
            progress_interval_seconds=request.progress_interval_seconds,
            progress=progress,
            diagnostic_progress=diagnostic_progress,
        )

    def test_application_service_categorizes_lower_level_failures(self) -> None:
        request = ScheduleApplicationRequest(input_path=Path("missing.json"))

        with patch.object(
            application,
            "run_schedule_file",
            side_effect=OSError("file unavailable"),
        ), self.assertRaises(ScheduleApplicationError) as raised:
            run_schedule_application(request)

        self.assertIs(
            raised.exception.kind,
            ScheduleApplicationFailureKind.FILE_ERROR,
        )
        self.assertIsInstance(raised.exception.cause, OSError)
        self.assertEqual(str(raised.exception), "file unavailable")


if __name__ == "__main__":
    unittest.main()
