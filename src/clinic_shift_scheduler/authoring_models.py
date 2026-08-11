"""Immutable, user-editable weekly-v1 authoring document models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from .enums import EmploymentType, FullTimeClass, PERIODS_V1, Period, ShiftMode, Weekday


@dataclass(frozen=True, slots=True)
class WeeklyPeriod:
    start_date: date
    end_date: date
    holidays: tuple[date, ...] = ()
    holidays_declared: bool = True

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }
        if self.holidays_declared:
            result["holidays"] = [item.isoformat() for item in self.holidays]
        return result


@dataclass(frozen=True, slots=True)
class StaffingPlan:
    """Dynamic role counts in fixed morning/afternoon/evening order."""

    counts: tuple[tuple[Period, tuple[tuple[str, int], ...]], ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], roles: tuple[str, ...]) -> StaffingPlan:
        return cls(
            tuple(
                (
                    period,
                    tuple((role, payload[period.value][role]) for role in roles),
                )
                for period in PERIODS_V1
            )
        )

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {
            period.value: dict(role_counts)
            for period, role_counts in self.counts
        }


@dataclass(frozen=True, slots=True)
class WeeklyDemandRule:
    weekdays: tuple[Weekday, ...]
    is_open: bool
    staffing: StaffingPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "weekdays": [item.value for item in self.weekdays],
            "is_open": self.is_open,
        }
        if self.staffing is not None:
            result["staffing"] = self.staffing.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class DateOverrideRule:
    date: date
    is_open: bool
    staffing: StaffingPlan | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "date": self.date.isoformat(),
            "is_open": self.is_open,
        }
        if self.staffing is not None:
            result["staffing"] = self.staffing.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class AuthoringAvailableSlot:
    date: date
    period: Period
    roles: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "date": self.date.isoformat(),
            "period": self.period.value,
        }
        if self.roles is not None:
            result["roles"] = list(self.roles)
        return result


@dataclass(frozen=True, slots=True)
class AuthoringEmployee:
    employee_id: str
    name: str
    employment_type: EmploymentType
    full_time_class: FullTimeClass | None
    full_time_class_declared: bool
    roles: tuple[str, ...]
    fairness_group: str
    shift_mode: ShiftMode
    required_shifts: int | None = None
    target_shifts: int | None = None
    min_shifts: int | None = None
    max_shifts: int | None = None
    available_slots: tuple[AuthoringAvailableSlot, ...] | None = None
    notes: str | None = None
    notes_declared: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "employee_id": self.employee_id,
            "name": self.name,
            "employment_type": self.employment_type.value,
            "roles": list(self.roles),
            "fairness_group": self.fairness_group,
            "shift_mode": self.shift_mode.value,
        }
        if self.full_time_class_declared:
            result["full_time_class"] = (
                None if self.full_time_class is None else self.full_time_class.value
            )
        for key, value in (
            ("required_shifts", self.required_shifts),
            ("target_shifts", self.target_shifts),
            ("min_shifts", self.min_shifts),
            ("max_shifts", self.max_shifts),
        ):
            if value is not None:
                result[key] = value
        if self.available_slots is not None:
            result["available_slots"] = [item.to_dict() for item in self.available_slots]
        if self.notes_declared:
            result["notes"] = self.notes
        return result


@dataclass(frozen=True, slots=True)
class AuthoringLeaveRequest:
    employee_id: str
    date: date
    all_day: bool
    period: Period | None = None
    note: str | None = None
    note_declared: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "employee_id": self.employee_id,
            "date": self.date.isoformat(),
            "all_day": self.all_day,
        }
        if self.period is not None:
            result["period"] = self.period.value
        if self.note_declared:
            result["note"] = self.note
        return result


@dataclass(frozen=True, slots=True)
class AuthoringUnavailableSlot:
    employee_id: str
    date: date
    period: Period

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "date": self.date.isoformat(),
            "period": self.period.value,
        }


@dataclass(frozen=True, slots=True)
class WeeklyAuthoringDocument:
    authoring_version: str
    schema_version: str
    period: WeeklyPeriod
    periods: tuple[Period, ...]
    roles: tuple[str, ...]
    weekly_demands: tuple[WeeklyDemandRule, ...]
    date_overrides: tuple[DateOverrideRule, ...]
    employees: tuple[AuthoringEmployee, ...]
    leave_requests: tuple[AuthoringLeaveRequest, ...]
    unavailable_slots: tuple[AuthoringUnavailableSlot, ...]
    date_overrides_declared: bool = True
    leave_requests_declared: bool = True
    unavailable_slots_declared: bool = True

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> WeeklyAuthoringDocument:
        """Validate raw user data before constructing a typed document."""

        from .authoring import parse_weekly_authoring

        return parse_weekly_authoring(payload)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "authoring_version": self.authoring_version,
            "schema_version": self.schema_version,
            "period": self.period.to_dict(),
            "periods": [item.value for item in self.periods],
            "roles": list(self.roles),
            "weekly_demands": [item.to_dict() for item in self.weekly_demands],
            "employees": [item.to_dict() for item in self.employees],
        }
        if self.date_overrides_declared:
            result["date_overrides"] = [item.to_dict() for item in self.date_overrides]
        if self.leave_requests_declared:
            result["leave_requests"] = [item.to_dict() for item in self.leave_requests]
        if self.unavailable_slots_declared:
            result["unavailable_slots"] = [
                item.to_dict() for item in self.unavailable_slots
            ]
        return result
