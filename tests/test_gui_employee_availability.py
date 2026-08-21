from __future__ import annotations

import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QHeaderView, QLabel

from clinic_shift_scheduler.authoring_application import AuthoringApplication
from clinic_shift_scheduler.enums import EmploymentType, Period, ShiftMode
from clinic_shift_scheduler.gui.main import create_application
from clinic_shift_scheduler.gui.dialogs import EmployeeEditDialog
from clinic_shift_scheduler.gui.pages import EmployeePage
from clinic_shift_scheduler.gui.pages import FullTimeUnavailablePage, PartTimeAvailablePage
from clinic_shift_scheduler.gui.drafts import UnavailableSlotDraft
from clinic_shift_scheduler.gui.models import (
    AvailabilityFilterProxyModel,
    AvailabilitySummaryTableModel,
    AvailabilityTableModel,
    EmployeeTableModel,
)
from clinic_shift_scheduler.gui.pages.availability_page import _parse_day_numbers


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
        self.draft.set_employee_type(employee, EmploymentType.PART_TIME)

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

    def test_full_time_rejects_target_and_part_time_uses_explicit_slots(self) -> None:
        employee = self.draft.employees[0]
        with self.assertRaisesRegex(ValueError, "正職"):
            self.draft.set_shift_mode(employee, ShiftMode.TARGET)

        self.draft.set_employee_type(employee, EmploymentType.PART_TIME)

        self.assertIsNone(employee.full_time_class)
        self.assertEqual(employee.available_slots, [])
        self.draft.set_shift_mode(employee, ShiftMode.TARGET)
        self.assertEqual(employee.target_shifts, 0)
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
        self.assertEqual(model.columnCount(), 6)
        headers = {
            model.headerData(column, Qt.Orientation.Horizontal)
            for column in range(model.columnCount())
        }
        self.assertIn("職務", headers)
        self.assertNotIn("公平分組", headers)

    def test_employee_summary_model_notifies_view_when_employee_is_added(self) -> None:
        model = EmployeeTableModel(self.session.draft)
        original_count = model.rowCount()
        rows_inserted = QSignalSpy(model.rowsInserted)

        employee = model.append_employee()

        self.assertEqual(model.rowCount(), original_count + 1)
        self.assertEqual(rows_inserted.count(), 1)
        self.assertEqual(
            model.employee_at(original_count).employee_id,
            employee.employee_id,
        )

    def test_summary_models_show_all_employees_of_their_own_type(self) -> None:
        full_time = AvailabilitySummaryTableModel(
            EmploymentType.FULL_TIME,
            self.session.draft,
        )
        part_time = AvailabilitySummaryTableModel(
            EmploymentType.PART_TIME,
            self.session.draft,
        )

        self.assertEqual(full_time.rowCount(), 4)
        self.assertEqual(part_time.rowCount(), 2)
        self.assertEqual(full_time.columnCount(), 2)
        self.assertEqual(part_time.columnCount(), 3)
        self.assertIn("2 號（早）", part_time.data(part_time.index(0, 1)))
        self.assertEqual(
            part_time.headerData(2, Qt.Orientation.Horizontal),
            "不可排日期與時段",
        )

    def test_part_time_available_and_unavailable_periods_are_complements(self) -> None:
        model = AvailabilitySummaryTableModel(
            EmploymentType.PART_TIME,
            self.session.draft,
        )
        employee = model.employee_at(0)
        assert employee is not None
        unavailable = {(date(2026, 8, 1), Period.MORNING)}

        model.replace_selected_periods(employee, unavailable, complement=True)

        available_after = model.selected_periods(employee)
        unavailable_after = model.selected_periods(employee, complement=True)
        self.assertEqual(unavailable_after, unavailable)
        self.assertFalse(available_after & unavailable_after)
        self.assertEqual(len(available_after) + len(unavailable_after), 31 * 3)

    def test_full_time_summary_replaces_only_selected_employee_periods(self) -> None:
        model = AvailabilitySummaryTableModel(
            EmploymentType.FULL_TIME,
            self.session.draft,
        )
        employee = model.employee_at(0)
        assert employee is not None
        selected = {
            (date(2026, 8, 3), Period.MORNING),
            (date(2026, 8, 3), Period.EVENING),
        }

        model.replace_selected_periods(employee, selected)

        self.assertEqual(model.selected_periods(employee), selected)
        self.assertEqual(
            self.session.draft.availability_state(
                employee, date(2026, 8, 3), Period.AFTERNOON
            ),
            "available",
        )
        self.assertTrue(self.application.validate(self.session.draft).is_valid)

    def test_new_full_day_selection_stays_unavailable_not_leave(self) -> None:
        model = AvailabilitySummaryTableModel(
            EmploymentType.FULL_TIME,
            self.session.draft,
        )
        employee = model.employee_at(0)
        assert employee is not None
        day = date(2026, 8, 5)

        model.replace_selected_periods(
            employee,
            {(day, period) for period in self.session.draft.periods},
        )

        self.assertFalse(
            any(
                item.employee_id == employee.employee_id
                and item.date == day
                and item.all_day
                for item in self.session.draft.leave_requests
            )
        )
        self.assertEqual(
            {
                item.period
                for item in self.session.draft.unavailable_slots
                if item.employee_id == employee.employee_id and item.date == day
            },
            set(self.session.draft.periods),
        )

    def test_part_time_summary_preserves_existing_role_restrictions(self) -> None:
        model = AvailabilitySummaryTableModel(
            EmploymentType.PART_TIME,
            self.session.draft,
        )
        employee = model.employee_at(0)
        assert employee is not None and employee.available_slots
        original = employee.available_slots[0]
        original.roles = [employee.roles[0]]
        selected = model.selected_periods(employee)
        selected.add((date(2026, 8, 5), Period.AFTERNOON))

        model.replace_selected_periods(employee, selected)

        preserved = self.session.draft.available_slot(
            employee, original.date, original.period
        )
        added = self.session.draft.available_slot(
            employee, date(2026, 8, 5), Period.AFTERNOON
        )
        assert preserved is not None and added is not None
        self.assertEqual(preserved.roles, [employee.roles[0]])
        self.assertIsNone(added.roles)

    def test_date_list_parser_accepts_common_separators_and_validates_month(self) -> None:
        self.assertEqual(_parse_day_numbers("1、 3,5；3", 31), (1, 3, 5))
        self.assertEqual(_parse_day_numbers("", 31), ())
        with self.assertRaisesRegex(ValueError, "1 到 28"):
            _parse_day_numbers("29", 28)
        with self.assertRaisesRegex(ValueError, "不是有效日號"):
            _parse_day_numbers("星期一", 31)

    def test_full_time_and_part_time_pages_use_same_fixed_name_width(self) -> None:
        full_time_page = FullTimeUnavailablePage()
        part_time_page = PartTimeAvailablePage()
        self.addCleanup(full_time_page.close)
        self.addCleanup(part_time_page.close)
        full_time_page.bind_draft(self.session.draft)
        part_time_page.bind_draft(self.session.draft)

        self.assertEqual(
            full_time_page.table.columnWidth(0),
            part_time_page.table.columnWidth(0),
        )
        self.assertGreaterEqual(
            full_time_page.table.columnWidth(0),
            full_time_page.table.fontMetrics().horizontalAdvance("中文四字"),
        )
        self.assertEqual(part_time_page.table.model().columnCount(), 3)
        header = part_time_page.table.horizontalHeader()
        self.assertEqual(
            header.sectionResizeMode(1),
            QHeaderView.ResizeMode.Stretch,
        )
        self.assertEqual(
            header.sectionResizeMode(2),
            QHeaderView.ResizeMode.Stretch,
        )
        self.assertTrue(part_time_page.table.wordWrap())
        self.assertTrue(
            any(
                "只需手動編輯其中一邊" in label.text()
                for label in part_time_page.findChildren(QLabel, "mutedText")
            )
        )
        self.assertIn(
            "兼職時段",
            [
                label.text()
                for label in part_time_page.findChildren(QLabel, "pageTitle")
            ],
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

    def test_employee_page_shows_selected_employee_as_read_only_summary(self) -> None:
        page = EmployeePage()
        self.addCleanup(page.close)
        page.bind_draft(self.session.draft)

        self.assertEqual(page.name_label.text(), self.session.draft.employees[0].name)
        self.assertTrue(page.edit_button.isEnabled())
        self.assertFalse(hasattr(page, "name_edit"))

    def test_employee_editor_role_checkboxes_use_chinese_labels_and_domain_keys(self) -> None:
        dialog = EmployeeEditDialog(
            self.session.draft.roles,
            employee=self.session.draft.employees[0],
        )
        self.addCleanup(dialog.close)

        self.assertEqual(
            [checkbox.text() for checkbox in dialog.role_checks],
            ["櫃台", "跟診"],
        )
        self.assertEqual(
            [checkbox.property("role_key") for checkbox in dialog.role_checks],
            ["reception", "nursing"],
        )
        self.assertTrue(any(checkbox.isChecked() for checkbox in dialog.role_checks))

    def test_new_employee_editor_allows_full_time_class_selection(self) -> None:
        dialog = EmployeeEditDialog(self.session.draft.roles)
        self.addCleanup(dialog.close)

        self.assertTrue(dialog.class_combo.isEnabled())
        dialog.class_combo.setCurrentIndex(1)
        self.assertEqual(dialog.values.full_time_class.value, "B")

    def test_double_clicking_employee_name_opens_editor(self) -> None:
        page = EmployeePage()
        self.addCleanup(page.close)
        page.bind_draft(self.session.draft)

        with patch.object(page, "_edit_employee") as edit_employee:
            page.table.doubleClicked.emit(page.model.index(0, 0))
            edit_employee.assert_called_once_with()
            page.table.doubleClicked.emit(page.model.index(0, 1))
            edit_employee.assert_called_once_with()

    def test_employee_editor_shows_only_fields_for_selected_shift_mode(self) -> None:
        dialog = EmployeeEditDialog(self.session.draft.roles)
        self.addCleanup(dialog.close)

        for control, field in (
            (dialog.required_spin, dialog.required_field),
            (dialog.target_spin, dialog.target_field),
            (dialog.min_spin, dialog.min_field),
            (dialog.max_spin, dialog.max_field),
        ):
            self.assertEqual(control.suffix(), "")
            self.assertEqual(field.unit_label.text(), "節")

        self.assertTrue(dialog.shift_form.isRowVisible(dialog.required_field))
        self.assertFalse(dialog.shift_form.isRowVisible(dialog.target_field))
        self.assertFalse(dialog.shift_form.isRowVisible(dialog.minimum_row))

        dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData(ShiftMode.RANGE))
        self.assertFalse(dialog.shift_form.isRowVisible(dialog.required_field))
        self.assertFalse(dialog.shift_form.isRowVisible(dialog.target_field))
        self.assertTrue(dialog.shift_form.isRowVisible(dialog.minimum_row))
        self.assertTrue(dialog.shift_form.isRowVisible(dialog.maximum_row))
        self.assertTrue(dialog.min_enabled.isHidden())
        self.assertTrue(dialog.max_enabled.isHidden())

        dialog.type_combo.setCurrentIndex(
            dialog.type_combo.findData(EmploymentType.PART_TIME)
        )
        dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData(ShiftMode.TARGET))
        self.assertFalse(dialog.shift_form.isRowVisible(dialog.required_field))
        self.assertTrue(dialog.shift_form.isRowVisible(dialog.target_field))
        self.assertTrue(dialog.shift_form.isRowVisible(dialog.minimum_row))
        self.assertFalse(dialog.min_enabled.isHidden())
        self.assertFalse(dialog.max_enabled.isHidden())

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
