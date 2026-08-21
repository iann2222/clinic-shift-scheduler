from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, Signal
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
from ..widgets import LockedStaffingCellDelegate, PeriodToggleDelegate
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
            "每個時段可獨立開啟或休診；單擊人數即可在 1、2、3 之間輪替。"
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableView()
        self.table.setAccessibleName("每週人力需求")
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.model = WeeklyDemandTableModel()
        self.model.draft_changed.connect(self.draft_changed.emit)
        self.table.setModel(self.model)
        self.table.setItemDelegate(LockedStaffingCellDelegate(self.table))
        self.table.setItemDelegateForColumn(0, PeriodToggleDelegate(self.table))
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.clicked.connect(self._handle_table_click)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 65), (1, 130), (2, 110)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

    def _handle_table_click(self, index: QModelIndex) -> None:
        if index.column() == 0:
            current = self.model.data(index, Qt.ItemDataRole.CheckStateRole)
            self.model.setData(
                index,
                (
                    Qt.CheckState.Unchecked
                    if current == Qt.CheckState.Checked
                    else Qt.CheckState.Checked
                ),
                Qt.ItemDataRole.CheckStateRole,
            )
        elif index.column() >= 3:
            self.model.cycle_count(index)

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
        column = 0 if location.field == "is_open" else 1
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
