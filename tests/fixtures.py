"""Small synthetic v1 inputs used by unit tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def minimal_valid_input() -> dict[str, Any]:
    """Return a complete one-day input with positive and zero demand."""

    return {
        "schema_version": "v1",
        "period": {
            "start_date": "2024-10-01",
            "end_date": "2024-10-01",
            "closed_weekdays": [],
            "closed_dates": [],
            "holidays": ["2024-10-01"],
        },
        "periods": ["morning", "afternoon", "evening"],
        "roles": ["reception", "assistant"],
        "demands": [
            {"date": "2024-10-01", "period": "morning", "role": "reception", "count": 1},
            {"date": "2024-10-01", "period": "morning", "role": "assistant", "count": 1},
            {"date": "2024-10-01", "period": "afternoon", "role": "reception", "count": 1},
            {"date": "2024-10-01", "period": "afternoon", "role": "assistant", "count": 1},
            {"date": "2024-10-01", "period": "evening", "role": "reception", "count": 0},
            {"date": "2024-10-01", "period": "evening", "role": "assistant", "count": 1},
        ],
        "employees": [
            {
                "employee_id": "FT001",
                "name": "怡秀",
                "employment_type": "full_time",
                "full_time_class": "A",
                "roles": ["reception", "assistant"],
                "fairness_group": "A_GENERAL",
                "shift_mode": "EXACT",
                "required_shifts": 2,
            },
            {
                "employee_id": "FT002",
                "name": "晴雯",
                "employment_type": "full_time",
                "full_time_class": "B",
                "roles": ["assistant"],
                "fairness_group": "B_ASSISTANT",
                "shift_mode": "TARGET",
                "target_shifts": 5,
            },
            {
                "employee_id": "PT001",
                "name": "兼職A",
                "employment_type": "part_time",
                "full_time_class": None,
                "roles": ["assistant"],
                "fairness_group": "PT_ASSISTANT",
                "shift_mode": "RANGE",
                "min_shifts": 0,
                "max_shifts": 2,
                "available_slots": [
                    {
                        "date": "2024-10-01",
                        "period": "morning",
                        "roles": ["assistant"],
                    }
                ],
            },
        ],
        "leave_requests": [],
        "unavailable_slots": [],
    }


def clone_fixture() -> dict[str, Any]:
    return deepcopy(minimal_valid_input())


def single_employee_pattern_input(
    *,
    employment_type: str,
    full_time_class: str | None,
    worked_periods: set[str],
) -> dict[str, Any]:
    """Build a complete one-day fixture that forces one daily pattern."""

    employee: dict[str, Any] = {
        "employee_id": "E001",
        "name": "測試人員",
        "employment_type": employment_type,
        "full_time_class": full_time_class,
        "roles": ["assistant"],
        "fairness_group": (
            f"FT_{full_time_class}" if employment_type == "full_time" else "PT"
        ),
        "shift_mode": "EXACT",
        "required_shifts": len(worked_periods),
    }
    if employment_type == "part_time":
        employee["available_slots"] = [
            {"date": "2024-10-01", "period": period, "roles": ["assistant"]}
            for period in ("morning", "afternoon", "evening")
        ]

    return {
        "schema_version": "v1",
        "period": {
            "start_date": "2024-10-01",
            "end_date": "2024-10-01",
            "closed_weekdays": [],
            "closed_dates": [],
            "holidays": [],
        },
        "periods": ["morning", "afternoon", "evening"],
        "roles": ["assistant"],
        "demands": [
            {
                "date": "2024-10-01",
                "period": period,
                "role": "assistant",
                "count": int(period in worked_periods),
            }
            for period in ("morning", "afternoon", "evening")
        ],
        "employees": [employee],
        "leave_requests": [],
        "unavailable_slots": [],
    }
