"""Reusable, locale-friendly calendar controls for bounded date selection."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QLocale, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .localized_dialogs import localize_dialog_buttons


class _FixedMonthCalendar(QCalendarWidget):
    """Calendar with explicit painting for adjacent-month and selected cells."""

    def __init__(self, year: int, month: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fixed_year = year
        self._fixed_month = month

    def paintCell(self, painter: QPainter, rect: QRect, value: QDate) -> None:
        if value.year() != self._fixed_year or value.month() != self._fixed_month:
            painter.save()
            painter.fillRect(rect.adjusted(1, 1, -1, -1), QColor("#D8DDE0"))
            painter.setPen(QColor("#8A959B"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(value.day()))
            painter.restore()
            return
        if value == self.selectedDate():
            painter.save()
            selected_rect = rect.adjusted(1, 1, -1, -1)
            painter.fillRect(selected_rect, QColor("#3E6575"))
            painter.setPen(QColor("#244652"))
            painter.drawRect(selected_rect)
            font = QFont(painter.font())
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(value.day()))
            painter.restore()
            return
        super().paintCell(painter, rect, value)


class MonthCalendarWidget(QWidget):
    """QCalendarWidget with an explicit year-first navigation contract."""

    selection_changed = Signal(QDate)

    def __init__(
        self,
        start_date: date,
        end_date: date,
        *,
        initial: date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if end_date < start_date:
            raise ValueError("日期範圍結束日不得早於開始日")
        self._minimum = _to_qdate(start_date)
        self._maximum = _to_qdate(end_date)
        selected = _to_qdate(initial or start_date)
        if selected < self._minimum or selected > self._maximum:
            selected = self._minimum

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        navigation = QHBoxLayout()
        navigation.setSpacing(8)
        self.year_label = QLabel(f"{selected.year()} 年")
        self.year_label.setObjectName("calendarMonthLabel")
        self.month_label = QLabel(f"{selected.month()} 月")
        self.month_label.setObjectName("calendarMonthLabel")
        navigation.addStretch(1)
        navigation.addWidget(self.year_label)
        navigation.addWidget(self.month_label)
        navigation.addStretch(1)
        layout.addLayout(navigation)

        self.calendar = _FixedMonthCalendar(selected.year(), selected.month())
        self.calendar.setLocale(
            QLocale(QLocale.Language.Chinese, QLocale.Country.Taiwan)
        )
        self.calendar.setGridVisible(True)
        self.calendar.setNavigationBarVisible(False)
        self.calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self.calendar.setSelectionMode(
            QCalendarWidget.SelectionMode.SingleSelection
        )
        self.calendar.setDateRange(self._minimum, self._maximum)
        self.calendar.setSelectedDate(selected)
        self.calendar.setCurrentPage(selected.year(), selected.month())
        palette = self.calendar.palette()
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#3E6575"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        self.calendar.setPalette(palette)
        self.calendar.setStyleSheet(
            "QCalendarWidget QTableView:enabled {"
            " selection-background-color: #3E6575;"
            " selection-color: #FFFFFF;"
            "}"
            "QCalendarWidget QTableView::item:selected {"
            " background-color: #3E6575;"
            " color: #FFFFFF;"
            " border: 2px solid #244652;"
            " font-weight: 600;"
            "}"
        )
        layout.addWidget(self.calendar)

        self.calendar.selectionChanged.connect(self._selection_changed)

    def selected_date(self) -> QDate:
        return self.calendar.selectedDate()

    def _selection_changed(self) -> None:
        self.selection_changed.emit(self.calendar.selectedDate())


class DatePickerDialog(QDialog):
    def __init__(
        self,
        title: str,
        description: str,
        start_date: date,
        end_date: date,
        *,
        initial: date | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        layout = QVBoxLayout(self)
        hint = QLabel(description)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.date_picker = MonthCalendarWidget(
            start_date,
            end_date,
            initial=initial,
        )
        self.calendar = self.date_picker.calendar
        layout.addWidget(self.date_picker)

        self.selection_label = QLabel()
        self.selection_label.setObjectName("selectedDateLabel")
        layout.addWidget(self.selection_label)
        self.date_picker.selection_changed.connect(self._update_selection_label)
        self._update_selection_label(self.calendar.selectedDate())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        localize_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 0, Qt.AlignmentFlag.AlignRight)

    @property
    def selected_date(self) -> date:
        selected = self.calendar.selectedDate()
        return date(selected.year(), selected.month(), selected.day())

    def _update_selection_label(self, selected: QDate) -> None:
        self.selection_label.setText(
            f"已選日期：{selected.year()} 年 {selected.month()} 月 {selected.day()} 日"
        )


def _to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)
