from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ..navigation import NAVIGATION_ITEMS, PageId
from .base import InputPage


class AvailabilityPage(InputPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        item = next(item for item in NAVIGATION_ITEMS if item.page_id is PageId.AVAILABILITY)
        super().__init__(item.page_id, item.title, item.description, parent=parent)
