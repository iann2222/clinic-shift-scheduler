from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from clinic_shift_scheduler.gui.main import create_application
from clinic_shift_scheduler.gui.main_window import MainWindow
from clinic_shift_scheduler.gui.navigation import PageId


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

    def test_open_document_binds_month_roles_and_clean_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = self.make_window(Path(directory))
            window.open_document_path(WEEKLY_EXAMPLE)

            self.assertIsNotNone(window.session)
            assert window.session is not None
            self.assertFalse(window.session.is_dirty)
            self.assertEqual(window.document_header.month_label.text(), "2026-08")
            self.assertEqual(window.document_header.status_label.text(), "已儲存")
            self.assertEqual(window.month_clinic_page.role_list.count(), 2)

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
