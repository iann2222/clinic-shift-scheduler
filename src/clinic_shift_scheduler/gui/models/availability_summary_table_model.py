"""Employee-row summaries for the simplified availability editors."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...enums import PERIODS_V1, EmploymentType, Period
from ..drafts import EmployeeDraft, ScheduleDraft


_PERIOD_LABELS = {
    Period.MORNING: "早",
    Period.AFTERNOON: "午",
    Period.EVENING: "晚",
}


class AvailabilitySummaryTableModel(QAbstractTableModel):
    def __init__(
        self,
        employment_type: EmploymentType,
        draft: ScheduleDraft | None = None,
    ) -> None:
        super().__init__()
        self._employment_type = employment_type
        self._draft = draft

    def set_draft(self, draft: ScheduleDraft | None) -> None:
        self.beginResetModel()
        self._draft = draft
        self.endResetModel()

    def refresh_row(self, row: int) -> None:
        if 0 <= row < self.rowCount():
            self.dataChanged.emit(
                self.index(row, 0),
                self.index(row, self.columnCount() - 1),
            )

    def employee_at(self, row: int) -> EmployeeDraft | None:
        employees = self._employees()
        return employees[row] if 0 <= row < len(employees) else None

    def row_for_employee_id(self, employee_id: str) -> int:
        return next(
            (
                index
                for index, employee in enumerate(self._employees())
                if employee.employee_id == employee_id
            ),
            -1,
        )

    def selected_periods(
        self,
        employee: EmployeeDraft,
        *,
        complement: bool = False,
    ) -> set[tuple[date, Period]]:
        if self._draft is None:
            return set()
        if self._employment_type is EmploymentType.FULL_TIME:
            return self._draft.unavailable_periods_for(employee)
        available = {
            (item.date, item.period)
            for item in employee.available_slots or []
        }
        return self._all_month_periods() - available if complement else available

    def replace_selected_periods(
        self,
        employee: EmployeeDraft,
        selected: set[tuple[date, Period]],
        *,
        complement: bool = False,
    ) -> None:
        if self._draft is None:
            return
        if self._employment_type is EmploymentType.FULL_TIME:
            self._draft.replace_full_time_unavailable_periods(employee, selected)
        else:
            available = (
                self._all_month_periods() - selected if complement else selected
            )
            self._draft.replace_part_time_available_periods(employee, available)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._employees())

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return 3 if self._employment_type is EmploymentType.PART_TIME else 2

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        employee = self.employee_at(index.row()) if index.isValid() else None
        if employee is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return employee.name
            return _format_periods(
                self.selected_periods(
                    employee,
                    complement=(
                        self._employment_type is EmploymentType.PART_TIME
                        and index.column() == 2
                    ),
                )
            )
        if role == Qt.ItemDataRole.UserRole:
            return employee.employee_id
        if role == Qt.ItemDataRole.ToolTipRole and index.column() >= 1:
            return "雙擊以編輯日期與早、午、晚時段。"
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == 0:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

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
        if section == 0:
            return "姓名"
        if self._employment_type is EmploymentType.FULL_TIME:
            return "不可排日期與時段"
        return "可排日期與時段" if section == 1 else "不可排日期與時段"

    def _employees(self) -> tuple[EmployeeDraft, ...]:
        if self._draft is None:
            return ()
        return tuple(
            employee
            for employee in self._draft.employees
            if employee.employment_type is self._employment_type
        )

    def _all_month_periods(self) -> set[tuple[date, Period]]:
        if self._draft is None:
            return set()
        return {
            (date.fromordinal(ordinal), period)
            for ordinal in range(
                self._draft.start_date.toordinal(),
                self._draft.end_date.toordinal() + 1,
            )
            for period in PERIODS_V1
        }


def _format_periods(selected: set[tuple[date, Period]]) -> str:
    if not selected:
        return "未設定"
    by_date: dict[date, set[Period]] = {}
    for day, period in selected:
        by_date.setdefault(day, set()).add(period)
    parts = []
    for day in sorted(by_date):
        labels = "、".join(
            _PERIOD_LABELS[period]
            for period in PERIODS_V1
            if period in by_date[day]
        )
        parts.append(f"{day.day} 號（{labels}）")
    return "、".join(parts)
