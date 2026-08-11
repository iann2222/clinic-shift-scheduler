"""Expand compact weekly authoring input into the canonical v1 contract.

Users maintain weekly opening and staffing templates.  The solver-facing v1
contract remains explicit per date, period, and role so its existing strict
validation is unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set as AbstractSet
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .authoring_models import (
    AuthoringAvailableSlot,
    AuthoringEmployee,
    AuthoringLeaveRequest,
    AuthoringUnavailableSlot,
    DateOverrideRule,
    StaffingPlan,
    WeeklyAuthoringDocument,
    WeeklyDemandRule,
    WeeklyPeriod,
)
from .enums import (
    PERIODS_V1,
    WEEKDAY_BY_INDEX,
    EmploymentType,
    FullTimeClass,
    Period,
    ShiftMode,
    Weekday,
)
from .errors import InputValidationError, ValidationIssue
from .json_io import read_json_object, write_json_object_atomic
from .input_contracts import (
    DATE_OVERRIDE_FIELDS,
    WEEKLY_DEMAND_FIELDS,
    WEEKLY_PERIOD_FIELDS,
    WEEKLY_TOP_LEVEL_FIELDS,
)
from .models import NormalizedScheduleInput


WEEKLY_AUTHORING_VERSION = "weekly-v1"


def _invalid(code: str, path: str, message: str) -> None:
    raise InputValidationError((ValidationIssue(code, path, message),))


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _invalid("invalid_type", path, "must be an object")
    return value


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _invalid("invalid_type", path, "must be an array")
    return value


def _date(value: object, path: str) -> date:
    if not isinstance(value, str):
        _invalid("invalid_date", path, "must be an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError:
        _invalid("invalid_date", path, "must be a valid ISO date (YYYY-MM-DD)")


def _reject_unknown(
    value: Mapping[str, Any],
    allowed: AbstractSet[str],
    path: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid(
            "unknown_field",
            f"{path}.{unknown[0]}",
            f"field is not allowed in {WEEKLY_AUTHORING_VERSION}",
        )


def _parse_staffing(
    value: object,
    path: str,
    roles: tuple[str, ...],
) -> dict[str, dict[str, int]]:
    staffing = _mapping(value, path)
    expected_periods = tuple(period.value for period in PERIODS_V1)
    if set(staffing) != set(expected_periods):
        _invalid(
            "incomplete_weekly_staffing",
            path,
            "must explicitly contain morning, afternoon, and evening",
        )

    parsed: dict[str, dict[str, int]] = {}
    for period in expected_periods:
        role_counts = _mapping(staffing[period], f"{path}.{period}")
        if set(role_counts) != set(roles):
            _invalid(
                "incomplete_weekly_staffing",
                f"{path}.{period}",
                "must explicitly contain every role exactly once",
            )
        parsed[period] = {}
        for role in roles:
            count = role_counts[role]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                _invalid(
                    "invalid_demand_count",
                    f"{path}.{period}.{role}",
                    "must be a non-negative integer",
                )
            parsed[period][role] = count
    return parsed


def _expand_weekly_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and expand a raw weekly mapping into canonical v1."""

    root = _mapping(payload, "$")
    if root.get("authoring_version") != WEEKLY_AUTHORING_VERSION:
        _invalid(
            "unsupported_authoring_version",
            "$.authoring_version",
            f"must be {WEEKLY_AUTHORING_VERSION}",
        )
    if "demands" in root:
        _invalid(
            "conflicting_demand_sources",
            "$.demands",
            "weekly authoring input must not also provide canonical demands",
        )
    _reject_unknown(root, WEEKLY_TOP_LEVEL_FIELDS, "$")

    period = _mapping(root.get("period"), "$.period")
    _reject_unknown(period, WEEKLY_PERIOD_FIELDS, "$.period")
    start = _date(period.get("start_date"), "$.period.start_date")
    end = _date(period.get("end_date"), "$.period.end_date")
    if start > end:
        _invalid("invalid_period", "$.period", "start_date must not be after end_date")

    roles_raw = _sequence(root.get("roles"), "$.roles")
    roles = tuple(roles_raw)
    if (
        not roles
        or any(not isinstance(role, str) or not role.strip() for role in roles)
        or len(set(roles)) != len(roles)
    ):
        _invalid("invalid_roles", "$.roles", "must contain unique non-empty strings")

    templates = _sequence(root.get("weekly_demands"), "$.weekly_demands")
    weekly: dict[Weekday, dict[str, dict[str, int]] | None] = {}
    for index, raw in enumerate(templates):
        path = f"$.weekly_demands[{index}]"
        item = _mapping(raw, path)
        _reject_unknown(item, WEEKLY_DEMAND_FIELDS, path)
        weekday_values = _sequence(item.get("weekdays"), f"{path}.weekdays")
        if not weekday_values:
            _invalid("empty_weekdays", f"{path}.weekdays", "must not be empty")
        parsed_weekdays: list[Weekday] = []
        for weekday_index, raw_weekday in enumerate(weekday_values):
            try:
                parsed_weekdays.append(Weekday(raw_weekday))
            except (TypeError, ValueError):
                _invalid(
                    "invalid_weekday",
                    f"{path}.weekdays[{weekday_index}]",
                    "must be a weekday from monday through sunday",
                )
        if len(set(parsed_weekdays)) != len(parsed_weekdays):
            _invalid("duplicate_weekday", f"{path}.weekdays", "must not contain duplicates")

        is_open = item.get("is_open")
        if not isinstance(is_open, bool):
            _invalid("invalid_boolean", f"{path}.is_open", "must be a boolean")
        if is_open:
            if "staffing" not in item:
                _invalid(
                    "missing_staffing",
                    f"{path}.staffing",
                    "is required when is_open is true",
                )
            staffing = _parse_staffing(item["staffing"], f"{path}.staffing", roles)
        else:
            if "staffing" in item:
                _invalid(
                    "closed_with_staffing",
                    f"{path}.staffing",
                    "must be omitted when is_open is false",
                )
            staffing = None

        for weekday in parsed_weekdays:
            if weekday in weekly:
                _invalid(
                    "duplicate_weekday",
                    f"{path}.weekdays",
                    f"{weekday.value} is already defined by another weekly template",
                )
            weekly[weekday] = staffing

    missing = [weekday.value for weekday in Weekday if weekday not in weekly]
    if missing:
        _invalid(
            "incomplete_weekdays",
            "$.weekly_demands",
            f"missing weekly rules for: {', '.join(missing)}",
        )

    overrides_raw = _sequence(root.get("date_overrides", []), "$.date_overrides")
    overrides: dict[date, dict[str, dict[str, int]] | None] = {}
    for index, raw in enumerate(overrides_raw):
        path = f"$.date_overrides[{index}]"
        item = _mapping(raw, path)
        _reject_unknown(item, DATE_OVERRIDE_FIELDS, path)
        day = _date(item.get("date"), f"{path}.date")
        if not start <= day <= end:
            _invalid("date_out_of_range", f"{path}.date", "must be inside the period")
        if day in overrides:
            _invalid("duplicate_date_override", f"{path}.date", "date is already overridden")
        is_open = item.get("is_open")
        if not isinstance(is_open, bool):
            _invalid("invalid_boolean", f"{path}.is_open", "must be a boolean")
        weekday = WEEKDAY_BY_INDEX[day.weekday()]
        if is_open:
            if weekly[weekday] is None:
                _invalid(
                    "unsupported_open_override",
                    path,
                    "canonical v1 cannot reopen a weekday declared closed",
                )
            if "staffing" not in item:
                _invalid(
                    "missing_staffing",
                    f"{path}.staffing",
                    "is required for an open date override",
                )
            overrides[day] = _parse_staffing(
                item["staffing"], f"{path}.staffing", roles
            )
        else:
            if "staffing" in item:
                _invalid(
                    "closed_with_staffing",
                    f"{path}.staffing",
                    "must be omitted when is_open is false",
                )
            overrides[day] = None

    closed_weekdays = [weekday.value for weekday in Weekday if weekly[weekday] is None]
    closed_dates: list[str] = []
    demands: list[dict[str, Any]] = []
    day = start
    while day <= end:
        weekday = WEEKDAY_BY_INDEX[day.weekday()]
        staffing = overrides.get(day, weekly[weekday])
        if staffing is None:
            if day in overrides and weekly[weekday] is not None:
                closed_dates.append(day.isoformat())
        else:
            for period_name in (period.value for period in PERIODS_V1):
                for role in roles:
                    demands.append(
                        {
                            "date": day.isoformat(),
                            "period": period_name,
                            "role": role,
                            "count": staffing[period_name][role],
                        }
                    )
        day += timedelta(days=1)

    canonical = deepcopy(dict(root))
    canonical.pop("authoring_version", None)
    canonical.pop("weekly_demands", None)
    canonical.pop("date_overrides", None)
    canonical["period"] = {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "closed_weekdays": closed_weekdays,
        "closed_dates": closed_dates,
        "holidays": deepcopy(period.get("holidays", [])),
    }
    canonical["demands"] = demands
    return canonical


