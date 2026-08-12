from __future__ import annotations

from PySide6.QtCore import QItemSelection, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...enums import EmploymentType, ShiftMode
from ..dialogs import EmployeeEditDialog, EmployeeEditorValues
from ..display_labels import role_display_name
from ..drafts import EmployeeDraft, ScheduleDraft
from ..field_location import FieldLocation
from ..models import EmployeeTableModel
from ..navigation import NAVIGATION_ITEMS, PageId
from .base import InputPage


class EmployeePage(InputPage):
    draft_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        item = next(
            item for item in NAVIGATION_ITEMS if item.page_id is PageId.EMPLOYEE
        )
        super().__init__(
            item.page_id,
            item.title,
            item.description,
            show_empty_state=False,
            parent=parent,
        )
        self._draft: ScheduleDraft | None = None
        self._employee: EmployeeDraft | None = None

        layout = QVBoxLayout()
        layout.setSpacing(12)
        self.surface_layout.addLayout(layout, 1)
        actions = QHBoxLayout()
        self.add_button = QPushButton("新增員工")
        actions.addWidget(self.add_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.inline_validation_label = QLabel()
        self.inline_validation_label.setObjectName("documentStatusDirty")
        self.inline_validation_label.setWordWrap(True)
        layout.addWidget(self.inline_validation_label)

        self.table = QTableView()
        self.table.setAccessibleName("員工資料清單")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.model = EmployeeTableModel()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 3)

        detail_header = QHBoxLayout()
        detail_title = QLabel("所選員工詳細資料")
        detail_title.setObjectName("sectionTitle")
        self.edit_button = QPushButton("編輯")
        detail_header.addWidget(detail_title)
        detail_header.addWidget(self.edit_button)
        detail_header.addStretch(1)
        layout.addSpacing(6)
        layout.addLayout(detail_header)

        detail = QGroupBox()
        detail.setObjectName("employeeReadOnlyDetail")
        detail_form = QFormLayout(detail)
        self.employee_id_label = QLabel("—")
        self.name_label = QLabel("—")
        self.type_label = QLabel("—")
        self.class_label = QLabel("—")
        self.roles_label = QLabel("—")
        self.mode_label = QLabel("—")
        self.shift_label = QLabel("—")
        self.notes_label = QLabel("—")
        self.notes_label.setWordWrap(True)
        detail_form.addRow("員工 ID：", self.employee_id_label)
        detail_form.addRow("姓名：", self.name_label)
        detail_form.addRow("聘用類別：", self.type_label)
        detail_form.addRow("正職類別：", self.class_label)
        detail_form.addRow("職務：", self.roles_label)
        detail_form.addRow("班次模式：", self.mode_label)
        detail_form.addRow("班次條件：", self.shift_label)
        detail_form.addRow("備註：", self.notes_label)
        layout.addWidget(detail, 2)

        self.add_button.clicked.connect(self._add_employee)
        self.edit_button.clicked.connect(self._edit_employee)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(self._edit_from_double_click)
        self.bind_draft(None)

    def bind_draft(self, draft: ScheduleDraft | None) -> None:
        selected_id = self._employee.employee_id if self._employee else None
        self._draft = draft
        self.model.set_draft(draft)
        row = self.model.row_for_employee_id(selected_id) if selected_id else -1
        if row < 0 and self.model.rowCount():
            row = 0
        if row >= 0:
            self.table.selectRow(row)
            self._load_employee(self.model.employee_at(row))
        else:
            self._load_employee(None)
        self.add_button.setEnabled(draft is not None)
        self.edit_button.setEnabled(self._employee is not None)
        self._refresh_inline_validation()

    def focus_employee(self, employee_index: int) -> None:
        if 0 <= employee_index < self.model.rowCount():
            self.table.selectRow(employee_index)
            self.table.scrollTo(self.model.index(employee_index, 0))

    def focus_location(self, location: FieldLocation) -> None:
        if location.employee_index is not None:
            self.focus_employee(location.employee_index)
        target = self.table if location.field == "employee_id" else self.edit_button
        target.setFocus()

    def _selection_changed(
        self,
        selected: QItemSelection,
        _deselected: QItemSelection,
    ) -> None:
        indexes = selected.indexes()
        if indexes:
            self._load_employee(self.model.employee_at(indexes[0].row()))

    def _load_employee(self, employee: EmployeeDraft | None) -> None:
        self._employee = employee
        enabled = employee is not None
        self.edit_button.setEnabled(enabled)
        if employee is None:
            self.employee_id_label.setText("—")
            for label in (
                self.name_label,
                self.type_label,
                self.class_label,
                self.roles_label,
                self.mode_label,
                self.shift_label,
                self.notes_label,
            ):
                label.setText("—")
        else:
            self.employee_id_label.setText(employee.employee_id)
            self.name_label.setText(employee.name)
            self.type_label.setText(
                "正職"
                if employee.employment_type is EmploymentType.FULL_TIME
                else "兼職"
            )
            self.class_label.setText(
                "—"
                if employee.full_time_class is None
                else f"{employee.full_time_class.value} 類"
            )
            self.roles_label.setText(
                "、".join(role_display_name(role) for role in employee.roles) or "—"
            )
            self.mode_label.setText(
                {
                    ShiftMode.EXACT: "固定班次",
                    ShiftMode.RANGE: "班次範圍",
                    ShiftMode.TARGET: "目標班次",
                }[employee.shift_mode]
            )
            self.shift_label.setText(_shift_summary(employee))
            self.notes_label.setText(employee.notes or "—")
        self._refresh_inline_validation()

    def _add_employee(self) -> None:
        if self._draft is None:
            return
        dialog = EmployeeEditDialog(self._draft.roles, parent=self)
        if not dialog.exec():
            return
        employee = self._draft.add_employee()
        self._apply_editor_values(employee, dialog.values)
        self.model.refresh()
        row = self.model.row_for_employee_id(employee.employee_id)
        self.table.selectRow(row)
        self._load_employee(employee)
        self._changed()

    def _edit_employee(self) -> None:
        if self._draft is None or self._employee is None:
            return
        employee_id = self._employee.employee_id
        dialog = EmployeeEditDialog(
            self._draft.roles,
            employee=self._employee,
            parent=self,
        )
        if not dialog.exec():
            return
        if dialog.delete_requested:
            self._draft.remove_employee(employee_id)
            self._employee = None
            self.bind_draft(self._draft)
        else:
            self._apply_editor_values(self._employee, dialog.values)
            self.model.refresh()
            self._load_employee(self._employee)
        self._changed()

    def _edit_from_double_click(self, index: QModelIndex) -> None:
        if index.isValid() and index.column() == 0:
            self._edit_employee()

    def _apply_editor_values(
        self,
        employee: EmployeeDraft,
        values: EmployeeEditorValues,
    ) -> None:
        assert self._draft is not None
        draft = self._draft
        previous_class = employee.full_time_class
        if employee.employment_type is not values.employment_type:
            draft.set_employee_type(employee, values.employment_type)
        if values.employment_type is EmploymentType.FULL_TIME:
            employee.full_time_class = values.full_time_class
            employee.full_time_class_declared = True
            if previous_class is not values.full_time_class:
                employee.fairness_group = f"{values.full_time_class.value}_GENERAL"
        employee.name = values.name
        employee.roles = list(values.roles)
        if employee.available_slots:
            for slot in employee.available_slots:
                if slot.roles is not None:
                    kept = [role for role in slot.roles if role in employee.roles]
                    slot.roles = kept or None
        if employee.shift_mode is not values.shift_mode:
            draft.set_shift_mode(employee, values.shift_mode)
        employee.required_shifts = values.required_shifts
        employee.target_shifts = values.target_shifts
        employee.min_shifts = values.min_shifts
        employee.max_shifts = values.max_shifts
        employee.notes = values.notes
        employee.notes_declared = values.notes is not None
        draft.touch()

    def _changed(self) -> None:
        self.model.refresh()
        self._refresh_inline_validation()
        self.draft_changed.emit()

    def _refresh_inline_validation(self) -> None:
        draft = self._draft
        employee = self._employee
        messages: list[str] = []
        if draft is not None and not draft.employees:
            messages.append("至少需要新增一位員工。")
        if employee is not None:
            if not employee.name.strip():
                messages.append("姓名不可留空。")
            if not employee.roles:
                messages.append("至少選擇一項職務。")
            if (
                employee.min_shifts is not None
                and employee.max_shifts is not None
                and employee.min_shifts > employee.max_shifts
            ):
                messages.append("最低班次不可大於最高班次。")
            if employee.shift_mode is ShiftMode.TARGET:
                target = employee.target_shifts or 0
                if employee.min_shifts is not None and employee.min_shifts > target:
                    messages.append("最低班次不可大於目標班次。")
                if employee.max_shifts is not None and target > employee.max_shifts:
                    messages.append("目標班次不可大於最高班次。")
        self.inline_validation_label.setText("　".join(messages))
        self.inline_validation_label.setVisible(bool(messages))


def _shift_summary(employee: EmployeeDraft) -> str:
    if employee.shift_mode is ShiftMode.EXACT:
        return f"{employee.required_shifts or 0} 節"
    if employee.shift_mode is ShiftMode.RANGE:
        return f"{employee.min_shifts or 0}～{employee.max_shifts or 0} 節"
    bounds: list[str] = []
    if employee.min_shifts is not None:
        bounds.append(f"最低 {employee.min_shifts}")
    if employee.max_shifts is not None:
        bounds.append(f"最高 {employee.max_shifts}")
    suffix = f"（{'、'.join(bounds)}）" if bounds else ""
    return f"目標 {employee.target_shifts or 0} 節{suffix}"
