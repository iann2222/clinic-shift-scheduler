"""Simplified employee-list editors for FT unavailable and PT available slots."""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...enums import PERIODS_V1, EmploymentType, Period
from ..dialogs import localize_dialog_buttons, show_warning
from ..drafts import EmployeeDraft, ScheduleDraft
from ..field_location import FieldLocation
from ..models import AvailabilitySummaryTableModel
from ..navigation import NAVIGATION_ITEMS, PageId
from .base import InputPage


_PERIOD_ROWS = (
    (Period.MORNING, "早上日號："),
    (Period.AFTERNOON, "下午日號："),
    (Period.EVENING, "晚上日號："),
)


class PeriodDateListDialog(QDialog):
    """Edit one employee's month-bound dates without asking for year/month."""

    def __init__(
        self,
        employee: EmployeeDraft,
        start_date: date,
        selected: set[tuple[date, Period]],
        *,
        mode_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._start_date = start_date
        self._days_in_month = monthrange(start_date.year, start_date.month)[1]
        self.setWindowTitle(f"{employee.name}－{mode_label}")
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"目前月份：{start_date:%Y-%m}。\n只需輸入幾號，"
            "以逗號、空白或頓號分隔，例如：2、5、12。"
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.period_edits: dict[Period, QLineEdit] = {}
        for period, label in _PERIOD_ROWS:
            edit = QLineEdit()
            edit.setPlaceholderText("未設定")
            edit.setText(
                "、".join(
                    str(day.day)
                    for day, selected_period in sorted(selected)
                    if selected_period is period
                )
            )
            form.addRow(label, edit)
            self.period_edits[period] = edit
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        localize_dialog_buttons(buttons)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 0, Qt.AlignmentFlag.AlignRight)
        self._selected_periods: set[tuple[date, Period]] | None = None

    @property
    def selected_periods(self) -> set[tuple[date, Period]]:
        if self._selected_periods is None:
            raise RuntimeError("dialog has not been accepted")
        return set(self._selected_periods)

    def _accept_if_valid(self) -> None:
        selected: set[tuple[date, Period]] = set()
        try:
            for period, edit in self.period_edits.items():
                for day_number in _parse_day_numbers(
                    edit.text(),
                    self._days_in_month,
                ):
                    selected.add(
                        (
                            date(
                                self._start_date.year,
                                self._start_date.month,
                                day_number,
                            ),
                            period,
                        )
                    )
        except ValueError as error:
            show_warning(self, "日期格式有誤", str(error))
            return
        self._selected_periods = selected
        self.accept()


class _EmployeeAvailabilityListPage(InputPage):
    draft_changed = Signal()

    def __init__(
        self,
        page_id: PageId,
        employment_type: EmploymentType,
        *,
        mode_label: str,
        hint_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        item = next(item for item in NAVIGATION_ITEMS if item.page_id is page_id)
        super().__init__(
            item.page_id,
            item.title,
            item.description,
            show_empty_state=False,
            parent=parent,
        )
        self._draft: ScheduleDraft | None = None
        self._employment_type = employment_type
        self._mode_label = mode_label
        layout = QVBoxLayout()
        self.surface_layout.addLayout(layout, 1)
        hint = QLabel(
            hint_text
            or "雙擊員工或日期清單後，輸入該月日期並分別設定早、午、晚時段。"
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableView()
        self.table.setAccessibleName(item.title)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.model = AvailabilitySummaryTableModel(employment_type)
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        name_width = self.table.fontMetrics().horizontalAdvance("中文字五個") + 24
        self.table.setColumnWidth(0, name_width)
        self.table.doubleClicked.connect(self._edit_employee)
        layout.addWidget(self.table, 1)

    def bind_draft(self, draft: ScheduleDraft | None) -> None:
        self._draft = draft
        self.model.set_draft(draft)

    def focus_location(self, location: FieldLocation) -> None:
        if location.employee_index is not None:
            self.focus_employee(location.employee_index)
        else:
            self.table.setFocus()

    def focus_employee(self, employee_index: int) -> None:
        if self._draft is None or not 0 <= employee_index < len(self._draft.employees):
            return
        employee_id = self._draft.employees[employee_index].employee_id
        row = self.model.row_for_employee_id(employee_id)
        if row >= 0:
            self.table.selectRow(row)
            self.table.scrollTo(self.model.index(row, 1))
            self.table.setFocus()

    def focus_employee_id(self, employee_id: str) -> None:
        row = self.model.row_for_employee_id(employee_id)
        if row >= 0:
            self.table.selectRow(row)
            self.table.scrollTo(self.model.index(row, 1))
            self.table.setFocus()

    def _edit_employee(self, index: QModelIndex) -> None:
        if self._draft is None:
            return
        employee = self.model.employee_at(index.row())
        if employee is None:
            return
        complement = (
            self._employment_type is EmploymentType.PART_TIME
            and index.column() == 2
        )
        dialog = PeriodDateListDialog(
            employee,
            self._draft.start_date,
            self.model.selected_periods(employee, complement=complement),
            mode_label="不可排日期" if complement else self._mode_label,
            parent=self,
        )
        if not dialog.exec():
            return
        try:
            self.model.replace_selected_periods(
                employee,
                dialog.selected_periods,
                complement=complement,
            )
        except ValueError as error:
            show_warning(self, "無法更新日期", str(error))
            return
        self.model.refresh_row(index.row())
        self.draft_changed.emit()


class FullTimeUnavailablePage(_EmployeeAvailabilityListPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            PageId.FULL_TIME_UNAVAILABLE,
            EmploymentType.FULL_TIME,
            mode_label="不可排日期",
            parent=parent,
        )


class PartTimeAvailablePage(_EmployeeAvailabilityListPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            PageId.PART_TIME_AVAILABLE,
            EmploymentType.PART_TIME,
            mode_label="可排日期",
            hint_text=(
                "雙擊可排或不可排欄位後，輸入該月日期並分別設定早、午、晚時段。"
                "兩欄會自動同步更新，只需手動編輯其中一邊。"
            ),
            parent=parent,
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )


def _parse_day_numbers(raw: str, days_in_month: int) -> tuple[int, ...]:
    text = raw.strip()
    if not text:
        return ()
    values = re.split(r"[\s,，、;；]+", text)
    result: set[int] = set()
    for value in values:
        if not value:
            continue
        if not value.isdigit():
            raise ValueError(f"「{value}」不是有效日號")
        day_number = int(value)
        if not 1 <= day_number <= days_in_month:
            raise ValueError(f"日號必須介於 1 到 {days_in_month}：{day_number}")
        result.add(day_number)
    return tuple(sorted(result))
