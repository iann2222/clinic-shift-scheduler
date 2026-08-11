"""Lightweight field contracts shared by Schemas and runtime parsers."""

from __future__ import annotations


CANONICAL_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "period",
        "periods",
        "roles",
        "demands",
        "employees",
        "leave_requests",
        "unavailable_slots",
    }
)
CANONICAL_PERIOD_FIELDS = frozenset(
    {
        "start_date",
        "end_date",
        "closed_weekdays",
        "closed_dates",
        "holidays",
    }
)
EMPLOYEE_FIELDS = frozenset(
    {
        "employee_id",
        "name",
        "employment_type",
        "full_time_class",
        "roles",
        "fairness_group",
        "shift_mode",
        "required_shifts",
        "target_shifts",
        "min_shifts",
        "max_shifts",
        "available_slots",
        "notes",
    }
)

WEEKLY_TOP_LEVEL_FIELDS = frozenset(
    (CANONICAL_TOP_LEVEL_FIELDS - {"demands"})
    | {"authoring_version", "weekly_demands", "date_overrides"}
)
WEEKLY_PERIOD_FIELDS = frozenset({"start_date", "end_date", "holidays"})
WEEKLY_DEMAND_FIELDS = frozenset({"weekdays", "is_open", "staffing"})
DATE_OVERRIDE_FIELDS = frozenset({"date", "is_open", "staffing"})

CONFIG_ROOT_FIELDS = frozenset({"使用者設定", "預設設定"})
CONFIG_SETTINGS_FIELDS = frozenset(
    {
        "設定版本",
        "輸入檔名",
        "覆寫既有結果",
        "進度更新秒數",
        "候選診斷",
    }
)
CONFIG_CANDIDATE_FIELDS = frozenset(
    {
        "啟用",
        "搜尋上限",
        "診斷時間上限",
        "額外輸出候選班表份數上限",
        "輸出格式",
    }
)
CONFIG_DIAGNOSTIC_TIME_FIELDS = frozenset(
    {"模式", "秒數", "排班時間比例"}
)
