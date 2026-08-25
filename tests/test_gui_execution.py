from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from clinic_shift_scheduler.gui.execution_controller import (
    ExecutionController,
    _is_ortools_dll_load_noise,
    _worker_stdout_decoder,
)
from clinic_shift_scheduler.execution_protocol import encode_execution_message
from clinic_shift_scheduler.gui.main import create_application
from clinic_shift_scheduler.gui.pages.execution_page import ExecutionPage
from clinic_shift_scheduler.events import ExecutionPhase, ProgressEventKind


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class GuiExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_application(["gui-execution-test"])

    def test_controller_launches_source_worker_and_receives_structured_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = ExecutionController(REPOSITORY_ROOT)
            self.addCleanup(controller.stop_for_shutdown)
            messages: list[dict[str, object]] = []
            controller.message_received.connect(messages.append)
            finished = QSignalSpy(controller.finished)

            controller.start(
                config_path=root / "missing-config.json",
                input_path=root / "input.json",
                output_directory=root / "output",
                intermediate_directory=root / "runtime" / "expanded-input",
            )

            self.assertTrue(finished.wait(10000))

        self.assertEqual(messages[0]["type"], "started")
        self.assertEqual(messages[-1]["type"], "failed")
        self.assertEqual(messages[-1]["kind"], "CONFIG_ERROR")

    def test_known_ortools_dll_loader_noise_is_filtered(self) -> None:
        self.assertTrue(
            _is_ortools_dll_load_noise(
                r"load D:\env\Lib\site-packages\ortools\.libs\ortools.dll..."
            )
        )
        self.assertFalse(_is_ortools_dll_load_noise("real solver error"))

    def test_worker_stdout_decoder_ignores_native_loader_chatter(self) -> None:
        decoder = _worker_stdout_decoder()
        loader_line = (
            "load D:\\env\\Lib\\site-packages\\ortools\\.libs\\"
            "ortools.dll...\n"
        ).encode("utf-8")

        messages = decoder.feed(
            loader_line
            + encode_execution_message("started", input_path="input.json")
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["type"], "started")

    def test_execution_page_shows_config_and_separates_candidate_stop(self) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        config_path = Path("D:/clinic/config.json")
        page.bind_document(
            month="2026-08",
            path=Path("D:/clinic/input/schedule.json"),
            config_path=config_path,
        )

        self.assertEqual(page.config_label.text(), str(config_path))
        self.assertEqual(page.cancel_button.text(), "終止排班")
        self.assertEqual(
            page.preserve_button.text(),
            "終止排班並保留當前最佳班表",
        )
        self.assertEqual(page.elapsed_label.text(), "0 秒")
        self.assertIs(page.status_group.parentWidget(), page.surface)
        self.assertIs(page.document_group.parentWidget(), page.scroll_content)
        self.assertIs(page.log_group.parentWidget(), page.scroll_content)
        self.assertIs(page.result_group.parentWidget(), page.scroll_content)
        self.assertIsNot(
            page.content_scroll.verticalScrollBar(),
            page.log.verticalScrollBar(),
        )
        self.assertFalse(page.result_group.isVisible())
        page.begin()
        self.assertTrue(page.cancel_button.isEnabled())
        self.assertFalse(page.preserve_button.isEnabled())
        self.assertFalse(page.stop_candidate_button.isEnabled())
        self.assertTrue(page.result_group.isHidden())

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.CANDIDATE_SEARCH.value,
                "kind": ProgressEventKind.STEP_STARTED.value,
                "message": "開始搜尋；按「終止候選處理」可終止（不影響先前已完成的排班輸出）",
            }
        )
        self.assertFalse(page.cancel_button.isEnabled())
        self.assertTrue(page.stop_candidate_button.isEnabled())
        page.request_candidate_stopping()
        self.assertFalse(page.stop_candidate_button.isEnabled())
        self.assertIn("正式班表不受影響", page.status_detail_label.text())
        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.CANDIDATE_SEARCH.value,
                "kind": ProgressEventKind.CANDIDATE_COUNT.value,
                "message": "已找到 1 份同品質候選班表",
            }
        )
        self.assertFalse(page.stop_candidate_button.isEnabled())
        page.process_finished()

    def test_execution_log_follows_tail_without_stealing_history_position(
        self,
    ) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        page.resize(780, 620)
        page.show()
        page.log.setPlainText(
            "\n".join(f"執行訊息 {index}" for index in range(120))
        )
        QApplication.processEvents()
        scroll_bar = page.log.verticalScrollBar()

        scroll_bar.setValue(scroll_bar.maximum())
        page.append_stderr("最新訊息")
        QApplication.processEvents()
        self.assertEqual(scroll_bar.value(), scroll_bar.maximum())

        history_position = max(1, scroll_bar.maximum() // 3)
        scroll_bar.setValue(history_position)
        page.append_stderr("另一則最新訊息")
        QApplication.processEvents()
        self.assertEqual(scroll_bar.value(), history_position)

    def test_execution_log_append_preserves_selection_and_page_position(
        self,
    ) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        page.resize(780, 520)
        page.document_group.setMinimumHeight(260)
        page.log_group.setMinimumHeight(520)
        page.show()
        page.log.setPlainText(
            "\n".join(f"執行訊息 {index}" for index in range(160))
        )
        QApplication.processEvents()

        log_cursor = page.log.textCursor()
        log_cursor.setPosition(10)
        log_cursor.setPosition(
            24,
            QTextCursor.MoveMode.KeepAnchor,
        )
        page.log.setTextCursor(log_cursor)
        log_scroll = page.log.verticalScrollBar()
        log_position = max(1, log_scroll.maximum() // 3)
        log_scroll.setValue(log_position)

        page_scroll = page.content_scroll.verticalScrollBar()
        self.assertGreater(page_scroll.maximum(), 0)
        page_position = max(1, page_scroll.maximum() // 2)
        page_scroll.setValue(page_position)

        for index in range(10):
            page.append_stderr(f"持續訊息 {index}")
            QApplication.processEvents()

        self.assertEqual(log_scroll.value(), log_position)
        self.assertEqual(page_scroll.value(), page_position)
        self.assertEqual(page.log.textCursor().selectionStart(), 10)
        self.assertEqual(page.log.textCursor().selectionEnd(), 24)

    def test_execution_page_scroll_position_survives_status_layout_changes(
        self,
    ) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        page.resize(780, 520)
        page.document_group.setMinimumHeight(260)
        page.log_group.setMinimumHeight(520)
        page.show()
        page.bind_document(
            month="2026-08",
            path=Path("D:/clinic/input/schedule.json"),
            config_path=Path("D:/clinic/config.json"),
        )
        page.begin()
        QApplication.processEvents()

        scroll_bar = page.content_scroll.verticalScrollBar()
        self.assertGreater(scroll_bar.maximum(), 0)
        position = max(1, scroll_bar.maximum() // 2)
        scroll_bar.setValue(position)

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OPTIMIZATION.value,
                "kind": ProgressEventKind.HEARTBEAT.value,
                "message": "正在最佳化",
                "details": {
                    "activity": "formal_stage",
                    "has_feasible_solution": True,
                    "can_preserve_output": True,
                    "user_step_index": 5,
                    "user_step_total": 10,
                    "user_step_title": "平衡正職個人的班型比例",
                    "formal_stage_index": 8,
                    "formal_stage_total": 16,
                    "formal_stages_completed": 7,
                    "incumbent": 20.0,
                    "best_bound": 18.0,
                    "relative_gap": 0.1,
                },
            }
        )
        QApplication.processEvents()

        self.assertEqual(
            scroll_bar.value(),
            min(position, scroll_bar.maximum()),
        )
        self.assertEqual(page.preserve_button.toolTip(), "")

        position = min(scroll_bar.maximum(), scroll_bar.value() + 20)
        scroll_bar.setValue(position)
        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.VALIDATION.value,
                "kind": ProgressEventKind.STEP_STARTED.value,
                "message": "執行獨立結果驗證",
            }
        )
        QApplication.processEvents()

        self.assertEqual(
            scroll_bar.value(),
            min(position, scroll_bar.maximum()),
        )

    def test_execution_log_extends_selection_while_scrolling_at_bottom_edge(
        self,
    ) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        page.resize(780, 620)
        page.show()
        page.log.setPlainText(
            "\n".join(f"執行訊息 {index}" for index in range(160))
        )
        QApplication.processEvents()
        scroll_bar = page.log.verticalScrollBar()
        scroll_bar.setValue(0)

        cursor = page.log.textCursor()
        cursor.setPosition(0)
        page.log.setTextCursor(cursor)
        page.log._selection_drag_active = True
        page.log._auto_scroll_direction = 1
        page.log._last_drag_position = QPoint(
            12,
            page.log.viewport().height() - 1,
        )

        page.log._scroll_selection_toward_edge()

        self.assertGreater(scroll_bar.value(), 0)
        self.assertTrue(page.log.textCursor().hasSelection())
        self.assertGreater(page.log.textCursor().selectionEnd(), 0)
        page.log._selection_drag_active = False
        page.log._stop_selection_auto_scroll()

    def test_execution_page_renders_structured_solver_progress(self) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        page.bind_document(
            month="2026-08",
            path=Path("D:/clinic/input/schedule.json"),
            config_path=Path("D:/clinic/config.json"),
        )
        page.begin()

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OPTIMIZATION.value,
                "kind": ProgressEventKind.HEARTBEAT.value,
                "message": "fallback",
                "details": {
                    "activity": "formal_stage",
                    "has_feasible_solution": True,
                    "can_preserve_output": True,
                    "user_step_index": 5,
                    "user_step_total": 10,
                    "user_step_title": "平衡正職個人的班型比例",
                    "formal_stage_index": 6,
                    "formal_stage_total": 16,
                    "formal_stage_name": "正職個人班型比例最大 gap",
                    "formal_stages_completed": 5,
                    "incumbent": 438.0,
                    "best_bound": 421.0,
                    "relative_gap": 17 / 438,
                    "stage_elapsed_seconds": 138.0,
                    "seconds_since_last_solution": 17.0,
                    "seconds_since_bound_update": 4.0,
                    "total_elapsed_seconds": 342.0,
                },
            }
        )

        self.assertEqual(page.status_label.text(), "已找到合法班表")
        self.assertEqual(page.status_detail_label.text(), "目前仍在最佳化品質")
        self.assertEqual(page.progress_count_label.text(), "最佳化進度 5 / 10")
        self.assertEqual(
            page.progress_title_label.text(),
            "平衡正職個人的班型比例",
        )
        self.assertIn("正式流程 6 / 16", page.progress_technical_label.text())
        self.assertIn("已完成 5 / 16", page.progress_technical_label.text())
        self.assertEqual(page.metric_values["incumbent"].text(), "438")
        self.assertEqual(page.metric_values["best_bound"].text(), "421")
        self.assertEqual(page.metric_values["relative_gap"].text(), "3.9%")
        self.assertEqual(
            page.metric_labels["incumbent"].text(),
            "目前找到的最佳值",
        )
        self.assertEqual(
            page.metric_labels["best_bound"].text(),
            "已證明的最佳值界限",
        )
        self.assertEqual(
            page.metric_labels["relative_gap"].text(),
            "與證明最佳的距離",
        )
        self.assertIn(
            "不能換算為剩餘時間",
            page.metric_labels["relative_gap"].toolTip(),
        )
        visible_status_text = "\n".join(
            (
                page.status_label.text(),
                page.status_detail_label.text(),
                page.progress_count_label.text(),
                page.progress_title_label.text(),
                page.progress_technical_label.text(),
            )
        )
        self.assertNotIn("總耗時", visible_status_text)
        self.assertNotIn("fallback", visible_status_text)
        self.assertFalse(page.progress_section.isHidden())
        self.assertFalse(page.metrics_section.isHidden())
        self.assertTrue(page.preserve_button.isEnabled())

    def test_execution_status_contracts_across_phases_without_empty_rows(
        self,
    ) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        page.bind_document(
            month="2026-08",
            path=Path("D:/clinic/input/schedule.json"),
            config_path=Path("D:/clinic/config.json"),
        )
        page.begin()

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.PRECHECK.value,
                "kind": ProgressEventKind.STEP_STARTED.value,
                "message": "執行前置可行性檢查",
            }
        )
        self.assertEqual(page.status_label.text(), "正在執行前置可行性檢查")
        self.assertTrue(page.progress_section.isHidden())
        self.assertTrue(page.metrics_section.isHidden())

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OPTIMIZATION.value,
                "kind": ProgressEventKind.HEARTBEAT.value,
                "message": "benchmark",
                "details": {
                    "activity": "preference_benchmark",
                    "has_feasible_solution": True,
                    "user_step_index": 3,
                    "user_step_total": 10,
                    "user_step_title": "共同保護主要偏好",
                    "rank": "first",
                    "full_time_class": "A",
                    "benchmark_index": 1,
                    "benchmark_total": 2,
                    "formal_stages_completed": 4,
                    "formal_stage_total": 16,
                },
            }
        )
        self.assertEqual(
            page.progress_subtask_label.text(),
            "A 類第一偏好基準 1 / 2",
        )
        self.assertFalse(page.progress_subtask_frame.isHidden())
        self.assertTrue(page.metrics_section.isHidden())

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.VALIDATION.value,
                "kind": ProgressEventKind.STEP_STARTED.value,
                "message": "執行獨立結果驗證",
            }
        )
        self.assertEqual(page.status_label.text(), "正在驗證排班結果")
        self.assertTrue(page.progress_section.isHidden())
        self.assertTrue(page.metrics_section.isHidden())

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OUTPUT.value,
                "kind": ProgressEventKind.STEP_STARTED.value,
                "message": "輸出正式檔案：JSON、Excel、PDF",
            }
        )
        self.assertEqual(page.status_label.text(), "正在產生輸出檔案")
        self.assertTrue(page.progress_section.isHidden())

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.CANDIDATE_SEARCH.value,
                "kind": ProgressEventKind.CANDIDATE_COUNT.value,
                "message": "已找到 7 份同品質候選班表",
                "current": 7,
                "total": 100,
            }
        )
        self.assertEqual(page.status_label.text(), "正式班表已完成")
        self.assertEqual(
            page.status_detail_label.text(),
            "正在搜尋同品質候選班表",
        )
        self.assertEqual(page.progress_count_label.text(), "候選搜尋 7 / 100")
        self.assertFalse(page.progress_section.isHidden())
        self.assertTrue(page.metrics_section.isHidden())

    def test_execution_status_completion_cancel_and_failure_are_compact(
        self,
    ) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        page.begin()
        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OPTIMIZATION.value,
                "kind": ProgressEventKind.HEARTBEAT.value,
                "message": "正在最佳化",
                "details": {
                    "activity": "formal_stage",
                    "has_feasible_solution": True,
                    "user_step_index": 4,
                    "user_step_total": 10,
                    "user_step_title": "共同保護第二偏好",
                    "formal_stage_index": 7,
                    "formal_stage_total": 16,
                    "formal_stages_completed": 6,
                    "incumbent": 12.0,
                    "best_bound": 10.0,
                    "relative_gap": 1 / 6,
                },
            }
        )
        page.request_cancelling()
        self.assertEqual(page.status_label.text(), "正在終止排班")
        self.assertFalse(page.progress_section.isHidden())
        self.assertFalse(page.metrics_section.isHidden())

        page.show_message(
            {
                "type": "failed",
                "kind": "CANCELLED",
                "message": "排班已取消。",
                "issues": [],
            }
        )
        self.assertEqual(page.status_label.text(), "排班已終止")
        self.assertIn("終止當下", page.status_detail_label.text())
        self.assertEqual(page.metric_values["incumbent"].text(), "12")
        self.assertFalse(page.metrics_section.isHidden())

        page.begin()
        page.show_message(
            {
                "type": "failed",
                "kind": "UNEXPECTED_ERROR",
                "message": "測試錯誤",
                "issues": [],
            }
        )
        self.assertEqual(page.status_label.text(), "排班未完成")
        self.assertEqual(page.status_detail_label.text(), "測試錯誤")
        self.assertEqual(page.status_indicator.property("state"), "error")

    def test_preserved_result_is_labeled_feasible_and_not_formal(self) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        page.bind_document(
            month="2026-08",
            path=Path("D:/clinic/input/schedule.json"),
            config_path=Path("D:/clinic/config.json"),
        )
        page.begin()

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OPTIMIZATION.value,
                "kind": ProgressEventKind.HEARTBEAT.value,
                "message": "正在最佳化",
                "details": {
                    "activity": "formal_stage",
                    "has_feasible_solution": True,
                    "user_step_index": 5,
                    "user_step_total": 10,
                    "user_step_title": "平衡正職個人的班型比例",
                    "formal_stage_index": 8,
                    "formal_stage_total": 16,
                    "formal_stages_completed": 7,
                    "incumbent": 20.0,
                    "best_bound": 18.0,
                    "relative_gap": 0.1,
                },
            }
        )
        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OPTIMIZATION.value,
                "kind": ProgressEventKind.STEP_COMPLETED.value,
                "message": "正式流程已完成 8/16",
                "details": {
                    "activity": "formal_stage",
                    "has_feasible_solution": True,
                    "user_step_index": 5,
                    "user_step_total": 10,
                    "user_step_title": "平衡正職個人的班型比例",
                    "formal_stage_index": 8,
                    "formal_stage_total": 16,
                    "formal_stage_name": "正職個人班型比例公平",
                    "formal_stages_completed": 8,
                    "stage_status": "FEASIBLE",
                    "objective_value": 19,
                    "best_objective_bound": 18,
                    "stage_elapsed_seconds": 25.0,
                },
            }
        )
        page.request_preserving()
        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OPTIMIZATION.value,
                "kind": ProgressEventKind.STEP_COMPLETED.value,
                "message": "嚴格分階段最佳化完成：共耗時 30 秒",
                "details": {},
            }
        )
        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.VALIDATION.value,
                "kind": ProgressEventKind.STEP_STARTED.value,
                "message": "驗證目前班表",
            }
        )
        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OUTPUT.value,
                "kind": ProgressEventKind.STEP_STARTED.value,
                "message": "輸出暫存結果",
            }
        )

        page.show_message(
            {
                "type": "preserved",
                "status": "FEASIBLE",
                "validation": "PASS",
                "selected_formats": ["json", "pdf"],
                "paths": {
                    "json": "output/partial.json",
                    "pdf": "output/partial.pdf",
                },
                "timings": {"total_execution_seconds": 30.0},
            }
        )

        self.assertEqual(page.result_group.title(), "目前最佳合法班表")
        self.assertIn("未證明最佳", page.result_status_label.text())
        self.assertEqual(page.validation_label.text(), "通過（PASS）")
        self.assertIn("Excel：未選擇", page.output_label.text())
        self.assertIn("尚未完成", page.status_detail_label.text())
        self.assertEqual(page.progress_count_label.text(), "最佳化進度 5 / 10")
        self.assertIn("正式流程 8 / 16", page.progress_technical_label.text())
        self.assertEqual(page.metric_values["incumbent"].text(), "19")
        self.assertEqual(page.metric_values["best_bound"].text(), "18")
        self.assertEqual(page.metric_values["relative_gap"].text(), "5.3%")
        self.assertFalse(page.progress_section.isHidden())
        self.assertFalse(page.metrics_section.isHidden())
        self.assertFalse(page.result_group.isHidden())
        QApplication.processEvents()
        result_scroll = page.content_scroll.verticalScrollBar()
        self.assertEqual(result_scroll.value(), result_scroll.maximum())

    def test_completed_page_reveals_all_outputs_and_scrolls_to_result(self) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)
        page.resize(780, 620)
        page.show()
        page.bind_document(
            month="2026-08",
            path=Path("D:/clinic/input/schedule.json"),
            config_path=Path("D:/clinic/config.json"),
        )
        page.begin()
        page.log.setPlainText("\n".join(f"執行訊息 {index}" for index in range(40)))

        page.show_message(
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
        QApplication.processEvents()

        self.assertTrue(page.result_group.isVisible())
        self.assertIn("JSON：output/result.json", page.output_label.text())
        self.assertIn("Excel：output/result.xlsx", page.output_label.text())
        self.assertIn("PDF：output/result.pdf", page.output_label.text())
        result_scroll = page.content_scroll.verticalScrollBar()
        self.assertGreater(result_scroll.maximum(), 0)
        self.assertEqual(result_scroll.value(), result_scroll.maximum())
        self.assertTrue(page.status_group.isVisible())
        page.process_finished()


if __name__ == "__main__":
    unittest.main()
