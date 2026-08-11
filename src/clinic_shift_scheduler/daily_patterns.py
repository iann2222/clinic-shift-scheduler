"""Shared v1 daily-pattern definitions used by prechecks and CP-SAT."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .enums import EmploymentType, FullTimeClass, PERIODS_V1, Period


B_MAX_SINGLE_SHIFT_DAYS_PER_MONTH = 3


class DailyPattern(StrEnum):
    OFF = "off"
    MORNING_ONLY = "morning_only"
    AFTERNOON_ONLY = "afternoon_only"
    EVENING_ONLY = "evening_only"
    MORNING_AFTERNOON = "morning_afternoon"
    AFTERNOON_EVENING = "afternoon_evening"
    MORNING_EVENING = "morning_evening"
    TRIPLE = "triple"


PATTERN_PERIODS: Mapping[DailyPattern, frozenset[Period]] = MappingProxyType(
    {
        DailyPattern.OFF: frozenset(),
        DailyPattern.MORNING_ONLY: frozenset({Period.MORNING}),
        DailyPattern.AFTERNOON_ONLY: frozenset({Period.AFTERNOON}),
        DailyPattern.EVENING_ONLY: frozenset({Period.EVENING}),
        DailyPattern.MORNING_AFTERNOON: frozenset(
            {Period.MORNING, Period.AFTERNOON}
        ),
        DailyPattern.AFTERNOON_EVENING: frozenset(
            {Period.AFTERNOON, Period.EVENING}
        ),
        DailyPattern.MORNING_EVENING: frozenset(
            {Period.MORNING, Period.EVENING}
        ),
        DailyPattern.TRIPLE: frozenset(PERIODS_V1),
    }
)


def allowed_daily_patterns(
    employment_type: EmploymentType,
    full_time_class: FullTimeClass | None,
) -> frozenset[DailyPattern]:
    """Return the v1 patterns allowed for one employment classification."""

    patterns = set(DailyPattern)
    if employment_type is EmploymentType.PART_TIME:
        patterns.remove(DailyPattern.TRIPLE)
    elif full_time_class is FullTimeClass.A:
        patterns.remove(DailyPattern.TRIPLE)
    elif full_time_class is FullTimeClass.B:
        patterns.remove(DailyPattern.MORNING_EVENING)
    else:  # Protected by canonical input validation.
        raise ValueError("full-time employee must have class A or B")
    return frozenset(patterns)
