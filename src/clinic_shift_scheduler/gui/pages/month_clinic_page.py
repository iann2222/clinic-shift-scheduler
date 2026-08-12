"""Month entry actions and read-only fixed clinic settings."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..drafts import ScheduleDraft
from ..field_location import FieldLocation
from ..navigation import NAVIGATION_ITEMS, PageId
from .base import InputPage


class MonthClinicPage(InputPage):
    draft_changed = Signal()
    create_requested = Signal()
    copy_previous_requested = Signal()
    open_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        item = next(
            item
            for item in NAVIGATION_ITEMS
            if item.page_id is PageId.MONTH_CLINIC
        )
        super().__init__(
            item.page_id,
            item.title,
            item.description,
            show_empty_state=False,
            parent=parent,
        )
        self._draft: ScheduleDraft | None = None

        start_panel = QFrame()
        start_panel.setObjectName("monthStartPanel")
        start_layout = QVBoxLayout(start_panel)
        start_layout.setContentsMargins(16, 14, 16, 14)
        start_layout.setSpacing(10)
        start_title = QLabel("開始設定排班月份")
        start_title.setObjectName("sectionTitle")
        start_hint = QLabel(
            "建立新的月份、沿用上個月固定資料，或開啟先前儲存的排班輸入。"
        )
        start_hint.setObjectName("mutedText")
        start_hint.setWordWrap(True)
        start_layout.addWidget(start_title)
        start_layout.addWidget(start_hint)
        action_row = QHBoxLayout()
        action_row.setSpacing(12)
        for title, hint, signal in (
            ("建立新月份", "從空白資料開始設定", self.create_requested),
            ("從上月建立", "沿用人員與固定設定", self.copy_previous_requested),
            ("開啟既有月份", "繼續編輯已儲存檔案", self.open_requested),
        ):
            card = QFrame()
            card.setObjectName("monthActionCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)
            button = QPushButton(title)
            button.setObjectName("monthActionButton")
            button.clicked.connect(signal.emit)
            description = QLabel(hint)
            description.setObjectName("mutedText")
            description.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(button)
            card_layout.addWidget(description)
            action_row.addWidget(card, 1)
        start_layout.addLayout(action_row)
        self.surface_layout.addWidget(start_panel)

        month_group = QGroupBox("月份與固定設定")
        month_form = QFormLayout(month_group)
        self.period_label = QLabel("尚未開啟月份")
        self.fixed_periods_label = QLabel("早上、下午、晚上")
        self.version_label = QLabel("weekly-v1 / v1")
        month_form.addRow("排班月份：", self.period_label)
        month_form.addRow("每日時段：", self.fixed_periods_label)
        month_form.addRow("規格版本：", self.version_label)
        self.surface_layout.addWidget(month_group)
        self.surface_layout.addStretch(1)

    def bind_draft(self, draft: ScheduleDraft | None) -> None:
        self._draft = draft
        self._refresh()

    def focus_location(self, location: FieldLocation) -> None:
        self.period_label.setFocus()

    def _refresh(self) -> None:
        draft = self._draft
        if draft is None:
            self.period_label.setText("尚未開啟月份")
            self.version_label.setText("weekly-v1 / v1")
        else:
            self.period_label.setText(
                f"{draft.start_date.year} 年 {draft.start_date.month} 月"
                f"（{draft.start_date:%Y-%m-%d} ~ {draft.end_date:%Y-%m-%d}）"
            )
            self.version_label.setText(
                f"{draft.authoring_version} / {draft.schema_version}"
            )
