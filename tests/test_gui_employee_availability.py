from __future__ import annotations

import os
import unittest
from datetime import date
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from clinic_shift_scheduler.authoring_application import AuthoringApplication
from clinic_shift_scheduler.enums import EmploymentType, Period, ShiftMode
from clinic_shift_scheduler.gui.main import create_application
from clinic_shift_scheduler.gui.pages import EmployeePage
from clinic_shift_scheduler.gui.drafts import UnavailableSlotDraft
from clinic_shift_scheduler.gui.models import (
    AvailabilityFilterProxyModel,
    AvailabilityTableModel,
    EmployeeTableModel,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WEEKLY_EXAMPLE = (
    REPOSITORY_ROOT
    / "input"
    / "匿名範本"
    / "排班輸入_匿名_2026-08.json"
)


class EmployeeDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.application = AuthoringApplication()
        self.session = self.application.open_document(WEEKLY_EXAMPLE)
        self.draft = self.session.draft

    def test_new_employee_has_unique_permanent_id_and_valid_defaults(self) -> None:
        original_ids = {item.employee_id for item in self.draft.employees}

        employee = self.draft.add_employee()

        self.assertNotIn(employee.employee_id, original_ids)
        self.assertTrue(employee.employee_id.startswith("EMP-"))
        self.assertEqual(employee.roles, [self.draft.roles[0]])
        self.assertEqual(employee.shift_mode, ShiftMode.EXACT)
        self.assertEqual(employee.required_shifts, 0)
        self.assertTrue(self.application.validate(self.draft).is_valid)

    def test_shift_mode_transition_clears_incompatible_fields(self) -> None:
        employee = self.draft.employees[0]

        self.draft.set_shift_mode(employee, ShiftMode.TARGET)
        employee.target_shifts = 20
        employee.min_shifts = 10
        employee.max_shifts = 25
        self.assertTrue(self.application.validate(self.draft).is_valid)

        self.draft.set_shift_mode(employee, ShiftMode.EXACT)

        self.assertEqual(employee.required_shifts, 0)
        self.assertIsNone(employee.target_shifts)
        self.assertIsNone(employee.min_shifts)
        self.assertIsNone(employee.max_shifts)
        self.assertTrue(self.application.validate(self.draft).is_valid)

    def test_part_time_rejects_target_and_uses_explicit_slots(self) -> None:
        employee = self.draft.employees[0]
        self.draft.set_employee_type(employee, EmploymentType.PART_TIME)

        self.assertIsNone(employee.full_time_class)
        self.assertEqual(employee.available_slots, [])
        with self.assertRaisesRegex(ValueError, "兼職"):
            self.draft.set_shift_mode(employee, ShiftMode.TARGET)
        self.assertTrue(self.application.validate(self.draft).is_valid)

    def test_remove_employee_cascades_all_cross_references(self) -> None:
        employee = self.draft.employees[0]
        self.draft.unavailable_slots.append(
            UnavailableSlotDraft(
                employee.employee_id,
                date(2026, 8, 3),
                Period.MORNING,
            )
        )

        self.draft.remove_employee(employee.employee_id)

        self.assertNotIn(employee.employee_id, {item.employee_id for item in self.draft.employees})
        self.assertFalse(
            any(item.employee_id == employee.employee_id for item in self.draft.leave_requests)
        )
        self.assertFalse(
            any(item.employee_id == employee.employee_id for item in self.draft.unavailable_slots)
        )
        self.assertTrue(self.application.validate(self.draft).is_valid)


class AvailabilityDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.application = AuthoringApplication()
        self.session = self.application.open_document(WEEKLY_EXAMPLE)
        self.draft = self.session.draft

    def test_full_time_defaults_available_and_supports_unavailable_or_leave(self) -> None:
        employee = self.draft.employees[0]
        day = date(2026, 8, 3)
        self.assertEqual(
            self.draft.availability_state(employee, day, Period.MORNING),
            "available",
        )

        self.draft.set_period_availability(
            employee.employee_id,
            day,
            Period.MORNING,
            "unavailable",
        )
        self.assertEqual(
            self.draft.availability_state(employee, day, Period.MORNING),
            "unavailable",
        )
        self.draft.set_period_availability(
            employee.employee_id,
            day,
            Period.MORNING,
            "leave",
        )
        self.assertEqual(
            self.draft.availability_state(employee, day, Period.MORNING),
            "leave",
        )
        self.assertTrue(self.application.validate(self.draft).is_valid)

    def test_all_day_leave_removes_lower_priority_states(self) -> None:
        employee = self.draft.employees[0]
        day = date(2026, 8, 3)
        self.draft.set_period_availability(
            employee.employee_id,
            day,
            Period.MORNING,
            "unavailable",
        )

        self.draft.set_all_day_leave(employee.employee_id, day, True)

        for period in self.draft.periods:
            self.assertEqual(
                self.draft.availability_state(employee, day, period),
                "leave",
            )
        self.assertFalse(
            any(item.employee_id == employee.employee_id and item.date == day for item in self.draft.unavailable_slots)
        )
        with self.assertRaisesRegex(ValueError, "整日請假"):
            self.draft.set_period_availability(
                employee.employee_id,
                day,
                Period.MORNING,
                "available",
            )

    def test_part_time_explicit_available_slot_and_role_restriction(self) -> None:
        employee = next(
            item
            for item in self.draft.employees
            if item.employment_type is EmploymentType.PART_TIME
        )
        day = date(2026, 8, 3)
        self.assertEqual(
            self.draft.availability_state(employee, day, Period.MORNING),
            "unavailable",
        )

        self.draft.set_period_availability(
            employee.employee_id,
            day,
            Period.MORNING,
            "available",
        )
        self.draft.set_available_slot_roles(
            employee,
            day,
            Period.MORNING,
            [employee.roles[0]],
        )

        slot = self.draft.available_slot(employee, day, Period.MORNING)
        self.assertIsNotNone(slot)
        assert slot is not None
        self.assertEqual(slot.roles, [employee.roles[0]])
        self.assertEqual(
            self.draft.availability_state(employee, day, Period.MORNING),
            "available",
        )
        self.assertTrue(self.application.validate(self.draft).is_valid)


class EmployeeAvailabilityModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = create_application(["employee-availability-test"])

    def setUp(self) -> None:
        self.application = AuthoringApplication()
        self.session = self.application.open_document(WEEKLY_EXAMPLE)

    def test_employee_summary_model_exposes_stable_id(self) -> None:
        model = EmployeeTableModel(self.session.draft)

        self.assertEqual(model.rowCount(), len(self.session.draft.employees))
        self.assertEqual(
            model.data(model.index(0, 0), Qt.ItemDataRole.UserRole),
            self.session.draft.employees[0].employee_id,
        )

    def test_availability_model_edits_full_time_matrix(self) -> None:
        employee = self.session.draft.employees[0]
        model = AvailabilityTableModel()
        model.set_context(self.session.draft, employee.employee_id)
        row = (date(2026, 8, 3) - self.session.draft.start_date).days
        index = model.index(row, 3)

        self.assertEqual(model.data(index, Qt.ItemDataRole.EditRole), "available")
        self.assertTrue(model.setData(index, "unavailable"))
        self.assertEqual(model.data(index, Qt.ItemDataRole.EditRole), "unavailable")

    def test_all_day_leave_disables_period_cells(self) -> None:
        employee = self.session.draft.employees[0]
        model = AvailabilityTableModel()
        model.set_context(self.session.draft, employee.employee_id)
        row = (date(2026, 8, 3) - self.session.draft.start_date).days

        self.assertTrue(
            model.setData(
                model.index(row, 2),
                Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )
        )
        flags = model.flags(model.index(row, 3))
        self.assertFalse(flags & Qt.ItemFlag.ItemIsEnabled)
        self.assertFalse(flags & Qt.ItemFlag.ItemIsEditable)

    def test_employee_page_shows_immediate_basic_validation(self) -> None:
        page = EmployeePage()
        self.addCleanup(page.close)
        page.bind_draft(self.session.draft)

        page.name_edit.setText("")
        page.name_edit.editingFinished.emit()

        self.assertFalse(page.inline_validation_label.isHidden())
        self.assertIn("姓名不可留空", page.inline_validation_label.text())

    def test_batch_period_state_updates_multiple_cells_once(self) -> None:
        employee = self.session.draft.employees[0]
        model = AvailabilityTableModel()
        model.set_context(self.session.draft, employee.employee_id)
        row = (date(2026, 8, 3) - self.session.draft.start_date).days
        emissions: list[bool] = []
        model.draft_changed.connect(lambda: emissions.append(True))

        changed, skipped = model.apply_period_state(
            {(row, 3), (row, 4)},
            "unavailable",
        )

        self.assertEqual((changed, skipped), (2, 0))
        self.assertEqual(emissions, [True])
        self.assertEqual(
            self.session.draft.availability_state(
                employee,
                date(2026, 8, 3),
                Period.MORNING,
            ),
            "unavailable",
        )
        self.assertEqual(
            self.session.draft.availability_state(
                employee,
                date(2026, 8, 3),
                Period.AFTERNOON,
            ),
            "unavailable",
        )

    def test_batch_all_day_leave_and_filters_use_source_dates(self) -> None:
        employee = self.session.draft.employees[0]
        model = AvailabilityTableModel()
        model.set_context(self.session.draft, employee.employee_id)
        proxy = AvailabilityFilterProxyModel()
        proxy.setSourceModel(model)
        monday_row = (date(2026, 8, 3) - self.session.draft.start_date).days

        self.assertEqual(model.apply_all_day_leave({monday_row}, True), 1)
        proxy.set_weekday_filter(0)
        self.assertEqual(proxy.rowCount(), 5)
        proxy.set_state_filter("leave")
        self.assertGreaterEqual(proxy.rowCount(), 1)
        visible_dates = {
            model.date_at(proxy.mapToSource(proxy.index(row, 0)).row())
            for row in range(proxy.rowCount())
        }
        self.assertIn(date(2026, 8, 3), visible_dates)


if __name__ == "__main__":
    unittest.main()
