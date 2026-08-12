"""Stable navigation definitions for the first desktop milestone."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PageId(StrEnum):
    MONTH_CLINIC = "month_clinic"
    WEEKLY_DEMAND = "weekly_demand"
    DATE_OVERRIDE = "date_override"
    EMPLOYEE = "employee"
    AVAILABILITY = "availability"
    REVIEW_SAVE = "review_save"


@dataclass(frozen=True, slots=True)
class NavigationItem:
    page_id: PageId
    title: str
    description: str


NAVIGATION_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem(
        PageId.MONTH_CLINIC,
        "月份與診所設定",
        "設定排班月份、假日、固定時段與診所職務。",
    ),
    NavigationItem(
        PageId.WEEKLY_DEMAND,
        "每週人力需求",
        "設定平日、星期六與星期日的開診狀態及人力需求。",
    ),
    NavigationItem(
        PageId.DATE_OVERRIDE,
        "特定日期調整",
        "處理臨時休診、加診或與週間模板不同的日期。",
    ),
    NavigationItem(
        PageId.EMPLOYEE,
        "員工資料",
        "維護人員類別、職務資格、公平分組與班次需求。",
    ),
    NavigationItem(
        PageId.AVAILABILITY,
        "休假與可排",
        "設定正職休假與不可排，以及兼職明確可排時段。",
    ),
    NavigationItem(
        PageId.REVIEW_SAVE,
        "檢查與儲存",
        "執行完整輸入檢查、定位問題並安全儲存文件。",
    ),
)
