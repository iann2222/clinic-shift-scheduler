"""Consistent focus clearing when users click non-interactive background areas."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QScrollBar,
    QTabBar,
    QTextEdit,
    QWidget,
)


_INTERACTIVE_WIDGETS = (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QScrollBar,
    QTabBar,
    QTextEdit,
)


class BackgroundFocusClearer(QObject):
    """Clear stale input/button focus after a click on unrelated whitespace."""

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        application.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() != QEvent.Type.MouseButtonPress
            or not isinstance(watched, QWidget)
            or _has_interactive_ancestor(watched, watched.window())
        ):
            return False
        window = watched.window()
        QTimer.singleShot(0, lambda: self._clear_focus(window))
        return False

    def _clear_focus(self, window: QWidget) -> None:
        focused = QApplication.focusWidget()
        if focused is None or focused.window() is not window:
            return
        if isinstance(focused, QLineEdit):
            focused.deselect()
        elif isinstance(focused, QAbstractSpinBox):
            focused.lineEdit().deselect()
        elif isinstance(focused, QComboBox) and focused.isEditable():
            focused.lineEdit().deselect()
        focused.clearFocus()


def install_background_focus_clear(
    application: QApplication,
) -> BackgroundFocusClearer:
    return BackgroundFocusClearer(application)


def _has_interactive_ancestor(widget: QWidget, boundary: QWidget) -> bool:
    current: QWidget | None = widget
    while current is not None and current is not boundary:
        if isinstance(current, _INTERACTIVE_WIDGETS):
            return True
        parent = current.parentWidget()
        current = parent
    return False
