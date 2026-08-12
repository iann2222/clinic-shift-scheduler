"""Mutable weekly authoring draft without Qt or solver dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ...enums import (
    PERIODS_V1,
    EmploymentType,
    FullTimeClass,
    Period,
    ShiftMode,
    Weekday,
)


class RoleMutationError(ValueError):
    """Raised when a role change would leave an invalid or ambiguous draft."""


@dataclass(slots=True)
class StaffingDraft:
    counts: dict[Period, dict[str, int]]

    @classmethod
    def zero(cls, roles: list[str]) -> StaffingDraft:
        return cls(
            {
                period: {role: 0 for role in roles}
                for period in PERIODS_V1
            }
        )


@dataclass(slots=True)
class WeeklyDemandDraft:
    weekdays: list[Weekday]
    is_open: bool
    staffing: StaffingDraft | None = None


@dataclass(slots=True)
class DateOverrideDraft:
    date: date
    is_open: bool
    staffing: StaffingDraft | None = None


@dataclass(slots=True)
class AvailableSlotDraft:
    date: date
    period: Period
    roles: list[str] | None = None


@dataclass(slots=True)
class EmployeeDraft:
    employee_id: str
    name: str
    employment_type: EmploymentType
    full_time_class: FullTimeClass | None
    full_time_class_declared: bool
    roles: list[str]
    fairness_group: str
    shift_mode: ShiftMode
    required_shifts: int | None = None
    target_shifts: int | None = None
    min_shifts: int | None = None
    max_shifts: int | None = None
    available_slots: list[AvailableSlotDraft] | None = None
    notes: str | None = None
    notes_declared: bool = False


@dataclass(slots=True)
class LeaveRequestDraft:
    employee_id: str
    date: date
    all_day: bool
    period: Period | None = None
    note: str | None = None
    note_declared: bool = False


@dataclass(slots=True)
class UnavailableSlotDraft:
    employee_id: str
    date: date
    period: Period


@dataclass(slots=True)
class ScheduleDraft:
    authoring_version: str
    schema_version: str
    start_date: date
    end_date: date
    holidays: list[date]
    holidays_declared: bool
    periods: list[Period]
    roles: list[str]
    weekly_demands: list[WeeklyDemandDraft]
    date_overrides: list[DateOverrideDraft]
    employees: list[EmployeeDraft]
    leave_requests: list[LeaveRequestDraft]
    unavailable_slots: list[UnavailableSlotDraft]
    date_overrides_declared: bool = True
    leave_requests_declared: bool = True
    unavailable_slots_declared: bool = True
    _revision: int = field(default=0, repr=False, compare=False)

    def touch(self) -> None:
        self._revision += 1

    def add_role(self, role: str) -> None:
        normalized = role.strip()
        if not normalized:
            raise RoleMutationError("職務名稱不可留空")
        if normalized in self.roles:
            raise RoleMutationError(f"職務已存在：{normalized}")
        self.roles.append(normalized)
        for staffing in self._staffing_plans():
            for period in PERIODS_V1:
                staffing.counts[period][normalized] = 0
        self.touch()

    def rename_role(self, old: str, new: str) -> None:
        normalized = new.strip()
        if old not in self.roles:
            raise RoleMutationError(f"找不到職務：{old}")
        if not normalized:
            raise RoleMutationError("職務名稱不可留空")
        if normalized != old and normalized in self.roles:
            raise RoleMutationError(f"職務已存在：{normalized}")
        if normalized == old:
            return
        index = self.roles.index(old)
        self.roles[index] = normalized
        for staffing in self._staffing_plans():
            for period in PERIODS_V1:
                counts = staffing.counts[period]
                counts[normalized] = counts.pop(old)
        for employee in self.employees:
            employee.roles = [
                normalized if role == old else role
                for role in employee.roles
            ]
            if employee.available_slots is not None:
                for slot in employee.available_slots:
                    if slot.roles is not None:
                        slot.roles = [
                            normalized if role == old else role
                            for role in slot.roles
                        ]
        self.touch()

    def delete_role(self, role: str) -> None:
        if role not in self.roles:
            raise RoleMutationError(f"找不到職務：{role}")
        if len(self.roles) == 1:
            raise RoleMutationError("至少必須保留一個職務")
        affected = [
            employee.name or employee.employee_id
            for employee in self.employees
            if employee.roles == [role]
        ]
        if affected:
            raise RoleMutationError(
                "下列人員只具備此職務，請先調整資格：" + "、".join(affected)
            )
        self.roles.remove(role)
        for staffing in self._staffing_plans():
            for period in PERIODS_V1:
                staffing.counts[period].pop(role, None)
        for employee in self.employees:
            employee.roles = [item for item in employee.roles if item != role]
            if employee.available_slots is not None:
                for slot in employee.available_slots:
                    if slot.roles is not None:
                        remaining = [
                            item for item in slot.roles if item != role
                        ]
                        slot.roles = remaining or None
        self.touch()

    def add_date_override(self, value: date, *, is_open: bool) -> None:
        if not self.start_date <= value <= self.end_date:
            raise ValueError("特定日期必須位於目前排班月份內")
        if any(item.date == value for item in self.date_overrides):
            raise ValueError(f"此日期已有調整：{value.isoformat()}")
        self.date_overrides.append(
            DateOverrideDraft(
                date=value,
                is_open=is_open,
                staffing=StaffingDraft.zero(self.roles) if is_open else None,
            )
        )
        self.date_overrides.sort(key=lambda item: item.date)
        self.date_overrides_declared = True
        self.touch()

    def remove_date_override(self, value: date) -> None:
        original_count = len(self.date_overrides)
        self.date_overrides = [
            item for item in self.date_overrides if item.date != value
        ]
        if len(self.date_overrides) == original_count:
            raise ValueError(f"找不到特定日期調整：{value.isoformat()}")
        self.touch()

    def _staffing_plans(self) -> tuple[StaffingDraft, ...]:
        return tuple(
            item.staffing
            for item in (*self.weekly_demands, *self.date_overrides)
            if item.staffing is not None
        )
