"""Left-side workflow navigation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..navigation import NAVIGATION_ITEMS, PageId


class NavigationSidebar(QFrame):
    page_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navigationSidebar")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(14)

        title = QLabel("診所排班系統")
        title.setObjectName("applicationTitle")
        layout.addWidget(title)

        subtitle = QLabel("排班資料編輯器")
        subtitle.setObjectName("mutedText")
        layout.addWidget(subtitle)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("navigationList")
        self.list_widget.setAccessibleName("輸入流程導覽")
        for item in NAVIGATION_ITEMS:
            widget_item = QListWidgetItem(item.title)
            widget_item.setData(Qt.ItemDataRole.UserRole, item.page_id.value)
            widget_item.setToolTip(item.description)
            self.list_widget.addItem(widget_item)
        self.list_widget.currentRowChanged.connect(self._emit_page)
        layout.addWidget(self.list_widget, 1)
        self.list_widget.setCurrentRow(0)

    def _emit_page(self, row: int) -> None:
        if row < 0:
            return
        value = self.list_widget.item(row).data(Qt.ItemDataRole.UserRole)
        self.page_selected.emit(PageId(value))

    def select_page(self, page_id: PageId) -> None:
        row = next(
            index
            for index, item in enumerate(NAVIGATION_ITEMS)
            if item.page_id is page_id
        )
        self.list_widget.setCurrentRow(row)
