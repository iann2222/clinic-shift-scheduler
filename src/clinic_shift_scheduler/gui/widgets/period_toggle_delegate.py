"""Stable, full-cell period toggle indicator for staffing tables."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from ..styles.palette import PRIMARY, PRIMARY_SOFT, SURFACE, TEXT


class PeriodToggleDelegate(QStyledItemDelegate):
    """Paint the opening checkbox directly instead of relying on Qt themes."""

    _INDICATOR_SIZE = 16
    _LEFT_MARGIN = 8
    _TEXT_GAP = 8
    _CHECKED_FILL = "#6F919F"
    _CHECKED_HOVER_FILL = "#5E7D89"

    def paint(
        self,
        painter: QPainter,
        option: object,
        index: QModelIndex,
    ) -> None:
        rect = option.rect
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        painter.fillRect(
            rect,
            option.palette.brush(QPalette.ColorRole.Base),
        )
        indicator = QRect(
            rect.left() + self._LEFT_MARGIN,
            rect.center().y() - self._INDICATOR_SIZE // 2,
            self._INDICATOR_SIZE,
            self._INDICATOR_SIZE,
        )
        self._draw_indicator(painter, indicator, checked, enabled, hovered)

        text_rect = QRect(
            indicator.right() + self._TEXT_GAP,
            rect.top(),
            max(0, rect.right() - indicator.right() - self._TEXT_GAP),
            rect.height(),
        )
        color = QColor(TEXT if enabled else "#6B7280")
        painter.setPen(color)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
        )
        painter.restore()

    @staticmethod
    def _draw_indicator(
        painter: QPainter,
        rect: QRect,
        checked: bool,
        enabled: bool,
        hovered: bool,
    ) -> None:
        if not enabled:
            fill = QColor("#D9DEE1")
            border = QColor("#AAB3B8")
        elif checked:
            fill = QColor(
                PeriodToggleDelegate._CHECKED_HOVER_FILL
                if hovered
                else PeriodToggleDelegate._CHECKED_FILL
            )
            border = fill
        else:
            fill = QColor(PRIMARY_SOFT if hovered else SURFACE)
            border = QColor(PRIMARY if hovered else "#74858D")

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(fill)
        painter.setPen(QPen(border, 2.0))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)
        if not checked:
            return
        painter.setPen(QPen(Qt.GlobalColor.white, 2.2))
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


class LockedStaffingCellDelegate(QStyledItemDelegate):
    """Keep closed-period cells stable while preserving native table styling."""

    def paint(
        self,
        painter: QPainter,
        option: object,
        index: QModelIndex,
    ) -> None:
        if index.flags() & Qt.ItemFlag.ItemIsEnabled:
            super().paint(painter, option, index)
            return

        # Let Qt render the original model-provided background, grid, font,
        # and alignment.  Only remove transient view states that could mask
        # the locked gray when the mouse enters or focuses this cell.
        stable_option = QStyleOptionViewItem(option)
        stable_option.state &= ~(
            QStyle.StateFlag.State_MouseOver
            | QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_HasFocus
        )
        super().paint(painter, stable_option, index)
