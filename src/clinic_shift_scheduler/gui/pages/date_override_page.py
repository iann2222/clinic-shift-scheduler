from __future__ import annotations

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...enums import Period
from ..dialogs import DatePickerDialog, show_warning
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
        layout.setSpacing(16)
        self.surface_layout.addLayout(layout, 1)

        date_group = QGroupBox("特定日期")
        date_layout = QVBoxLayout(date_group)
        date_layout.setSpacing(10)
        date_hint = QLabel(
            "只有當某一天與平常設定不同時才需要新增，"
            "如國定假日、臨時額外的加診或休診。"
        )
        date_hint.setObjectName("mutedText")
        date_hint.setWordWrap(True)
        date_layout.addWidget(date_hint)
        controls = QHBoxLayout()
        self.add_open_button = QPushButton("新增加診")
        self.add_closed_button = QPushButton("新增休診")
        self.remove_button = QPushButton("移除調整")
        controls.addWidget(self.add_open_button)
        controls.addWidget(self.add_closed_button)
        controls.addStretch(1)
        controls.addWidget(self.remove_button)
        date_layout.addLayout(controls)

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
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.model = DateOverrideTableModel()
        self.model.draft_changed.connect(self.draft_changed.emit)
        self.table.setModel(self.model)
        self.table.clicked.connect(self._cycle_staffing_count)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 65), (1, 130), (2, 110)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().setVisible(False)
        date_layout.addWidget(self.table, 1)
        layout.addWidget(date_group, 1)

        self.holiday_group = QGroupBox("假日標記")
        self.holiday_group.setObjectName("frozenSection")
        holiday_layout = QHBoxLayout(self.holiday_group)
        holiday_text = QLabel(
            "假日只影響統計與公平性，不會自動設為休診。"
        )
        holiday_text.setWordWrap(True)
        holiday_layout.addWidget(holiday_text, 2)
        self.holiday_list = QListWidget()
        self.holiday_list.setAccessibleName("本月已標記假日")
        self.holiday_list.setMaximumHeight(70)
        holiday_layout.addWidget(self.holiday_list, 2)
        holiday_actions = QVBoxLayout()
        self.add_holiday_button = QPushButton("新增假日")
        self.remove_holiday_button = QPushButton("移除")
        holiday_actions.addWidget(self.add_holiday_button)
        holiday_actions.addWidget(self.remove_holiday_button)
        holiday_actions.addStretch(1)
        holiday_layout.addLayout(holiday_actions)
        self.holiday_group.setToolTip(
            "此區目前僅顯示輸入檔既有標記；第一版前端暫不提供修改。"
        )
        self.holiday_group.setEnabled(False)
        layout.addWidget(self.holiday_group)

        self.add_open_button.clicked.connect(lambda: self._add(True))
        self.add_closed_button.clicked.connect(lambda: self._add(False))
        self.remove_button.clicked.connect(self._remove_selected)
        self.table.selectionModel().selectionChanged.connect(
            self._update_remove_button
        )
        self.bind_draft(None)

    def bind_draft(self, draft: ScheduleDraft | None) -> None:
        self._draft = draft
        self.model.set_draft(draft)
        self._refresh_holidays()
        enabled = draft is not None
        self.add_open_button.setEnabled(enabled)
        self.add_closed_button.setEnabled(enabled)
        self.table.clearSelection()
        self._update_remove_button()

    def focus_location(self, location: FieldLocation) -> None:
        if location.field == "holidays":
            self.holiday_list.setFocus()
            return
        if location.override_index is None:
            self.add_open_button.setFocus()
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
        index = self.model.index(location.override_index * 3 + period_index, column)
        if index.isValid():
            self.table.setCurrentIndex(index)
            self.table.scrollTo(index)
            self.table.setFocus()

    def _cycle_staffing_count(self, index: QModelIndex) -> None:
        if index.column() >= 3:
            self.model.cycle_count(index)

    def _add(self, is_open: bool) -> None:
        if self._draft is None:
            return
        dialog = DatePickerDialog(
            "新增特定日期調整",
            "請先從日曆選擇要新增的日期，再按右下角的確定。",
            self._draft.start_date,
            self._draft.end_date,
            parent=self,
        )
        if not dialog.exec():
            return
        try:
            self.model.add_override(dialog.selected_date, is_open=is_open)
        except ValueError as error:
            show_warning(self, "無法新增日期", str(error))

    def _remove_selected(self) -> None:
        if self._draft is None:
            return
        current = self.table.currentIndex()
        if not current.isValid():
            return
        try:
            self.model.remove_override_at(current.row())
        except ValueError as error:
            show_warning(self, "無法移除日期", str(error))
        self._update_remove_button()

    def _update_remove_button(self, *_args: object) -> None:
        self.remove_button.setEnabled(
            self._draft is not None and self.table.currentIndex().isValid()
        )

    def _refresh_holidays(self) -> None:
        self.holiday_list.clear()
        if self._draft is None:
            return
        for holiday in sorted(self._draft.holidays):
            self.holiday_list.addItem(holiday.isoformat())
