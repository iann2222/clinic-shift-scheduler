from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QPushButton,
    QTableWidget,
)

from clinic_shift_scheduler.gui.dialogs import (
    DatePickerDialog,
    MonthDialog,
    SettingsDialog,
    build_message_box,
)
from clinic_shift_scheduler.gui.main import create_application
from clinic_shift_scheduler.gui.main_window import MainWindow
from clinic_shift_scheduler.gui.navigation import NAVIGATION_ITEMS, PageId
from clinic_shift_scheduler.gui.styles.loader import load_application_stylesheet
from clinic_shift_scheduler.gui.widgets.document_header import DocumentState
from clinic_shift_scheduler.config_application import ConfigApplication


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GuiFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_application(["gui-foundation-test"])

    def test_navigation_contract_has_the_seven_input_pages_in_order(self) -> None:
        self.assertEqual(
            tuple(item.page_id for item in NAVIGATION_ITEMS),
            (
                PageId.MONTH_CLINIC,
                PageId.WEEKLY_DEMAND,
                PageId.DATE_OVERRIDE,
                PageId.EMPLOYEE,
                PageId.FULL_TIME_UNAVAILABLE,
                PageId.PART_TIME_AVAILABLE,
                PageId.REVIEW_SAVE,
            ),
        )

    def test_main_window_builds_navigation_header_and_page_stack(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertEqual(
            window.page_ids,
            tuple(item.page_id for item in NAVIGATION_ITEMS),
        )
        self.assertEqual(window.page_stack.count(), 7)
        self.assertEqual(
            window.page_stack.currentWidget().page_id,
            PageId.MONTH_CLINIC,
        )
        self.assertEqual(window.findChildren(QTableWidget), [])
        self.assertFalse(window.navigation.list_widget.isEnabled())
        self.assertEqual(window.navigation.list_widget.currentRow(), -1)

        window.navigation.select_page(PageId.EMPLOYEE)
        self.assertEqual(
            window.page_stack.currentWidget().page_id,
            PageId.MONTH_CLINIC,
        )
        window.create_new_month(2027, 1)
        self.assertTrue(window.navigation.list_widget.isEnabled())
        window.navigation.select_page(PageId.EMPLOYEE)
        self.assertEqual(window.page_stack.currentWidget().page_id, PageId.EMPLOYEE)
        assert window.session is not None
        window.session.mark_clean(Path("test.json"))

    def test_document_header_exposes_clear_clean_and_dirty_states(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertTrue(
            all(
                not button.isEnabled()
                for button in window.document_header.document_action_buttons
            )
        )

        window.document_header.set_document(
            month="2026-08",
            path=Path("input/排班輸入_2026-08.json"),
            state=DocumentState.CLEAN,
        )
        self.assertEqual(window.document_header.month_label.text(), "2026-08")
        self.assertEqual(window.document_header.status_label.text(), "已儲存")
        self.assertTrue(
            all(
                button.isEnabled()
                for button in window.document_header.document_action_buttons
            )
        )

        window.document_header.set_document(
            month="2026-08",
            path=Path("input/排班輸入_2026-08.json"),
            state=DocumentState.DIRTY,
        )
        self.assertEqual(window.document_header.status_label.text(), "尚未儲存")

        header_buttons = {
            button.text()
            for button in window.document_header.findChildren(QPushButton)
        }
        self.assertFalse(
            {"建立月份", "從上月建立", "開啟"} & header_buttons
        )
        month_page_buttons = {
            button.text()
            for button in window.month_clinic_page.findChildren(QPushButton)
        }
        self.assertTrue(
            {"建立新月份", "從上月建立", "開啟既有月份"}
            <= month_page_buttons
        )

    def test_document_workflow_has_standard_keyboard_shortcuts(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)

        shortcuts = {
            label: action.shortcut().toString()
            for label, action in window.document_actions.items()
        }
        self.assertEqual(shortcuts["建立月份"], "Ctrl+N")
        self.assertEqual(shortcuts["開啟"], "Ctrl+O")
        self.assertEqual(shortcuts["儲存"], "Ctrl+S")
        self.assertEqual(shortcuts["另存"], "Ctrl+Shift+S")
        self.assertEqual(shortcuts["檢查輸入資料"], "Ctrl+Shift+V")

    def test_settings_are_separate_from_required_navigation(self) -> None:
        dialog = self._settings_dialog()
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.tabs.count(), 2)
        self.assertEqual(dialog.tabs.tabText(0), "一般設定")
        self.assertEqual(dialog.tabs.tabText(1), "進階設定")
        self.assertNotIn("設定", {item.title for item in NAVIGATION_ITEMS})

    def test_standard_dialog_buttons_are_always_chinese(self) -> None:
        month_dialog = MonthDialog("建立月份", "選擇月份")
        settings_dialog = self._settings_dialog()
        self.addCleanup(month_dialog.close)
        self.addCleanup(settings_dialog.close)

        month_buttons = month_dialog.findChild(QDialogButtonBox)
        settings_buttons = settings_dialog.findChild(QDialogButtonBox)
        assert month_buttons is not None and settings_buttons is not None
        self.assertEqual(
            month_buttons.button(QDialogButtonBox.StandardButton.Ok).text(),
            "確定",
        )
        self.assertEqual(
            month_buttons.button(QDialogButtonBox.StandardButton.Cancel).text(),
            "取消",
        )
        self.assertEqual(
            settings_buttons.button(QDialogButtonBox.StandardButton.Save).text(),
            "儲存設定",
        )
        self.assertEqual(
            settings_buttons.button(QDialogButtonBox.StandardButton.Cancel).text(),
            "取消",
        )
        self.assertEqual(
            month_buttons.layoutDirection(),
            Qt.LayoutDirection.LeftToRight,
        )
        self.assertEqual(
            settings_buttons.layoutDirection(),
            Qt.LayoutDirection.LeftToRight,
        )
        month_dialog.show()
        settings_dialog.show()
        QApplication.processEvents()
        for dialog, button_box, reject_button, accept_button in (
            (
                month_dialog,
                month_buttons,
                month_buttons.button(QDialogButtonBox.StandardButton.Cancel),
                month_buttons.button(QDialogButtonBox.StandardButton.Ok),
            ),
            (
                settings_dialog,
                settings_buttons,
                settings_buttons.button(QDialogButtonBox.StandardButton.Cancel),
                settings_buttons.button(QDialogButtonBox.StandardButton.Save),
            ),
        ):
            self.assertLess(reject_button.x(), accept_button.x())
            bottom_right = button_box.mapTo(
                dialog,
                button_box.rect().bottomRight(),
            )
            self.assertLessEqual(dialog.width() - bottom_right.x(), 16)
            self.assertLessEqual(dialog.height() - bottom_right.y(), 16)

    def test_month_dialog_uses_simple_year_and_month_fields(self) -> None:
        month_dialog = MonthDialog("建立月份", "選擇月份")
        self.addCleanup(month_dialog.close)

        expected = QDate.currentDate().addMonths(1)
        self.assertEqual(month_dialog.year_month, (expected.year(), expected.month()))

        month_dialog.year_edit.setValue(2028)
        month_dialog.month_edit.setCurrentIndex(10)

        self.assertEqual(month_dialog.year_month, (2028, 11))
        self.assertEqual(month_dialog.month_edit.maxVisibleItems(), 12)
        self.assertEqual(
            month_dialog.month_edit.view().verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        month_dialog.year_edit.lineEdit().selectAll()
        month_dialog.year_edit.stepBy(1)
        QApplication.processEvents()
        self.assertEqual(month_dialog.year_edit.lineEdit().selectedText(), "")

    def test_settings_dialog_loads_effective_config_and_switches_time_mode(
        self,
    ) -> None:
        dialog = self._settings_dialog()
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.input_file.text(), "排班輸入_2026-08.json")
        self.assertEqual(dialog.time_mode.currentData(), "比例")
        self.assertTrue(dialog.time_ratio.isEnabled())
        self.assertFalse(dialog.fixed_seconds.isEnabled())

        dialog.time_mode.setCurrentIndex(dialog.time_mode.findData("定值"))
        self.assertFalse(dialog.time_ratio.isEnabled())
        self.assertTrue(dialog.fixed_seconds.isEnabled())

    def test_main_window_settings_save_updates_root_config_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_bytes(
                (REPOSITORY_ROOT / "config.json").read_bytes()
            )
            input_directory = root / "input"
            input_directory.mkdir()
            window = MainWindow(
                input_directory=input_directory,
                config_path=config_path,
            )
            self.addCleanup(window.close)

            def edit_and_accept(dialog: SettingsDialog) -> int:
                dialog.input_file.setText("排班輸入_2026-09.json")
                dialog.progress_seconds.setValue(9.0)
                dialog.accept()
                return QDialog.DialogCode.Accepted

            with patch.object(
                SettingsDialog,
                "exec",
                new=edit_and_accept,
            ):
                window.open_settings()

            saved = ConfigApplication().open_document(config_path)

        self.assertEqual(saved.draft.input_file, "排班輸入_2026-09.json")
        self.assertEqual(saved.draft.progress_update_seconds, 9.0)

    def test_message_box_choices_are_always_chinese(self) -> None:
        message = build_message_box(
            None,
            QMessageBox.Icon.Warning,
            "尚未儲存",
            "要先儲存嗎？",
            buttons=(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            ),
        )
        self.addCleanup(message.close)

        self.assertEqual(
            message.button(QMessageBox.StandardButton.Save).text(),
            "儲存",
        )
        self.assertEqual(
            message.button(QMessageBox.StandardButton.Discard).text(),
            "不要儲存",
        )
        self.assertEqual(
            message.button(QMessageBox.StandardButton.Cancel).text(),
            "取消",
        )
        button_box = message.findChild(QDialogButtonBox)
        assert button_box is not None
        self.assertEqual(
            button_box.layoutDirection(),
            Qt.LayoutDirection.LeftToRight,
        )

    def test_date_picker_is_month_bounded_and_uses_bottom_right_actions(self) -> None:
        dialog = DatePickerDialog(
            "選擇日期",
            "請選擇日期",
            date(2026, 8, 1),
            date(2026, 8, 31),
        )
        self.addCleanup(dialog.close)

        calendar = dialog.findChild(QCalendarWidget)
        buttons = dialog.findChild(QDialogButtonBox)
        assert calendar is not None and buttons is not None
        self.assertEqual(calendar.minimumDate().toString("yyyy-MM-dd"), "2026-08-01")
        self.assertEqual(calendar.maximumDate().toString("yyyy-MM-dd"), "2026-08-31")
        self.assertFalse(calendar.isNavigationBarVisible())
        self.assertEqual(
            calendar.verticalHeaderFormat(),
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader,
        )
        self.assertEqual(dialog.date_picker.year_label.text(), "2026 年")
        self.assertEqual(dialog.date_picker.month_label.text(), "8 月")
        self.assertFalse(hasattr(dialog.date_picker, "previous_button"))
        self.assertFalse(hasattr(dialog.date_picker, "next_button"))
        self.assertEqual(calendar._fixed_year, 2026)
        self.assertEqual(calendar._fixed_month, 8)
        calendar.setSelectedDate(QDate(2026, 8, 15))
        self.assertEqual(dialog.selected_date, date(2026, 8, 15))
        self.assertEqual(dialog.selection_label.text(), "已選日期：2026 年 8 月 15 日")
        self.assertEqual(buttons.layoutDirection(), Qt.LayoutDirection.LeftToRight)
        self.assertTrue(
            dialog.layout().itemAt(dialog.layout().count() - 1).alignment()
            & Qt.AlignmentFlag.AlignRight
        )

    def test_stylesheet_substitutes_every_palette_token(self) -> None:
        stylesheet = load_application_stylesheet()
        self.assertNotIn("$BACKGROUND", stylesheet)
        self.assertNotIn("$PRIMARY", stylesheet)
        self.assertIn("Microsoft JhengHei UI", stylesheet)
        self.assertIn("QTabBar::tab:selected", stylesheet)
        self.assertIn("QTabWidget#settingsTabs::pane", stylesheet)
        self.assertIn("QScrollBar::handle:vertical", stylesheet)
        self.assertIn("QPushButton:focus", stylesheet)

    def test_gui_smoke_entry_exits_without_loading_a_document(self) -> None:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "src/run_gui.py", "--smoke-test"],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr + completed.stdout,
        )

    def test_gui_smoke_round_trips_formal_input(self) -> None:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        source = REPOSITORY_ROOT / "input/匿名範本/排班輸入_匿名_2026-08.json"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "round-trip.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "src/run_gui.py",
                    "--smoke-test",
                    f"--smoke-input={source}",
                    f"--smoke-output={output}",
                ],
                cwd=REPOSITORY_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            self.assertEqual(
                completed.returncode,
                0,
                completed.stderr + completed.stdout,
            )
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                json.loads(source.read_text(encoding="utf-8")),
            )

    @staticmethod
    def _settings_dialog() -> SettingsDialog:
        session = ConfigApplication().open_document(
            REPOSITORY_ROOT / "config.json"
        )
        return SettingsDialog(
            session.draft,
            config_path=session.path,
            input_directory=REPOSITORY_ROOT / "input",
            current_document_path=(
                REPOSITORY_ROOT / "input" / session.draft.input_file
            ),
        )


if __name__ == "__main__":
    unittest.main()
