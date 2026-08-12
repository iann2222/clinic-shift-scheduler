from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from clinic_shift_scheduler import (
    ExecutionPhase,
    InputValidationError,
    SchedulerConfigDocument,
    WeeklyAuthoringDocument,
    load_scheduler_config_document,
    load_weekly_authoring_document,
    write_scheduler_config_document,
    write_weekly_authoring_document,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WEEKLY_EXAMPLE = (
    REPOSITORY_ROOT
    / "input"
    / "匿名範本"
    / "排班輸入_匿名_2026-08.json"
)


class UserDocumentTests(unittest.TestCase):
    def test_weekly_document_reports_multiple_structural_issues(self) -> None:
        payload = json.loads(WEEKLY_EXAMPLE.read_text(encoding="utf-8"))
        payload["unknown_root"] = True
        payload["period"]["unknown_period"] = True
        payload["weekly_demands"][0]["unknown_rule"] = True

        with self.assertRaises(InputValidationError) as raised:
            WeeklyAuthoringDocument.from_dict(payload)

        self.assertEqual(len(raised.exception.issues), 3)
        self.assertEqual(
            {issue.phase for issue in raised.exception.issues},
            {ExecutionPhase.INPUT},
        )

    def test_config_document_reports_multiple_structural_issues(self) -> None:
        payload = json.loads(
            (REPOSITORY_ROOT / "config.json").read_text(encoding="utf-8")
        )
        payload["unknown_root"] = True
        payload["使用者設定"].pop("輸入檔名")
        payload["預設設定"]["unknown_default"] = True

        with self.assertRaises(InputValidationError) as raised:
            SchedulerConfigDocument.from_dict(payload)

        self.assertEqual(len(raised.exception.issues), 3)
        self.assertEqual(
            {issue.phase for issue in raised.exception.issues},
            {ExecutionPhase.CONFIG},
        )

    def test_weekly_document_round_trip_preserves_all_user_fields(self) -> None:
        payload = json.loads(WEEKLY_EXAMPLE.read_text(encoding="utf-8"))

        document = WeeklyAuthoringDocument.from_dict(payload)

        self.assertEqual(document.to_dict(), payload)
        self.assertEqual(document.employees[0].notes, payload["employees"][0]["notes"])
        self.assertEqual(document.roles, ("reception", "nursing"))
        self.assertEqual(document.weekly_demands[0].staffing.to_dict(), payload["weekly_demands"][0]["staffing"])

    def test_weekly_document_atomic_write_revalidates_edits(self) -> None:
        document = load_weekly_authoring_document(WEEKLY_EXAMPLE)
        edited_employee = replace(document.employees[0], name="更新姓名")
        edited = replace(
            document,
            employees=(edited_employee, *document.employees[1:]),
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "input.json"
            write_weekly_authoring_document(target, edited)
            loaded = load_weekly_authoring_document(target)

        self.assertEqual(loaded.employees[0].name, "更新姓名")
        self.assertEqual(loaded.employees[0].notes, document.employees[0].notes)

    def test_invalid_weekly_edit_cannot_replace_last_valid_file(self) -> None:
        document = load_weekly_authoring_document(WEEKLY_EXAMPLE)
        invalid_employee = replace(
            document.employees[0],
            required_shifts=None,
        )
        invalid = replace(
            document,
            employees=(invalid_employee, *document.employees[1:]),
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "input.json"
            write_weekly_authoring_document(target, document)
            original = target.read_bytes()

            with self.assertRaises(InputValidationError):
                write_weekly_authoring_document(target, invalid)

            self.assertEqual(target.read_bytes(), original)

    def test_config_document_preserves_annotations_and_round_trips(self) -> None:
        source = REPOSITORY_ROOT / "config.json"
        payload = json.loads(source.read_text(encoding="utf-8"))

        document = SchedulerConfigDocument.from_dict(payload)

        self.assertEqual(document.to_dict(), payload)
        self.assertEqual(document.user_config.input_file, "排班輸入_2026-08.json")
        self.assertEqual(document.default_config.candidate_diagnostic.export_count, 3)

    def test_config_document_atomic_write_preserves_explanatory_fields(self) -> None:
        document = load_scheduler_config_document(REPOSITORY_ROOT / "config.json")
        edited = replace(
            document,
            user_config=replace(document.user_config, progress_update_seconds=8),
        )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.json"
            write_scheduler_config_document(target, edited)
            payload = json.loads(target.read_text(encoding="utf-8"))
            loaded = load_scheduler_config_document(target)

        self.assertEqual(loaded.user_config.progress_update_seconds, 8)
        self.assertIn("__檔案說明__", payload)
        self.assertIn(
            "__模式選項說明__",
            payload["使用者設定"]["候選診斷"]["診斷時間上限"],
        )


if __name__ == "__main__":
    unittest.main()
