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

from PySide6.QtCore import QDate, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor, QImage, QPainter, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
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
from clinic_shift_scheduler.gui.pages import DateOverridePage, WeeklyDemandPage
from clinic_shift_scheduler.gui.styles.loader import load_application_stylesheet
from clinic_shift_scheduler.gui.widgets.document_header import DocumentState
from clinic_shift_scheduler.gui.widgets import (
    LockedStaffingCellDelegate,
    PeriodToggleDelegate,
)
from clinic_shift_scheduler.config_application import ConfigApplication
from clinic_shift_scheduler.authoring_application import AuthoringApplication


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GuiFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_application(["gui-foundation-test"])

    def test_navigation_contract_has_input_pages_then_execution_in_order(self) -> None:
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
                PageId.EXECUTION,
            ),
        )

    def test_staffing_tables_use_the_same_non_alternating_row_background(self) -> None:
        weekly_page = WeeklyDemandPage()
        date_override_page = DateOverridePage()
        self.addCleanup(weekly_page.close)
        self.addCleanup(date_override_page.close)

        self.assertFalse(weekly_page.table.alternatingRowColors())
        self.assertFalse(date_override_page.table.alternatingRowColors())
        self.assertIsInstance(
            weekly_page.table.itemDelegate(), LockedStaffingCellDelegate
        )
        self.assertIsInstance(
            date_override_page.table.itemDelegate(), LockedStaffingCellDelegate
        )
        self.assertIsInstance(
            weekly_page.table.itemDelegateForColumn(0), PeriodToggleDelegate
        )
        self.assertIsInstance(
            date_override_page.table.itemDelegateForColumn(0), PeriodToggleDelegate
        )

    def test_staffing_period_switches_toggle_from_any_column_zero_click(self) -> None:
        draft = AuthoringApplication().open_document(
            REPOSITORY_ROOT / "input/匿名範本/排班輸入_匿名_2026-08.json"
        ).draft
        weekly_page = WeeklyDemandPage()
        date_override_page = DateOverridePage()
        self.addCleanup(weekly_page.close)
        self.addCleanup(date_override_page.close)
        weekly_page.bind_draft(draft)
        date_override_page.bind_draft(draft)

        weekly_index = weekly_page.model.index(0, 0)
        weekly_page._handle_table_click(weekly_index)
        self.assertEqual(
            weekly_page.model.data(weekly_index, Qt.ItemDataRole.CheckStateRole),
            Qt.CheckState.Unchecked,
        )

        date_override_page.model.add_override(date(2026, 8, 15), is_open=False)
        override_index = date_override_page.model.index(0, 0)
        date_override_page._handle_table_click(override_index)
        self.assertEqual(
            date_override_page.model.data(
                override_index, Qt.ItemDataRole.CheckStateRole
            ),
            Qt.CheckState.Checked,
        )

    def test_period_toggle_delegate_draws_a_white_check_mark(self) -> None:
        model = QStandardItemModel(1, 1)
        index = model.index(0, 0)
        model.setData(index, "開啟", Qt.ItemDataRole.DisplayRole)
        model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        image = QImage(80, 32, QImage.Format.Format_ARGB32)
        image.fill(QColor("#000000"))
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, image.width(), image.height())
        option.state = QStyle.StateFlag.State_Enabled
        option.palette = QApplication.palette()
        painter = QPainter(image)
        try:
            PeriodToggleDelegate().paint(painter, option, index)
        finally:
            painter.end()

        # The indicator fills its own rectangle with the primary color, so a
        # white pixel in this area can only be the explicitly drawn check mark.
        check_area = (
            image.pixelColor(x, y)
            for x in range(11, 23)
            for y in range(11, 22)
        )
        self.assertTrue(
            any(color.red() > 220 and color.green() > 220 and color.blue() > 220
                for color in check_area)
        )

    def test_main_window_builds_navigation_header_and_page_stack(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        QApplication.processEvents()

        self.assertEqual(
            window.page_ids,
            tuple(item.page_id for item in NAVIGATION_ITEMS),
        )
        self.assertEqual(window.page_stack.count(), 8)
        self.assertEqual(
            window.page_stack.currentWidget().page_id,
            PageId.MONTH_CLINIC,
        )
        self.assertEqual(window.findChildren(QTableWidget), [])
        self.assertFalse(window.navigation.list_widget.isEnabled())
        self.assertEqual(window.navigation.list_widget.currentRow(), -1)
        self.assertFalse(window.document_header.settings_button.hasFocus())

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

    def test_document_header_keeps_file_actions_beside_identity(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        QApplication.processEvents()

        save_button, save_as_button = (
            window.document_header.document_action_buttons
        )
        self.assertLess(window.document_header.path_label.x(), save_button.x())
        self.assertLess(save_button.x(), save_as_button.x())
        self.assertLess(save_as_button.x(), window.document_header.status_label.x())
        self.assertLess(
            window.document_header.status_label.x(),
            window.document_header.settings_button.x(),
        )

    def test_clicking_background_clears_stale_button_focus(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)
        window.show()
        QApplication.processEvents()
        button = next(
            item
            for item in window.month_clinic_page.findChildren(QPushButton)
            if item.text() == "建立新月份"
        )
        button.setFocus()
        self.assertTrue(button.hasFocus())

        QTest.mouseClick(
            window.month_clinic_page.period_label,
            Qt.MouseButton.LeftButton,
        )
        QApplication.processEvents()

        self.assertFalse(button.hasFocus())

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

        self.assertEqual(dialog.tabs.count(), 3)
        self.assertEqual(dialog.tabs.tabText(0), "一般設定")
        self.assertEqual(dialog.tabs.tabText(1), "候選班表設定")
        self.assertEqual(dialog.tabs.tabText(2), "詳情")
        self.assertNotIn("設定", {item.title for item in NAVIGATION_ITEMS})

        dialog.tabs.setCurrentIndex(2)
        visible_text = "\n".join(
            label.text() for label in dialog.tabs.currentWidget().findChildren(QLabel)
        )
        self.assertIn("A 類正職", visible_text)
        self.assertIn("B 類正職", visible_text)
        self.assertIn("先確認班表合法且能完整補足需求", visible_text)
        self.assertIn("最後改善全體正職週日公平", visible_text)

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
        self.assertEqual(month_dialog.year_edit.suffix(), "")
        self.assertEqual(month_dialog.year_field.unit_label.text(), "年")
        self.assertEqual(month_dialog.month_edit.currentText(), "11")
        self.assertEqual(month_dialog.month_field.unit_label.text(), "月")
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

        self.assertTrue(dialog.input_file.text().endswith(".json"))
        self.assertEqual(dialog.time_mode.currentData(), "比例")
        self.assertTrue(dialog.time_ratio.isEnabled())
        self.assertTrue(dialog.candidate_form.isRowVisible(dialog.time_ratio))
        self.assertFalse(
            dialog.candidate_form.isRowVisible(dialog.fixed_seconds_field)
        )

        dialog.time_mode.setCurrentIndex(dialog.time_mode.findData("定值"))
        self.assertTrue(dialog.fixed_seconds.isEnabled())
        self.assertFalse(dialog.candidate_form.isRowVisible(dialog.time_ratio))
        self.assertTrue(
            dialog.candidate_form.isRowVisible(dialog.fixed_seconds_field)
        )

    def test_numeric_units_are_outside_settings_inputs_and_decimals_are_trimmed(
        self,
    ) -> None:
        dialog = self._settings_dialog()
        self.addCleanup(dialog.close)

        for control, field, unit in (
            (dialog.progress_seconds, dialog.progress_seconds_field, "秒"),
            (dialog.search_limit, dialog.search_limit_field, "份"),
            (dialog.fixed_seconds, dialog.fixed_seconds_field, "秒"),
            (dialog.export_count, dialog.export_count_field, "份"),
        ):
            self.assertEqual(control.suffix(), "")
            self.assertEqual(field.unit_label.text(), unit)

        dialog.progress_seconds.setValue(100.0)
        self.assertEqual(dialog.progress_seconds.text(), "100")
        dialog.time_ratio.setValue(0.20)
        self.assertEqual(dialog.time_ratio.text(), "0.2")

    def test_disabling_candidate_processing_keeps_configured_values(self) -> None:
        dialog = self._settings_dialog()
        self.addCleanup(dialog.close)
        dialog.candidate_enabled.setChecked(True)
        dialog.search_limit.setValue(321)
        dialog.export_count.setValue(12)
        dialog.time_ratio.setValue(0.35)

        dialog.candidate_enabled.setChecked(False)

        self.assertFalse(dialog.candidate_options.isEnabled())
        self.assertEqual(dialog.search_limit.value(), 321)
        self.assertEqual(dialog.export_count.value(), 12)
        self.assertEqual(dialog.time_ratio.value(), 0.35)

    def test_settings_use_stable_checkboxes(self) -> None:
        from clinic_shift_scheduler.gui.widgets import VisibleCheckBox

        dialog = self._settings_dialog()
        self.addCleanup(dialog.close)

        for checkbox in (
            dialog.overwrite,
            dialog.candidate_enabled,
            dialog.format_json,
            dialog.format_excel,
            dialog.format_pdf,
        ):
            self.assertIsInstance(checkbox, VisibleCheckBox)

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
        self.assertIn("QTableView::item:selected", stylesheet)
        self.assertIn("selection-background-color: transparent", stylesheet)
        self.assertNotIn("QTableView::indicator", stylesheet)
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
