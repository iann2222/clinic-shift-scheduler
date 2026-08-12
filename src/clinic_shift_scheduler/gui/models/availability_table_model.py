"""Date-by-period availability editor for one selected employee."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)

from ...enums import PERIODS_V1, EmploymentType, Period
from ..drafts import EmployeeDraft, ScheduleDraft


AVAILABILITY_LABELS = {
    "available": "可排",
    "unavailable": "不可排",
    "leave": "請假",
}
_HEADERS = ("日期", "星期", "整日請假", "早上", "下午", "晚上")
_WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")


class AvailabilityTableModel(QAbstractTableModel):
    draft_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._draft: ScheduleDraft | None = None
        self._employee: EmployeeDraft | None = None
        self._dates: tuple[date, ...] = ()

    @property
    def employee(self) -> EmployeeDraft | None:
        return self._employee

    def set_context(
        self,
        draft: ScheduleDraft | None,
        employee_id: str | None,
    ) -> None:
        self.beginResetModel()
        self._draft = draft
        self._employee = None
        self._dates = ()
        if draft is not None:
            self._dates = _date_range(draft.start_date, draft.end_date)
            self._employee = next(
                (
                    item
                    for item in draft.employees
                    if item.employee_id == employee_id
                ),
                None,
            )
        self.endResetModel()

    def date_at(self, row: int) -> date | None:
        return self._dates[row] if 0 <= row < len(self._dates) else None

    def period_at(self, column: int) -> Period | None:
        return PERIODS_V1[column - 3] if 3 <= column < 6 else None

    def apply_period_state(
        self,
        cells: set[tuple[int, int]],
        state: str,
    ) -> tuple[int, int]:
        if self._draft is None or self._employee is None:
            return 0, len(cells)
        changed = 0
        skipped = 0
        changed_rows: set[int] = set()
        for row, column in sorted(cells):
            day = self.date_at(row)
            period = self.period_at(column)
            if day is None or period is None or self._all_day_leave(day):
                skipped += 1
                continue
            current = self._draft.availability_state(self._employee, day, period)
            if current == state:
                continue
            self._draft.set_period_availability(
                self._employee.employee_id,
                day,
                period,
                state,
            )
            changed += 1
            changed_rows.add(row)
        for row in changed_rows:
            self.dataChanged.emit(self.index(row, 3), self.index(row, 5))
        if changed:
            self.draft_changed.emit()
        return changed, skipped

    def apply_all_day_leave(
        self,
        rows: set[int],
        enabled: bool,
    ) -> int:
        if self._draft is None or self._employee is None:
            return 0
        changed = 0
        for row in sorted(rows):
            day = self.date_at(row)
            if day is None or self._all_day_leave(day) == enabled:
                continue
            self._draft.set_all_day_leave(
                self._employee.employee_id,
                day,
                enabled,
            )
            self.dataChanged.emit(self.index(row, 2), self.index(row, 5))
            changed += 1
        if changed:
            self.draft_changed.emit()
        return changed

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() or self._employee is None else len(self._dates)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_HEADERS)

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if (
            not index.isValid()
            or self._draft is None
            or self._employee is None
        ):
            return None
        value = self._dates[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return value.isoformat()
            if column == 1:
                return _WEEKDAY_LABELS[value.weekday()]
            if column == 2:
                return "請假" if self._all_day_leave(value) else "—"
            period = self.period_at(column)
            assert period is not None
            state = self._draft.availability_state(self._employee, value, period)
            label = AVAILABILITY_LABELS[state]
            if (
                state == "available"
                and self._employee.employment_type is EmploymentType.PART_TIME
            ):
                slot = self._draft.available_slot(self._employee, value, period)
                if slot is not None and slot.roles is not None:
                    return f"{label}（{'、'.join(slot.roles)}）"
            return label
        if role == Qt.ItemDataRole.EditRole and column >= 3:
            period = self.period_at(column)
            assert period is not None
            return self._draft.availability_state(self._employee, value, period)
        if role == Qt.ItemDataRole.CheckStateRole and column == 2:
            return (
                Qt.CheckState.Checked
                if self._all_day_leave(value)
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ToolTipRole and column >= 3:
            if self._all_day_leave(value):
                return "整日請假優先；取消整日請假後才能調整個別時段。"
            if self._employee.employment_type is EmploymentType.FULL_TIME:
                return "正職預設可排，可改為不可排或請假。"
            return "兼職預設不可排，只有明確標記可排的時段才可安排。"
        return None

    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if (
            not index.isValid()
            or self._draft is None
            or self._employee is None
        ):
            return False
        day = self._dates[index.row()]
        if index.column() == 2 and role == Qt.ItemDataRole.CheckStateRole:
            enabled = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
            if self._all_day_leave(day) == enabled:
                return False
            self._draft.set_all_day_leave(
                self._employee.employee_id,
                day,
                enabled,
            )
            self.dataChanged.emit(self.index(index.row(), 2), self.index(index.row(), 5))
            self.draft_changed.emit()
            return True
        if index.column() >= 3 and role == Qt.ItemDataRole.EditRole:
            if self._all_day_leave(day) or value not in AVAILABILITY_LABELS:
                return False
            period = self.period_at(index.column())
            assert period is not None
            current = self._draft.availability_state(self._employee, day, period)
            if current == value:
                return False
            self._draft.set_period_availability(
                self._employee.employee_id,
                day,
                period,
                str(value),
            )
            self.dataChanged.emit(index, index)
            self.draft_changed.emit()
            return True
        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid() or self._employee is None:
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 2:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        if index.column() >= 3:
            if self._all_day_leave(self._dates[index.row()]):
                return Qt.ItemFlag.ItemIsSelectable
            return base | Qt.ItemFlag.ItemIsEditable
        return base

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

    def _all_day_leave(self, value: date) -> bool:
        assert self._draft is not None and self._employee is not None
        return any(
            item.employee_id == self._employee.employee_id
            and item.date == value
            and item.all_day
            for item in self._draft.leave_requests
        )


def _date_range(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    )


class AvailabilityFilterProxyModel(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self._weekday: int | None = None
        self._state: str | None = None

    def set_weekday_filter(self, weekday: int | None) -> None:
        self._weekday = weekday
        self.invalidateFilter()

    def set_state_filter(self, state: str | None) -> None:
        self._state = state
        self.invalidateFilter()

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex,
    ) -> bool:
        source = self.sourceModel()
        if not isinstance(source, AvailabilityTableModel):
            return True
        day = source.date_at(source_row)
        if day is None:
            return False
        if self._weekday is not None and day.weekday() != self._weekday:
            return False
        if self._state is None:
            return True
        if self._state == "leave" and source._all_day_leave(day):
            return True
        return any(
            source.data(
                source.index(source_row, column, source_parent),
                Qt.ItemDataRole.EditRole,
            )
            == self._state
            for column in range(3, 6)
        )