def _document_from_validated_mapping(
    payload: Mapping[str, Any],
) -> WeeklyAuthoringDocument:
    """Build immutable authoring models after complete validation succeeds."""

    roles = tuple(payload["roles"])

    def staffing(value: Mapping[str, Any] | None) -> StaffingPlan | None:
        return None if value is None else StaffingPlan.from_dict(value, roles)

    period = payload["period"]
    weekly_demands = tuple(
        WeeklyDemandRule(
            weekdays=tuple(Weekday(item) for item in raw["weekdays"]),
            is_open=raw["is_open"],
            staffing=staffing(raw.get("staffing")),
        )
        for raw in payload["weekly_demands"]
    )
    overrides = tuple(
        DateOverrideRule(
            date=date.fromisoformat(raw["date"]),
            is_open=raw["is_open"],
            staffing=staffing(raw.get("staffing")),
        )
        for raw in payload.get("date_overrides", [])
    )
    employees: list[AuthoringEmployee] = []
    for raw in payload["employees"]:
        available = None
        if "available_slots" in raw:
            available = tuple(
                AuthoringAvailableSlot(
                    date=date.fromisoformat(slot["date"]),
                    period=Period(slot["period"]),
                    roles=(
                        tuple(slot["roles"])
                        if "roles" in slot
                        else None
                    ),
                )
                for slot in raw["available_slots"]
            )
        class_value = raw.get("full_time_class")
        employees.append(
            AuthoringEmployee(
                employee_id=raw["employee_id"],
                name=raw["name"],
                employment_type=EmploymentType(raw["employment_type"]),
                full_time_class=(
                    None if class_value is None else FullTimeClass(class_value)
                ),
                full_time_class_declared="full_time_class" in raw,
                roles=tuple(raw["roles"]),
                fairness_group=raw["fairness_group"],
                shift_mode=ShiftMode(raw["shift_mode"]),
                required_shifts=raw.get("required_shifts"),
                target_shifts=raw.get("target_shifts"),
                min_shifts=raw.get("min_shifts"),
                max_shifts=raw.get("max_shifts"),
                available_slots=available,
                notes=raw.get("notes"),
                notes_declared="notes" in raw,
            )
        )
    leaves = tuple(
        AuthoringLeaveRequest(
            employee_id=raw["employee_id"],
            date=date.fromisoformat(raw["date"]),
            all_day=raw["all_day"],
            period=(Period(raw["period"]) if "period" in raw else None),
            note=raw.get("note"),
            note_declared="note" in raw,
        )
        for raw in payload.get("leave_requests", [])
    )
    unavailable = tuple(
        AuthoringUnavailableSlot(
            employee_id=raw["employee_id"],
            date=date.fromisoformat(raw["date"]),
            period=Period(raw["period"]),
        )
        for raw in payload.get("unavailable_slots", [])
    )
    return WeeklyAuthoringDocument(
        authoring_version=payload["authoring_version"],
        schema_version=payload["schema_version"],
        period=WeeklyPeriod(
            start_date=date.fromisoformat(period["start_date"]),
            end_date=date.fromisoformat(period["end_date"]),
            holidays=tuple(
                date.fromisoformat(item) for item in period.get("holidays", [])
            ),
            holidays_declared="holidays" in period,
        ),
        periods=tuple(Period(item) for item in payload["periods"]),
        roles=roles,
        weekly_demands=weekly_demands,
        date_overrides=overrides,
        employees=tuple(employees),
        leave_requests=leaves,
        unavailable_slots=unavailable,
        date_overrides_declared="date_overrides" in payload,
        leave_requests_declared="leave_requests" in payload,
        unavailable_slots_declared="unavailable_slots" in payload,
    )


