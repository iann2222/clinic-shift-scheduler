"""Editable month, holiday, fixed period, and dynamic role settings."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..dialogs import ask_yes_no, show_warning
from ..drafts import RoleMutationError, ScheduleDraft
from ..field_location import FieldLocation
from ..navigation import NAVIGATION_ITEMS, PageId
from .base import InputPage


class MonthClinicPage(InputPage):
    draft_changed = Signal()

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

        columns = QHBoxLayout()
        columns.setSpacing(20)
        self.surface_layout.addLayout(columns, 1)

        month_group = QGroupBox("月份與固定時段")
        month_form = QFormLayout(month_group)
        self.period_label = QLabel("尚未開啟月份")
        self.fixed_periods_label = QLabel("早上、下午、晚上")
        self.version_label = QLabel("weekly-v1 / v1")
        month_form.addRow("排班月份：", self.period_label)
        month_form.addRow("固定時段：", self.fixed_periods_label)
        month_form.addRow("資料版本：", self.version_label)
        columns.addWidget(month_group, 1)

        holiday_group = QGroupBox("假日")
        holiday_layout = QVBoxLayout(holiday_group)
        self.holiday_list = QListWidget()
        self.holiday_list.setAccessibleName("假日清單")
        holiday_layout.addWidget(self.holiday_list, 1)
        holiday_actions = QHBoxLayout()
        self.holiday_date = QDateEdit()
        self.holiday_date.setCalendarPopup(True)
        self.holiday_date.setDisplayFormat("yyyy-MM-dd")
        add_holiday = QPushButton("加入")
        remove_holiday = QPushButton("移除")
        add_holiday.clicked.connect(self._add_holiday)
        remove_holiday.clicked.connect(self._remove_holiday)
        holiday_actions.addWidget(self.holiday_date, 1)
        holiday_actions.addWidget(add_holiday)
        holiday_actions.addWidget(remove_holiday)
        holiday_layout.addLayout(holiday_actions)
        columns.addWidget(holiday_group, 1)

        role_group = QGroupBox("診所職務")
        role_layout = QVBoxLayout(role_group)
        role_hint = QLabel("職務變更會同步更新人力需求、人員資格與兼職時段。")
        role_hint.setObjectName("mutedText")
        role_hint.setWordWrap(True)
        role_layout.addWidget(role_hint)
        self.role_list = QListWidget()
        self.role_list.setAccessibleName("診所職務清單")
        self.role_list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.role_list.itemChanged.connect(self._rename_role)
        role_layout.addWidget(self.role_list, 1)
        role_actions = QHBoxLayout()
        add_role = QPushButton("新增")
        delete_role = QPushButton("刪除")
        add_role.clicked.connect(self._add_role)
        delete_role.clicked.connect(self._delete_role)
        role_actions.addWidget(add_role)
        role_actions.addWidget(delete_role)
        role_actions.addStretch(1)
        role_layout.addLayout(role_actions)
        columns.addWidget(role_group, 1)

    def bind_draft(self, draft: ScheduleDraft | None) -> None:
        self._draft = draft
        self._refresh()

    def focus_location(self, location: FieldLocation) -> None:
        if location.field == "holidays":
            self.holiday_date.setFocus()
        elif location.field == "roles":
            self.role_list.setFocus()
        else:
            self.period_label.setFocus()

    def _refresh(self) -> None:
        draft = self._draft
        self.holiday_list.blockSignals(True)
        self.role_list.blockSignals(True)
        self.holiday_list.clear()
        self.role_list.clear()
        if draft is None:
            self.period_label.setText("尚未開啟月份")
            self.version_label.setText("weekly-v1 / v1")
            self.holiday_date.setEnabled(False)
        else:
            self.period_label.setText(
                f"{draft.start_date:%Y-%m-%d} ～ {draft.end_date:%Y-%m-%d}"
            )
            self.version_label.setText(
                f"{draft.authoring_version} / {draft.schema_version}"
            )
            for holiday in sorted(draft.holidays):
                self.holiday_list.addItem(holiday.isoformat())
            for role in draft.roles:
                self.role_list.addItem(role)
                item = self.role_list.item(self.role_list.count() - 1)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.holiday_date.setDate(
                QDate(
                    draft.start_date.year,
                    draft.start_date.month,
                    draft.start_date.day,
                )
            )
            self.holiday_date.setMinimumDate(
                QDate(draft.start_date.year, draft.start_date.month, 1)
            )
            self.holiday_date.setMaximumDate(
                QDate(draft.end_date.year, draft.end_date.month, draft.end_date.day)
            )
            self.holiday_date.setEnabled(True)
        self.holiday_list.blockSignals(False)
        self.role_list.blockSignals(False)

    def _add_holiday(self) -> None:
        if self._draft is None:
            return
        selected = self.holiday_date.date()
        value = date(selected.year(), selected.month(), selected.day())
        if value not in self._draft.holidays:
            self._draft.holidays.append(value)
            self._draft.holidays.sort()
            self._draft.touch()
            self._refresh()
            self.draft_changed.emit()

    def _remove_holiday(self) -> None:
        if self._draft is None or self.holiday_list.currentItem() is None:
            return
        value = date.fromisoformat(self.holiday_list.currentItem().text())
        self._draft.holidays.remove(value)
        self._draft.touch()
        self._refresh()
        self.draft_changed.emit()

    def _add_role(self) -> None:
        if self._draft is None:
            return
        base = "新職務"
        candidate = base
        index = 2
        while candidate in self._draft.roles:
            candidate = f"{base}{index}"
            index += 1
        self._draft.add_role(candidate)
        self._refresh()
        self.role_list.setCurrentRow(self.role_list.count() - 1)
        self.role_list.editItem(self.role_list.currentItem())
        self.draft_changed.emit()

    def _rename_role(self, item: object) -> None:
        if self._draft is None:
            return
        row = self.role_list.row(item)
        if row < 0 or row >= len(self._draft.roles):
            return
        old = self._draft.roles[row]
        try:
            self._draft.rename_role(old, item.text())
        except RoleMutationError as error:
            show_warning(self, "無法修改職務", str(error))
            self._refresh()
            return
        self._refresh()
        self.draft_changed.emit()

    def _delete_role(self) -> None:
        if self._draft is None or self.role_list.currentItem() is None:
            return
        role = self.role_list.currentItem().text()
        if not ask_yes_no(
            self,
            "刪除職務",
            f"確定要刪除「{role}」並同步移除所有參照嗎？",
        ):
            return
        try:
            self._draft.delete_role(role)
        except RoleMutationError as error:
            show_warning(self, "無法刪除職務", str(error))
            return
        self._refresh()
        self.draft_changed.emit()
