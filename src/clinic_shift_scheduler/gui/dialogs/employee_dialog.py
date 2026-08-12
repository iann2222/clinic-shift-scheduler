"""Modal employee editor that commits only validated values."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...enums import EmploymentType, FullTimeClass, ShiftMode
from ..display_labels import role_display_name
from ..drafts import EmployeeDraft
from ..widgets import UnitInput, VisibleCheckBox
from .localized_dialogs import ask_yes_no, localize_dialog_buttons, show_warning


_TYPE_OPTIONS = (
    ("正職", EmploymentType.FULL_TIME),
    ("兼職", EmploymentType.PART_TIME),
)
_CLASS_OPTIONS = (("A 類", FullTimeClass.A), ("B 類", FullTimeClass.B))
_MODE_OPTIONS = (
    ("固定班次", ShiftMode.EXACT),
    ("班次範圍", ShiftMode.RANGE),
    ("目標班次", ShiftMode.TARGET),
)


@dataclass(frozen=True, slots=True)
class EmployeeEditorValues:
    name: str
    employment_type: EmploymentType
    full_time_class: FullTimeClass | None
    roles: tuple[str, ...]
    shift_mode: ShiftMode
    required_shifts: int | None
    target_shifts: int | None
    min_shifts: int | None
    max_shifts: int | None
    notes: str | None


class EmployeeEditDialog(QDialog):
    def __init__(
        self,
        roles: list[str],
        *,
        employee: EmployeeDraft | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._employee = employee
        self.delete_requested = False
        self.setWindowTitle(
            "新增員工" if employee is None else f"編輯員工－{employee.name}"
        )
        self.setModal(True)
        self.setMinimumWidth(530)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.employee_id_label = QLabel(
            "儲存後自動產生" if employee is None else employee.employee_id
        )
        self.name_edit = QLineEdit()
        self.type_combo = _combo(_TYPE_OPTIONS)
        self.class_combo = _combo(_CLASS_OPTIONS)
        self.mode_combo = _combo(_MODE_OPTIONS)
        form.addRow("員工 ID：", self.employee_id_label)
        form.addRow("姓名：", self.name_edit)
        form.addRow("聘用類別：", self.type_combo)
        form.addRow("正職類別：", self.class_combo)
        form.addRow("班次模式：", self.mode_combo)
        layout.addLayout(form)

        roles_group = QGroupBox("職務")
        roles_layout = QHBoxLayout(roles_group)
        self.role_checks: list[VisibleCheckBox] = []
        for role in roles:
            checkbox = VisibleCheckBox(role_display_name(role))
            checkbox.setProperty("role_key", role)
            roles_layout.addWidget(checkbox)
            self.role_checks.append(checkbox)
        roles_layout.addStretch(1)
        layout.addWidget(roles_group)

        shift_group = QGroupBox("班次條件")
        self.shift_form = QFormLayout(shift_group)
        self.required_spin = _shift_spin()
        self.target_spin = _shift_spin()
        self.min_enabled = VisibleCheckBox("啟用最低班次")
        self.min_spin = _shift_spin()
        self.max_enabled = VisibleCheckBox("啟用最高班次")
        self.max_spin = _shift_spin()
        self.required_field = UnitInput(self.required_spin, "節")
        self.target_field = UnitInput(self.target_spin, "節")
        self.shift_form.addRow("固定班次：", self.required_field)
        self.shift_form.addRow("目標班次：", self.target_field)
        self.minimum_row = QWidget()
        minimum_layout = QHBoxLayout(self.minimum_row)
        minimum_layout.setContentsMargins(0, 0, 0, 0)
        minimum_layout.addWidget(self.min_enabled)
        self.min_field = UnitInput(self.min_spin, "節")
        minimum_layout.addWidget(self.min_field)
        self.shift_form.addRow("最低班次：", self.minimum_row)
        self.maximum_row = QWidget()
        maximum_layout = QHBoxLayout(self.maximum_row)
        maximum_layout.setContentsMargins(0, 0, 0, 0)
        maximum_layout.addWidget(self.max_enabled)
        self.max_field = UnitInput(self.max_spin, "節")
        maximum_layout.addWidget(self.max_field)
        self.shift_form.addRow("最高班次：", self.maximum_row)
        layout.addWidget(shift_group)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("可留空")
        self.notes_edit.setMaximumHeight(80)
        layout.addWidget(QLabel("備註"))
        layout.addWidget(self.notes_edit)

        action_row = QHBoxLayout()
        if employee is not None:
            self.delete_button = QPushButton("刪除此員工")
            self.delete_button.setObjectName("destructiveButton")
            self.delete_button.clicked.connect(self._request_delete)
            action_row.addWidget(self.delete_button)
        action_row.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        localize_dialog_buttons(buttons)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        action_row.addWidget(buttons)
        layout.addLayout(action_row)

        self.type_combo.currentIndexChanged.connect(self._update_conditional_fields)
        self.mode_combo.currentIndexChanged.connect(self._update_conditional_fields)
        self.min_enabled.toggled.connect(self._update_conditional_fields)
        self.max_enabled.toggled.connect(self._update_conditional_fields)
        self._load(employee, roles)

    @property
    def values(self) -> EmployeeEditorValues:
        employment_type = EmploymentType(self.type_combo.currentData())
        shift_mode = ShiftMode(self.mode_combo.currentData())
        return EmployeeEditorValues(
            name=self.name_edit.text().strip(),
            employment_type=employment_type,
            full_time_class=(
                FullTimeClass(self.class_combo.currentData())
                if employment_type is EmploymentType.FULL_TIME
                else None
            ),
            roles=tuple(
                checkbox.property("role_key")
                for checkbox in self.role_checks
                if checkbox.isChecked()
            ),
            shift_mode=shift_mode,
            required_shifts=(
                self.required_spin.value()
                if shift_mode is ShiftMode.EXACT
                else None
            ),
            target_shifts=(
                self.target_spin.value()
                if shift_mode is ShiftMode.TARGET
                else None
            ),
            min_shifts=(
                self.min_spin.value()
                if shift_mode is ShiftMode.RANGE
                or (shift_mode is ShiftMode.TARGET and self.min_enabled.isChecked())
                else None
            ),
            max_shifts=(
                self.max_spin.value()
                if shift_mode is ShiftMode.RANGE
                or (shift_mode is ShiftMode.TARGET and self.max_enabled.isChecked())
                else None
            ),
            notes=self.notes_edit.toPlainText().strip() or None,
        )

    def _load(self, employee: EmployeeDraft | None, roles: list[str]) -> None:
        if employee is None:
            selected_roles = roles[:1]
            self.name_edit.setText("")
            self.required_spin.setValue(0)
        else:
            selected_roles = employee.roles
            self.name_edit.setText(employee.name)
            _select_data(self.type_combo, employee.employment_type)
            if employee.full_time_class is not None:
                _select_data(self.class_combo, employee.full_time_class)
            _select_data(self.mode_combo, employee.shift_mode)
            self.required_spin.setValue(employee.required_shifts or 0)
            self.target_spin.setValue(employee.target_shifts or 0)
            self.min_enabled.setChecked(employee.min_shifts is not None)
            self.min_spin.setValue(employee.min_shifts or 0)
            self.max_enabled.setChecked(employee.max_shifts is not None)
            self.max_spin.setValue(employee.max_shifts or 0)
            self.notes_edit.setPlainText(employee.notes or "")
        for checkbox in self.role_checks:
            checkbox.setChecked(checkbox.property("role_key") in selected_roles)
        self._update_conditional_fields()

    def _update_conditional_fields(self) -> None:
        full_time = (
            EmploymentType(self.type_combo.currentData())
            is EmploymentType.FULL_TIME
        )
        self.class_combo.setEnabled(full_time)
        target_index = self.mode_combo.findData(ShiftMode.TARGET)
        self.mode_combo.model().item(target_index).setEnabled(full_time)
        if (
            not full_time
            and ShiftMode(self.mode_combo.currentData()) is ShiftMode.TARGET
        ):
            _select_data(self.mode_combo, ShiftMode.RANGE)
        mode = ShiftMode(self.mode_combo.currentData())
        exact_mode = mode is ShiftMode.EXACT
        range_mode = mode is ShiftMode.RANGE
        target_mode = mode is ShiftMode.TARGET
        self.shift_form.setRowVisible(self.required_field, exact_mode)
        self.shift_form.setRowVisible(self.target_field, target_mode)
        self.shift_form.setRowVisible(self.minimum_row, range_mode or target_mode)
        self.shift_form.setRowVisible(self.maximum_row, range_mode or target_mode)
        self.min_enabled.setVisible(target_mode)
        self.max_enabled.setVisible(target_mode)
        self.required_field.setEnabled(exact_mode)
        self.target_field.setEnabled(target_mode)
        self.min_enabled.setEnabled(target_mode)
        self.max_enabled.setEnabled(target_mode)
        self.min_field.setEnabled(
            range_mode or (target_mode and self.min_enabled.isChecked())
        )
        self.max_field.setEnabled(
            range_mode or (target_mode and self.max_enabled.isChecked())
        )

    def _validate_and_accept(self) -> None:
        values = self.values
        issues: list[str] = []
        if not values.name:
            issues.append("姓名不可留空。")
        if not values.roles:
            issues.append("至少選擇一項職務。")
        if (
            values.min_shifts is not None
            and values.max_shifts is not None
            and values.min_shifts > values.max_shifts
        ):
            issues.append("最低班次不可大於最高班次。")
        if values.shift_mode is ShiftMode.TARGET:
            target = values.target_shifts or 0
            if values.min_shifts is not None and values.min_shifts > target:
                issues.append("最低班次不可大於目標班次。")
            if values.max_shifts is not None and target > values.max_shifts:
                issues.append("目標班次不可大於最高班次。")
        if issues:
            show_warning(self, "員工資料尚未完成", "\n".join(issues))
            return
        self.accept()

    def _request_delete(self) -> None:
        assert self._employee is not None
        if ask_yes_no(
            self,
            "刪除員工",
            f"確定刪除「{self._employee.name}」？其休假、不可排與可排資料也會移除。",
        ):
            self.delete_requested = True
            self.accept()


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
    return spin
