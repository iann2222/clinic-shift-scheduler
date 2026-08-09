"""Expand compact weekly authoring input into the canonical v1 contract.

Users maintain weekly opening and staffing templates.  The solver-facing v1
contract remains explicit per date, period, and role so its existing strict
validation is unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from .enums import PERIODS_V1, WEEKDAY_BY_INDEX, Weekday
from .errors import InputValidationError, ValidationIssue
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


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
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


def expand_weekly_template(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical v1 mapping with complete per-date demands."""

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

    period = _mapping(root.get("period"), "$.period")
    _reject_unknown(period, {"start_date", "end_date", "holidays"}, "$.period")
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
        _reject_unknown(item, {"weekdays", "is_open", "staffing"}, path)
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
        _reject_unknown(item, {"date", "is_open", "staffing"}, path)
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


def validate_and_normalize_weekly(
    payload: Mapping[str, Any],
) -> NormalizedScheduleInput:
    """Expand compact input, then run the unchanged canonical v1 validator."""

    from .validation import validate_and_normalize

    return validate_and_normalize(expand_weekly_template(payload))
