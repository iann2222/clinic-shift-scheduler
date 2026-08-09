"""CP-SAT hard-feasibility model with phase-three conservative prechecks.

This module intentionally has no objective. It consumes the phase-one
``NormalizedScheduleInput`` and enforces the v1 hard constraints.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from ortools.sat.python import cp_model

from .daily_patterns import (
    B_MAX_SINGLE_SHIFT_DAYS_PER_MONTH,
    PATTERN_PERIODS,
    DailyPattern,
    allowed_daily_patterns,
)
from .enums import EmploymentType, FullTimeClass, PERIODS_V1, Period, ShiftMode
from .models import AssignmentKey, DemandKey, NormalizedScheduleInput
from .precheck import PrecheckResult, PrecheckStatus, run_prechecks


class FeasibilityStatus(StrEnum):
    PRECHECK_INFEASIBLE = "PRECHECK_INFEASIBLE"
    FEASIBLE = "FEASIBLE"
    OPTIMAL = "OPTIMAL"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    VALIDATION_FAILED = "VALIDATION_FAILED"


@dataclass(frozen=True, slots=True)
class Assignment:
    employee_id: str
    date: date
    period: Period
    role: str


@dataclass(frozen=True, slots=True)
class FeasibilitySolverConfig:
    max_time_seconds: float | None = None
    num_search_workers: int = 1
    random_seed: int = 0
    enable_precheck: bool = True

    def __post_init__(self) -> None:
        if self.max_time_seconds is not None and self.max_time_seconds <= 0:
            raise ValueError("max_time_seconds must be greater than 0")
        if self.num_search_workers <= 0:
            raise ValueError("num_search_workers must be greater than 0")


PersonDayKey = tuple[str, date]
PersonPeriodKey = tuple[str, date, Period]
PatternKey = tuple[str, date, DailyPattern]


@dataclass(frozen=True, slots=True)
class FeasibilityModel:
    model: cp_model.CpModel
    x: Mapping[AssignmentKey, cp_model.IntVar]
    slot_work: Mapping[PersonPeriodKey, cp_model.IntVar]
    daily_patterns: Mapping[PatternKey, cp_model.IntVar]
    employee_shift_counts: Mapping[str, cp_model.IntVar]


@dataclass(frozen=True, slots=True)
class FeasibilityResult:
    status: FeasibilityStatus
    assignments: tuple[Assignment, ...]
    daily_patterns: Mapping[PersonDayKey, DailyPattern]
    raw_solver_status: str
    wall_time_seconds: float
    precheck: PrecheckResult | None

    @property
    def is_feasible(self) -> bool:
        return self.status in (
            FeasibilityStatus.FEASIBLE,
            FeasibilityStatus.OPTIMAL,
        )


def _var_name(prefix: str, *parts: object) -> str:
    return f"{prefix}[{','.join(str(part) for part in parts)}]"


def build_feasibility_model(data: NormalizedScheduleInput) -> FeasibilityModel:
    """Build the v1 hard-constraint model without any objective."""

    model = cp_model.CpModel()

    x: dict[AssignmentKey, cp_model.IntVar] = {}
    x_by_demand: dict[DemandKey, list[cp_model.IntVar]] = defaultdict(list)
    x_by_person_period: dict[PersonPeriodKey, list[cp_model.IntVar]] = defaultdict(list)
    x_by_employee: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    for employee_id, day, period, role in sorted(
        data.allowed_assignments,
        key=lambda item: (item[1], PERIODS_V1.index(item[2]), item[3], item[0]),
    ):
        key = (employee_id, day, period, role)
        x[key] = model.new_bool_var(
            _var_name("x", employee_id, day.isoformat(), period.value, role)
        )
        x_by_demand[(day, period, role)].append(x[key])
        x_by_person_period[(employee_id, day, period)].append(x[key])
        x_by_employee[employee_id].append(x[key])

    # Every (date, period, role) is covered by exactly demand qualified people.
    for (day, period, role), count in data.demands.items():
        model.add(sum(x_by_demand[(day, period, role)]) == count)

    slot_work: dict[PersonPeriodKey, cp_model.IntVar] = {}
    daily_patterns: dict[PatternKey, cp_model.IntVar] = {}
    employee_shift_counts: dict[str, cp_model.IntVar] = {}

    for employee in data.source.employees:
        for day in data.dates:
            day_slot_vars: dict[Period, cp_model.IntVar] = {}
            for period in PERIODS_V1:
                slot_key = (employee.employee_id, day, period)
                slot_variable = model.new_bool_var(
                    _var_name(
                        "slot_work",
                        employee.employee_id,
                        day.isoformat(),
                        period.value,
                    )
                )
                slot_work[slot_key] = slot_variable
                role_variables = x_by_person_period[slot_key]
                # Equality both links slot_work and enforces at most one role per period.
                model.add(slot_variable == sum(role_variables))
                day_slot_vars[period] = slot_variable

            pattern_variables: dict[DailyPattern, cp_model.IntVar] = {}
            for pattern in DailyPattern:
                key = (employee.employee_id, day, pattern)
                pattern_variables[pattern] = model.new_bool_var(
                    _var_name(
                        "daily_pattern",
                        employee.employee_id,
                        day.isoformat(),
                        pattern.value,
                    )
                )
                daily_patterns[key] = pattern_variables[pattern]
            model.add_exactly_one(pattern_variables.values())

            for period in PERIODS_V1:
                containing_patterns = [
                    pattern_variables[pattern]
                    for pattern, periods in PATTERN_PERIODS.items()
                    if period in periods
                ]
                model.add(day_slot_vars[period] == sum(containing_patterns))

            allowed_patterns = allowed_daily_patterns(
                employee.employment_type, employee.full_time_class
            )
            for pattern in set(DailyPattern) - allowed_patterns:
                model.add(pattern_variables[pattern] == 0)

            daily_count = sum(day_slot_vars.values())
            if employee.employment_type is EmploymentType.PART_TIME:
                model.add(daily_count <= 2)
            elif employee.full_time_class is FullTimeClass.A:
                model.add(daily_count <= 2)
            else:
                model.add(daily_count <= 3)

        if employee.full_time_class is FullTimeClass.B:
            months = sorted({(day.year, day.month) for day in data.dates})
            for year, month in months:
                model.add(
                    sum(
                        daily_patterns[(employee.employee_id, day, pattern)]
                        for day in data.dates
                        if (day.year, day.month) == (year, month)
                        for pattern in (
                            DailyPattern.MORNING_ONLY,
                            DailyPattern.AFTERNOON_ONLY,
                            DailyPattern.EVENING_ONLY,
                        )
                    )
                    <= B_MAX_SINGLE_SHIFT_DAYS_PER_MONTH
                )

        assignment_variables = x_by_employee[employee.employee_id]
        total_shifts = model.new_int_var(
            0,
            len(assignment_variables),
            _var_name("total_shifts", employee.employee_id),
        )
        model.add(total_shifts == sum(assignment_variables))
        employee_shift_counts[employee.employee_id] = total_shifts
        if employee.shift_mode is ShiftMode.EXACT:
            assert employee.required_shifts is not None
            model.add(total_shifts == employee.required_shifts)
        elif employee.shift_mode is ShiftMode.RANGE:
            assert employee.min_shifts is not None and employee.max_shifts is not None
            model.add(total_shifts >= employee.min_shifts)
            model.add(total_shifts <= employee.max_shifts)
        else:
            # target_shifts itself is handled only by the optimization controller.
            if employee.min_shifts is not None:
                model.add(total_shifts >= employee.min_shifts)
            if employee.max_shifts is not None:
                model.add(total_shifts <= employee.max_shifts)

    return FeasibilityModel(
        model=model,
        x=MappingProxyType(x),
        slot_work=MappingProxyType(slot_work),
        daily_patterns=MappingProxyType(daily_patterns),
        employee_shift_counts=MappingProxyType(employee_shift_counts),
    )


def extract_model_solution(
    built: FeasibilityModel,
    solver: cp_model.CpSolver,
) -> tuple[tuple[Assignment, ...], Mapping[PersonDayKey, DailyPattern]]:
    """Extract the shared raw assignment and daily-pattern representation."""

    assignments = tuple(
        Assignment(employee_id, day, period, role)
        for (employee_id, day, period, role), variable in built.x.items()
        if solver.value(variable)
    )
    selected_patterns: dict[PersonDayKey, DailyPattern] = {}
    for (employee_id, day, pattern), variable in built.daily_patterns.items():
        if solver.value(variable):
            selected_patterns[(employee_id, day)] = pattern
    return assignments, MappingProxyType(selected_patterns)


def solve_feasibility(
    data: NormalizedScheduleInput,
    config: FeasibilitySolverConfig | None = None,
) -> FeasibilityResult:
    """Solve only the hard-feasibility problem and extract a raw assignment."""

    config = config or FeasibilitySolverConfig()
    precheck = run_prechecks(data) if config.enable_precheck else None
    if precheck is not None and precheck.status is PrecheckStatus.PRECHECK_INFEASIBLE:
        return FeasibilityResult(
            status=FeasibilityStatus.PRECHECK_INFEASIBLE,
            assignments=(),
            daily_patterns=MappingProxyType({}),
            raw_solver_status="NOT_RUN",
            wall_time_seconds=0.0,
            precheck=precheck,
        )
    built = build_feasibility_model(data)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = config.num_search_workers
    solver.parameters.random_seed = config.random_seed
    if config.max_time_seconds is not None:
        solver.parameters.max_time_in_seconds = config.max_time_seconds

    raw_status = solver.solve(built.model)
    raw_status_name = solver.status_name(raw_status)
    if raw_status == cp_model.INFEASIBLE:
        return FeasibilityResult(
            status=FeasibilityStatus.INFEASIBLE,
            assignments=(),
            daily_patterns=MappingProxyType({}),
            raw_solver_status=raw_status_name,
            wall_time_seconds=solver.wall_time,
            precheck=precheck,
        )
    if raw_status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return FeasibilityResult(
            status=FeasibilityStatus.UNKNOWN,
            assignments=(),
            daily_patterns=MappingProxyType({}),
            raw_solver_status=raw_status_name,
            wall_time_seconds=solver.wall_time,
            precheck=precheck,
        )

    assignments, selected_patterns = extract_model_solution(built, solver)

    return FeasibilityResult(
        status=FeasibilityStatus.FEASIBLE,
        assignments=assignments,
        daily_patterns=selected_patterns,
        raw_solver_status=raw_status_name,
        wall_time_seconds=solver.wall_time,
        precheck=precheck,
    )
