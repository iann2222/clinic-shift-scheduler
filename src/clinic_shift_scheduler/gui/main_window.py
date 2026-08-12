"""Main desktop input-editor shell with stable workflow navigation."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .dialogs import SettingsDialog
from .navigation import NAVIGATION_ITEMS, PageId
from .pages import (
    AvailabilityPage,
    DateOverridePage,
    EmployeePage,
    MonthClinicPage,
    ReviewSavePage,
    WeeklyDemandPage,
)
from .widgets import DocumentHeader, NavigationSidebar


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("診所排班系統－排班資料編輯器")
        self.resize(1180, 760)
        self.setMinimumSize(920, 620)

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        self.navigation = NavigationSidebar()
        root_layout.addWidget(self.navigation)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(16)
        root_layout.addWidget(content, 1)

        self.document_header = DocumentHeader()
        content_layout.addWidget(self.document_header)

        self.page_stack = QStackedWidget()
        content_layout.addWidget(self.page_stack, 1)

        page_objects = (
            MonthClinicPage(),
            WeeklyDemandPage(),
            DateOverridePage(),
            EmployeePage(),
            AvailabilityPage(),
            ReviewSavePage(),
        )
        self._page_indexes: dict[PageId, int] = {}
        for page in page_objects:
            self._page_indexes[page.page_id] = self.page_stack.addWidget(page)

        if tuple(self._page_indexes) != tuple(
            item.page_id for item in NAVIGATION_ITEMS
        ):
            raise RuntimeError("page stack must follow the navigation contract")

        self.navigation.page_selected.connect(self.navigate_to)
        self.document_header.settings_requested.connect(self.open_settings)
        self.navigate_to(PageId.MONTH_CLINIC)

    @property
    def page_ids(self) -> tuple[PageId, ...]:
        return tuple(self._page_indexes)

    def navigate_to(self, page_id: PageId) -> None:
        self.page_stack.setCurrentIndex(self._page_indexes[page_id])

    def open_settings(self) -> None:
        SettingsDialog(self).exec()
