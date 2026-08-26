"""Run-page presentation for the independent scheduling worker."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QElapsedTimer, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFocusEvent, QMouseEvent, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...events import ExecutionPhase, ProgressEventKind
from ...time_formatting import format_duration
from ..navigation import NAVIGATION_ITEMS, PageId
from ..styles.icons import themed_information_icon
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


def _compact_number(value: object) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _formatted_duration_or_none(
    value: object,
    *,
    suffix: str = "",
) -> str | None:
    if value is None:
        return None
    return f"{format_duration(float(value))}{suffix}"


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
        scroll_bar = self.verticalScrollBar()
        previous_maximum = scroll_bar.maximum()
        previous_value = scroll_bar.value()
        was_at_bottom = (
            previous_maximum > 0
            and previous_value >= previous_maximum - 2
        )
        super().resizeEvent(event)
        self._content.setMinimumHeight(self.viewport().height())
        target = (
            scroll_bar.maximum()
            if was_at_bottom
            else min(previous_value, scroll_bar.maximum())
        )
        scroll_bar.setValue(target)


class _ExecutionLog(QPlainTextEdit):
    """Read-only log with stable follow-tail and drag-selection scrolling."""

    _EDGE_MARGIN = 24

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._follow_tail = True
        self._applying_scroll_policy = False
        self._selection_drag_active = False
        self._auto_scroll_direction = 0
        self._last_drag_position = QPoint()
        self._selection_scroll_timer = QTimer(self)
        self._selection_scroll_timer.setInterval(50)
        self._selection_scroll_timer.timeout.connect(
            self._scroll_selection_toward_edge
        )
        scroll_bar = self.verticalScrollBar()
        scroll_bar.valueChanged.connect(self._record_scroll_position)
        scroll_bar.rangeChanged.connect(self._follow_changed_scroll_range)

    def appendPlainText(self, text: str) -> None:
        """Append without stealing a reader's current scroll position."""

        scroll_bar = self.verticalScrollBar()
        was_at_bottom = self._follow_tail
        previous_value = scroll_bar.value()

        self._applying_scroll_policy = True
        try:
            append_cursor = QTextCursor(self.document())
            append_cursor.movePosition(QTextCursor.MoveOperation.End)
            if not self.document().isEmpty():
                append_cursor.insertBlock()
            append_cursor.insertText(text)
            if was_at_bottom:
                scroll_bar.setValue(scroll_bar.maximum())
            else:
                scroll_bar.setValue(
                    min(previous_value, scroll_bar.maximum())
                )
        finally:
            self._applying_scroll_policy = False
        self._follow_tail = was_at_bottom

    def _record_scroll_position(self, value: int) -> None:
        if self._applying_scroll_policy:
            return
        scroll_bar = self.verticalScrollBar()
        self._follow_tail = value >= scroll_bar.maximum() - 2

    def _follow_changed_scroll_range(
        self,
        _minimum: int,
        maximum: int,
    ) -> None:
        if not self._follow_tail or self._applying_scroll_policy:
            return
        self._applying_scroll_policy = True
        try:
            self.verticalScrollBar().setValue(maximum)
        finally:
            self._applying_scroll_policy = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._stop_selection_auto_scroll()
        self._selection_drag_active = (
            event.button() == Qt.MouseButton.LeftButton
        )
        self._last_drag_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._last_drag_position = event.position().toPoint()
        self._selection_drag_active = bool(
            event.buttons() & Qt.MouseButton.LeftButton
        )
        super().mouseMoveEvent(event)
        self._update_selection_auto_scroll()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._selection_drag_active = False
            self._stop_selection_auto_scroll()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self._selection_drag_active = False
        self._stop_selection_auto_scroll()
        super().focusOutEvent(event)

    def _update_selection_auto_scroll(self) -> None:
        if not self._selection_drag_active:
            self._stop_selection_auto_scroll()
            return

        viewport_height = self.viewport().height()
        if self._last_drag_position.y() <= self._EDGE_MARGIN:
            direction = -1
        elif (
            self._last_drag_position.y()
            >= viewport_height - self._EDGE_MARGIN
        ):
            direction = 1
        else:
            self._stop_selection_auto_scroll()
            return

        self._auto_scroll_direction = direction
        if not self._selection_scroll_timer.isActive():
            self._selection_scroll_timer.start()

    def _scroll_selection_toward_edge(self) -> None:
        if not self._selection_drag_active or not self._auto_scroll_direction:
            self._stop_selection_auto_scroll()
            return

        scroll_bar = self.verticalScrollBar()
        old_value = scroll_bar.value()
        step = max(1, scroll_bar.singleStep())
        scroll_bar.setValue(old_value + self._auto_scroll_direction * step)
        if scroll_bar.value() == old_value:
            return

        viewport = self.viewport()
        target_y = (
            1
            if self._auto_scroll_direction < 0
            else max(1, viewport.height() - 2)
        )
        target_x = min(
            max(1, self._last_drag_position.x()),
            max(1, viewport.width() - 2),
        )
        target_position = self.cursorForPosition(
            QPoint(target_x, target_y)
        ).position()
        cursor = self.textCursor()
        anchor = cursor.anchor()
        cursor.setPosition(anchor)
        cursor.setPosition(
            target_position,
            QTextCursor.MoveMode.KeepAnchor,
        )
        self.setTextCursor(cursor)

    def _stop_selection_auto_scroll(self) -> None:
        self._auto_scroll_direction = 0
        self._selection_scroll_timer.stop()


