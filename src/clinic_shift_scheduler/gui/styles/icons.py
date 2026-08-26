"""Small programmatic icons that follow the centralized GUI palette."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from .palette import PRIMARY


_ICON_SIZES = (16, 20, 24, 32, 48)


def themed_information_icon() -> QIcon:
    """Return a crisp, palette-colored information icon for High DPI UI."""

    icon = QIcon()
    for size in _ICON_SIZES:
        scale = size / 16.0
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PRIMARY))
        painter.drawEllipse(QRectF(scale, scale, 14 * scale, 14 * scale))

        painter.setBrush(QColor(Qt.GlobalColor.white))
        painter.drawEllipse(
            QRectF(7 * scale, 3.5 * scale, 2 * scale, 2 * scale)
        )
        painter.drawRoundedRect(
            QRectF(7 * scale, 7 * scale, 2 * scale, 5.5 * scale),
            scale,
            scale,
        )
        painter.end()
        icon.addPixmap(pixmap)
    return icon
