"""Numeric controls with units rendered outside the editable value."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)


class TrimmedDoubleSpinBox(QDoubleSpinBox):
    """Display significant decimals without fixed-width trailing zeroes."""

    def textFromValue(self, value: float) -> str:
        rendered = f"{value:.{self.decimals()}f}"
        return rendered.rstrip("0").rstrip(".")


class UnitInput(QWidget):
    """Keep a spin control's editable text numeric and show its unit beside it."""

    def __init__(
        self,
        control: QWidget,
        unit: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.control = control
        self.unit_label = QLabel(unit)
        self.unit_label.setObjectName("inputUnit")
        control.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            control.sizePolicy().verticalPolicy(),
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(control, 1)
        layout.addWidget(self.unit_label)
