"""Run-page presentation for the independent scheduling worker."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...events import ExecutionPhase, ProgressEventKind
from ...time_formatting import format_duration
from ..navigation import NAVIGATION_ITEMS, PageId
from .base import InputPage


_PHASE_LABELS = {
    ExecutionPhase.INPUT.value: "輸入",
    ExecutionPhase.CONFIG.value: "設定",
    ExecutionPhase.NORMALIZATION.value: "正規化",
    ExecutionPhase.PRECHECK.value: "前置檢查",
    ExecutionPhase.OPTIMIZATION.value: "排班",
    ExecutionPhase.VALIDATION.value: "驗證",
    ExecutionPhase.OUTPUT.value: "輸出",
    ExecutionPhase.CANDIDATE_SEARCH.value: "候選處理",
    ExecutionPhase.APPLICATION.value: "執行",
}

_OUTPUT_PATH_LABELS = (
    ("json", "JSON"),
    ("excel", "Excel"),
    ("pdf", "PDF"),
)


class _ExecutionContentScrollArea(QScrollArea):
    """Page-level scrolling independent from the execution log viewport."""

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._content = content
        self.setObjectName("executionContentScrollArea")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidget(content)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._content.setMinimumHeight(self.viewport().height())


class ExecutionPage(InputPage):
    run_requested = Signal()
    cancel_requested = Signal()
    stop_candidate_requested = Signal()
    open_output_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        item = next(
            item for item in NAVIGATION_ITEMS if item.page_id is PageId.EXECUTION
        )
        super().__init__(
            item.page_id,
            item.title,
            item.description,
            show_empty_state=False,
            parent=parent,
        )
        self._running = False
        self._terminal_received = False
        self._candidate_processing = False
        self._candidate_stop_requested = False
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh_elapsed)

        self.status_group = QGroupBox("執行狀態")
        self.status_group.setObjectName("executionStickyStatus")
        status_layout = QVBoxLayout(self.status_group)
        self.status_label = QLabel("資料準備完成後即可執行排班。")
        self.status_label.setObjectName("mutedText")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        self.elapsed_label = QLabel("總耗時：0 秒")
        self.elapsed_label.setObjectName("mutedText")
        status_layout.addWidget(self.elapsed_label)
        actions = QHBoxLayout()
        self.run_button = QPushButton("檢查、儲存並執行")
        self.run_button.setObjectName("primaryActionButton")
        self.cancel_button = QPushButton("終止排班")
        self.cancel_button.setEnabled(False)
        self.stop_candidate_button = QPushButton("終止候選處理")
        self.stop_candidate_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.stop_candidate_button.clicked.connect(
            self.stop_candidate_requested.emit
        )
        actions.addWidget(self.run_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.stop_candidate_button)
        actions.addStretch(1)
        status_layout.addLayout(actions)
        # This group deliberately stays outside the page scroll area.
        self.surface_layout.addWidget(self.status_group)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("executionScrollContent")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 4, 0)
        self.scroll_layout.setSpacing(12)

        self.document_group = QGroupBox("本次排班")
        document_form = QFormLayout(self.document_group)
        self.month_label = QLabel("尚未開啟月份")
        self.config_label = QLabel("—")
        self.config_label.setWordWrap(True)
        self.path_label = QLabel("尚未儲存檔案")
        self.path_label.setWordWrap(True)
        document_form.addRow("月份：", self.month_label)
        document_form.addRow("載入設定檔：", self.config_label)
        document_form.addRow("載入輸入檔：", self.path_label)
        self.scroll_layout.addWidget(self.document_group)

        self.log_group = QGroupBox("執行訊息")
        self.log_group.setMinimumHeight(240)
        self.log_group.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        log_layout = QVBoxLayout(self.log_group)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("排班開始後會在這裡顯示處理進度。")
        self.log.setAccessibleName("排班執行訊息")
        log_layout.addWidget(self.log)
        self.scroll_layout.addWidget(self.log_group, 1)

        self.result_group = QGroupBox("正式結果")
        result_form = QFormLayout(self.result_group)
        self.result_status_label = QLabel("尚未產生")
        self.validation_label = QLabel("尚未執行")
        self.output_label = QLabel("—")
        self.output_label.setWordWrap(True)
        self.candidate_label = QLabel("尚未執行")
        result_form.addRow("正式狀態：", self.result_status_label)
        result_form.addRow("獨立驗證：", self.validation_label)
        result_form.addRow("候選處理：", self.candidate_label)
        result_form.addRow("輸出檔案：", self.output_label)
        self.open_output_button = QPushButton("開啟輸出資料夾")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self._request_open_output)
        result_form.addRow("", self.open_output_button)
        self.scroll_layout.addWidget(self.result_group)
        self.result_group.hide()

        self.content_scroll = _ExecutionContentScrollArea(
            self.scroll_content,
            self,
        )
        self.surface_layout.addWidget(self.content_scroll, 1)

    @property
    def terminal_received(self) -> bool:
        return self._terminal_received

    def bind_document(
        self,
        *,
        month: str | None,
        path: Path | None,
        config_path: Path,
    ) -> None:
        self.month_label.setText(month or "尚未開啟月份")
        self.config_label.setText(str(config_path))
        self.path_label.setText(str(path) if path is not None else "尚未儲存檔案")
        if not self._running:
            self.run_button.setEnabled(month is not None)

    def reset_for_document(self) -> None:
        if self._running:
            return
        self._terminal_received = False
        self._candidate_processing = False
        self._candidate_stop_requested = False
        self.status_label.setText("資料準備完成後即可執行排班。")
        self.status_label.setObjectName("mutedText")
        self._repolish_status()
        self.elapsed_label.setText("總耗時：0 秒")
        self.result_status_label.setText("尚未產生")
        self.validation_label.setText("尚未執行")
        self.candidate_label.setText("尚未執行")
        self.output_label.setText("—")
        self.open_output_button.setEnabled(False)
        self.open_output_button.setProperty("output_directory", None)
        self.log.clear()
        self.result_group.hide()
        self.content_scroll.verticalScrollBar().setValue(0)
        self.cancel_button.setEnabled(False)
        self.stop_candidate_button.setEnabled(False)

    def mark_input_changed(self) -> None:
        if self._running or not self._terminal_received:
            return
        self.status_label.setText("輸入資料已修改；再次執行前會先儲存最新內容。")
        self.status_label.setObjectName("documentStatusDirty")
        self._repolish_status()
        self.result_status_label.setText("先前結果（不含目前修改）")

    def begin(self) -> None:
        self._running = True
        self._terminal_received = False
        self._candidate_processing = False
        self._candidate_stop_requested = False
        self.log.clear()
        self.result_group.hide()
        self.content_scroll.verticalScrollBar().setValue(0)
        self.result_status_label.setText("執行中")
        self.validation_label.setText("等待驗證")
        self.output_label.setText("—")
        self.candidate_label.setText("等待執行")
        self.open_output_button.setEnabled(False)
        self.open_output_button.setProperty("output_directory", None)
        self.status_label.setText("正在啟動獨立排班程序……")
        self.status_label.setObjectName("documentStatusDirty")
        self._repolish_status()
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.stop_candidate_button.setEnabled(False)
        self._elapsed.start()
        self._timer.start()
        self._refresh_elapsed()

    def show_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "started":
            self.status_label.setText("排班程序已啟動，正在讀取資料。")
            self.log.appendPlainText("[執行] 已啟動獨立排班程序。")
        elif message_type == "progress":
            self._show_progress(message)
        elif message_type == "completed":
            self._show_completed(message)
        elif message_type == "failed":
            self._show_failed(message)

    def append_stderr(self, text: str) -> None:
        if text:
            self.log.appendPlainText(f"[程序訊息] {text}")

    def request_cancelling(self) -> None:
        self.cancel_button.setEnabled(False)
        self.stop_candidate_button.setEnabled(False)
        self.status_label.setText("正在取消排班，請稍候……")
        self.log.appendPlainText("[執行] 已提出取消要求。")

    def request_candidate_stopping(self) -> None:
        if not self._candidate_processing or self._candidate_stop_requested:
            return
        self._candidate_stop_requested = True
        self.stop_candidate_button.setEnabled(False)
        self.status_label.setText(
            "正在終止候選處理；已完成的正式班表不受影響。"
        )
        self.log.appendPlainText("[候選處理] 已提出終止要求。")

    def process_finished(self) -> None:
        self._running = False
        self._timer.stop()
        self.run_button.setEnabled(self.month_label.text() != "尚未開啟月份")
        self.cancel_button.setEnabled(False)
        self.stop_candidate_button.setEnabled(False)
        self._candidate_processing = False
        self._refresh_elapsed()

    def _show_progress(self, message: dict[str, Any]) -> None:
        phase = str(message.get("phase", "APPLICATION"))
        label = _PHASE_LABELS.get(phase, phase)
        rendered = str(message.get("message", ""))
        self.status_label.setText(rendered)
        kind = message.get("kind")
        if phase == ExecutionPhase.CANDIDATE_SEARCH.value:
            self._candidate_processing = True
            self.cancel_button.setEnabled(False)
            self.stop_candidate_button.setEnabled(
                not self._candidate_stop_requested
            )
        elif self._candidate_processing:
            self._candidate_processing = False
            self.cancel_button.setEnabled(False)
            self.stop_candidate_button.setEnabled(False)
        elif phase in {
            ExecutionPhase.VALIDATION.value,
            ExecutionPhase.OUTPUT.value,
        }:
            # Independent validation and formal file commit are deliberately
            # non-interruptible; the dedicated candidate control becomes
            # available if the optional search starts afterwards.
            self.cancel_button.setEnabled(False)
        if kind not in {
            ProgressEventKind.HEARTBEAT.value,
            ProgressEventKind.CANDIDATE_COUNT.value,
        }:
            self.log.appendPlainText(f"[{label}] {rendered}")

    def _show_completed(self, message: dict[str, Any]) -> None:
        self._terminal_received = True
        self._candidate_processing = False
        self.stop_candidate_button.setEnabled(False)
        self.status_label.setText("排班完成，正式結果已輸出。")
        self.status_label.setObjectName("documentStatusClean")
        self._repolish_status()
        status = str(message.get("status", "—"))
        validation = str(message.get("validation", "—"))
        self.result_status_label.setText(
            "最佳排班完成（OPTIMAL）" if status == "OPTIMAL" else status
        )
        self.validation_label.setText(
            "通過（PASS）" if validation == "PASS" else validation
        )
        paths = message.get("paths", {})
        if not isinstance(paths, dict):
            paths = {}
        self.output_label.setText(_render_output_paths(paths))
        candidate = message.get("candidate_diagnostic")
        if isinstance(candidate, dict):
            count = int(candidate.get("alternative_count", 0))
            diagnostic_status = str(candidate.get("status", "UNKNOWN"))
            self.candidate_label.setText(
                f"找到 {count} 份同品質候選（{diagnostic_status}）"
            )
        else:
            self.candidate_label.setText("未啟用")
        json_path = paths.get("json") if isinstance(paths, dict) else None
        if json_path:
            output_directory = str(Path(str(json_path)).parent)
            self.open_output_button.setProperty(
                "output_directory", output_directory
            )
            self.open_output_button.setEnabled(True)
        total = message.get("timings", {}).get("total_execution_seconds")
        suffix = (
            ""
            if total is None
            else f"，總耗時 {format_duration(float(total))}"
        )
        self.log.appendPlainText(f"[執行] 正式結果完成{suffix}。")
        self.result_group.show()
        self.scroll_content.updateGeometry()
        QTimer.singleShot(0, self._scroll_to_completed_result)

    def _show_failed(self, message: dict[str, Any]) -> None:
        self._terminal_received = True
        self._candidate_processing = False
        self.stop_candidate_button.setEnabled(False)
        kind = str(message.get("kind", "UNKNOWN"))
        cancelled = kind == "CANCELLED"
        rendered = str(message.get("message", "排班失敗。"))
        self.status_label.setText("排班已取消。" if cancelled else "排班未完成。")
        self.status_label.setObjectName(
            "mutedText" if cancelled else "documentStatusDirty"
        )
        self._repolish_status()
        self.result_status_label.setText("CANCELLED" if cancelled else kind)
        self.validation_label.setText("未完成")
        self.candidate_label.setText("未完成")
        self.result_group.hide()
        self.log.appendPlainText(f"[執行] {rendered}")
        for issue in message.get("issues", []):
            self.log.appendPlainText(
                f"[{issue.get('phase', '執行')}] {issue.get('message', '')}"
            )

    def _refresh_elapsed(self) -> None:
        elapsed_seconds = (
            0
            if not self._elapsed.isValid()
            else self._elapsed.elapsed() // 1000
        )
        self.elapsed_label.setText(f"總耗時：{format_duration(elapsed_seconds)}")

    def _repolish_status(self) -> None:
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _request_open_output(self) -> None:
        directory = self.open_output_button.property("output_directory")
        if isinstance(directory, str) and directory:
            self.open_output_requested.emit(directory)

    def _scroll_to_completed_result(self) -> None:
        """Move document metadata out while keeping log context above results."""

        layout = self.scroll_content.layout()
        if layout is not None:
            layout.activate()
        bar = self.content_scroll.verticalScrollBar()
        result_top = self.result_group.y()
        context_height = max(96, self.content_scroll.viewport().height() // 3)
        bar.setValue(min(max(result_top - context_height, 0), bar.maximum()))


def _render_output_paths(paths: dict[str, Any]) -> str:
    """Make every required formal medium visible, including missing ones."""

    return "\n".join(
        f"{label}：{paths.get(key) or '未產生'}"
        for key, label in _OUTPUT_PATH_LABELS
    )
