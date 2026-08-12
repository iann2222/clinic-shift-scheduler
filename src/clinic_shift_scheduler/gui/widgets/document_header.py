"""Persistent document identity, state, and primary file actions."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class DocumentState(StrEnum):
    NEW = "NEW"
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"


class DocumentHeader(QFrame):
    create_requested = Signal()
    copy_previous_requested = Signal()
    open_requested = Signal()
    save_requested = Signal()
    save_as_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("documentHeader")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 12, 12)
        outer.setSpacing(12)

        identity = QVBoxLayout()
        identity.setSpacing(2)
        self.month_label = QLabel("尚未開啟月份")
        self.month_label.setObjectName("documentMonth")
        self.path_label = QLabel("尚未開啟檔案")
        self.path_label.setObjectName("documentPath")
        self.path_label.setToolTip("尚未開啟檔案")
        identity.addWidget(self.month_label)
        identity.addWidget(self.path_label)
        outer.addLayout(identity, 1)

        self.status_label = QLabel("尚未建立檔案")
        self.status_label.setObjectName("documentStatusDirty")
        outer.addWidget(self.status_label)

        for text, shortcut, signal in (
            ("建立月份", "Ctrl+N", self.create_requested),
            ("從上月建立", None, self.copy_previous_requested),
            ("開啟", "Ctrl+O", self.open_requested),
            ("儲存", "Ctrl+S", self.save_requested),
            ("另存", "Ctrl+Shift+S", self.save_as_requested),
        ):
            button = QPushButton(text)
            if shortcut is not None:
                button.setToolTip(f"{text}（{shortcut}）")
            button.clicked.connect(signal.emit)
            outer.addWidget(button)

        self.settings_button = QToolButton()
        self.settings_button.setText("設定")
        self.settings_button.setToolTip("開啟一般與進階設定")
        self.settings_button.setAccessibleName("設定")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        outer.addWidget(self.settings_button)

    def set_document(
        self,
        *,
        month: str | None,
        path: Path | None,
        state: DocumentState,
    ) -> None:
        self.month_label.setText(month or "尚未開啟月份")
        rendered_path = str(path) if path is not None else "尚未開啟檔案"
        self.path_label.setText(rendered_path)
        self.path_label.setToolTip(rendered_path)
        label = {
            DocumentState.NEW: "尚未建立檔案",
            DocumentState.CLEAN: "已儲存",
            DocumentState.DIRTY: "尚未儲存",
        }[state]
        self.status_label.setText(label)
        self.status_label.setObjectName(
            "documentStatusClean"
            if state is DocumentState.CLEAN
            else "documentStatusDirty"
        )
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
