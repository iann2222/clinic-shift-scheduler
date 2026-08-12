"""Table model for month-specific opening and staffing overrides."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from ...enums import PERIODS_V1, Period
from ..drafts import ScheduleDraft, StaffingDraft


_PERIOD_LABELS = {
    Period.MORNING: "早上",
    Period.AFTERNOON: "下午",
    Period.EVENING: "晚上",
}


class DateOverrideTableModel(QAbstractTableModel):
    draft_changed = Signal()

    def __init__(self, draft: ScheduleDraft | None = None) -> None:
        super().__init__()
        self._draft = draft

    def set_draft(self, draft: ScheduleDraft | None) -> None:
        self.beginResetModel()
        self._draft = draft
        self.endResetModel()

    def add_override(self, value: date, *, is_open: bool) -> None:
        if self._draft is None:
            raise ValueError("請先建立或開啟月份")
        self.beginResetModel()
        try:
            self._draft.add_date_override(value, is_open=is_open)
        finally:
            self.endResetModel()
        self.draft_changed.emit()

    def remove_override_at(self, row: int) -> None:
        if self._draft is None or not 0 <= row < self.rowCount():
            raise ValueError("請先選擇要移除的日期")
        value = self._draft.date_overrides[row // len(PERIODS_V1)].date
        self.beginResetModel()
        try:
            self._draft.remove_date_override(value)
        finally:
            self.endResetModel()
        self.draft_changed.emit()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._draft is None:
            return 0
        return len(self._draft.date_overrides) * len(PERIODS_V1)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return 3 + (0 if self._draft is None else len(self._draft.roles))

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or self._draft is None:
            return None
        override_index, period_index = divmod(index.row(), len(PERIODS_V1))
        override = self._draft.date_overrides[override_index]
        period = PERIODS_V1[period_index]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return override.date.isoformat()
            if column == 1:
                return "開診" if override.is_open else "休診"
            if column == 2:
                return _PERIOD_LABELS[period]
            if not override.is_open or override.staffing is None:
                return "—"
            return override.staffing.counts[period][self._draft.roles[column - 3]]
        if role == Qt.ItemDataRole.EditRole and column >= 3:
            if override.is_open and override.staffing is not None:
                return override.staffing.counts[period][self._draft.roles[column - 3]]
        if role == Qt.ItemDataRole.CheckStateRole and column == 1:
            return (
                Qt.CheckState.Checked
                if override.is_open
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.TextAlignmentRole and column >= 1:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == 1:
                return "同一日期的三個時段會一起切換為開診或休診。"
            if column >= 3 and not override.is_open:
                return "休診調整不需要填寫人力需求。"
        return None

    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if not index.isValid() or self._draft is None:
            return False
        override_index, period_index = divmod(index.row(), len(PERIODS_V1))
        override = self._draft.date_overrides[override_index]
        if index.column() == 1 and role == Qt.ItemDataRole.CheckStateRole:
            is_open = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
            if override.is_open == is_open:
                return False
            override.is_open = is_open
            override.staffing = (
                StaffingDraft.zero(self._draft.roles) if is_open else None
            )
            self._draft.touch()
            first = self.index(override_index * 3, 1)
            last = self.index(override_index * 3 + 2, self.columnCount() - 1)
            self.dataChanged.emit(first, last)
            self.draft_changed.emit()
            return True
        if index.column() >= 3 and role == Qt.ItemDataRole.EditRole:
            if not override.is_open or override.staffing is None:
                return False
            try:
                count = int(value)
            except (TypeError, ValueError):
                return False
            if count < 0 or isinstance(value, bool):
                return False
            period = PERIODS_V1[period_index]
            role_name = self._draft.roles[index.column() - 3]
            if override.staffing.counts[period][role_name] == count:
                return False
            override.staffing.counts[period][role_name] = count
            self._draft.touch()
            self.dataChanged.emit(index, index)
            self.draft_changed.emit()
            return True
        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid() or self._draft is None:
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        override = self._draft.date_overrides[index.row() // len(PERIODS_V1)]
        if index.column() == 1:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        if index.column() >= 3:
            if not override.is_open:
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
        if section == 0:
            return "日期"
        if section == 1:
            return "調整"
        if section == 2:
            return "時段"
        if self._draft is None:
            return None
        return self._draft.roles[section - 3]
