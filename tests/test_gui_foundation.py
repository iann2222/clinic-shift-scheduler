from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialogButtonBox, QMessageBox, QTableWidget

from clinic_shift_scheduler.gui.dialogs import (
    MonthDialog,
    SettingsDialog,
    build_message_box,
)
from clinic_shift_scheduler.gui.main import create_application
from clinic_shift_scheduler.gui.main_window import MainWindow
from clinic_shift_scheduler.gui.navigation import NAVIGATION_ITEMS, PageId
from clinic_shift_scheduler.gui.styles.loader import load_application_stylesheet
from clinic_shift_scheduler.gui.widgets.document_header import DocumentState


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GuiFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_application(["gui-foundation-test"])

    def test_navigation_contract_has_the_six_input_pages_in_order(self) -> None:
        self.assertEqual(
            tuple(item.page_id for item in NAVIGATION_ITEMS),
            (
                PageId.MONTH_CLINIC,
                PageId.WEEKLY_DEMAND,
                PageId.DATE_OVERRIDE,
                PageId.EMPLOYEE,
                PageId.AVAILABILITY,
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
        self.assertEqual(window.page_stack.count(), 6)
        self.assertEqual(
            window.page_stack.currentWidget().page_id,
            PageId.MONTH_CLINIC,
        )
        self.assertEqual(window.findChildren(QTableWidget), [])

        window.navigation.select_page(PageId.EMPLOYEE)
        self.assertEqual(
            window.page_stack.currentWidget().page_id,
            PageId.EMPLOYEE,
        )

    def test_document_header_exposes_clear_clean_and_dirty_states(self) -> None:
        window = MainWindow()
        self.addCleanup(window.close)

        window.document_header.set_document(
            month="2026-08",
            path=Path("input/排班輸入_2026-08.json"),
            state=DocumentState.CLEAN,
        )
        self.assertEqual(window.document_header.month_label.text(), "2026-08")
        self.assertEqual(window.document_header.status_label.text(), "已儲存")

        window.document_header.set_document(
            month="2026-08",
            path=Path("input/排班輸入_2026-08.json"),
            state=DocumentState.DIRTY,
        )
        self.assertEqual(window.document_header.status_label.text(), "尚未儲存")

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
        dialog = SettingsDialog()
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.tabs.count(), 2)
        self.assertEqual(dialog.tabs.tabText(0), "一般設定")
        self.assertEqual(dialog.tabs.tabText(1), "進階設定")
        self.assertNotIn("設定", {item.title for item in NAVIGATION_ITEMS})

    def test_standard_dialog_buttons_are_always_chinese(self) -> None:
        month_dialog = MonthDialog("建立月份", "選擇月份")
        settings_dialog = SettingsDialog()
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
            settings_buttons.button(QDialogButtonBox.StandardButton.Close).text(),
            "關閉",
        )

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

    def test_stylesheet_substitutes_every_palette_token(self) -> None:
        stylesheet = load_application_stylesheet()
        self.assertNotIn("$BACKGROUND", stylesheet)
        self.assertNotIn("$PRIMARY", stylesheet)
        self.assertIn("Microsoft JhengHei UI", stylesheet)

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


if __name__ == "__main__":
    unittest.main()
