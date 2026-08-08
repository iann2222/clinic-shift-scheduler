"""Canonical expansion of already validated v1 input."""

from __future__ import annotations

from datetime import date, timedelta

from .enums import EmploymentType, PERIODS_V1, WEEKDAY_BY_INDEX
from .models import (
    AssignmentKey,
    DemandKey,
    NormalizedScheduleInput,
    PersonPeriodKey,
    ScheduleInput,
)


def date_range(start: date, end: date) -> tuple[date, ...]:
    days = (end - start).days
    return tuple(start + timedelta(days=offset) for offset in range(days + 1))


def normalize(schedule: ScheduleInput) -> NormalizedScheduleInput:
    """Expand defaults and precedence into a deterministic canonical form."""

    dates = date_range(schedule.period.start_date, schedule.period.end_date)
    closed_dates = set(schedule.period.closed_dates)
    closed_dates.update(
        day
        for day in dates
        if WEEKDAY_BY_INDEX[day.weekday()] in schedule.period.closed_weekdays
    )
    open_dates = tuple(day for day in dates if day not in closed_dates)

    demands: dict[DemandKey, int] = {
        (item.date, item.period, item.role): item.count for item in schedule.demands
    }
    employees = {employee.employee_id: employee for employee in schedule.employees}

    unavailable: set[PersonPeriodKey] = {
        (item.employee_id, item.date, item.period)
        for item in schedule.unavailable_slots
    }
    for leave in schedule.leave_requests:
        leave_periods = PERIODS_V1 if leave.all_day else (leave.period,)
        unavailable.update(
            (leave.employee_id, leave.date, period)
            for period in leave_periods
            if period is not None
        )

    declared_slots: dict[str, list] = {employee_id: [] for employee_id in employees}
    for slot in schedule.available_slots:
        declared_slots[slot.employee_id].append(slot)

    allowed: set[AssignmentKey] = set()
    for employee in schedule.employees:
        if (
            employee.employment_type is EmploymentType.FULL_TIME
            and not employee.available_slots_declared
        ):
            candidates = (
                (day, period, role)
                for day in open_dates
                for period in PERIODS_V1
                for role in employee.roles
            )
        else:
            candidates = (
                (slot.date, slot.period, role)
                for slot in declared_slots[employee.employee_id]
                for role in (slot.roles or employee.roles)
            )

        for day, period, role in candidates:
            if day not in open_dates:
                continue
            if (employee.employee_id, day, period) in unavailable:
                continue
            if demands.get((day, period, role), 0) <= 0:
                continue
            allowed.add((employee.employee_id, day, period, role))

    return NormalizedScheduleInput(
        source=schedule,
        dates=dates,
        open_dates=open_dates,
        closed_dates=frozenset(closed_dates),
        demands=NormalizedScheduleInput.readonly_mapping(demands),
        employees=NormalizedScheduleInput.readonly_mapping(employees),
        allowed_assignments=frozenset(allowed),
        unavailable_periods=frozenset(unavailable),
    )

