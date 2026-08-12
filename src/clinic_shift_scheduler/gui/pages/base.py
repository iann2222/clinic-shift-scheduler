"""Shared visual shell used before individual input models are connected."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..navigation import PageId


class InputPage(QWidget):
    """A workflow page with stable identity and restrained empty state."""

    def __init__(
        self,
        page_id: PageId,
        title: str,
        description: str,
        *,
        show_empty_state: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.page_id = page_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        title_label.setAccessibleName(f"目前頁面：{title}")
        layout.addWidget(title_label)

        description_label = QLabel(description)
        description_label.setObjectName("mutedText")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

        self.surface = QFrame()
        self.surface.setObjectName("pageSurface")
        self.surface_layout = QVBoxLayout(self.surface)
        self.surface_layout.setContentsMargins(24, 24, 24, 24)
        if show_empty_state:
            empty_state = QLabel("輸入功能將在後續小步提交中接上正式資料模型。")
            empty_state.setObjectName("mutedText")
            empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_state.setWordWrap(True)
            self.surface_layout.addWidget(empty_state, 1)
        layout.addWidget(self.surface, 1)
