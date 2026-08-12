"""Checkbox with a stable, single check mark on Windows Qt styles."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QProxyStyle, QStyle, QWidget


class _VisibleCheckStyle(QProxyStyle):
    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: object,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            super().drawPrimitive(element, option, painter, widget)
            return
        checked = bool(option.state & QStyle.StateFlag.State_On)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        rect = option.rect.adjusted(1, 1, -1, -1)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor("#3E6575" if checked else "#FFFFFF")
        border = QColor("#3E6575" if checked else "#8B989F")
        if not enabled:
            fill = QColor("#D9DEE1")
            border = QColor("#AAB3B8")
        painter.setBrush(fill)
        painter.setPen(QPen(border, 1.0))
        painter.drawRoundedRect(rect, 2, 2)
        if checked:
            painter.setPen(QPen(Qt.GlobalColor.white, 2.0))
            painter.drawLine(
                rect.left() + 3,
                rect.center().y(),
                rect.center().x() - 1,
                rect.bottom() - 3,
            )
            painter.drawLine(
                rect.center().x() - 1,
                rect.bottom() - 3,
                rect.right() - 2,
                rect.top() + 3,
            )
        painter.restore()


class VisibleCheckBox(QCheckBox):
    """Draw one high-contrast check without relying on hover repainting."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        style = _VisibleCheckStyle()
        style.setParent(self)
        self.setStyle(style)
        self._visible_check_style = style
