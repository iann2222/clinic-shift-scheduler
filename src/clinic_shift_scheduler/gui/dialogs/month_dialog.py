"""Small month picker shared by new and copy-from-previous actions."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..widgets import UnitInput
from .localized_dialogs import localize_dialog_buttons


class _YearSpinBox(QSpinBox):
    def stepBy(self, steps: int) -> None:
        super().stepBy(steps)
        QTimer.singleShot(0, self.lineEdit().deselect)


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
        selected = initial or QDate.currentDate().addMonths(1)
        self.year_edit = _YearSpinBox()
        self.year_edit.setRange(2000, 2100)
        self.year_edit.setValue(selected.year())
        self.year_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.year_edit.setFixedWidth(90)
        self.year_field = UnitInput(self.year_edit, "年")
        self.month_edit = QComboBox()
        for month in range(1, 13):
            self.month_edit.addItem(str(month), month)
        self.month_edit.setCurrentIndex(selected.month() - 1)
        self.month_edit.setFixedWidth(90)
        self.month_field = UnitInput(self.month_edit, "月")
        self.month_edit.setEditable(True)
        self.month_edit.lineEdit().setReadOnly(True)
        self.month_edit.lineEdit().setAlignment(Qt.AlignmentFlag.AlignLeft)
        for index in range(self.month_edit.count()):
            self.month_edit.setItemData(
                index,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                Qt.ItemDataRole.TextAlignmentRole,
            )
        self.month_edit.setMaxVisibleItems(12)
        self.month_edit.view().setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        row_height = max(self.month_edit.view().sizeHintForRow(0), 20)
        self.month_edit.view().setMinimumHeight(row_height * 12 + 2)
        form.addRow("年份：", self.year_field)
        form.addRow("月份：", self.month_field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        localize_dialog_buttons(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 0, Qt.AlignmentFlag.AlignRight)
        self._accept_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        QTimer.singleShot(0, self._focus_primary_action)

    @property
    def year_month(self) -> tuple[int, int]:
        return self.year_edit.value(), int(self.month_edit.currentData())

    def _focus_primary_action(self) -> None:
        self.year_edit.lineEdit().deselect()
        self.month_edit.lineEdit().deselect()
        self.year_edit.clearFocus()
        self._accept_button.setFocus()
