"""Shared A/B preference ranks and independently recomputable regret rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .enums import FullTimeClass
from .models import NormalizedScheduleInput
from .ratio_fairness import ratio_basis_points


class PreferenceRank(StrEnum):
    FIRST = "first"
    SECOND = "second"


class ClassPreferenceMetric(StrEnum):
    CONSECUTIVE_DOUBLES = "consecutive_double_days"
    SINGLE_SHIFT_DAYS = "single_shift_days"
    MORNING_EVENING_DAYS = "morning_evening_days"


class PreferenceDirection(StrEnum):
    MAXIMIZE = "MAXIMIZE"
    MINIMIZE = "MINIMIZE"


@dataclass(frozen=True, slots=True)
class ClassPreferenceDefinition:
    full_time_class: FullTimeClass
    rank: PreferenceRank
    metric: ClassPreferenceMetric
    direction: PreferenceDirection


def class_opportunity_days(
    data: NormalizedScheduleInput,
    full_time_class: FullTimeClass,
) -> int:
    """Count employee-days containing at least one normalized candidate assignment."""

    candidate_days = {
        (employee_id, day)
        for employee_id, day, _period, _role in data.allowed_assignments
    }
    return sum(
        (employee.employee_id, day) in candidate_days
        for employee in data.source.employees
        if employee.full_time_class is full_time_class
        for day in data.dates
    )


def preference_regret_days(
    actual: int,
    ideal: int,
    direction: PreferenceDirection,
) -> int:
    regret = (
        ideal - actual
        if direction is PreferenceDirection.MAXIMIZE
        else actual - ideal
    )
    # Invalid/tampered assignments are reported by the independent validator;
    # keep metric recomputation total so validation can finish and list issues.
    return max(0, regret)


def preference_regret_basis_points(
    regret_days: int,
    opportunity_days: int,
) -> int | None:
    return ratio_basis_points(regret_days, opportunity_days)
