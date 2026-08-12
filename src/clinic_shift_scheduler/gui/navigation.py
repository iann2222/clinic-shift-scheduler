"""Stable navigation definitions for the first desktop milestone."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PageId(StrEnum):
    MONTH_CLINIC = "month_clinic"
    WEEKLY_DEMAND = "weekly_demand"
    DATE_OVERRIDE = "date_override"
    EMPLOYEE = "employee"
    FULL_TIME_UNAVAILABLE = "full_time_unavailable"
    PART_TIME_AVAILABLE = "part_time_available"
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
        "建立、開啟月份並確認本月使用的固定設定。",
    ),
    NavigationItem(
        PageId.WEEKLY_DEMAND,
        "每週人力需求",
        "設定平日、星期六與星期日的開診狀態及人力需求。",
    ),
    NavigationItem(
        PageId.DATE_OVERRIDE,
        "特殊日期設定",
        "設定與一般日期所沿用之每週人力需求不同的調整。",
    ),
    NavigationItem(
        PageId.EMPLOYEE,
        "員工資料",
        "查看員工資料；雙擊員工姓名即可開啟編輯。",
    ),
    NavigationItem(
        PageId.FULL_TIME_UNAVAILABLE,
        "正職不可排",
        "集中設定所有正職人員不能排班的日期與時段。",
    ),
    NavigationItem(
        PageId.PART_TIME_AVAILABLE,
        "兼職可排",
        "集中設定所有兼職人員明確可以排班的日期與時段。",
    ),
    NavigationItem(
        PageId.REVIEW_SAVE,
        "檢查與儲存",
        "執行完整輸入檢查、定位問題並安全儲存文件。",
    ),
)
