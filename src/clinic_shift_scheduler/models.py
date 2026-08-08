"""Immutable v1 input and normalized domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping

from .enums import EmploymentType, FullTimeClass, Period, ShiftMode, Weekday


@dataclass(frozen=True, slots=True)
class PeriodConfig:
    start_date: date
    end_date: date
    closed_weekdays: frozenset[Weekday]
    closed_dates: frozenset[date]
    holidays: frozenset[date]


@dataclass(frozen=True, slots=True)
class Demand:
    date: date
    period: Period
    role: str
    count: int


@dataclass(frozen=True, slots=True)
class Employee:
    employee_id: str
    name: str
    employment_type: EmploymentType
    full_time_class: FullTimeClass | None
    roles: frozenset[str]
    fairness_group: str
    shift_mode: ShiftMode
    required_shifts: int | None = None
    target_shifts: int | None = None
    min_shifts: int | None = None
    max_shifts: int | None = None
    available_slots_declared: bool = False


@dataclass(frozen=True, slots=True)
class AvailableSlot:
    employee_id: str
    date: date
    period: Period
    roles: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class UnavailableSlot:
    employee_id: str
    date: date
    period: Period


@dataclass(frozen=True, slots=True)
class LeaveRequest:
    employee_id: str
    date: date
    all_day: bool
    period: Period | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduleInput:
    schema_version: str
    period: PeriodConfig
    periods: tuple[Period, ...]
    roles: tuple[str, ...]
    demands: tuple[Demand, ...]
    employees: tuple[Employee, ...]
    available_slots: tuple[AvailableSlot, ...]
    unavailable_slots: tuple[UnavailableSlot, ...]
    leave_requests: tuple[LeaveRequest, ...]


AssignmentKey = tuple[str, date, Period, str]
DemandKey = tuple[date, Period, str]
PersonPeriodKey = tuple[str, date, Period]


@dataclass(frozen=True, slots=True)
class NormalizedScheduleInput:
    """Canonical, solver-ready data without any solver variables."""

    source: ScheduleInput
    dates: tuple[date, ...]
    open_dates: tuple[date, ...]
    closed_dates: frozenset[date]
    demands: Mapping[DemandKey, int]
    employees: Mapping[str, Employee]
    allowed_assignments: frozenset[AssignmentKey]
    unavailable_periods: frozenset[PersonPeriodKey]

    @staticmethod
    def readonly_mapping(values: Mapping) -> Mapping:
        return MappingProxyType(dict(values))

