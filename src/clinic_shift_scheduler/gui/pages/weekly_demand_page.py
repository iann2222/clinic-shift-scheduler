from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...enums import Period
from ..drafts import ScheduleDraft
from ..field_location import FieldLocation
from ..models import WeeklyDemandTableModel
from ..navigation import NAVIGATION_ITEMS, PageId
from .base import InputPage


class WeeklyDemandPage(InputPage):
    draft_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        self._draft: ScheduleDraft | None = None
        item = next(
            item
            for item in NAVIGATION_ITEMS
            if item.page_id is PageId.WEEKLY_DEMAND
        )
        super().__init__(
            item.page_id,
            item.title,
            item.description,
            show_empty_state=False,
            parent=parent,
        )
        layout = QVBoxLayout()
        self.surface_layout.addLayout(layout, 1)
        hint = QLabel(
            "勾選開診後，填寫早、午、晚各職務需要的人數；0 表示明確不需要。"
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableView()
        self.table.setAccessibleName("每週人力需求")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.model = WeeklyDemandTableModel()
        self.model.draft_changed.connect(self.draft_changed.emit)
        self.table.setModel(self.model)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

    def bind_draft(self, draft: ScheduleDraft | None) -> None:
        self._draft = draft
        self.model.set_draft(draft)

    def focus_location(self, location: FieldLocation) -> None:
        if location.weekly_index is None:
            self.table.setFocus()
            return
        period_index = 0
        if location.period is not None:
            period_index = list(Period).index(Period(location.period))
        column = 1 if location.field == "is_open" else 0
        if location.role is not None and self._draft is not None:
            try:
                column = 3 + self._draft.roles.index(location.role)
            except ValueError:
                column = 3
        index = self.model.index(location.weekly_index * 3 + period_index, column)
        if index.isValid():
            self.table.setCurrentIndex(index)
            self.table.scrollTo(index)
            self.table.setFocus()
