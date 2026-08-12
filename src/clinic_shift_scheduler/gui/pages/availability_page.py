from __future__ import annotations

from datetime import date

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...enums import EmploymentType, Period
from ..dialogs import localize_dialog_buttons, show_information, show_warning
from ..drafts import EmployeeDraft, LeaveRequestDraft, ScheduleDraft
from ..models import AvailabilityFilterProxyModel, AvailabilityTableModel
from ..navigation import NAVIGATION_ITEMS, PageId
from ..widgets import AvailabilityDelegate
from .base import InputPage


class AvailabilityPage(InputPage):
    draft_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        item = next(
            item
            for item in NAVIGATION_ITEMS
            if item.page_id is PageId.AVAILABILITY
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
        controls = QHBoxLayout()
        controls.addWidget(QLabel("人員："))
        self.employee_combo = QComboBox()
        self.employee_combo.setMinimumWidth(220)
        controls.addWidget(self.employee_combo)
        self.type_hint = QLabel()
        self.type_hint.setObjectName("mutedText")
        controls.addWidget(self.type_hint)
        controls.addStretch(1)
        controls.addWidget(QLabel("星期："))
        self.weekday_filter = QComboBox()
        self.weekday_filter.addItem("全部", None)
        for index, label in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            self.weekday_filter.addItem(f"星期{label}", index)
        controls.addWidget(self.weekday_filter)
        controls.addWidget(QLabel("狀態："))
        self.state_filter = QComboBox()
        self.state_filter.addItem("全部", None)
        self.state_filter.addItem("含可排", "available")
        self.state_filter.addItem("含不可排", "unavailable")
        self.state_filter.addItem("含請假", "leave")
        controls.addWidget(self.state_filter)
        layout.addLayout(controls)

        self.explanation = QLabel()
        self.explanation.setObjectName("mutedText")
        self.explanation.setWordWrap(True)
        layout.addWidget(self.explanation)

        batch = QHBoxLayout()
        batch.addWidget(QLabel("批次套用至所選時段："))
        self.batch_state_combo = QComboBox()
        self.batch_state_combo.addItem("可排", "available")
        self.batch_state_combo.addItem("不可排", "unavailable")
        self.batch_state_combo.addItem("請假", "leave")
        batch.addWidget(self.batch_state_combo)
        self.batch_apply_button = QPushButton("套用狀態")
        self.all_day_leave_button = QPushButton("所選日期設為整日請假")
        self.clear_all_day_button = QPushButton("取消所選日期整日請假")
        batch.addWidget(self.batch_apply_button)
        batch.addStretch(1)
        batch.addWidget(self.all_day_leave_button)
        batch.addWidget(self.clear_all_day_button)
        layout.addLayout(batch)

        self.table = QTableView()
        self.table.setAccessibleName("休假與可排日期矩陣")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.model = AvailabilityTableModel()
        self.model.draft_changed.connect(self._model_changed)
        self.proxy_model = AvailabilityFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.table.setModel(self.proxy_model)
        delegate = AvailabilityDelegate(self.table)
        for column in range(3, 6):
            self.table.setItemDelegateForColumn(column, delegate)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        detail = QFormLayout()
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("先選擇一個請假狀態；備註可留空")
        self.note_button = QPushButton("套用請假備註")
        note_row = QHBoxLayout()
        note_row.addWidget(self.note_edit, 1)
        note_row.addWidget(self.note_button)
        detail.addRow("請假備註：", note_row)
        self.role_button = QPushButton("設定所選兼職可排時段的職務")
        detail.addRow("兼職職務限制：", self.role_button)
        layout.addLayout(detail)

        self.employee_combo.currentIndexChanged.connect(self._employee_changed)
        self.weekday_filter.currentIndexChanged.connect(self._filter_changed)
        self.state_filter.currentIndexChanged.connect(self._filter_changed)
        self.table.selectionModel().currentChanged.connect(self._current_changed)
        self.batch_apply_button.clicked.connect(self._apply_batch_state)
        self.all_day_leave_button.clicked.connect(
            lambda: self._apply_batch_all_day(True)
        )
        self.clear_all_day_button.clicked.connect(
            lambda: self._apply_batch_all_day(False)
        )
        self.note_button.clicked.connect(self._apply_note)
        self.role_button.clicked.connect(self._edit_available_roles)
        self.bind_draft(None)

    def bind_draft(self, draft: ScheduleDraft | None) -> None:
        selected_id = self.employee_combo.currentData()
        self._draft = draft
        self.employee_combo.blockSignals(True)
        self.employee_combo.clear()
        if draft is not None:
            for employee in draft.employees:
                category = (
                    employee.full_time_class.value
                    if employee.full_time_class is not None
                    else "兼職"
                )
                self.employee_combo.addItem(
                    f"{employee.name}（{category}）",
                    employee.employee_id,
                )
        index = self.employee_combo.findData(selected_id)
        if index < 0 and self.employee_combo.count():
            index = 0
        self.employee_combo.setCurrentIndex(index)
        self.employee_combo.blockSignals(False)
        self._employee_changed()

    def focus_employee(self, employee_index: int) -> None:
        if self._draft is None or not 0 <= employee_index < len(self._draft.employees):
            return
        employee_id = self._draft.employees[employee_index].employee_id
        index = self.employee_combo.findData(employee_id)
        if index >= 0:
            self.employee_combo.setCurrentIndex(index)

    def focus_record(self, record_type: str, index: int) -> None:
        if self._draft is None:
            return
        records = (
            self._draft.leave_requests
            if record_type == "leave_requests"
            else self._draft.unavailable_slots
        )
        if not 0 <= index < len(records):
            return
        record = records[index]
        self._reset_filters()
        employee_index = next(
            (
                position
                for position, employee in enumerate(self._draft.employees)
                if employee.employee_id == record.employee_id
            ),
            -1,
        )
        self.focus_employee(employee_index)
        row = (record.date - self._draft.start_date).days
        column = 2 if getattr(record, "all_day", False) else 3 + list(Period).index(record.period)
        cell = self.proxy_model.mapFromSource(self.model.index(row, column))
        self.table.setCurrentIndex(cell)
        self.table.scrollTo(cell)

    def focus_available_slot(self, employee_index: int, slot_index: int) -> None:
        if self._draft is None or not 0 <= employee_index < len(self._draft.employees):
            return
        employee = self._draft.employees[employee_index]
        if employee.available_slots is None or not 0 <= slot_index < len(employee.available_slots):
            return
        self.focus_employee(employee_index)
        slot = employee.available_slots[slot_index]
        self._reset_filters()
        row = (slot.date - self._draft.start_date).days
        column = 3 + list(Period).index(slot.period)
        cell = self.proxy_model.mapFromSource(self.model.index(row, column))
        self.table.setCurrentIndex(cell)
        self.table.scrollTo(cell)

    def _employee_changed(self) -> None:
        employee_id = self.employee_combo.currentData()
        self.model.set_context(self._draft, employee_id)
        employee = self.model.employee
        if employee is None:
            self.type_hint.setText("尚無員工資料")
            self.explanation.setText("請先到「員工資料」新增人員。")
        elif employee.employment_type is EmploymentType.FULL_TIME:
            self.type_hint.setText("正職／預設可排")
            self.explanation.setText(
                "正職所有時段預設可排；只需標記整日請假、個別時段請假或不可排。"
            )
        else:
            self.type_hint.setText("兼職／預設不可排")
            self.explanation.setText(
                "兼職所有時段預設不可排；只有明確改成「可排」的時段才會納入排班。"
            )
        self._update_context_actions(QModelIndex())

    def _filter_changed(self) -> None:
        self.proxy_model.set_weekday_filter(self.weekday_filter.currentData())
        self.proxy_model.set_state_filter(self.state_filter.currentData())

    def _model_changed(self) -> None:
        self._update_context_actions(self.table.currentIndex())
        self.draft_changed.emit()

    def _current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self._update_context_actions(current)

    def _update_context_actions(self, index: QModelIndex) -> None:
        index = self.proxy_model.mapToSource(index) if index.isValid() else index
        employee = self.model.employee
        day = self.model.date_at(index.row()) if index.isValid() else None
        period = self.model.period_at(index.column()) if index.isValid() else None
        leave = self._selected_leave(employee, day, period, index.column() if index.isValid() else -1)
        self.note_edit.setEnabled(leave is not None)
        self.note_button.setEnabled(leave is not None)
        self.note_edit.setText("" if leave is None else leave.note or "")
        slot = (
            None
            if employee is None or day is None or period is None or self._draft is None
            else self._draft.available_slot(employee, day, period)
        )
        self.role_button.setEnabled(
            employee is not None
            and employee.employment_type is EmploymentType.PART_TIME
            and slot is not None
        )

    def _selected_leave(
        self,
        employee: EmployeeDraft | None,
        day: date | None,
        period: Period | None,
        column: int,
    ) -> LeaveRequestDraft | None:
        if self._draft is None or employee is None or day is None:
            return None
        expected_period = None if column == 2 else period
        return next(
            (
                item
                for item in self._draft.leave_requests
                if item.employee_id == employee.employee_id
                and item.date == day
                and item.period is expected_period
            ),
            None,
        )

    def _apply_note(self) -> None:
        index = self._current_source_index()
        employee = self.model.employee
        day = self.model.date_at(index.row())
        period = self.model.period_at(index.column())
        if self._draft is None or employee is None or day is None:
            return
        try:
            self._draft.set_leave_note(
                employee.employee_id,
                day,
                None if index.column() == 2 else period,
                self.note_edit.text(),
            )
        except ValueError as error:
            show_warning(self, "無法設定備註", str(error))
            return
        self.draft_changed.emit()

    def _edit_available_roles(self) -> None:
        index = self._current_source_index()
        employee = self.model.employee
        day = self.model.date_at(index.row())
        period = self.model.period_at(index.column())
        if self._draft is None or employee is None or day is None or period is None:
            return
        slot = self._draft.available_slot(employee, day, period)
        if slot is None:
            return
        dialog = RoleRestrictionDialog(employee, slot.roles, self)
        if not dialog.exec():
            return
        try:
            self._draft.set_available_slot_roles(
                employee,
                day,
                period,
                dialog.selected_roles,
            )
        except ValueError as error:
            show_warning(self, "無法設定職務", str(error))
            return
        self.model.dataChanged.emit(index, index)
        self.draft_changed.emit()

    def _apply_batch_state(self) -> None:
        cells = {
            (source.row(), source.column())
            for index in self.table.selectionModel().selectedIndexes()
            if (source := self.proxy_model.mapToSource(index)).column() >= 3
        }
        if not cells:
            show_information(
                self,
                "尚未選擇時段",
                "請先選擇一個或多個早、午、晚時段儲存格。",
            )
            return
        changed, skipped = self.model.apply_period_state(
            cells,
            self.batch_state_combo.currentData(),
        )
        if not changed and skipped:
            show_information(
                self,
                "未套用變更",
                "所選時段皆為整日請假；請先取消整日請假。",
            )

    def _apply_batch_all_day(self, enabled: bool) -> None:
        rows = {
            self.proxy_model.mapToSource(index).row()
            for index in self.table.selectionModel().selectedIndexes()
        }
        if not rows:
            show_information(self, "尚未選擇日期", "請先選擇一個或多個日期。")
            return
        self.model.apply_all_day_leave(rows, enabled)

    def _current_source_index(self) -> QModelIndex:
        current = self.table.currentIndex()
        return self.proxy_model.mapToSource(current) if current.isValid() else current

    def _reset_filters(self) -> None:
        self.weekday_filter.setCurrentIndex(0)
        self.state_filter.setCurrentIndex(0)


class RoleRestrictionDialog(QDialog):
    def __init__(
        self,
        employee: EmployeeDraft,
        selected: list[str] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("兼職可排職務")
        layout = QVBoxLayout(self)
        self.unrestricted = QCheckBox("不限制（適用此員工全部職務資格）")
        self.unrestricted.setChecked(selected is None)
        layout.addWidget(self.unrestricted)
        self.role_checks: list[QCheckBox] = []
        for role in employee.roles:
            checkbox = QCheckBox(role)
            checkbox.setChecked(selected is not None and role in selected)
            layout.addWidget(checkbox)
            self.role_checks.append(checkbox)
        self.unrestricted.toggled.connect(self._toggle_restrictions)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        localize_dialog_buttons(buttons)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._toggle_restrictions(self.unrestricted.isChecked())

    @property
    def selected_roles(self) -> list[str] | None:
        if self.unrestricted.isChecked():
            return None
        return [item.text() for item in self.role_checks if item.isChecked()]

    def _toggle_restrictions(self, unrestricted: bool) -> None:
        for checkbox in self.role_checks:
            checkbox.setEnabled(not unrestricted)

    def _accept_if_valid(self) -> None:
        if self.selected_roles == []:
            show_warning(self, "請選擇職務", "至少選擇一項職務，或使用不限制。")
            return
        self.accept()