class ExecutionPage(InputPage):
    run_requested = Signal()
    cancel_requested = Signal()
    preserve_requested = Signal()
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
        self._has_feasible_solution = False
        self._can_preserve_output = False
        self._preserve_requested = False
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh_elapsed)

        self.status_group = QGroupBox("執行狀態")
        self.status_group.setObjectName("executionStickyStatus")
        status_layout = QVBoxLayout(self.status_group)

        self.status_summary = QFrame()
        self.status_summary.setObjectName("executionStatusSummary")
        summary_layout = QHBoxLayout(self.status_summary)
        summary_layout.setContentsMargins(0, 0, 0, 8)
        summary_layout.setSpacing(10)
        self.status_indicator = QLabel("●")
        self.status_indicator.setObjectName("executionStatusIndicator")
        self.status_indicator.setProperty("state", "neutral")
        summary_layout.addWidget(
            self.status_indicator,
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        summary_text_layout = QVBoxLayout()
        summary_text_layout.setContentsMargins(0, 0, 0, 0)
        summary_text_layout.setSpacing(2)
        self.status_label = QLabel("資料準備完成後即可執行排班。")
        self.status_label.setObjectName("executionStatusPrimary")
        self.status_label.setWordWrap(True)
        summary_text_layout.addWidget(self.status_label)
        self.status_detail_label = QLabel()
        self.status_detail_label.setObjectName("executionStatusDetail")
        self.status_detail_label.setWordWrap(True)
        self.status_detail_label.hide()
        summary_text_layout.addWidget(self.status_detail_label)
        summary_layout.addLayout(summary_text_layout, 1)

        elapsed_layout = QVBoxLayout()
        elapsed_layout.setContentsMargins(12, 0, 0, 0)
        elapsed_layout.setSpacing(0)
        elapsed_title = QLabel("總耗時")
        elapsed_title.setObjectName("executionElapsedTitle")
        elapsed_title.setAlignment(Qt.AlignmentFlag.AlignRight)
        elapsed_layout.addWidget(elapsed_title)
        self.elapsed_label = QLabel("0 秒")
        self.elapsed_label.setObjectName("executionElapsedValue")
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        elapsed_layout.addWidget(self.elapsed_label)
        summary_layout.addLayout(elapsed_layout)
        status_layout.addWidget(self.status_summary)

        self.progress_section = QFrame()
        self.progress_section.setObjectName("executionProgressSection")
        progress_layout = QVBoxLayout(self.progress_section)
        progress_layout.setContentsMargins(0, 6, 0, 6)
        progress_layout.setSpacing(4)
        progress_header = QHBoxLayout()
        progress_header.setContentsMargins(0, 0, 0, 0)
        self.progress_count_label = QLabel()
        self.progress_count_label.setObjectName("executionProgressCount")
        self.progress_title_label = QLabel()
        self.progress_title_label.setObjectName("executionProgressTitle")
        self.progress_title_label.setWordWrap(True)
        progress_header.addWidget(self.progress_count_label)
        progress_header.addWidget(self.progress_title_label, 1)
        progress_layout.addLayout(progress_header)
        self.progress_subtask_frame = QFrame()
        self.progress_subtask_frame.setObjectName("executionProgressSubtask")
        subtask_layout = QVBoxLayout(self.progress_subtask_frame)
        subtask_layout.setContentsMargins(10, 2, 0, 2)
        self.progress_subtask_label = QLabel()
        self.progress_subtask_label.setObjectName("executionProgressSubtaskText")
        self.progress_subtask_label.setWordWrap(True)
        subtask_layout.addWidget(self.progress_subtask_label)
        progress_layout.addWidget(self.progress_subtask_frame)
        self.progress_technical_label = QLabel()
        self.progress_technical_label.setObjectName(
            "executionProgressTechnical"
        )
        self.progress_technical_label.setWordWrap(True)
        progress_layout.addWidget(self.progress_technical_label)
        self.progress_section.hide()
        self.progress_subtask_frame.hide()
        self.progress_technical_label.hide()
        status_layout.addWidget(self.progress_section)

        self.metrics_section = QFrame()
        self.metrics_section.setObjectName("executionMetricsSection")
        metrics_layout = QVBoxLayout(self.metrics_section)
        metrics_layout.setContentsMargins(0, 6, 0, 6)
        metrics_layout.setSpacing(4)
        metrics_header = QHBoxLayout()
        metrics_header.setContentsMargins(0, 0, 0, 0)
        metrics_header.setSpacing(5)
        metrics_title = QLabel("最佳化指標")
        metrics_title.setObjectName("executionMetricsTitle")
        metrics_header.addWidget(metrics_title)
        self.objective_info_button = QToolButton()
        self.objective_info_button.setObjectName("executionObjectiveInfo")
        self.objective_info_button.setAccessibleName("目前最佳化目標說明")
        self.objective_info_button.setAutoRaise(True)
        self.objective_info_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.objective_info_button.setIcon(themed_information_icon())
        self.objective_info_button.setIconSize(QSize(16, 16))
        self.objective_info_button.hide()
        metrics_header.addWidget(self.objective_info_button)
        metrics_header.addStretch(1)
        metrics_layout.addLayout(metrics_header)
        metrics_grid = QGridLayout()
        metrics_grid.setContentsMargins(0, 0, 0, 0)
        metrics_grid.setHorizontalSpacing(20)
        metrics_grid.setVerticalSpacing(5)
        self.metric_items: dict[str, QWidget] = {}
        self.metric_labels: dict[str, QLabel] = {}
        self.metric_values: dict[str, QLabel] = {}
        metric_definitions = (
            (
                "incumbent",
                "目前找到的最佳值",
                "目前已找到且符合現行限制的班表，在本階段達到的最佳值。",
            ),
            (
                "best_bound",
                "已證明的最佳值界限",
                "求解器目前能證明的最佳可能界限，不代表已經找到該數值的班表。",
            ),
            (
                "relative_gap",
                "與證明最佳的距離",
                "目前找到的最佳值與已證明的最佳值界限之相對差距；0% 代表本階段已證明最佳，不能換算為剩餘時間。",
            ),
            ("stage_elapsed_seconds", "本階段耗時", "目前求解階段已使用的時間。"),
            (
                "seconds_since_last_solution",
                "最後找到更好解",
                "距離上一次找到更佳可行值已經過的時間。",
            ),
            (
                "seconds_since_bound_update",
                "最佳界限最後更新",
                "距離已證明的最佳值界限上一次改善已經過的時間。",
            ),
        )
        for index, (key, title, tooltip) in enumerate(metric_definitions):
            item = QFrame()
            item.setObjectName("executionMetricItem")
            item.setToolTip(tooltip)
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(0)
            label = QLabel(title)
            label.setObjectName("executionMetricLabel")
            label.setToolTip(tooltip)
            value = QLabel()
            value.setObjectName("executionMetricValue")
            value.setToolTip(tooltip)
            item_layout.addWidget(label)
            item_layout.addWidget(value)
            metrics_grid.addWidget(item, index // 3, index % 3)
            self.metric_items[key] = item
            self.metric_labels[key] = label
            self.metric_values[key] = value
            item.hide()
        for column in range(3):
            metrics_grid.setColumnStretch(column, 1)
        metrics_layout.addLayout(metrics_grid)
        self.metrics_section.hide()
        status_layout.addWidget(self.metrics_section)

        actions = QHBoxLayout()
        self.run_button = QPushButton("檢查、儲存並執行")
        self.run_button.setObjectName("primaryActionButton")
        self.cancel_button = QPushButton("終止排班")
        self.cancel_button.setEnabled(False)
        self.preserve_button = QPushButton("終止排班並保留當前最佳班表")
        self.preserve_button.setEnabled(False)
        self.stop_candidate_button = QPushButton("終止候選處理")
        self.stop_candidate_button.setEnabled(False)
        self.stop_candidate_button.hide()
        self.run_button.clicked.connect(self.run_requested.emit)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.preserve_button.clicked.connect(self.preserve_requested.emit)
        self.stop_candidate_button.clicked.connect(
            self.stop_candidate_requested.emit
        )
        actions.addWidget(self.run_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.preserve_button)
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
        self.log = _ExecutionLog()
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

    def _set_status_summary(
        self,
        primary: str,
        secondary: str | None = None,
        *,
        state: str = "neutral",
    ) -> None:
        """Render summary widgets without retaining domain or execution state."""

        self.status_label.setText(primary)
        if secondary:
            self.status_detail_label.setText(secondary)
            self.status_detail_label.show()
        else:
            self.status_detail_label.clear()
            self.status_detail_label.hide()
        self.status_indicator.setProperty("state", state)
        self.status_indicator.style().unpolish(self.status_indicator)
        self.status_indicator.style().polish(self.status_indicator)

    def _hide_progress_presentation(self) -> None:
        self.progress_count_label.clear()
        self.progress_count_label.hide()
        self.progress_title_label.clear()
        self.progress_title_label.hide()
        self.progress_subtask_label.clear()
        self.progress_subtask_frame.hide()
        self.progress_technical_label.clear()
        self.progress_technical_label.hide()
        self.objective_info_button.setToolTip("")
        self.objective_info_button.hide()
        self.progress_section.hide()
        for item in self.metric_items.values():
            item.hide()
        self.metrics_section.hide()

    def _present_progress_event(self, message: dict[str, Any]) -> None:
        """Map one event to UI widgets; this intentionally stores no new state."""

        phase = str(message.get("phase", ExecutionPhase.APPLICATION.value))
        rendered = str(message.get("message", "")).strip()
        details = message.get("details")
        details = details if isinstance(details, dict) else {}
        has_rich_optimization_context = bool(details.get("activity"))
        has_existing_optimization_presentation = any(
            (
                not self.progress_section.isHidden(),
                not self.metrics_section.isHidden(),
            )
        )
        if (
            phase == ExecutionPhase.OPTIMIZATION.value
            and not has_rich_optimization_context
            and has_existing_optimization_presentation
        ):
            # Runner-level elapsed/completion messages are only a fallback.
            # They must not erase a newer solver event with stage and bound
            # information, especially while preserving a partial schedule.
            return
        retain_stopped_optimization = (
            self._preserve_requested
            and phase
            in {
                ExecutionPhase.VALIDATION.value,
                ExecutionPhase.OUTPUT.value,
            }
        )
        if not retain_stopped_optimization:
            self._hide_progress_presentation()

        if phase == ExecutionPhase.INPUT.value:
            self._set_status_summary(
                "正在讀取輸入資料",
                rendered or None,
                state="running",
            )
        elif phase == ExecutionPhase.CONFIG.value:
            self._set_status_summary(
                "正在載入執行設定",
                rendered or None,
                state="running",
            )
        elif phase == ExecutionPhase.NORMALIZATION.value:
            self._set_status_summary(
                "正在驗證與整理輸入資料",
                rendered or None,
                state="running",
            )
        elif phase == ExecutionPhase.PRECHECK.value:
            self._set_status_summary(
                "正在執行前置可行性檢查",
                rendered or None,
                state="running",
            )
        elif phase == ExecutionPhase.OPTIMIZATION.value:
            self._present_optimization_event(rendered, details)
        elif phase == ExecutionPhase.VALIDATION.value:
            self._set_status_summary(
                "正在驗證排班結果",
                "依最終班表重新檢查硬性規則、統計與鎖定目標",
                state="running",
            )
        elif phase == ExecutionPhase.OUTPUT.value:
            self._set_status_summary(
                "正在產生輸出檔案",
                rendered.splitlines()[0] if rendered else None,
                state="running",
            )
        elif phase == ExecutionPhase.CANDIDATE_SEARCH.value:
            self._set_status_summary(
                "正式班表已完成",
                "正在搜尋同品質候選班表",
                state="running",
            )
            current = message.get("current")
            total = message.get("total")
            if current is not None and total is not None:
                self.progress_count_label.setText(
                    f"候選搜尋 {current} / {total}"
                )
                self.progress_count_label.show()
                self.progress_title_label.setText("已找到同品質候選班表")
                self.progress_title_label.show()
                self.progress_section.show()
        else:
            self._set_status_summary(
                rendered or "正在執行排班流程",
                state="running" if self._running else "neutral",
            )

    def _present_optimization_event(
        self,
        rendered: str,
        details: dict[str, Any],
    ) -> None:
        activity = str(details.get("activity", ""))
        has_feasible = details.get("has_feasible_solution") is True
        if activity == "formal_optimization_completed":
            self._set_status_summary(
                "排班品質最佳化已完成",
                "正式目標均已證明最佳，準備驗證與輸出",
                state="running",
            )
        elif has_feasible:
            self._set_status_summary(
                "已找到可行班表，持續最佳化中",
                "目前已有可行但非最佳的班表",
                state="running",
            )
        else:
            self._set_status_summary(
                "正在尋找合法班表",
                rendered or "正在檢查全部硬性限制",
                state="running",
            )

        user_index = details.get("user_step_index")
        user_total = details.get("user_step_total")
        user_title = details.get("user_step_title")
        if user_index is not None and user_total is not None:
            self.progress_count_label.setText(
                f"整體最佳化 {user_index} / {user_total}"
            )
            self.progress_count_label.show()
        if user_title:
            self.progress_title_label.setText(str(user_title))
            self.progress_title_label.show()

        completed = details.get("formal_stages_completed")
        formal_total = details.get("formal_stage_total")
        technical: str | None = None
        if activity == "formal_stage":
            stage_index = details.get("formal_stage_index")
            stage_name = details.get("formal_stage_name")
            if stage_index is not None and formal_total is not None:
                technical = f"技術細節：正式流程 {stage_index} / {formal_total}"
                if stage_name:
                    technical += f" · {stage_name}"
                if completed is not None:
                    technical += f"（已完成 {completed} / {formal_total}）"
        elif activity == "preference_benchmark":
            rank = "第一" if details.get("rank") == "first" else "第二"
            full_time_class = details.get("full_time_class")
            benchmark_index = details.get("benchmark_index")
            benchmark_total = details.get("benchmark_total")
            if (
                full_time_class
                and benchmark_index is not None
                and benchmark_total is not None
            ):
                self.progress_subtask_label.setText(
                    f"目前：{full_time_class} 類{rank}偏好基準 "
                    f"{benchmark_index} / {benchmark_total}"
                )
                self.progress_subtask_frame.show()
            if completed is not None and formal_total is not None:
                technical = (
                    "技術細節：正式流程已完成 "
                    f"{completed} / {formal_total}"
                )
        elif (
            activity == "formal_optimization_completed"
            and completed is not None
            and formal_total is not None
        ):
            technical = f"技術細節：正式流程 {completed} / {formal_total}"
        if technical:
            self.progress_technical_label.setText(technical)
            self.progress_technical_label.show()

        if any(
            (
                not self.progress_count_label.isHidden(),
                not self.progress_title_label.isHidden(),
                not self.progress_subtask_frame.isHidden(),
                not self.progress_technical_label.isHidden(),
            )
        ):
            self.progress_section.show()

        incumbent = details.get("incumbent")
        if incumbent is None:
            incumbent = details.get("objective_value")
        if incumbent is None:
            incumbent = details.get("benchmark_ideal_value")
        best_bound = details.get("best_bound")
        if best_bound is None:
            best_bound = details.get("best_objective_bound")
        relative_gap = details.get("relative_gap")
        if (
            relative_gap is None
            and incumbent is not None
            and best_bound is not None
        ):
            absolute_gap = abs(float(incumbent) - float(best_bound))
            relative_gap = absolute_gap / max(abs(float(incumbent)), 1.0)

        metric_values: dict[str, str | None] = {
            "incumbent": (
                None
                if incumbent is None
                else _compact_number(incumbent)
            ),
            "best_bound": (
                None
                if best_bound is None
                else _compact_number(best_bound)
            ),
            "relative_gap": (
                None
                if relative_gap is None
                else f"{float(relative_gap) * 100:.1f}%"
            ),
            "stage_elapsed_seconds": _formatted_duration_or_none(
                details.get("stage_elapsed_seconds")
            ),
            "seconds_since_last_solution": _formatted_duration_or_none(
                details.get("seconds_since_last_solution"),
                suffix="前",
            ),
            "seconds_since_bound_update": _formatted_duration_or_none(
                details.get("seconds_since_bound_update"),
                suffix="前",
            ),
        }
        has_metric = False
        for key, value in metric_values.items():
            item = self.metric_items[key]
            if value is None:
                item.hide()
                continue
            self.metric_values[key].setText(value)
            item.show()
            has_metric = True
        objective_direction = str(details.get("objective_direction", ""))
        objective_name = str(
            details.get("formal_stage_name")
            or details.get("objective_name")
            or rendered
        ).strip()
        if has_metric and objective_direction in {"MAXIMIZE", "MINIMIZE"}:
            direction_text = (
                "最大化，數值越大越好"
                if objective_direction == "MAXIMIZE"
                else "最小化，數值越小越好"
            )
            self.objective_info_button.setToolTip(
                f"目前目標：{objective_name}\n求解方向：{direction_text}"
            )
            self.objective_info_button.show()
        else:
            self.objective_info_button.setToolTip("")
            self.objective_info_button.hide()
        self.metrics_section.setVisible(has_metric)

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
        self._has_feasible_solution = False
        self._can_preserve_output = False
        self._preserve_requested = False
        self._set_status_summary(
            "資料準備完成後即可執行排班。",
            state="neutral",
        )
        self._hide_progress_presentation()
        self.elapsed_label.setText("0 秒")
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
        self.preserve_button.setEnabled(False)
        self.preserve_button.setToolTip("")
        self.stop_candidate_button.setEnabled(False)
        self.stop_candidate_button.hide()
        self.result_group.setTitle("正式結果")

    def mark_input_changed(self) -> None:
        if self._running or not self._terminal_received:
            return
        self._set_status_summary(
            "輸入資料已修改",
            "再次執行前會先儲存最新內容。",
            state="warning",
        )
        self._hide_progress_presentation()
        self.result_status_label.setText("先前結果（不含目前修改）")

    def begin(self) -> None:
        self._running = True
        self._terminal_received = False
        self._candidate_processing = False
        self._candidate_stop_requested = False
        self._has_feasible_solution = False
        self._can_preserve_output = False
        self._preserve_requested = False
        self.log.clear()
        self.result_group.hide()
        self.content_scroll.verticalScrollBar().setValue(0)
        self.result_status_label.setText("執行中")
        self.validation_label.setText("等待驗證")
        self.output_label.setText("—")
        self.candidate_label.setText("等待執行")
        self.open_output_button.setEnabled(False)
        self.open_output_button.setProperty("output_directory", None)
        self._set_status_summary(
            "正在啟動排班程序",
            "準備讀取設定與輸入資料",
            state="running",
        )
        self._hide_progress_presentation()
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.preserve_button.setEnabled(False)
        self.preserve_button.setToolTip("")
        self.stop_candidate_button.setEnabled(False)
        self.stop_candidate_button.hide()
        self._elapsed.start()
        self._timer.start()
        self._refresh_elapsed()

    def show_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "started":
            self._set_status_summary(
                "排班程序已啟動",
                "正在讀取資料",
                state="running",
            )
            self._hide_progress_presentation()
            self.log.appendPlainText("[執行] 已啟動獨立排班程序。")
        elif message_type == "progress":
            self._show_progress(message)
        elif message_type == "completed":
            self._show_completed(message)
        elif message_type == "preserved":
            self._show_preserved(message)
        elif message_type == "failed":
            self._show_failed(message)

    def append_stderr(self, text: str) -> None:
        if text:
            self.log.appendPlainText(f"[程序訊息] {text}")

    def request_cancelling(self) -> None:
        self.cancel_button.setEnabled(False)
        self.preserve_button.setEnabled(False)
        self.stop_candidate_button.setEnabled(False)
        self._set_status_summary(
            "正在終止排班",
            "本次結果將不會保留，請稍候。",
            state="warning",
        )
        self.log.appendPlainText("[執行] 已提出取消要求。")

    def request_preserving(self) -> None:
        if self._preserve_requested:
            return
        self._preserve_requested = True
        self.cancel_button.setEnabled(False)
        self.preserve_button.setEnabled(False)
        self.stop_candidate_button.setEnabled(False)
        self._set_status_summary(
            "正在保留目前最佳合法班表",
            "停止後續最佳化後，將先進行獨立驗證再輸出。",
            state="warning",
        )
        self.log.appendPlainText(
            "[排班] 已提出保留要求；完成獨立驗證後才會建立暫存結果。"
        )

    def request_candidate_stopping(self) -> None:
        if not self._candidate_processing or self._candidate_stop_requested:
            return
        self._candidate_stop_requested = True
        self.stop_candidate_button.setEnabled(False)
        self._set_status_summary(
            "正式班表已完成",
            "正在終止候選處理；已完成的正式班表不受影響。",
            state="running",
        )
        self._hide_progress_presentation()
        self.log.appendPlainText("[候選處理] 已提出終止要求。")

    def process_finished(self) -> None:
        self._running = False
        self._timer.stop()
        self.run_button.setEnabled(self.month_label.text() != "尚未開啟月份")
        self.cancel_button.setEnabled(False)
        self.preserve_button.setEnabled(False)
        self.stop_candidate_button.setEnabled(False)
        self.stop_candidate_button.hide()
        self._candidate_processing = False
        self._refresh_elapsed()

    def _show_progress(self, message: dict[str, Any]) -> None:
        phase = str(message.get("phase", "APPLICATION"))
        label = _PHASE_LABELS.get(phase, phase)
        rendered = str(message.get("message", ""))
        self._present_progress_event(message)
        kind = message.get("kind")
        details = message.get("details")
        if isinstance(details, dict):
            if details.get("has_feasible_solution") is True:
                self._has_feasible_solution = True
            if "can_preserve_output" in details:
                self._can_preserve_output = bool(
                    details.get("can_preserve_output")
                )
        if phase == ExecutionPhase.CANDIDATE_SEARCH.value:
            self._candidate_processing = True
            self.cancel_button.setEnabled(False)
            self.preserve_button.setEnabled(False)
            self.stop_candidate_button.show()
            self.stop_candidate_button.setEnabled(
                not self._candidate_stop_requested
            )
        elif self._candidate_processing:
            self._candidate_processing = False
            self.cancel_button.setEnabled(False)
            self.preserve_button.setEnabled(False)
            self.stop_candidate_button.setEnabled(False)
            self.stop_candidate_button.hide()
        elif phase in {
            ExecutionPhase.VALIDATION.value,
            ExecutionPhase.OUTPUT.value,
        }:
            # Independent validation and formal file commit are deliberately
            # non-interruptible; the dedicated candidate control becomes
            # available if the optional search starts afterwards.
            self.cancel_button.setEnabled(False)
            self.preserve_button.setEnabled(False)
            self.stop_candidate_button.hide()
        else:
            self.stop_candidate_button.hide()
            activity = (
                str(details.get("activity", ""))
                if isinstance(details, dict)
                else ""
            )
            self._update_preserve_button(
                phase,
                optimization_completed=(
                    activity == "formal_optimization_completed"
                ),
            )
        if kind not in {
            ProgressEventKind.HEARTBEAT.value,
            ProgressEventKind.CANDIDATE_COUNT.value,
        }:
            self.log.appendPlainText(f"[{label}] {rendered}")

    def _show_completed(self, message: dict[str, Any]) -> None:
        self._terminal_received = True
        self._candidate_processing = False
        self.preserve_button.setEnabled(False)
        self.stop_candidate_button.setEnabled(False)
        self.stop_candidate_button.hide()
        self.result_group.setTitle("正式結果")
        self._set_status_summary(
            "排班完成",
            "正式結果已通過驗證並完成輸出。",
            state="success",
        )
        self._hide_progress_presentation()
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
        self.log.appendPlainText("[執行] 正式結果完成。")
        self.result_group.show()
        self.scroll_content.updateGeometry()
        QTimer.singleShot(0, self._scroll_to_completed_result)

    def _show_preserved(self, message: dict[str, Any]) -> None:
        self._terminal_received = True
        self._candidate_processing = False
        self.cancel_button.setEnabled(False)
        self.preserve_button.setEnabled(False)
        self.stop_candidate_button.setEnabled(False)
        self.stop_candidate_button.hide()
        self._set_status_summary(
            "已保留目前最佳合法班表",
            "正式最佳化尚未完成，此結果未證明為最佳。",
            state="warning",
        )
        status = str(message.get("status", "—"))
        validation = str(message.get("validation", "—"))
        self.result_group.setTitle("目前最佳合法班表")
        self.result_status_label.setText(
            "合法班表（FEASIBLE，未證明最佳）"
            if status == "FEASIBLE"
            else status
        )
        self.validation_label.setText(
            "通過（PASS）" if validation == "PASS" else validation
        )
        paths = message.get("paths", {})
        if not isinstance(paths, dict):
            paths = {}
        selected_formats = message.get("selected_formats", ())
        if not isinstance(selected_formats, (list, tuple)):
            selected_formats = ()
        self.output_label.setText(
            _render_output_paths(
                paths,
                selected_formats={str(item) for item in selected_formats},
            )
        )
        self.candidate_label.setText("未執行（暫存結果不搜尋候選班表）")
        first_path = next(
            (
                paths.get(key)
                for key, _label in _OUTPUT_PATH_LABELS
                if paths.get(key)
            ),
            None,
        )
        if first_path:
            self.open_output_button.setProperty(
                "output_directory", str(Path(str(first_path)).parent)
            )
            self.open_output_button.setEnabled(True)
        self.log.appendPlainText(
            "[執行] 已輸出目前最佳合法班表；此結果尚未證明最佳。"
        )
        self.result_group.show()
        self.scroll_content.updateGeometry()
        QTimer.singleShot(0, self._scroll_to_completed_result)

    def _show_failed(self, message: dict[str, Any]) -> None:
        self._terminal_received = True
        self._candidate_processing = False
        self.preserve_button.setEnabled(False)
        self.stop_candidate_button.setEnabled(False)
        self.stop_candidate_button.hide()
        kind = str(message.get("kind", "UNKNOWN"))
        cancelled = kind == "CANCELLED"
        rendered = str(message.get("message", "排班失敗。"))
        self._set_status_summary(
            "排班已終止" if cancelled else "排班未完成",
            "已保留終止當下的求解進度。" if cancelled else rendered,
            state="neutral" if cancelled else "error",
        )
        if not cancelled:
            self._hide_progress_presentation()
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
        self.elapsed_label.setText(format_duration(elapsed_seconds))

    def _update_preserve_button(
        self,
        phase: str,
        *,
        optimization_completed: bool = False,
    ) -> None:
        self.preserve_button.setEnabled(
            self._running
            and not self._preserve_requested
            and not self._candidate_processing
            and not optimization_completed
            and phase == ExecutionPhase.OPTIMIZATION.value
            and self._has_feasible_solution
            and self._can_preserve_output
        )

    def _request_open_output(self) -> None:
        directory = self.open_output_button.property("output_directory")
        if isinstance(directory, str) and directory:
            self.open_output_requested.emit(directory)

    def _scroll_to_completed_result(self) -> None:
        """Reveal the complete result area and its output-directory action."""

        layout = self.scroll_content.layout()
        if layout is not None:
            layout.activate()
        bar = self.content_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


def _render_output_paths(
    paths: dict[str, Any],
    *,
    selected_formats: set[str] | None = None,
) -> str:
    """Make every required formal medium visible, including missing ones."""

    lines: list[str] = []
    for key, label in _OUTPUT_PATH_LABELS:
        path = paths.get(key)
        missing = (
            "未選擇"
            if selected_formats is not None and key not in selected_formats
            else "未產生"
        )
        lines.append(f"{label}：{path or missing}")
    return "\n".join(lines)
