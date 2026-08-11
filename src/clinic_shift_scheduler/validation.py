"""Structural and semantic INPUT_INVALID validation for schema v1."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from typing import AbstractSet, Any, TypeVar

from .enums import (
    PERIODS_V1,
    EmploymentType,
    FullTimeClass,
    Period,
    ShiftMode,
    Weekday,
)
from .errors import InputValidationError, ValidationIssue
from .input_contracts import (
    CANONICAL_PERIOD_FIELDS,
    CANONICAL_TOP_LEVEL_FIELDS,
    EMPLOYEE_FIELDS,
)
from .models import (
    AvailableSlot,
    Demand,
    Employee,
    LeaveRequest,
    NormalizedScheduleInput,
    PeriodConfig,
    ScheduleInput,
    UnavailableSlot,
)
from .normalization import date_range, normalize


E = TypeVar("E")

class _Issues:
    def __init__(self) -> None:
        self.items: list[ValidationIssue] = []

    def add(self, code: str, path: str, message: str) -> None:
        self.items.append(ValidationIssue(code=code, path=path, message=message))

    def unknown_keys(
        self,
        value: Mapping[str, Any],
        allowed: AbstractSet[str],
        path: str,
    ) -> None:
        for key in sorted(set(value) - allowed):
            self.add("unknown_field", f"{path}.{key}", "field is not allowed in schema v1")

    def raise_if_any(self) -> None:
        if self.items:
            raise InputValidationError(self.items)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _mapping(value: object, path: str, issues: _Issues) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        issues.add("invalid_type", path, "must be an object")
        return None
    return value


def _list(value: object, path: str, issues: _Issues) -> Sequence[Any] | None:
    if not _is_sequence(value):
        issues.add("invalid_type", path, "must be an array")
        return None
    return value


def _text(value: object, path: str, issues: _Issues) -> str | None:
    if not isinstance(value, str) or not value.strip():
        issues.add("invalid_string", path, "must be a non-empty string")
        return None
    return value.strip()


def _integer(value: object, path: str, issues: _Issues) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        issues.add("invalid_integer", path, "must be an integer")
        return None
    if value < 0:
        issues.add("negative_value", path, "must be greater than or equal to 0")
        return None
    return value


def _date(value: object, path: str, issues: _Issues) -> date | None:
    if not isinstance(value, str):
        issues.add("invalid_date", path, "must be an ISO date string (YYYY-MM-DD)")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        issues.add("invalid_date", path, "must be a valid ISO date (YYYY-MM-DD)")
        return None


def _enum(value: object, enum_type: type[E], path: str, issues: _Issues) -> E | None:
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except (TypeError, ValueError):
        allowed = ", ".join(item.value for item in enum_type)  # type: ignore[attr-defined]
        issues.add("invalid_enum", path, f"must be one of: {allowed}")
        return None


def _string_list(
    value: object,
    path: str,
    issues: _Issues,
    *,
    non_empty: bool = True,
) -> tuple[str, ...]:
    values = _list(value, path, issues)
    if values is None:
        return ()
    result: list[str] = []
    for index, item in enumerate(values):
        parsed = _text(item, f"{path}[{index}]", issues)
        if parsed is not None:
            result.append(parsed)
    if non_empty and not result:
        issues.add("empty_list", path, "must contain at least one value")
    if len(set(result)) != len(result):
        issues.add("duplicate_value", path, "must not contain duplicate values")
    return tuple(result)


def _date_list(value: object, path: str, issues: _Issues) -> frozenset[date]:
    values = _list(value, path, issues)
    if values is None:
        return frozenset()
    result: list[date] = []
    for index, item in enumerate(values):
        parsed = _date(item, f"{path}[{index}]", issues)
        if parsed is not None:
            result.append(parsed)
    return frozenset(result)


def _parse_period(payload: object, issues: _Issues) -> PeriodConfig | None:
    value = _mapping(payload, "$.period", issues)
    if value is None:
        return None
    issues.unknown_keys(value, CANONICAL_PERIOD_FIELDS, "$.period")
    start = _date(value.get("start_date"), "$.period.start_date", issues)
    end = _date(value.get("end_date"), "$.period.end_date", issues)

    weekdays_raw = value.get("closed_weekdays", [])
    weekdays_list = _list(weekdays_raw, "$.period.closed_weekdays", issues) or ()
    weekdays = frozenset(
        parsed
        for index, item in enumerate(weekdays_list)
        if (parsed := _enum(item, Weekday, f"$.period.closed_weekdays[{index}]", issues))
        is not None
    )
    closed = _date_list(value.get("closed_dates", []), "$.period.closed_dates", issues)
    holidays = _date_list(value.get("holidays", []), "$.period.holidays", issues)
    if start is None or end is None:
        return None
    if start > end:
        issues.add("invalid_period", "$.period", "start_date must not be after end_date")
        return None
    for label, days in (("closed_dates", closed), ("holidays", holidays)):
        for day in sorted(days):
            if not start <= day <= end:
                issues.add(
                    "date_out_of_range",
                    f"$.period.{label}",
                    f"{day.isoformat()} is outside the scheduling period",
                )
    return PeriodConfig(start, end, weekdays, closed, holidays)


def _parse_periods(payload: object, issues: _Issues) -> tuple[Period, ...]:
    values = _list(payload, "$.periods", issues)
    if values is None:
        return ()
    parsed = tuple(
        item
        for index, value in enumerate(values)
        if (item := _enum(value, Period, f"$.periods[{index}]", issues)) is not None
    )
    if parsed != PERIODS_V1:
        issues.add(
            "invalid_periods_v1",
            "$.periods",
            "v1 periods must be exactly [morning, afternoon, evening] in this order",
        )
    return parsed


def _parse_demands(payload: object, issues: _Issues) -> tuple[Demand, ...]:
    values = _list(payload, "$.demands", issues)
    if values is None:
        return ()
    result: list[Demand] = []
    allowed = {"date", "period", "role", "count"}
    for index, raw in enumerate(values):
        path = f"$.demands[{index}]"
        value = _mapping(raw, path, issues)
        if value is None:
            continue
        issues.unknown_keys(value, allowed, path)
        day = _date(value.get("date"), f"{path}.date", issues)
        period = _enum(value.get("period"), Period, f"{path}.period", issues)
        role = _text(value.get("role"), f"{path}.role", issues)
        count = _integer(value.get("count"), f"{path}.count", issues)
        if None not in (day, period, role, count):
            result.append(Demand(day, period, role, count))  # type: ignore[arg-type]
    return tuple(result)


def _parse_available_slots(
    payload: object,
    employee_id: str,
    path: str,
    issues: _Issues,
) -> tuple[AvailableSlot, ...]:
    values = _list(payload, path, issues)
    if values is None:
        return ()
    result: list[AvailableSlot] = []
    allowed = {"date", "period", "roles"}
    for index, raw in enumerate(values):
        item_path = f"{path}[{index}]"
        value = _mapping(raw, item_path, issues)
        if value is None:
            continue
        issues.unknown_keys(value, allowed, item_path)
        day = _date(value.get("date"), f"{item_path}.date", issues)
        period = _enum(value.get("period"), Period, f"{item_path}.period", issues)
        roles = None
        if "roles" in value:
            roles = frozenset(_string_list(value["roles"], f"{item_path}.roles", issues))
        if day is not None and period is not None:
            result.append(AvailableSlot(employee_id, day, period, roles))
    return tuple(result)


def _validate_shift_fields(
    value: Mapping[str, Any], mode: ShiftMode | None, path: str, issues: _Issues
) -> tuple[int | None, int | None, int | None, int | None]:
    names = ("required_shifts", "target_shifts", "min_shifts", "max_shifts")
    parsed = {
        name: _integer(value[name], f"{path}.{name}", issues) if name in value else None
        for name in names
    }
    present = {name for name in names if name in value}
    if mode is ShiftMode.EXACT:
        if present != {"required_shifts"}:
            issues.add(
                "invalid_shift_fields",
                path,
                "EXACT accepts only required_shifts",
            )
    elif mode is ShiftMode.RANGE:
        if present != {"min_shifts", "max_shifts"}:
            issues.add(
                "invalid_shift_fields",
                path,
                "RANGE requires only min_shifts and max_shifts",
            )
        minimum, maximum = parsed["min_shifts"], parsed["max_shifts"]
        if minimum is not None and maximum is not None and minimum > maximum:
            issues.add("invalid_shift_range", path, "min_shifts must not exceed max_shifts")
    elif mode is ShiftMode.TARGET:
        if "target_shifts" not in present or "required_shifts" in present:
            issues.add(
                "invalid_shift_fields",
                path,
                "TARGET requires target_shifts, forbids required_shifts, and allows optional min/max",
            )
        target = parsed["target_shifts"]
        minimum, maximum = parsed["min_shifts"], parsed["max_shifts"]
        if target is not None and minimum is not None and minimum > target:
            issues.add("target_outside_bounds", path, "min_shifts must not exceed target_shifts")
        if target is not None and maximum is not None and target > maximum:
            issues.add("target_outside_bounds", path, "target_shifts must not exceed max_shifts")
        if minimum is not None and maximum is not None and minimum > maximum:
            issues.add("invalid_shift_range", path, "min_shifts must not exceed max_shifts")
    return (
        parsed["required_shifts"],
        parsed["target_shifts"],
        parsed["min_shifts"],
        parsed["max_shifts"],
    )


def _parse_employees(
    payload: object, issues: _Issues
) -> tuple[tuple[Employee, ...], tuple[AvailableSlot, ...]]:
    values = _list(payload, "$.employees", issues)
    if values is None:
        return (), ()
    if not values:
        issues.add("empty_list", "$.employees", "must contain at least one employee")
    employees: list[Employee] = []
    available: list[AvailableSlot] = []
    for index, raw in enumerate(values):
        path = f"$.employees[{index}]"
        value = _mapping(raw, path, issues)
        if value is None:
            continue
        issues.unknown_keys(value, EMPLOYEE_FIELDS, path)
        employee_id = _text(value.get("employee_id"), f"{path}.employee_id", issues)
        name = _text(value.get("name"), f"{path}.name", issues)
        employment_type = _enum(
            value.get("employment_type"), EmploymentType, f"{path}.employment_type", issues
        )
        roles = frozenset(_string_list(value.get("roles"), f"{path}.roles", issues))
        fairness_group = _text(value.get("fairness_group"), f"{path}.fairness_group", issues)
        mode = _enum(value.get("shift_mode"), ShiftMode, f"{path}.shift_mode", issues)

        full_time_class = None
        if employment_type is EmploymentType.FULL_TIME:
            full_time_class = _enum(
                value.get("full_time_class"),
                FullTimeClass,
                f"{path}.full_time_class",
                issues,
            )
        elif employment_type is EmploymentType.PART_TIME:
            if value.get("full_time_class") is not None:
                issues.add(
                    "invalid_full_time_class",
                    f"{path}.full_time_class",
                    "part-time employee must omit full_time_class or set it to null",
                )
            if mode is ShiftMode.TARGET:
                issues.add(
                    "unsupported_part_time_target",
                    f"{path}.shift_mode",
                    "part-time v1 supports only EXACT or RANGE",
                )

        required, target, minimum, maximum = _validate_shift_fields(value, mode, path, issues)
        declared = "available_slots" in value
        slots: tuple[AvailableSlot, ...] = ()
        if declared and employee_id is not None:
            slots = _parse_available_slots(
                value["available_slots"], employee_id, f"{path}.available_slots", issues
            )
            available.extend(slots)
        if None not in (employee_id, name, employment_type, fairness_group, mode) and roles:
            employees.append(
                Employee(
                    employee_id=employee_id,
                    name=name,
                    employment_type=employment_type,
                    full_time_class=full_time_class,
                    roles=roles,
                    fairness_group=fairness_group,
                    shift_mode=mode,
                    required_shifts=required,
                    target_shifts=target,
                    min_shifts=minimum,
                    max_shifts=maximum,
                    available_slots_declared=declared,
                )
            )
    return tuple(employees), tuple(available)


def _parse_unavailable(payload: object, issues: _Issues) -> tuple[UnavailableSlot, ...]:
    values = _list(payload, "$.unavailable_slots", issues)
    if values is None:
        return ()
    result: list[UnavailableSlot] = []
    allowed = {"employee_id", "date", "period"}
    for index, raw in enumerate(values):
        path = f"$.unavailable_slots[{index}]"
        value = _mapping(raw, path, issues)
        if value is None:
            continue
        issues.unknown_keys(value, allowed, path)
        employee_id = _text(value.get("employee_id"), f"{path}.employee_id", issues)
        day = _date(value.get("date"), f"{path}.date", issues)
        period = _enum(value.get("period"), Period, f"{path}.period", issues)
        if None not in (employee_id, day, period):
            result.append(UnavailableSlot(employee_id, day, period))  # type: ignore[arg-type]
    return tuple(result)


def _parse_leave(payload: object, issues: _Issues) -> tuple[LeaveRequest, ...]:
    values = _list(payload, "$.leave_requests", issues)
    if values is None:
        return ()
    result: list[LeaveRequest] = []
    allowed = {"employee_id", "date", "period", "all_day", "note"}
    for index, raw in enumerate(values):
        path = f"$.leave_requests[{index}]"
        value = _mapping(raw, path, issues)
        if value is None:
            continue
        issues.unknown_keys(value, allowed, path)
        employee_id = _text(value.get("employee_id"), f"{path}.employee_id", issues)
        day = _date(value.get("date"), f"{path}.date", issues)
        all_day_raw = value.get("all_day")
        if not isinstance(all_day_raw, bool):
            issues.add("invalid_boolean", f"{path}.all_day", "must be a boolean")
            continue
        period = None
        if all_day_raw:
            if "period" in value:
                issues.add("invalid_leave_period", f"{path}.period", "must be omitted for all-day leave")
        else:
            period = _enum(value.get("period"), Period, f"{path}.period", issues)
        note = value.get("note")
        if note is not None and not isinstance(note, str):
            issues.add("invalid_type", f"{path}.note", "must be a string or null")
            note = None
        if employee_id is not None and day is not None and (all_day_raw or period is not None):
            result.append(LeaveRequest(employee_id, day, all_day_raw, period, note))
    return tuple(result)


def _deduplicate_records(records: tuple[E, ...]) -> tuple[E, ...]:
    return tuple(dict.fromkeys(records))


def _semantic_validation(
    schedule: ScheduleInput,
    issues: _Issues,
) -> ScheduleInput:
    period = schedule.period
    valid_dates = set(date_range(period.start_date, period.end_date))
    closed_dates = set(period.closed_dates)
    closed_dates.update(
        day
        for day in valid_dates
        if Weekday(tuple(Weekday)[day.weekday()]) in period.closed_weekdays
    )
    open_dates = valid_dates - closed_dates
    role_set = set(schedule.roles)

    ids: set[str] = set()
    employee_by_id: dict[str, Employee] = {}
    employee_index_by_id: dict[str, int] = {}
    group_signatures: dict[str, tuple[EmploymentType, FullTimeClass | None]] = {}
    for index, employee in enumerate(schedule.employees):
        if employee.employee_id in ids:
            issues.add(
                "duplicate_employee_id",
                f"$.employees[{index}].employee_id",
                f"employee_id {employee.employee_id!r} must be unique",
            )
        ids.add(employee.employee_id)
        employee_by_id.setdefault(employee.employee_id, employee)
        employee_index_by_id.setdefault(employee.employee_id, index)
        unknown_roles = employee.roles - role_set
        if unknown_roles:
            issues.add(
                "unknown_role",
                f"$.employees[{index}].roles",
                f"unknown roles: {', '.join(sorted(unknown_roles))}",
            )
        signature = (employee.employment_type, employee.full_time_class)
        prior = group_signatures.setdefault(employee.fairness_group, signature)
        if prior != signature:
            issues.add(
                "incompatible_fairness_group",
                f"$.employees[{index}].fairness_group",
                "a fairness_group cannot mix employment types or full-time classes",
            )

    demand_by_key: dict[tuple[date, Period, str], Demand] = {}
    for index, demand in enumerate(schedule.demands):
        path = f"$.demands[{index}]"
        if demand.date not in valid_dates:
            issues.add("date_out_of_range", f"{path}.date", "demand date is outside the period")
        if demand.date in closed_dates:
            issues.add("demand_on_closed_date", path, "closed dates must not contain demand records")
        if demand.role not in role_set:
            issues.add("unknown_role", f"{path}.role", f"unknown role: {demand.role}")
        key = (demand.date, demand.period, demand.role)
        prior = demand_by_key.get(key)
        if prior is not None and prior.count != demand.count:
            issues.add("conflicting_duplicate", path, "duplicate demand key has conflicting counts")
        demand_by_key.setdefault(key, demand)

    for day in sorted(open_dates):
        for period_value in PERIODS_V1:
            for role in schedule.roles:
                key = (day, period_value, role)
                if key not in demand_by_key:
                    issues.add(
                        "missing_demand",
                        "$.demands",
                        f"missing explicit demand for ({day}, {period_value.value}, {role})",
                    )

    def validate_person_period(
        employee_id: str, day: date, path: str, roles: frozenset[str] | None = None
    ) -> None:
        employee = employee_by_id.get(employee_id)
        if employee is None:
            issues.add("unknown_employee_id", f"{path}.employee_id", f"unknown employee_id: {employee_id}")
        if day not in valid_dates:
            issues.add("date_out_of_range", f"{path}.date", "date is outside the period")
        if employee is not None and roles is not None:
            unknown = roles - role_set
            unqualified = roles - employee.roles
            if unknown:
                issues.add("unknown_role", f"{path}.roles", f"unknown roles: {', '.join(sorted(unknown))}")
            if unqualified:
                issues.add(
                    "unqualified_available_role",
                    f"{path}.roles",
                    f"employee is not qualified for: {', '.join(sorted(unqualified))}",
                )

    available_index_by_employee: dict[str, int] = {}
    for slot in schedule.available_slots:
        slot_index = available_index_by_employee.get(slot.employee_id, 0)
        available_index_by_employee[slot.employee_id] = slot_index + 1
        employee_index = employee_index_by_id.get(slot.employee_id, "?")
        validate_person_period(
            slot.employee_id,
            slot.date,
            f"$.employees[{employee_index}].available_slots[{slot_index}]",
            slot.roles,
        )
    for index, slot in enumerate(schedule.unavailable_slots):
        validate_person_period(slot.employee_id, slot.date, f"$.unavailable_slots[{index}]")
    for index, leave in enumerate(schedule.leave_requests):
        validate_person_period(leave.employee_id, leave.date, f"$.leave_requests[{index}]")

    canonical_demands = tuple(demand_by_key.values())
    return replace(
        schedule,
        demands=canonical_demands,
        available_slots=_deduplicate_records(schedule.available_slots),
        unavailable_slots=_deduplicate_records(schedule.unavailable_slots),
        leave_requests=_deduplicate_records(schedule.leave_requests),
    )


def validate_and_normalize(payload: Mapping[str, Any]) -> NormalizedScheduleInput:
    """Validate raw v1 input and return immutable normalized data.

    All structural or semantic failures are aggregated into one
    :class:`InputValidationError` with status ``INPUT_INVALID``.
    """

    issues = _Issues()
    root = _mapping(payload, "$", issues)
    if root is None:
        issues.raise_if_any()
        raise AssertionError("unreachable")
    issues.unknown_keys(root, CANONICAL_TOP_LEVEL_FIELDS, "$")

    version = _text(root.get("schema_version"), "$.schema_version", issues)
    if version is not None and version != "v1":
        issues.add("unsupported_schema_version", "$.schema_version", "only schema version v1 is supported")
    period = _parse_period(root.get("period"), issues)
    periods = _parse_periods(root.get("periods"), issues)
    roles = _string_list(root.get("roles"), "$.roles", issues)
    demands = _parse_demands(root.get("demands"), issues)
    employees, available = _parse_employees(root.get("employees"), issues)
    unavailable = _parse_unavailable(root.get("unavailable_slots", []), issues)
    leave = _parse_leave(root.get("leave_requests", []), issues)
    issues.raise_if_any()

    assert version is not None and period is not None
    schedule = ScheduleInput(
        schema_version=version,
        period=period,
        periods=periods,
        roles=roles,
        demands=demands,
        employees=employees,
        available_slots=available,
        unavailable_slots=unavailable,
        leave_requests=leave,
    )
    schedule = _semantic_validation(schedule, issues)
    issues.raise_if_any()
    return normalize(schedule)
