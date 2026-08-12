"""Formal input validation summary and save actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...events import DiagnosticIssue
from ..navigation import NAVIGATION_ITEMS, PageId
from ..validation_presentation import format_validation_issue
from .base import InputPage


class ReviewSavePage(InputPage):
    validate_requested = Signal()
    save_requested = Signal()
    save_as_requested = Signal()
    issue_activated = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        item = next(
            item
            for item in NAVIGATION_ITEMS
            if item.page_id is PageId.REVIEW_SAVE
        )
        super().__init__(
            item.page_id,
            item.title,
            item.description,
            show_empty_state=False,
            parent=parent,
        )
        self._issues: tuple[DiagnosticIssue, ...] = ()

        layout = QVBoxLayout()
        self.surface_layout.addLayout(layout, 1)
        self.status_label = QLabel("尚未執行輸入資料檢查。")
        self.status_label.setObjectName("mutedText")
        layout.addWidget(self.status_label)
        self.issue_list = QListWidget()
        self.issue_list.setAccessibleName("輸入資料問題清單")
        self.issue_list.itemActivated.connect(self._activate_issue)
        layout.addWidget(self.issue_list, 1)
        hint = QLabel(
            "此處只檢查輸入格式與正式規則，不代表整份班表一定可排。"
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        actions = QHBoxLayout()
        validate_button = QPushButton("檢查輸入資料")
        validate_button.setToolTip("檢查輸入資料（Ctrl+Shift+V）")
        save_button = QPushButton("儲存")
        save_as_button = QPushButton("另存")
        validate_button.clicked.connect(self.validate_requested.emit)
        save_button.clicked.connect(self.save_requested.emit)
        save_as_button.clicked.connect(self.save_as_requested.emit)
        actions.addWidget(validate_button)
        actions.addStretch(1)
        actions.addWidget(save_button)
        actions.addWidget(save_as_button)
        layout.addLayout(actions)

    def show_validation(
        self,
        *,
        is_valid: bool,
        issues: tuple[DiagnosticIssue, ...],
    ) -> None:
        self._issues = issues
        self.issue_list.clear()
        if is_valid:
            self.status_label.setText("輸入資料檢查通過，可以安全儲存。")
            self.status_label.setObjectName("documentStatusClean")
        else:
            self.status_label.setText(f"發現 {len(issues)} 項需要修正的問題。")
            self.status_label.setObjectName("documentStatusDirty")
            for index, issue in enumerate(issues):
                item = QListWidgetItem(format_validation_issue(issue))
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip(
                    f"{issue.code} / {issue.phase.value}\n"
                    f"{issue.path}\n{issue.message}"
                )
                self.issue_list.addItem(item)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def clear_validation(self) -> None:
        self._issues = ()
        self.issue_list.clear()
        self.status_label.setText("資料已修改，請重新執行輸入資料檢查。")
        self.status_label.setObjectName("mutedText")

    def _activate_issue(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and 0 <= index < len(self._issues):
            self.issue_activated.emit(self._issues[index])
