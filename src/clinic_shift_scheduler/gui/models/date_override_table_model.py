"""Table model for month-specific opening and staffing overrides."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

from ...enums import PERIODS_V1, Period
from ..display_labels import role_display_name
from ..drafts import DateOverrideDraft, ScheduleDraft, StaffingDraft


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

    def remove_override(self, value: date) -> None:
        if self._draft is None:
            raise ValueError("請先建立或開啟月份")
        if not any(item.date == value for item in self._draft.date_overrides):
            raise ValueError(f"此日期沒有特定調整：{value.isoformat()}")
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
                return "開啟" if self._period_is_open(override, period) else "休診"
            if column == 1:
                return override.date.isoformat()
            if column == 2:
                return _PERIOD_LABELS[period]
            if not self._period_is_open(override, period):
                return "—"
            return override.staffing.counts[period][self._draft.roles[column - 3]]
        if role == Qt.ItemDataRole.EditRole and column >= 3:
            if self._period_is_open(override, period):
                return override.staffing.counts[period][self._draft.roles[column - 3]]
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return (
                Qt.CheckState.Checked
                if self._period_is_open(override, period)
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if column >= 3 and not self._period_is_open(override, period):
            if role == Qt.ItemDataRole.BackgroundRole:
                return QColor("#D5D8DC")
            if role == Qt.ItemDataRole.ForegroundRole:
                return QColor("#6B7280")
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == 0:
                return "只切換這一個時段；休診時該時段各職務需求皆為 0。"
            if column >= 3 and not self._period_is_open(override, period):
                return "此時段休診；請先開啟時段。"
            if column >= 3:
                return "單擊後依序切換 1、2、3 人。"
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
        period = PERIODS_V1[period_index]
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            is_open = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
            if self._period_is_open(override, period) == is_open:
                return False
            if is_open:
                if override.staffing is None:
                    override.staffing = StaffingDraft.zero(self._draft.roles)
                for role_name in self._draft.roles:
                    override.staffing.counts[period][role_name] = 1
                override.is_open = True
            else:
                assert override.staffing is not None
                for role_name in self._draft.roles:
                    override.staffing.counts[period][role_name] = 0
                if not any(
                    count > 0
                    for counts in override.staffing.counts.values()
                    for count in counts.values()
                ):
                    override.is_open = False
                    override.staffing = None
            self._draft.touch()
            first = self.index(index.row(), 0)
            last = self.index(index.row(), self.columnCount() - 1)
            self.dataChanged.emit(first, last)
            self.draft_changed.emit()
            return True
        if index.column() >= 3 and role == Qt.ItemDataRole.EditRole:
            if not self._period_is_open(override, period):
                return False
            try:
                count = int(value)
            except (TypeError, ValueError):
                return False
            if count < 1 or count > 3 or isinstance(value, bool):
                return False
            role_name = self._draft.roles[index.column() - 3]
            if override.staffing.counts[period][role_name] == count:
                return False
            override.staffing.counts[period][role_name] = count
            self._draft.touch()
            self.dataChanged.emit(index, index)
            self.draft_changed.emit()
            return True
        return False

    def cycle_count(self, index: QModelIndex) -> bool:
        if not index.isValid() or self._draft is None or index.column() < 3:
            return False
        current = self.data(index, Qt.ItemDataRole.EditRole)
        if not isinstance(current, int):
            return False
        return self.setData(
            index,
            1 if current >= 3 or current < 1 else current + 1,
            Qt.ItemDataRole.EditRole,
        )

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid() or self._draft is None:
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        override = self._draft.date_overrides[index.row() // len(PERIODS_V1)]
        period = PERIODS_V1[index.row() % len(PERIODS_V1)]
        if index.column() == 0:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        if index.column() >= 3:
            if not self._period_is_open(override, period):
                # Keep closed-period staffing cells fully locked so a click
                # cannot apply a selection background over the disabled gray.
                return Qt.ItemFlag.NoItemFlags
            return base
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
            return "時段開關"
        if section == 1:
            return "日期"
        if section == 2:
            return "時段"
        if self._draft is None:
            return None
        return role_display_name(self._draft.roles[section - 3])

    @staticmethod
    def _period_is_open(override: DateOverrideDraft, period: Period) -> bool:
        return bool(
            override.is_open
            and override.staffing is not None
            and any(override.staffing.counts[period].values())
        )
