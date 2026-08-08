"""Closed vocabularies defined by the v1 specification."""

from __future__ import annotations

from enum import StrEnum


class Period(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


PERIODS_V1: tuple[Period, ...] = (
    Period.MORNING,
    Period.AFTERNOON,
    Period.EVENING,
)


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"


class FullTimeClass(StrEnum):
    A = "A"
    B = "B"


class ShiftMode(StrEnum):
    EXACT = "EXACT"
    RANGE = "RANGE"
    TARGET = "TARGET"


class Weekday(StrEnum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


WEEKDAY_BY_INDEX: tuple[Weekday, ...] = tuple(Weekday)

