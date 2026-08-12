"""Chinese standard buttons independent of the installed Qt translations."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QMessageBox,
    QProxyStyle,
    QStyle,
    QWidget,
)


_DIALOG_BUTTON_TEXT = {
    QDialogButtonBox.StandardButton.Ok: "確定",
    QDialogButtonBox.StandardButton.Cancel: "取消",
    QDialogButtonBox.StandardButton.Close: "關閉",
    QDialogButtonBox.StandardButton.Save: "儲存",
    QDialogButtonBox.StandardButton.Discard: "不要儲存",
    QDialogButtonBox.StandardButton.Yes: "是",
    QDialogButtonBox.StandardButton.No: "否",
}
_MESSAGE_BUTTON_TEXT = {
    QMessageBox.StandardButton.Ok: "確定",
    QMessageBox.StandardButton.Cancel: "取消",
    QMessageBox.StandardButton.Close: "關閉",
    QMessageBox.StandardButton.Save: "儲存",
    QMessageBox.StandardButton.Discard: "不要儲存",
    QMessageBox.StandardButton.Yes: "是",
    QMessageBox.StandardButton.No: "否",
}


class _DialogButtonStyle(QProxyStyle):
    """Keep action buttons right-aligned with reject left of accept."""

    def styleHint(
        self,
        hint: QStyle.StyleHint,
        option: object = None,
        widget: QWidget | None = None,
        return_data: object = None,
    ) -> int:
        if hint == QStyle.StyleHint.SH_DialogButtonLayout:
            return int(QDialogButtonBox.ButtonLayout.MacLayout.value)
        return super().styleHint(hint, option, widget, return_data)


def _position_dialog_buttons(buttons: QDialogButtonBox) -> None:
    style = _DialogButtonStyle()
    style.setParent(buttons)
    buttons.setStyle(style)
    buttons.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    # Keep the Python wrapper alive together with its parent widget.
    buttons._dialog_button_style = style


def localize_dialog_buttons(buttons: QDialogButtonBox) -> QDialogButtonBox:
    for standard_button, text in _DIALOG_BUTTON_TEXT.items():
        button = buttons.button(standard_button)
        if button is not None:
            button.setText(text)
    _position_dialog_buttons(buttons)
    return buttons


def build_message_box(
    parent: QWidget | None,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    *,
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    informative_text: str | None = None,
) -> QMessageBox:
    message = QMessageBox(parent)
    message.setIcon(icon)
    message.setWindowTitle(title)
    message.setText(text)
    if informative_text:
        message.setInformativeText(informative_text)
    message.setStandardButtons(buttons)
    for standard_button, label in _MESSAGE_BUTTON_TEXT.items():
        button = message.button(standard_button)
        if button is not None:
            button.setText(label)
    button_box = message.findChild(QDialogButtonBox)
    if button_box is not None:
        _position_dialog_buttons(button_box)
    return message


def show_information(parent: QWidget | None, title: str, text: str) -> int:
    return build_message_box(
        parent,
        QMessageBox.Icon.Information,
        title,
        text,
    ).exec()


def show_warning(parent: QWidget | None, title: str, text: str) -> int:
    return build_message_box(
        parent,
        QMessageBox.Icon.Warning,
        title,
        text,
    ).exec()


def show_critical(parent: QWidget | None, title: str, text: str) -> int:
    return build_message_box(
        parent,
        QMessageBox.Icon.Critical,
        title,
        text,
    ).exec()


def ask_yes_no(parent: QWidget | None, title: str, text: str) -> bool:
    message = build_message_box(
        parent,
        QMessageBox.Icon.Question,
        title,
        text,
        buttons=(
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
        ),
    )
    message.setDefaultButton(QMessageBox.StandardButton.No)
    return message.exec() == QMessageBox.StandardButton.Yes
