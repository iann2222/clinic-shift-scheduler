"""Table model for weekly opening rules and dynamic role requirements."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal

from ...enums import PERIODS_V1, Period, Weekday
from ..drafts import ScheduleDraft, StaffingDraft


_WEEKDAY_LABELS = {
    Weekday.MONDAY: "星期一",
    Weekday.TUESDAY: "星期二",
    Weekday.WEDNESDAY: "星期三",
    Weekday.THURSDAY: "星期四",
    Weekday.FRIDAY: "星期五",
    Weekday.SATURDAY: "星期六",
    Weekday.SUNDAY: "星期日",
}
_PERIOD_LABELS = {
    Period.MORNING: "早上",
    Period.AFTERNOON: "下午",
    Period.EVENING: "晚上",
}
_WEEKDAYS = (
    Weekday.MONDAY,
    Weekday.TUESDAY,
    Weekday.WEDNESDAY,
    Weekday.THURSDAY,
    Weekday.FRIDAY,
)


class WeeklyDemandTableModel(QAbstractTableModel):
    draft_changed = Signal()

    def __init__(self, draft: ScheduleDraft | None = None) -> None:
        super().__init__()
        self._draft = draft

    def set_draft(self, draft: ScheduleDraft | None) -> None:
        self.beginResetModel()
        self._draft = draft
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._draft is None:
            return 0
        return len(self._draft.weekly_demands) * len(PERIODS_V1)

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
        rule_index, period_index = divmod(index.row(), len(PERIODS_V1))
        rule = self._draft.weekly_demands[rule_index]
        period = PERIODS_V1[period_index]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return self._weekday_group_label(rule.weekdays)
            if column == 1:
                return "開診" if rule.is_open else "休診"
            if column == 2:
                return _PERIOD_LABELS[period]
            if not rule.is_open or rule.staffing is None:
                return "—"
            return rule.staffing.counts[period][self._draft.roles[column - 3]]
        if role == Qt.ItemDataRole.EditRole and column >= 3:
            if not rule.is_open or rule.staffing is None:
                return None
            return rule.staffing.counts[period][self._draft.roles[column - 3]]
        if role == Qt.ItemDataRole.CheckStateRole and column == 1:
            return (
                Qt.CheckState.Checked
                if rule.is_open
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.TextAlignmentRole and column >= 1:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == 1:
                return "切換後會同時套用此日期類型的早、午、晚。"
            if column >= 3 and not rule.is_open:
                return "休診時不使用人力需求數值。"
        return None

    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if not index.isValid() or self._draft is None:
            return False
        rule_index, period_index = divmod(index.row(), len(PERIODS_V1))
        rule = self._draft.weekly_demands[rule_index]
        if index.column() == 1 and role == Qt.ItemDataRole.CheckStateRole:
            is_open = value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked
            if rule.is_open == is_open:
                return False
            rule.is_open = is_open
            rule.staffing = StaffingDraft.zero(self._draft.roles) if is_open else None
            self._draft.touch()
            first = self.index(rule_index * 3, 1)
            last = self.index(rule_index * 3 + 2, self.columnCount() - 1)
            self.dataChanged.emit(first, last)
            self.draft_changed.emit()
            return True
        if index.column() >= 3 and role == Qt.ItemDataRole.EditRole:
            if not rule.is_open or rule.staffing is None:
                return False
            try:
                count = int(value)
            except (TypeError, ValueError):
                return False
            if count < 0 or isinstance(value, bool):
                return False
            period = PERIODS_V1[period_index]
            role_name = self._draft.roles[index.column() - 3]
            if rule.staffing.counts[period][role_name] == count:
                return False
            rule.staffing.counts[period][role_name] = count
            self._draft.touch()
            self.dataChanged.emit(index, index)
            self.draft_changed.emit()
            return True
        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid() or self._draft is None:
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        rule_index = index.row() // len(PERIODS_V1)
        rule = self._draft.weekly_demands[rule_index]
        if index.column() == 1:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        if index.column() >= 3:
            if not rule.is_open:
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
            return "日期類型"
        if section == 1:
            return "營業"
        if section == 2:
            return "時段"
        if self._draft is None:
            return None
        return self._draft.roles[section - 3]

    @staticmethod
    def _weekday_group_label(weekdays: list[Weekday]) -> str:
        values = tuple(weekdays)
        if values == _WEEKDAYS:
            return "平日"
        if values == (Weekday.SATURDAY,):
            return "星期六"
        if values == (Weekday.SUNDAY,):
            return "星期日"
        return "、".join(_WEEKDAY_LABELS[item] for item in values)
