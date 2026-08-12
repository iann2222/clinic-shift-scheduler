"""Mutable weekly authoring draft without Qt or solver dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

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

    def add_employee(self) -> EmployeeDraft:
        employee_id = self._new_employee_id()
        employee = EmployeeDraft(
            employee_id=employee_id,
            name="新員工",
            employment_type=EmploymentType.FULL_TIME,
            full_time_class=FullTimeClass.A,
            full_time_class_declared=True,
            roles=[self.roles[0]],
            fairness_group="A_GENERAL",
            shift_mode=ShiftMode.EXACT,
            required_shifts=0,
            available_slots=None,
        )
        self.employees.append(employee)
        self.touch()
        return employee

    def remove_employee(self, employee_id: str) -> None:
        if not any(
            employee.employee_id == employee_id
            for employee in self.employees
        ):
            raise ValueError(f"找不到人員：{employee_id}")
        self.employees = [
            employee
            for employee in self.employees
            if employee.employee_id != employee_id
        ]
        self.leave_requests = [
            item
            for item in self.leave_requests
            if item.employee_id != employee_id
        ]
        self.unavailable_slots = [
            item
            for item in self.unavailable_slots
            if item.employee_id != employee_id
        ]
        self.touch()

    def set_employee_type(
        self,
        employee: EmployeeDraft,
        employment_type: EmploymentType,
    ) -> None:
        if employee.employment_type is employment_type:
            return
        employee.employment_type = employment_type
        if employment_type is EmploymentType.FULL_TIME:
            employee.full_time_class = FullTimeClass.A
            employee.full_time_class_declared = True
            employee.available_slots = None
            if employee.fairness_group.startswith("PT_"):
                employee.fairness_group = "A_GENERAL"
        else:
            employee.full_time_class = None
            employee.full_time_class_declared = True
            employee.available_slots = []
            self.unavailable_slots = [
                item
                for item in self.unavailable_slots
                if item.employee_id != employee.employee_id
            ]
            if employee.shift_mode is ShiftMode.TARGET:
                self.set_shift_mode(employee, ShiftMode.RANGE)
            if not employee.fairness_group.startswith("PT_"):
                employee.fairness_group = "PT_GENERAL"
        self.touch()

    def set_shift_mode(
        self,
        employee: EmployeeDraft,
        shift_mode: ShiftMode,
    ) -> None:
        if (
            employee.employment_type is EmploymentType.PART_TIME
            and shift_mode is ShiftMode.TARGET
        ):
            raise ValueError("兼職人員只支援固定班次或班次範圍")
        employee.shift_mode = shift_mode
        employee.required_shifts = None
        employee.target_shifts = None
        employee.min_shifts = None
        employee.max_shifts = None
        if shift_mode is ShiftMode.EXACT:
            employee.required_shifts = 0
        elif shift_mode is ShiftMode.RANGE:
            employee.min_shifts = 0
            employee.max_shifts = 0
        else:
            employee.target_shifts = 0
        self.touch()

    def set_all_day_leave(
        self,
        employee_id: str,
        value: date,
        enabled: bool,
    ) -> None:
        self._assert_employee_date(employee_id, value)
        self.leave_requests = [
            item
            for item in self.leave_requests
            if not (item.employee_id == employee_id and item.date == value)
        ]
        if enabled:
            self.leave_requests.append(
                LeaveRequestDraft(employee_id, value, True)
            )
            self._remove_unavailable(employee_id, value)
            self._remove_available(employee_id, value)
        self.leave_requests_declared = True
        self.touch()

    def set_period_availability(
        self,
        employee_id: str,
        value: date,
        period: Period,
        state: str,
    ) -> None:
        employee = self._assert_employee_date(employee_id, value)
        if self._all_day_leave(employee_id, value) is not None:
            raise ValueError("請先取消整日請假，再調整個別時段")
        allowed = {"available", "unavailable", "leave"}
        if state not in allowed:
            raise ValueError(f"不支援的可排狀態：{state}")
        self.leave_requests = [
            item
            for item in self.leave_requests
            if not (
                item.employee_id == employee_id
                and item.date == value
                and item.period is period
            )
        ]
        self.unavailable_slots = [
            item
            for item in self.unavailable_slots
            if not (
                item.employee_id == employee_id
                and item.date == value
                and item.period is period
            )
        ]
        self._remove_available(employee_id, value, period)
        if state == "leave":
            self.leave_requests.append(
                LeaveRequestDraft(employee_id, value, False, period)
            )
        elif employee.employment_type is EmploymentType.FULL_TIME:
            if state == "unavailable":
                self.unavailable_slots.append(
                    UnavailableSlotDraft(employee_id, value, period)
                )
        elif state == "available":
            assert employee.available_slots is not None
            employee.available_slots.append(
                AvailableSlotDraft(value, period, None)
            )
            employee.available_slots.sort(
                key=lambda item: (item.date, PERIODS_V1.index(item.period))
            )
        self.leave_requests_declared = True
        self.unavailable_slots_declared = True
        self.touch()

    def availability_state(
        self,
        employee: EmployeeDraft,
        value: date,
        period: Period,
    ) -> str:
        if self._all_day_leave(employee.employee_id, value) is not None:
            return "leave"
        if any(
            item.employee_id == employee.employee_id
            and item.date == value
            and item.period is period
            for item in self.leave_requests
        ):
            return "leave"
        if employee.employment_type is EmploymentType.FULL_TIME:
            return (
                "unavailable"
                if any(
                    item.employee_id == employee.employee_id
                    and item.date == value
                    and item.period is period
                    for item in self.unavailable_slots
                )
                else "available"
            )
        return (
            "available"
            if employee.available_slots is not None
            and any(
                item.date == value and item.period is period
                for item in employee.available_slots
            )
            else "unavailable"
        )

    def set_leave_note(
        self,
        employee_id: str,
        value: date,
        period: Period | None,
        note: str,
    ) -> None:
        target = next(
            (
                item
                for item in self.leave_requests
                if item.employee_id == employee_id
                and item.date == value
                and item.period is period
            ),
            None,
        )
        if target is None:
            raise ValueError("所選日期或時段不是請假狀態")
        target.note = note or None
        target.note_declared = bool(note)
        self.touch()

    def available_slot(
        self,
        employee: EmployeeDraft,
        value: date,
        period: Period,
    ) -> AvailableSlotDraft | None:
        if employee.available_slots is None:
            return None
        return next(
            (
                item
                for item in employee.available_slots
                if item.date == value and item.period is period
            ),
            None,
        )

    def set_available_slot_roles(
        self,
        employee: EmployeeDraft,
        value: date,
        period: Period,
        roles: list[str] | None,
    ) -> None:
        slot = self.available_slot(employee, value, period)
        if slot is None:
            raise ValueError("所選時段不是兼職明確可排時段")
        if roles is not None:
            invalid = set(roles) - set(employee.roles)
            if invalid:
                raise ValueError("可排職務必須包含於該員工的職務資格")
            if not roles:
                raise ValueError("限制職務時至少必須選擇一項")
        slot.roles = None if roles is None else list(roles)
        self.touch()

    def _new_employee_id(self) -> str:
        existing = {employee.employee_id for employee in self.employees}
        while True:
            candidate = f"EMP-{uuid4().hex[:8].upper()}"
            if candidate not in existing:
                return candidate

    def _assert_employee_date(
        self,
        employee_id: str,
        value: date,
    ) -> EmployeeDraft:
        if not self.start_date <= value <= self.end_date:
            raise ValueError("日期必須位於目前排班月份內")
        employee = next(
            (
                item
                for item in self.employees
                if item.employee_id == employee_id
            ),
            None,
        )
        if employee is None:
            raise ValueError(f"找不到人員：{employee_id}")
        return employee

    def _all_day_leave(
        self,
        employee_id: str,
        value: date,
    ) -> LeaveRequestDraft | None:
        return next(
            (
                item
                for item in self.leave_requests
                if item.employee_id == employee_id
                and item.date == value
                and item.all_day
            ),
            None,
        )

    def _remove_unavailable(self, employee_id: str, value: date) -> None:
        self.unavailable_slots = [
            item
            for item in self.unavailable_slots
            if not (item.employee_id == employee_id and item.date == value)
        ]

    def _remove_available(
        self,
        employee_id: str,
        value: date,
        period: Period | None = None,
    ) -> None:
        employee = next(
            (
                item
                for item in self.employees
                if item.employee_id == employee_id
            ),
            None,
        )
        if employee is None or employee.available_slots is None:
            return
        employee.available_slots = [
            item
            for item in employee.available_slots
            if not (
                item.date == value
                and (period is None or item.period is period)
            )
        ]

    def _staffing_plans(self) -> tuple[StaffingDraft, ...]:
        return tuple(
            item.staffing
            for item in (*self.weekly_demands, *self.date_overrides)
            if item.staffing is not None
        )
