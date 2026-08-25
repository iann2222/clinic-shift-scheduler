from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import PropertyMock, patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from clinic_shift_scheduler.gui.main import create_application
from clinic_shift_scheduler.gui.main_window import MainWindow
from clinic_shift_scheduler.gui.navigation import PageId
from clinic_shift_scheduler.enums import Period
from clinic_shift_scheduler.gui.dialogs import EmployeeEditorValues
from clinic_shift_scheduler.events import DiagnosticIssue


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WEEKLY_EXAMPLE = (
    REPOSITORY_ROOT
    / "input"
    / "匿名範本"
    / "排班輸入_匿名_2026-08.json"
)


class GuiDocumentLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_application(["gui-lifecycle-test"])

    def make_window(self, input_directory: Path) -> MainWindow:
        window = MainWindow(input_directory=input_directory)

        def cleanup() -> None:
            window._bind_session(None)
            window.close()

        self.addCleanup(cleanup)
        return window

    def test_open_document_binds_month_and_clean_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)

            self.assertIsNotNone(window.session)
            assert window.session is not None
            self.assertFalse(window.session.is_dirty)
            self.assertEqual(window.document_header.month_label.text(), "2026-08")
            self.assertEqual(window.document_header.status_label.text(), "已儲存")
            self.assertFalse(hasattr(window.month_clinic_page, "role_list"))
            self.assertEqual(
                window.month_clinic_page.fixed_periods_label.text(),
                "早上、下午、晚上",
            )
            self.assertEqual(
                window.month_clinic_page.period_label.text(),
                "2026 年 8 月（2026-08-01 ~ 2026-08-31）",
            )

    def test_month_page_change_marks_document_dirty_and_invalidates_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)
            assert window.session is not None

            window.session.draft.holidays.append(date(2026, 8, 8))
            window.session.draft.touch()
            window._draft_changed()

            self.assertTrue(window.session.is_dirty)
            self.assertEqual(
                window.document_header.status_label.text(),
                "尚未儲存",
            )
            self.assertIn("重新", window.review_save_page.status_label.text())

    def test_existing_holiday_marks_are_shown_on_specific_date_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)
            assert window.session is not None
            window.session.draft.holidays = [date(2026, 8, 8)]

            window.date_override_page.bind_draft(window.session.draft)

            self.assertEqual(window.date_override_page.holiday_list.count(), 1)
            self.assertEqual(
                window.date_override_page.holiday_list.item(0).text(),
                "2026-08-08",
            )
            self.assertFalse(window.date_override_page.holiday_group.isEnabled())

    def test_specific_date_remove_requires_a_selected_adjustment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)
            page = window.date_override_page
            assert window.session is not None
            window.session.draft.date_overrides = []
            page.bind_draft(window.session.draft)

            self.assertFalse(page.remove_button.isEnabled())
            page.model.add_override(date(2026, 8, 15), is_open=True)
            page.table.selectRow(0)
            self.app.processEvents()
            self.assertTrue(page.remove_button.isEnabled())

            page._remove_selected()

            self.assertEqual(page.model.rowCount(), 0)
            self.assertFalse(page.remove_button.isEnabled())

    def test_validation_routes_to_review_page_and_reports_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)

            result = window.validate_document()

            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.is_valid)
            self.assertEqual(
                window.page_stack.currentWidget().page_id,
                PageId.REVIEW_SAVE,
            )
            self.assertIn("檢查通過", window.review_save_page.status_label.text())

    def test_execution_page_runs_current_saved_document_through_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)
            assert window.session is not None

            with patch.object(window.execution_controller, "start") as start:
                window._start_schedule()

            self.assertEqual(
                window.page_stack.currentWidget().page_id,
                PageId.EXECUTION,
            )
            start.assert_called_once()
            self.assertEqual(
                start.call_args.kwargs["input_path"],
                window.session.path,
            )
            self.assertFalse(window.navigation.list_widget.isEnabled())
            self.assertFalse(window.document_header.settings_button.isEnabled())

            window._show_execution_message(
                {
                    "type": "completed",
                    "status": "OPTIMAL",
                    "validation": "PASS",
                    "paths": {
                        "json": "output/result.json",
                        "excel": "output/result.xlsx",
                        "pdf": "output/result.pdf",
                    },
                    "timings": {"total_execution_seconds": 12.3},
                }
            )
            window._execution_finished(0)

            self.assertEqual(
                window.execution_page.result_status_label.text(),
                "最佳排班完成（OPTIMAL）",
            )
            self.assertEqual(
                window.execution_page.validation_label.text(),
                "通過（PASS）",
            )
            self.assertTrue(window.execution_page.open_output_button.isEnabled())
            self.assertTrue(window.navigation.list_widget.isEnabled())
            self.assertTrue(window.document_header.settings_button.isEnabled())

    def test_cancel_schedule_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))

            with (
                patch.object(
                    type(window.execution_controller),
                    "is_running",
                    new_callable=PropertyMock,
                    return_value=True,
                ),
                patch(
                    "clinic_shift_scheduler.gui.main_window.ask_cancel_confirm",
                    side_effect=(False, True),
                ) as confirm,
                patch.object(
                    window.execution_page,
                    "request_cancelling",
                ) as request_cancelling,
                patch.object(window.execution_controller, "cancel") as cancel,
            ):
                window._cancel_schedule()
                request_cancelling.assert_not_called()
                cancel.assert_not_called()

                window._cancel_schedule()

            self.assertEqual(confirm.call_count, 2)
            self.assertEqual(confirm.call_args.args[1], "終止排班")
            self.assertIn("不會保留", confirm.call_args.args[2])
            self.assertIn(
                "終止排班並保留當前最佳班表",
                confirm.call_args.args[2],
            )
            request_cancelling.assert_called_once_with()
            cancel.assert_called_once_with()

    def test_preserve_schedule_uses_cancel_confirm_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))

            with (
                patch.object(
                    type(window.execution_controller),
                    "is_running",
                    new_callable=PropertyMock,
                    return_value=True,
                ),
                patch(
                    "clinic_shift_scheduler.gui.main_window.ask_cancel_confirm",
                    return_value=False,
                ) as confirm,
                patch.object(
                    window.execution_controller,
                    "preserve_current_best",
                ) as preserve,
            ):
                window._preserve_current_schedule()

            confirm.assert_called_once()
            self.assertEqual(
                confirm.call_args.args[1],
                "保留目前最佳合法班表",
            )
            preserve.assert_not_called()

    def test_validation_issue_routes_to_relevant_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)
            assert window.session is not None
            window.session.draft.employees[0].roles = []

            result = window.validate_document()
            assert result is not None
            self.assertFalse(result.is_valid)
            issue = next(
                issue
                for issue in result.issues
                if issue.path.startswith("$.employees")
            )
            window.navigate_to_issue(issue)

            self.assertEqual(
                window.page_stack.currentWidget().page_id,
                PageId.EMPLOYEE,
            )
            self.assertEqual(
                window.employee_page.table.currentIndex().row(),
                0,
            )

    def test_employee_and_availability_edits_save_and_reopen_equivalently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "edited.json"
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)
            assert window.session is not None
            employee = window.session.draft.employees[0]

            window.employee_page._apply_editor_values(
                employee,
                EmployeeEditorValues(
                    name="修改姓名",
                    employment_type=employee.employment_type,
                    full_time_class=employee.full_time_class,
                    roles=tuple(employee.roles),
                    shift_mode=employee.shift_mode,
                    required_shifts=employee.required_shifts,
                    target_shifts=employee.target_shifts,
                    min_shifts=employee.min_shifts,
                    max_shifts=employee.max_shifts,
                    notes=employee.notes,
                ),
            )
            window.employee_page._changed()
            window.session.draft.set_period_availability(
                employee.employee_id,
                date(2026, 8, 3),
                Period.MORNING,
                "unavailable",
            )
            window.full_time_unavailable_page.draft_changed.emit()

            self.assertTrue(window.session.is_dirty)
            self.assertTrue(window._save_to(target, overwrite=False))
            reopened = window.authoring_application.open_document(target)

            self.assertEqual(reopened.draft.employees[0].name, "修改姓名")
            self.assertEqual(
                reopened.draft.availability_state(
                    reopened.draft.employees[0],
                    date(2026, 8, 3),
                    Period.MORNING,
                ),
                "unavailable",
            )
            self.assertFalse(window.session.is_dirty)

    def test_available_slot_issue_focuses_employee_date_and_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)
            assert window.session is not None
            employee = window.session.draft.employees[4]
            assert employee.available_slots is not None
            employee.available_slots[0].roles = ["missing-role"]

            result = window.validate_document()
            assert result is not None
            issue = next(
                item
                for item in result.issues
                if ".available_slots[0].roles" in item.path
            )
            window.navigate_to_issue(issue)

            self.assertEqual(
                window.page_stack.currentWidget().page_id,
                PageId.PART_TIME_AVAILABLE,
            )
            self.assertEqual(
                window.part_time_available_page.model.employee_at(
                    window.part_time_available_page.table.currentIndex().row()
                ).employee_id,
                employee.employee_id,
            )

    def test_weekly_and_employee_issues_focus_exact_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)

            window.navigate_to_issue(
                DiagnosticIssue(
                    code="invalid_value",
                    path="$.weekly_demands[2].staffing.evening.nursing",
                    message="invalid",
                )
            )
            self.assertEqual(
                window.page_stack.currentWidget().page_id,
                PageId.WEEKLY_DEMAND,
            )
            self.assertEqual(
                (
                    window.weekly_demand_page.table.currentIndex().row(),
                    window.weekly_demand_page.table.currentIndex().column(),
                ),
                (8, 4),
            )

            window.navigate_to_issue(
                DiagnosticIssue(
                    code="invalid_shift_fields",
                    path="$.employees[1].target_shifts",
                    message="invalid",
                )
            )
            self.assertEqual(
                window.employee_page.table.currentIndex().row(),
                1,
            )

    def test_close_is_cancelled_when_dirty_changes_are_not_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.create_new_month(2027, 1)
            event = QCloseEvent()

            with patch.object(
                QMessageBox,
                "exec",
                return_value=QMessageBox.StandardButton.Cancel,
            ):
                window.closeEvent(event)

            self.assertFalse(event.isAccepted())


if __name__ == "__main__":
    unittest.main()
