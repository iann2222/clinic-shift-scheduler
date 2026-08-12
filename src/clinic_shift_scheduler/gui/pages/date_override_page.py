from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...enums import Period
from ..dialogs import show_information, show_warning
from ..drafts import ScheduleDraft
from ..field_location import FieldLocation
from ..models import DateOverrideTableModel
from ..navigation import NAVIGATION_ITEMS, PageId
from .base import InputPage


class DateOverridePage(InputPage):
    draft_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        item = next(
            item
            for item in NAVIGATION_ITEMS
            if item.page_id is PageId.DATE_OVERRIDE
        )
        super().__init__(
            item.page_id,
            item.title,
            item.description,
            show_empty_state=False,
            parent=parent,
        )
        self._draft: ScheduleDraft | None = None
        layout = QVBoxLayout()
        self.surface_layout.addLayout(layout, 1)
        hint = QLabel(
            "只新增與每週模板不同的日期，例如國定假日休診或臨時加診。"
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        controls = QHBoxLayout()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        controls.addWidget(self.date_edit)
        self.add_open_button = QPushButton("新增開診調整")
        self.add_closed_button = QPushButton("新增休診調整")
        self.remove_button = QPushButton("移除所選日期")
        controls.addWidget(self.add_open_button)
        controls.addWidget(self.add_closed_button)
        controls.addStretch(1)
        controls.addWidget(self.remove_button)
        layout.addLayout(controls)

        self.table = QTableView()
        self.table.setAccessibleName("特定日期調整")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.model = DateOverrideTableModel()
        self.model.draft_changed.connect(self.draft_changed.emit)
        self.table.setModel(self.model)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column in range(3):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        self.add_open_button.clicked.connect(lambda: self._add(True))
        self.add_closed_button.clicked.connect(lambda: self._add(False))
        self.remove_button.clicked.connect(self._remove_selected)
        self.bind_draft(None)

    def bind_draft(self, draft: ScheduleDraft | None) -> None:
        self._draft = draft
        self.model.set_draft(draft)
        enabled = draft is not None
        self.date_edit.setEnabled(enabled)
        self.add_open_button.setEnabled(enabled)
        self.add_closed_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)
        if draft is not None:
            minimum = QDate(
                draft.start_date.year,
                draft.start_date.month,
                draft.start_date.day,
            )
            maximum = QDate(
                draft.end_date.year,
                draft.end_date.month,
                draft.end_date.day,
            )
            self.date_edit.setDateRange(minimum, maximum)
            self.date_edit.setDate(minimum)

    def focus_location(self, location: FieldLocation) -> None:
        if location.override_index is None:
            self.date_edit.setFocus()
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
        index = self.model.index(location.override_index * 3 + period_index, column)
        if index.isValid():
            self.table.setCurrentIndex(index)
            self.table.scrollTo(index)
            self.table.setFocus()

    def _add(self, is_open: bool) -> None:
        selected = self.date_edit.date()
        value = date(selected.year(), selected.month(), selected.day())
        try:
            self.model.add_override(value, is_open=is_open)
        except ValueError as error:
            show_warning(self, "無法新增日期", str(error))

    def _remove_selected(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            show_information(self, "尚未選擇", "請先選擇要移除的日期。")
            return
        try:
            self.model.remove_override_at(indexes[0].row())
        except ValueError as error:
            show_warning(self, "無法移除日期", str(error))
