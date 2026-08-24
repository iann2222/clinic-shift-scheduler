from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
        self.assertEqual(page.elapsed_label.text(), "總耗時：0 秒")
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
        self.assertIn("正式班表不受影響", page.status_label.text())
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

    def test_execution_page_renders_structured_solver_progress(self) -> None:
        page = ExecutionPage()
        self.addCleanup(page.close)

        page.show_message(
            {
                "type": "progress",
                "phase": ExecutionPhase.OPTIMIZATION.value,
                "kind": ProgressEventKind.HEARTBEAT.value,
                "message": "fallback",
                "details": {
                    "activity": "formal_stage",
                    "has_feasible_solution": True,
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

        rendered = page.status_label.text()
        self.assertIn("已找到合法班表 ✓", rendered)
        self.assertIn("第 5/10 步", rendered)
        self.assertIn("正式流程已完成 5/16", rendered)
        self.assertIn("目前 6/16", rendered)
        self.assertIn("目前目標 438", rendered)
        self.assertIn("最佳界 421", rendered)
        self.assertIn("gap 3.9%", rendered)
        self.assertNotIn("fallback", rendered)

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
        self.assertGreater(
            page.content_scroll.verticalScrollBar().value(),
            0,
        )
        self.assertTrue(page.status_group.isVisible())
        page.process_finished()


if __name__ == "__main__":
    unittest.main()
