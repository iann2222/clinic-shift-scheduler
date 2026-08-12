"""Read-only employee summary model backed by the mutable schedule draft."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...enums import EmploymentType, ShiftMode
from ..drafts import EmployeeDraft, ScheduleDraft


_TYPE_LABELS = {
    EmploymentType.FULL_TIME: "正職",
    EmploymentType.PART_TIME: "兼職",
}
_MODE_LABELS = {
    ShiftMode.EXACT: "固定班次",
    ShiftMode.RANGE: "班次範圍",
    ShiftMode.TARGET: "目標班次",
}
_HEADERS = (
    "姓名",
    "類別",
    "A／B 類",
    "職務資格",
    "公平分組",
    "班次模式",
    "班次條件",
)


class EmployeeTableModel(QAbstractTableModel):
    def __init__(self, draft: ScheduleDraft | None = None) -> None:
        super().__init__()
        self._draft = draft

    def set_draft(self, draft: ScheduleDraft | None) -> None:
        self.beginResetModel()
        self._draft = draft
        self.endResetModel()

    def refresh(self) -> None:
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
            )

    def employee_at(self, row: int) -> EmployeeDraft | None:
        if self._draft is None or not 0 <= row < len(self._draft.employees):
            return None
        return self._draft.employees[row]

    def row_for_employee_id(self, employee_id: str) -> int:
        if self._draft is None:
            return -1
        return next(
            (
                index
                for index, employee in enumerate(self._draft.employees)
                if employee.employee_id == employee_id
            ),
            -1,
        )

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._draft is None:
            return 0
        return len(self._draft.employees)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_HEADERS)

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        employee = self.employee_at(index.row()) if index.isValid() else None
        if employee is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                employee.name,
                _TYPE_LABELS[employee.employment_type],
                "—" if employee.full_time_class is None else employee.full_time_class.value,
                "、".join(employee.roles),
                employee.fairness_group,
                _MODE_LABELS[employee.shift_mode],
                _shift_summary(employee),
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            return employee.employee_id
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (1, 2, 5, 6):
            return Qt.AlignmentFlag.AlignCenter
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return _HEADERS[section]


def _shift_summary(employee: EmployeeDraft) -> str:
    if employee.shift_mode is ShiftMode.EXACT:
        return f"{employee.required_shifts or 0} 節"
    if employee.shift_mode is ShiftMode.RANGE:
        return f"{employee.min_shifts or 0}～{employee.max_shifts or 0} 節"
    bounds = []
    if employee.min_shifts is not None:
        bounds.append(f"最低 {employee.min_shifts}")
    if employee.max_shifts is not None:
        bounds.append(f"最高 {employee.max_shifts}")
    suffix = f"（{'、'.join(bounds)}）" if bounds else ""
    return f"目標 {employee.target_shifts or 0} 節{suffix}"