def parse_weekly_authoring(
    payload: Mapping[str, Any],
) -> WeeklyAuthoringDocument:
    """Validate one weekly-v1 mapping and return its typed document."""

    canonical = _expand_weekly_mapping(payload)
    from .validation import validate_and_normalize

    validate_and_normalize(canonical)
    return _document_from_validated_mapping(payload)


def expand_weekly_template(
    payload: Mapping[str, Any] | WeeklyAuthoringDocument,
) -> dict[str, Any]:
    """Return canonical v1 demands from a validated typed authoring document."""

    document = (
        payload
        if isinstance(payload, WeeklyAuthoringDocument)
        else parse_weekly_authoring(payload)
    )
    return _expand_weekly_mapping(document.to_dict())


def load_weekly_authoring_document(
    path: str | Path,
) -> WeeklyAuthoringDocument:
    """Read and validate a weekly-v1 user document."""

    return parse_weekly_authoring(read_json_object(path))


def write_weekly_authoring_document(
    path: str | Path,
    document: WeeklyAuthoringDocument,
) -> Path:
    """Atomically persist a validated weekly-v1 user document."""

    # Re-validate edited/replaced dataclass instances before committing them.
    validated = parse_weekly_authoring(document.to_dict())
    return write_json_object_atomic(path, validated.to_dict())


def validate_and_normalize_weekly(
    payload: Mapping[str, Any],
) -> NormalizedScheduleInput:
    """Expand compact input, then run the unchanged canonical v1 validator."""

    from .validation import validate_and_normalize

    return validate_and_normalize(expand_weekly_template(payload))
