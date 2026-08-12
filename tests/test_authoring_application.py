from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from clinic_shift_scheduler.authoring_application import (
    AuthoringApplication,
    AuthoringFileExistsError,
    default_month_filename,
)
from clinic_shift_scheduler.enums import EmploymentType, Period
from clinic_shift_scheduler.errors import InputValidationError
from clinic_shift_scheduler.gui.drafts import RoleMutationError
from clinic_shift_scheduler.gui.presenters import SchedulePresenter


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WEEKLY_EXAMPLE = (
    REPOSITORY_ROOT
    / "input"
    / "匿名範本"
    / "排班輸入_匿名_2026-08.json"
)


class AuthoringApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.application = AuthoringApplication()

    def test_document_draft_round_trip_is_lossless(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        expected = json.loads(WEEKLY_EXAMPLE.read_text(encoding="utf-8"))

        self.assertEqual(SchedulePresenter.to_payload(session.draft), expected)
        self.assertTrue(self.application.validate(session.draft).is_valid)
        self.assertFalse(session.is_dirty)

    def test_dirty_state_uses_semantic_snapshot_and_can_return_to_clean(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        original = list(session.draft.holidays)

        session.draft.holidays.append(date(2026, 8, 8))
        self.assertTrue(session.is_dirty)
        session.draft.holidays = original

        self.assertFalse(session.is_dirty)

    def test_create_month_has_fixed_period_and_three_user_demand_groups(self) -> None:
        session = self.application.create_month(2027, 2)

        self.assertEqual(session.draft.start_date, date(2027, 2, 1))
        self.assertEqual(session.draft.end_date, date(2027, 2, 28))
        self.assertEqual(
            [period.value for period in session.draft.periods],
            ["morning", "afternoon", "evening"],
        )
        self.assertEqual(len(session.draft.weekly_demands), 3)
        self.assertTrue(all(rule.is_open for rule in session.draft.weekly_demands))
        for rule in session.draft.weekly_demands:
            assert rule.staffing is not None
            for period in session.draft.periods:
                self.assertEqual(
                    rule.staffing.counts[period],
                    {role: 1 for role in session.draft.roles},
                )
        self.assertTrue(session.is_dirty)
        self.assertEqual(default_month_filename(2027, 2), "排班輸入_2027-02.json")

    def test_copy_previous_preserves_stable_data_and_clears_dates(self) -> None:
        source = self.application.open_document(WEEKLY_EXAMPLE)
        copied = self.application.create_month_from_previous(
            WEEKLY_EXAMPLE,
            2026,
            9,
        )

        self.assertEqual(copied.draft.start_date, date(2026, 9, 1))
        self.assertEqual(copied.draft.end_date, date(2026, 9, 30))
        self.assertEqual(copied.draft.holidays, [])
        self.assertEqual(copied.draft.date_overrides, [])
        self.assertEqual(copied.draft.leave_requests, [])
        self.assertEqual(copied.draft.unavailable_slots, [])
        self.assertEqual(
            [employee.employee_id for employee in copied.draft.employees],
            [employee.employee_id for employee in source.draft.employees],
        )
        self.assertEqual(
            copied.draft.weekly_demands,
            source.draft.weekly_demands,
        )
        for employee in copied.draft.employees:
            if employee.employment_type is EmploymentType.PART_TIME:
                self.assertEqual(employee.available_slots, [])
        self.assertTrue(copied.is_dirty)

    def test_copy_rejects_same_source_month(self) -> None:
        with self.assertRaisesRegex(ValueError, "不可與來源月份相同"):
            self.application.create_month_from_previous(
                WEEKLY_EXAMPLE,
                2026,
                8,
            )

    def test_role_rename_updates_every_reference(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        draft = session.draft

        draft.rename_role("nursing", "clinical_assistant")

        self.assertEqual(draft.roles, ["reception", "clinical_assistant"])
        for rule in draft.weekly_demands:
            if rule.staffing is not None:
                for period in draft.periods:
                    self.assertIn(
                        "clinical_assistant",
                        rule.staffing.counts[period],
                    )
                    self.assertNotIn("nursing", rule.staffing.counts[period])
        for employee in draft.employees:
            self.assertNotIn("nursing", employee.roles)
            if employee.available_slots:
                for slot in employee.available_slots:
                    if slot.roles is not None:
                        self.assertNotIn("nursing", slot.roles)
        self.assertTrue(self.application.validate(draft).is_valid)

    def test_role_add_initializes_all_staffing_counts_to_zero(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        session.draft.add_role("pharmacy")

        for rule in session.draft.weekly_demands:
            if rule.staffing is not None:
                for period in session.draft.periods:
                    self.assertEqual(rule.staffing.counts[period]["pharmacy"], 0)

    def test_role_delete_rejects_employee_losing_last_qualification(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)

        with self.assertRaises(RoleMutationError):
            session.draft.delete_role("reception")

    def test_role_delete_keeps_available_slot_role_restrictions_valid(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        draft = session.draft
        employee = next(
            employee
            for employee in draft.employees
            if employee.available_slots
        )
        for item in draft.employees:
            if "nursing" in item.roles and "reception" not in item.roles:
                item.roles.append("reception")
        assert employee.available_slots is not None
        employee.available_slots[0].roles = ["nursing"]

        draft.delete_role("nursing")

        self.assertIsNone(employee.available_slots[0].roles)
        self.assertTrue(self.application.validate(draft).is_valid)

    def test_save_round_trip_marks_session_clean(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        session.draft.employees[0].name = "新姓名"

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "schedule.json"
            saved = self.application.save(session, target)
            reopened = self.application.open_document(saved)

        self.assertFalse(session.is_dirty)
        self.assertEqual(reopened.draft.employees[0].name, "新姓名")
        self.assertEqual(
            SchedulePresenter.to_payload(reopened.draft),
            SchedulePresenter.to_payload(session.draft),
        )

    def test_save_as_refuses_unapproved_overwrite(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "schedule.json"
            target.write_text("existing", encoding="utf-8")

            with self.assertRaises(AuthoringFileExistsError):
                self.application.save(session, target, overwrite=False)

            self.assertEqual(target.read_text(encoding="utf-8"), "existing")

    def test_invalid_save_preserves_existing_file_and_draft(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        session.draft.employees[0].roles = []
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "schedule.json"
            target.write_text("last-valid", encoding="utf-8")

            with self.assertRaises(InputValidationError):
                self.application.save(session, target, overwrite=True)

            self.assertEqual(target.read_text(encoding="utf-8"), "last-valid")
            self.assertTrue(session.is_dirty)


if __name__ == "__main__":
    unittest.main()
