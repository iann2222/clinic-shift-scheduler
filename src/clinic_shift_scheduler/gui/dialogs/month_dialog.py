"""Small month picker shared by new and copy-from-previous actions."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .localized_dialogs import localize_dialog_buttons


class MonthDialog(QDialog):
    def __init__(
        self,
        title: str,
        description: str,
        *,
        initial: QDate | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        layout = QVBoxLayout(self)
        label = QLabel(description)
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        self.month_edit = QDateEdit(initial or QDate.currentDate())
        self.month_edit.setCalendarPopup(True)
        self.month_edit.setDisplayFormat("yyyy-MM")
        form.addRow("目標月份：", self.month_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        localize_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def year_month(self) -> tuple[int, int]:
        value = self.month_edit.date()
        return value.year(), value.month()
