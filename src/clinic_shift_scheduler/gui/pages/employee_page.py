from __future__ import annotations

from PySide6.QtCore import QItemSelection, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...enums import EmploymentType, FullTimeClass, ShiftMode
from ..dialogs import ask_yes_no, show_warning
from ..drafts import EmployeeDraft, ScheduleDraft
from ..field_location import FieldLocation
from ..models import EmployeeTableModel
from ..navigation import NAVIGATION_ITEMS, PageId
from .base import InputPage


_TYPE_OPTIONS = (("正職", EmploymentType.FULL_TIME), ("兼職", EmploymentType.PART_TIME))
_CLASS_OPTIONS = (("A 類", FullTimeClass.A), ("B 類", FullTimeClass.B))
_MODE_OPTIONS = (
    ("固定班次", ShiftMode.EXACT),
    ("班次範圍", ShiftMode.RANGE),
    ("目標班次", ShiftMode.TARGET),
)


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
        self._loading = False

        layout = QVBoxLayout()
        self.surface_layout.addLayout(layout, 1)
        actions = QHBoxLayout()
        self.add_button = QPushButton("新增員工")
        self.delete_button = QPushButton("刪除員工")
        actions.addWidget(self.add_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.inline_validation_label = QLabel()
        self.inline_validation_label.setObjectName("documentStatusDirty")
        self.inline_validation_label.setWordWrap(True)
        layout.addWidget(self.inline_validation_label)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableView()
        self.table.setAccessibleName("員工資料清單")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.model = EmployeeTableModel()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        splitter.addWidget(self.table)

        detail = QGroupBox("所選員工詳細資料")
        detail_layout = QHBoxLayout(detail)
        form = QFormLayout()
        self.employee_id_label = QLabel("—")
        self.name_edit = QLineEdit()
        self.type_combo = _combo(_TYPE_OPTIONS)
        self.class_combo = _combo(_CLASS_OPTIONS)
        self.fairness_edit = QLineEdit()
        self.mode_combo = _combo(_MODE_OPTIONS)
        form.addRow("員工 ID：", self.employee_id_label)
        form.addRow("姓名：", self.name_edit)
        form.addRow("聘用類別：", self.type_combo)
        form.addRow("正職類別：", self.class_combo)
        form.addRow("公平分組：", self.fairness_edit)
        form.addRow("班次模式：", self.mode_combo)
        detail_layout.addLayout(form, 2)

        middle = QVBoxLayout()
        roles_group = QGroupBox("職務資格")
        self.roles_layout = QVBoxLayout(roles_group)
        self.role_checks: list[QCheckBox] = []
        middle.addWidget(roles_group)
        shift_group = QGroupBox("班次條件")
        shift_form = QGridLayout(shift_group)
        self.required_spin = _shift_spin()
        self.target_spin = _shift_spin()
        self.min_enabled = QCheckBox("啟用最低班次")
        self.min_spin = _shift_spin()
        self.max_enabled = QCheckBox("啟用最高班次")
        self.max_spin = _shift_spin()
        shift_form.addWidget(QLabel("固定班次"), 0, 0)
        shift_form.addWidget(self.required_spin, 0, 1)
        shift_form.addWidget(QLabel("目標班次"), 1, 0)
        shift_form.addWidget(self.target_spin, 1, 1)
        shift_form.addWidget(self.min_enabled, 2, 0)
        shift_form.addWidget(self.min_spin, 2, 1)
        shift_form.addWidget(self.max_enabled, 3, 0)
        shift_form.addWidget(self.max_spin, 3, 1)
        middle.addWidget(shift_group)
        detail_layout.addLayout(middle, 2)

        notes_layout = QVBoxLayout()
        notes_layout.addWidget(QLabel("備註"))
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("可留空")
        notes_layout.addWidget(self.notes_edit, 1)
        detail_layout.addLayout(notes_layout, 2)
        splitter.addWidget(detail)
        splitter.setSizes([330, 310])
        layout.addWidget(splitter, 1)

        self.add_button.clicked.connect(self._add_employee)
        self.delete_button.clicked.connect(self._delete_employee)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.name_edit.editingFinished.connect(self._apply_text_fields)
        self.fairness_edit.editingFinished.connect(self._apply_text_fields)
        self.notes_edit.textChanged.connect(self._apply_text_fields)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.class_combo.currentIndexChanged.connect(self._class_changed)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.required_spin.valueChanged.connect(self._shift_values_changed)
        self.target_spin.valueChanged.connect(self._shift_values_changed)
        self.min_spin.valueChanged.connect(self._shift_values_changed)
        self.max_spin.valueChanged.connect(self._shift_values_changed)
        self.min_enabled.toggled.connect(self._shift_values_changed)
        self.max_enabled.toggled.connect(self._shift_values_changed)
        self.bind_draft(None)

    def bind_draft(self, draft: ScheduleDraft | None) -> None:
        selected_id = self._employee.employee_id if self._employee else None
        self._draft = draft
        self.model.set_draft(draft)
        self._rebuild_role_checks()
        row = self.model.row_for_employee_id(selected_id) if selected_id else -1
        if row < 0 and self.model.rowCount():
            row = 0
        if row >= 0:
            self.table.selectRow(row)
            self._load_employee(self.model.employee_at(row))
        else:
            self._load_employee(None)
        self.add_button.setEnabled(draft is not None)
        self._refresh_inline_validation()

    def focus_employee(self, employee_index: int) -> None:
        if 0 <= employee_index < self.model.rowCount():
            self.table.selectRow(employee_index)
            self.table.scrollTo(self.model.index(employee_index, 0))

    def focus_location(self, location: FieldLocation) -> None:
        if location.employee_index is not None:
            self.focus_employee(location.employee_index)
        widget_by_field = {
            "employee_id": self.table,
            "name": self.name_edit,
            "employment_type": self.type_combo,
            "full_time_class": self.class_combo,
            "roles": self.role_checks[0] if self.role_checks else self.table,
            "fairness_group": self.fairness_edit,
            "shift_mode": self.mode_combo,
            "required_shifts": self.required_spin,
            "target_shifts": self.target_spin,
            "min_shifts": self.min_spin,
            "max_shifts": self.max_spin,
            "notes": self.notes_edit,
        }
        target = widget_by_field.get(location.field, self.table)
        if not target.isEnabled() and location.field in {
            "required_shifts",
            "target_shifts",
            "min_shifts",
            "max_shifts",
        }:
            target = self.mode_combo
        target.setFocus()
        if isinstance(target, QLineEdit):
            target.selectAll()

    def _rebuild_role_checks(self) -> None:
        while self.roles_layout.count():
            item = self.roles_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.role_checks = []
        for role in (() if self._draft is None else self._draft.roles):
            checkbox = QCheckBox(role)
            checkbox.toggled.connect(self._roles_changed)
            self.roles_layout.addWidget(checkbox)
            self.role_checks.append(checkbox)
        self.roles_layout.addStretch(1)

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
        self._loading = True
        enabled = employee is not None
        self.delete_button.setEnabled(enabled)
        for widget in (
            self.name_edit,
            self.type_combo,
            self.class_combo,
            self.fairness_edit,
            self.mode_combo,
            self.required_spin,
            self.target_spin,
            self.min_enabled,
            self.min_spin,
            self.max_enabled,
            self.max_spin,
            self.notes_edit,
            *self.role_checks,
        ):
            widget.setEnabled(enabled)
        if employee is None:
            self.employee_id_label.setText("—")
            self.name_edit.clear()
            self.fairness_edit.clear()
            self.notes_edit.clear()
        else:
            self.employee_id_label.setText(employee.employee_id)
            self.name_edit.setText(employee.name)
            _select_data(self.type_combo, employee.employment_type)
            if employee.full_time_class is not None:
                _select_data(self.class_combo, employee.full_time_class)
            self.fairness_edit.setText(employee.fairness_group)
            _select_data(self.mode_combo, employee.shift_mode)
            for checkbox in self.role_checks:
                checkbox.setChecked(checkbox.text() in employee.roles)
            self.required_spin.setValue(employee.required_shifts or 0)
            self.target_spin.setValue(employee.target_shifts or 0)
            self.min_enabled.setChecked(employee.min_shifts is not None)
            self.min_spin.setValue(employee.min_shifts or 0)
            self.max_enabled.setChecked(employee.max_shifts is not None)
            self.max_spin.setValue(employee.max_shifts or 0)
            self.notes_edit.setPlainText(employee.notes or "")
        self._loading = False
        self._update_conditional_fields()
        self._refresh_inline_validation()

    def _add_employee(self) -> None:
        if self._draft is None:
            return
        employee = self._draft.add_employee()
        self.model.refresh()
        row = self.model.row_for_employee_id(employee.employee_id)
        self.table.selectRow(row)
        self._load_employee(employee)
        self._changed()

    def _delete_employee(self) -> None:
        if self._draft is None or self._employee is None:
            return
        if not ask_yes_no(
            self,
            "刪除員工",
            f"確定刪除「{self._employee.name}」？其休假、不可排與可排資料也會移除。",
        ):
            return
        self._draft.remove_employee(self._employee.employee_id)
        self._employee = None
        self.bind_draft(self._draft)
        self._changed()

    def _apply_text_fields(self) -> None:
        if self._loading or self._employee is None or self._draft is None:
            return
        employee = self._employee
        values = (
            self.name_edit.text(),
            self.fairness_edit.text(),
            self.notes_edit.toPlainText(),
        )
        if (employee.name, employee.fairness_group, employee.notes or "") == values:
            return
        employee.name = values[0]
        employee.fairness_group = values[1]
        employee.notes = values[2] or None
        employee.notes_declared = bool(values[2])
        self._draft.touch()
        self._changed()

    def _type_changed(self) -> None:
        if self._loading or self._employee is None or self._draft is None:
            return
        self._draft.set_employee_type(self._employee, self.type_combo.currentData())
        self._load_employee(self._employee)
        self._changed()

    def _class_changed(self) -> None:
        if self._loading or self._employee is None or self._draft is None:
            return
        value = self.class_combo.currentData()
        if self._employee.full_time_class is value:
            return
        self._employee.full_time_class = value
        self._employee.full_time_class_declared = True
        self._draft.touch()
        self._changed()

    def _mode_changed(self) -> None:
        if self._loading or self._employee is None or self._draft is None:
            return
        mode = self.mode_combo.currentData()
        if self._employee.shift_mode is not mode:
            try:
                self._draft.set_shift_mode(self._employee, mode)
            except ValueError as error:
                show_warning(self, "不支援的班次模式", str(error))
            self._load_employee(self._employee)
            self._changed()

    def _roles_changed(self) -> None:
        if self._loading or self._employee is None or self._draft is None:
            return
        selected = [item.text() for item in self.role_checks if item.isChecked()]
        if selected == self._employee.roles:
            return
        self._employee.roles = selected
        if self._employee.available_slots:
            for slot in self._employee.available_slots:
                if slot.roles is not None:
                    kept = [role for role in slot.roles if role in selected]
                    slot.roles = kept or None
        self._draft.touch()
        self._changed()

    def _shift_values_changed(self) -> None:
        if self._loading or self._employee is None or self._draft is None:
            return
        employee = self._employee
        if employee.shift_mode is ShiftMode.EXACT:
            employee.required_shifts = self.required_spin.value()
        elif employee.shift_mode is ShiftMode.RANGE:
            employee.min_shifts = self.min_spin.value()
            employee.max_shifts = self.max_spin.value()
        else:
            employee.target_shifts = self.target_spin.value()
            employee.min_shifts = self.min_spin.value() if self.min_enabled.isChecked() else None
            employee.max_shifts = self.max_spin.value() if self.max_enabled.isChecked() else None
        self._draft.touch()
        self._update_conditional_fields()
        self._changed()

    def _update_conditional_fields(self) -> None:
        employee = self._employee
        enabled = employee is not None
        full_time = enabled and employee.employment_type is EmploymentType.FULL_TIME
        self.class_combo.setEnabled(bool(full_time))
        target_allowed = bool(full_time)
        target_index = self.mode_combo.findData(ShiftMode.TARGET)
        self.mode_combo.model().item(target_index).setEnabled(target_allowed)
        mode = None if employee is None else employee.shift_mode
        self.required_spin.setEnabled(enabled and mode is ShiftMode.EXACT)
        self.target_spin.setEnabled(enabled and mode is ShiftMode.TARGET)
        range_mode = enabled and mode is ShiftMode.RANGE
        target_mode = enabled and mode is ShiftMode.TARGET
        self.min_enabled.setEnabled(bool(target_mode))
        self.max_enabled.setEnabled(bool(target_mode))
        self.min_spin.setEnabled(bool(range_mode or (target_mode and self.min_enabled.isChecked())))
        self.max_spin.setEnabled(bool(range_mode or (target_mode and self.max_enabled.isChecked())))

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
            if not employee.fairness_group.strip():
                messages.append("公平分組不可留空。")
            if not employee.roles:
                messages.append("至少選擇一項職務資格。")
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
            if draft is not None:
                signature = (employee.employment_type, employee.full_time_class)
                if any(
                    item.employee_id != employee.employee_id
                    and item.fairness_group == employee.fairness_group
                    and (item.employment_type, item.full_time_class) != signature
                    for item in draft.employees
                ):
                    messages.append("此公平分組已被不同聘用類別或 A／B 類別使用。")
        self.inline_validation_label.setText("　".join(messages))
        self.inline_validation_label.setVisible(bool(messages))


def _combo(options: tuple[tuple[str, object], ...]) -> QComboBox:
    combo = QComboBox()
    for label, value in options:
        combo.addItem(label, value)
    return combo


def _select_data(combo: QComboBox, value: object) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _shift_spin() -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 999)
    spin.setSuffix(" 節")
    return spin
