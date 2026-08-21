"""Table model for weekly opening rules and dynamic role requirements."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

from ...enums import PERIODS_V1, Period, Weekday
from ..display_labels import role_display_name
from ..drafts import ScheduleDraft, StaffingDraft, WeeklyDemandDraft


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
                return "開啟" if self._period_is_open(rule, period) else "休診"
            if column == 1:
                return self._weekday_group_label(rule.weekdays)
            if column == 2:
                return _PERIOD_LABELS[period]
            if not self._period_is_open(rule, period):
                return "—"
            return rule.staffing.counts[period][self._draft.roles[column - 3]]
        if role == Qt.ItemDataRole.EditRole and column >= 3:
            if not self._period_is_open(rule, period):
                return None
            return rule.staffing.counts[period][self._draft.roles[column - 3]]
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return (
                Qt.CheckState.Checked
                if self._period_is_open(rule, period)
                else Qt.CheckState.Unchecked
            )
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if column >= 3 and not self._period_is_open(rule, period):
            if role == Qt.ItemDataRole.BackgroundRole:
                return QColor("#D5D8DC")
            if role == Qt.ItemDataRole.ForegroundRole:
                return QColor("#6B7280")
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == 0:
                return "只切換這一個時段；關閉時該時段各職務需求皆為 0。"
            if column >= 3 and not self._period_is_open(rule, period):
                return "此時段關閉；請先開啟時段。"
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
        rule_index, period_index = divmod(index.row(), len(PERIODS_V1))
        rule = self._draft.weekly_demands[rule_index]
        period = PERIODS_V1[period_index]
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            is_open = value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked
            if self._period_is_open(rule, period) == is_open:
                return False
            if is_open:
                if rule.staffing is None:
                    rule.staffing = StaffingDraft.zero(self._draft.roles)
                for role_name in self._draft.roles:
                    rule.staffing.counts[period][role_name] = 1
                rule.is_open = True
            else:
                assert rule.staffing is not None
                for role_name in self._draft.roles:
                    rule.staffing.counts[period][role_name] = 0
                if not any(
                    count > 0
                    for values in rule.staffing.counts.values()
                    for count in values.values()
                ):
                    rule.is_open = False
                    rule.staffing = None
            self._draft.touch()
            first = self.index(index.row(), 0)
            last = self.index(index.row(), self.columnCount() - 1)
            self.dataChanged.emit(first, last)
            self.draft_changed.emit()
            return True
        if index.column() >= 3 and role == Qt.ItemDataRole.EditRole:
            if not self._period_is_open(rule, period):
                return False
            try:
                count = int(value)
            except (TypeError, ValueError):
                return False
            if count < 1 or count > 3 or isinstance(value, bool):
                return False
            role_name = self._draft.roles[index.column() - 3]
            if rule.staffing.counts[period][role_name] == count:
                return False
            rule.staffing.counts[period][role_name] = count
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
        rule_index = index.row() // len(PERIODS_V1)
        period_index = index.row() % len(PERIODS_V1)
        rule = self._draft.weekly_demands[rule_index]
        period = PERIODS_V1[period_index]
        if index.column() == 0:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        if index.column() >= 3:
            if not self._period_is_open(rule, period):
                # A closed period is intentionally a locked display cell.  It
                # must not remain selectable, otherwise the platform selection
                # palette can visually override its disabled background.
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
            return "日期類型"
        if section == 2:
            return "時段"
        if self._draft is None:
            return None
        return role_display_name(self._draft.roles[section - 3])

    @staticmethod
    def _period_is_open(rule: WeeklyDemandDraft, period: Period) -> bool:
        return bool(
            rule.is_open
            and rule.staffing is not None
            and any(rule.staffing.counts[period].values())
        )

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
