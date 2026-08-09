"""Strict v1 lexicographic objectives through group fairness.

Formal independent output validation remains outside this module's scope.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from ortools.sat.python import cp_model

from .daily_patterns import PATTERN_PERIODS, DailyPattern
from .enums import EmploymentType, FullTimeClass, PERIODS_V1, Period, ShiftMode
from .feasibility import (
    Assignment,
    FeasibilityModel,
    FeasibilityStatus,
    PatternKey,
    PersonDayKey,
    build_feasibility_model,
    extract_model_solution,
)
from .models import Employee, NormalizedScheduleInput
from .precheck import PrecheckResult, PrecheckStatus, run_prechecks
from .ratio_fairness import (
    BASIS_POINTS_SCALE,
    PatternQualityLevel,
    ratio_basis_points,
)


class OptimizationStage(StrEnum):
    HARD_FEASIBILITY = "hard_feasibility"
    FULL_TIME_TARGET_DEVIATION = "full_time_target_deviation"
    PART_TIME_USAGE = "part_time_usage"
    FULL_TIME_CONSECUTIVE_DOUBLES = "full_time_consecutive_doubles"
    FULL_TIME_SINGLE_SHIFT_DAYS = "full_time_single_shift_days"
    FULL_TIME_SECONDARY_PATTERNS = "full_time_secondary_patterns"
    FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP = (
        "full_time_class_quality_ratio_max_gap"
    )
    FULL_TIME_CLASS_QUALITY_RATIO_TOTAL_GAP = (
        "full_time_class_quality_ratio_total_gap"
    )
    FULL_TIME_PATTERN_RATIO_MAX_GAP = "full_time_pattern_ratio_max_gap"
    FULL_TIME_PATTERN_RATIO_TOTAL_GAP = "full_time_pattern_ratio_total_gap"
    FULL_TIME_PATTERN_INTEGER_FAIRNESS = "full_time_pattern_integer_fairness"
    PART_TIME_GROUP_FAIRNESS = "part_time_group_fairness"
    COMMON_GROUP_FAIRNESS = "common_group_fairness"


class FairnessMetric(StrEnum):
    ATTENDANCE_DAYS = "attendance_days"
    CONSECUTIVE_DOUBLES = "consecutive_doubles"
    SINGLE_SHIFT_DAYS = "single_shift_days"
    MORNING_EVENING_DAYS = "morning_evening_days"
    TRIPLE_DAYS = "triple_days"
    TOTAL_SHIFTS = "total_shifts"
    MORNING_SHIFTS = "morning_shifts"
    AFTERNOON_SHIFTS = "afternoon_shifts"
    EVENING_SHIFTS = "evening_shifts"
    SUNDAY_SHIFTS = "sunday_shifts"
    HOLIDAY_SHIFTS = "holiday_shifts"


class ObjectiveDirection(StrEnum):
    NONE = "NONE"
    MINIMIZE = "MINIMIZE"
    MAXIMIZE = "MAXIMIZE"


class OptimizationStageStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    OPTIMAL = "OPTIMAL"
    SKIPPED_CONSTANT = "SKIPPED_CONSTANT"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


class ConstantProof(StrEnum):
    NO_TARGET_EMPLOYEES = "NO_TARGET_EMPLOYEES"
    ALL_TARGET_COUNTS_HARD_FIXED = "ALL_TARGET_COUNTS_HARD_FIXED"
    NO_PART_TIME_EMPLOYEES = "NO_PART_TIME_EMPLOYEES"
    ALL_PART_TIME_COUNTS_HARD_FIXED = "ALL_PART_TIME_COUNTS_HARD_FIXED"
    ALL_FULL_TIME_COUNTS_HARD_FIXED_BY_COVERAGE = (
        "ALL_FULL_TIME_COUNTS_HARD_FIXED_BY_COVERAGE"
    )
    NO_FULL_TIME_EMPLOYEES = "NO_FULL_TIME_EMPLOYEES"
    NO_PATTERN_OPPORTUNITY = "NO_PATTERN_OPPORTUNITY"
    NO_COMPARABLE_FULL_TIME_CLASSES = "NO_COMPARABLE_FULL_TIME_CLASSES"
    NO_COMPARABLE_FAIRNESS_GROUPS = "NO_COMPARABLE_FAIRNESS_GROUPS"


@dataclass(frozen=True, slots=True)
class LexicographicSolverConfig:
    max_time_seconds_per_stage: float | None = None
    num_search_workers: int = 1
    random_seed: int = 0

    def __post_init__(self) -> None:
        if (
            self.max_time_seconds_per_stage is not None
            and self.max_time_seconds_per_stage <= 0
        ):
            raise ValueError("max_time_seconds_per_stage must be greater than 0")
        if self.num_search_workers <= 0:
            raise ValueError("num_search_workers must be greater than 0")


@dataclass(frozen=True, slots=True)
class OptimizationStageResult:
    stage: OptimizationStage
    direction: ObjectiveDirection
    status: OptimizationStageStatus
    objective_value: int | None
    raw_solver_status: str
    wall_time_seconds: float
    locked: bool
    constant_proof: ConstantProof | None = None


@dataclass(frozen=True, slots=True)
class OptimizationModel:
    feasibility: FeasibilityModel
    target_differences: Mapping[str, cp_model.IntVar]
    target_deviations: Mapping[str, cp_model.IntVar]
    target_objective: cp_model.LinearExpr | int
    part_time_objective: cp_model.LinearExpr | int
    consecutive_double_variables: Mapping[PatternKey, cp_model.IntVar]
    single_shift_variables: Mapping[PatternKey, cp_model.IntVar]
    secondary_pattern_variables: Mapping[PatternKey, cp_model.IntVar]
    consecutive_double_objective: cp_model.LinearExpr | int
    single_shift_objective: cp_model.LinearExpr | int
    secondary_pattern_objective: cp_model.LinearExpr | int
    employee_fairness_metrics: Mapping[
        tuple[str, FairnessMetric], cp_model.IntVar
    ]
    employee_pattern_ratio_basis_points: Mapping[
        tuple[str, FairnessMetric], cp_model.IntVar
    ]
    employee_attendance_active: Mapping[str, cp_model.IntVar]
    class_attendance_totals: Mapping[FullTimeClass, cp_model.IntVar]
    class_quality_counts: Mapping[
        tuple[FullTimeClass, PatternQualityLevel], cp_model.IntVar
    ]
    class_quality_ratio_basis_points: Mapping[
        tuple[FullTimeClass, PatternQualityLevel], cp_model.IntVar
    ]
    class_quality_ratio_gap_variables: Mapping[
        PatternQualityLevel, cp_model.IntVar
    ]
    class_quality_ratio_max_gap_variable: cp_model.IntVar | None
    class_quality_ratio_total_objective: cp_model.LinearExpr | int
    ratio_fairness_gap_variables: Mapping[
        tuple[str, FairnessMetric], cp_model.IntVar
    ]
    ratio_fairness_max_gap_variable: cp_model.IntVar | None
    ratio_fairness_total_objective: cp_model.LinearExpr | int
    fairness_gap_variables: Mapping[
        OptimizationStage,
        Mapping[tuple[str, FairnessMetric], cp_model.IntVar],
    ]
    fairness_objectives: Mapping[
        OptimizationStage, cp_model.LinearExpr | int
    ]


@dataclass(frozen=True, slots=True)
class _ClassQualityModel:
    attendance_totals: Mapping[FullTimeClass, cp_model.IntVar]
    quality_counts: Mapping[
        tuple[FullTimeClass, PatternQualityLevel], cp_model.IntVar
    ]
    ratios: Mapping[
        tuple[FullTimeClass, PatternQualityLevel], cp_model.IntVar
    ]
    gaps: Mapping[PatternQualityLevel, cp_model.IntVar]
    max_gap: cp_model.IntVar | None
    total_gap: cp_model.LinearExpr | int


# Backwards-compatible public name retained for existing phase-four callers.
PhaseFourModel = OptimizationModel


@dataclass(frozen=True, slots=True)
class LexicographicResult:
    status: FeasibilityStatus
    assignments: tuple[Assignment, ...]
    daily_patterns: Mapping[PersonDayKey, DailyPattern]
    employee_shift_counts: Mapping[str, int]
    target_deviations: Mapping[str, int]
    part_time_total: int | None
    stages: tuple[OptimizationStageResult, ...]
    precheck: PrecheckResult
    implemented_objective_prefix_optimal: bool

    @property
    def is_feasible(self) -> bool:
        return self.status in (
            FeasibilityStatus.FEASIBLE,
            FeasibilityStatus.OPTIMAL,
        )


@dataclass(frozen=True, slots=True)
class _ObjectiveSpec:
    stage: OptimizationStage
    direction: ObjectiveDirection
    variables: tuple[cp_model.IntVar, ...]
    expression: cp_model.LinearExpr | int
    constant_value: int | None
    constant_proof: ConstantProof | None


@dataclass(frozen=True, slots=True)
class _SolverRun:
    solver: cp_model.CpSolver
    raw_status: int
    raw_status_name: str
    wall_time_seconds: float


@dataclass(frozen=True, slots=True)
class _SolutionSnapshot:
    assignments: tuple[Assignment, ...]
    daily_patterns: Mapping[PersonDayKey, DailyPattern]
    employee_shift_counts: Mapping[str, int]
    target_deviations: Mapping[str, int]
    part_time_total: int


def _var_name(prefix: str, employee_id: str) -> str:
    return f"{prefix}[{employee_id}]"


def _build_class_quality_model(
    data: NormalizedScheduleInput,
    model: cp_model.CpModel,
    employee_metrics: Mapping[tuple[str, FairnessMetric], cp_model.IntVar],
) -> _ClassQualityModel:
    quality_metrics = {
        FullTimeClass.A: {
            PatternQualityLevel.FIRST: FairnessMetric.CONSECUTIVE_DOUBLES,
            PatternQualityLevel.SECOND: FairnessMetric.MORNING_EVENING_DAYS,
            PatternQualityLevel.THIRD: FairnessMetric.SINGLE_SHIFT_DAYS,
        },
        FullTimeClass.B: {
            PatternQualityLevel.FIRST: FairnessMetric.CONSECUTIVE_DOUBLES,
            PatternQualityLevel.SECOND: FairnessMetric.TRIPLE_DAYS,
            PatternQualityLevel.THIRD: FairnessMetric.SINGLE_SHIFT_DAYS,
        },
    }
    members_by_class = {
        full_time_class: tuple(
            employee
            for employee in data.source.employees
            if employee.full_time_class is full_time_class
        )
        for full_time_class in FullTimeClass
    }
    ratio_lookups: dict[int, list[int]] = {}

    def add_ratio_variable(
        numerator: cp_model.IntVar,
        denominator: cp_model.IntVar,
        maximum_denominator: int,
        name: str,
    ) -> cp_model.IntVar:
        if maximum_denominator not in ratio_lookups:
            ratio_lookups[maximum_denominator] = [
                (
                    ratio_basis_points(candidate_numerator, candidate_denominator)
                    or 0
                )
                if candidate_numerator <= candidate_denominator
                else 0
                for candidate_numerator in range(maximum_denominator + 1)
                for candidate_denominator in range(maximum_denominator + 1)
            ]
        index = model.new_int_var(
            0,
            (maximum_denominator + 1) ** 2 - 1,
            f"{name}_index",
        )
        model.add(
            index
            == numerator * (maximum_denominator + 1) + denominator
        )
        ratio = model.new_int_var(0, BASIS_POINTS_SCALE, name)
        model.add_element(index, ratio_lookups[maximum_denominator], ratio)
        return ratio

    attendance_totals: dict[FullTimeClass, cp_model.IntVar] = {}
    quality_counts: dict[
        tuple[FullTimeClass, PatternQualityLevel], cp_model.IntVar
    ] = {}
    ratios: dict[
        tuple[FullTimeClass, PatternQualityLevel], cp_model.IntVar
    ] = {}
    attendance_active: dict[FullTimeClass, cp_model.IntVar] = {}
    for full_time_class, members in members_by_class.items():
        maximum_attendance = len(members) * len(data.dates)
        attendance = model.new_int_var(
            0,
            maximum_attendance,
            f"class_attendance[{full_time_class.value}]",
        )
        model.add(
            attendance
            == sum(
                employee_metrics[
                    (employee.employee_id, FairnessMetric.ATTENDANCE_DAYS)
                ]
                for employee in members
            )
        )
        active = model.new_bool_var(
            f"class_attendance_active[{full_time_class.value}]"
        )
        model.add(attendance >= 1).only_enforce_if(active)
        model.add(attendance == 0).only_enforce_if(active.Not())
        attendance_totals[full_time_class] = attendance
        attendance_active[full_time_class] = active
        for quality_level, metric in quality_metrics[full_time_class].items():
            count = model.new_int_var(
                0,
                maximum_attendance,
                f"class_quality_count[{full_time_class.value},{quality_level.value}]",
            )
            model.add(
                count
                == sum(
                    employee_metrics[(employee.employee_id, metric)]
                    for employee in members
                )
            )
            ratio = add_ratio_variable(
                count,
                attendance,
                maximum_attendance,
                f"class_quality_ratio_bp[{full_time_class.value},{quality_level.value}]",
            )
            quality_counts[(full_time_class, quality_level)] = count
            ratios[(full_time_class, quality_level)] = ratio

    gaps: dict[PatternQualityLevel, cp_model.IntVar] = {}
    if all(members_by_class[item] for item in FullTimeClass):
        comparable = model.new_bool_var("class_quality_ratio_comparable")
        model.add_min_equality(
            comparable,
            [
                attendance_active[FullTimeClass.A],
                attendance_active[FullTimeClass.B],
            ],
        )
        for quality_level in PatternQualityLevel:
            difference = model.new_int_var(
                -BASIS_POINTS_SCALE,
                BASIS_POINTS_SCALE,
                f"class_quality_ratio_difference[{quality_level.value}]",
            )
            absolute_difference = model.new_int_var(
                0,
                BASIS_POINTS_SCALE,
                f"class_quality_ratio_absolute_difference[{quality_level.value}]",
            )
            gap = model.new_int_var(
                0,
                BASIS_POINTS_SCALE,
                f"class_quality_ratio_gap[{quality_level.value}]",
            )
            model.add(
                difference
                == ratios[(FullTimeClass.A, quality_level)]
                - ratios[(FullTimeClass.B, quality_level)]
            )
            model.add_abs_equality(absolute_difference, difference)
            model.add(gap == absolute_difference).only_enforce_if(comparable)
            model.add(gap == 0).only_enforce_if(comparable.Not())
            gaps[quality_level] = gap
    max_gap: cp_model.IntVar | None = None
    if gaps:
        max_gap = model.new_int_var(
            0,
            BASIS_POINTS_SCALE,
            "full_time_class_quality_ratio_max_gap",
        )
        model.add_max_equality(max_gap, list(gaps.values()))
    return _ClassQualityModel(
        attendance_totals=MappingProxyType(attendance_totals),
        quality_counts=MappingProxyType(quality_counts),
        ratios=MappingProxyType(ratios),
        gaps=MappingProxyType(gaps),
        max_gap=max_gap,
        total_gap=sum(gaps.values()),
    )


def build_optimization_model(
    data: NormalizedScheduleInput,
    *,
    include_class_quality: bool = True,
) -> OptimizationModel:
    """Add all currently implemented objectives to the shared hard model."""

    feasibility = build_feasibility_model(data)
    model = feasibility.model
    target_differences: dict[str, cp_model.IntVar] = {}
    target_deviations: dict[str, cp_model.IntVar] = {}
    for employee in data.source.employees:
        if employee.shift_mode is not ShiftMode.TARGET:
            continue
        assert employee.target_shifts is not None
        count_variable = feasibility.employee_shift_counts[employee.employee_id]
        candidate_count = sum(
            key[0] == employee.employee_id for key in feasibility.x
        )
        deviation_upper_bound = max(
            employee.target_shifts,
            abs(candidate_count - employee.target_shifts),
        )
        difference = model.new_int_var(
            -employee.target_shifts,
            candidate_count - employee.target_shifts,
            _var_name("target_difference", employee.employee_id),
        )
        model.add(
            difference == count_variable - employee.target_shifts
        )
        deviation = model.new_int_var(
            0,
            deviation_upper_bound,
            _var_name("target_deviation", employee.employee_id),
        )
        # OR-Tools 9.12 mis-encodes the negated offset when AddAbsEquality
        # receives a shifted expression directly, so take abs of a linked var.
        model.add_abs_equality(deviation, difference)
        target_differences[employee.employee_id] = difference
        target_deviations[employee.employee_id] = deviation

    part_time_counts = tuple(
        feasibility.employee_shift_counts[employee.employee_id]
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    available_periods: dict[PersonDayKey, set[Period]] = {}
    for employee_id, day, period, _role in data.allowed_assignments:
        available_periods.setdefault((employee_id, day), set()).add(period)

    consecutive_patterns = (
        DailyPattern.MORNING_AFTERNOON,
        DailyPattern.AFTERNOON_EVENING,
    )
    single_patterns = (
        DailyPattern.MORNING_ONLY,
        DailyPattern.AFTERNOON_ONLY,
        DailyPattern.EVENING_ONLY,
    )
    consecutive_variables: dict[PatternKey, cp_model.IntVar] = {}
    single_variables: dict[PatternKey, cp_model.IntVar] = {}
    secondary_variables: dict[PatternKey, cp_model.IntVar] = {}
    for employee in data.source.employees:
        if employee.employment_type is not EmploymentType.FULL_TIME:
            continue
        for day in data.dates:
            possible_periods = available_periods.get(
                (employee.employee_id, day), set()
            )
            for pattern in consecutive_patterns:
                if PATTERN_PERIODS[pattern].issubset(possible_periods):
                    key = (employee.employee_id, day, pattern)
                    consecutive_variables[key] = feasibility.daily_patterns[key]
            for pattern in single_patterns:
                if PATTERN_PERIODS[pattern].issubset(possible_periods):
                    key = (employee.employee_id, day, pattern)
                    single_variables[key] = feasibility.daily_patterns[key]
            secondary_pattern = (
                DailyPattern.MORNING_EVENING
                if employee.full_time_class is FullTimeClass.A
                else DailyPattern.TRIPLE
            )
            if PATTERN_PERIODS[secondary_pattern].issubset(possible_periods):
                key = (employee.employee_id, day, secondary_pattern)
                secondary_variables[key] = feasibility.daily_patterns[key]

    metric_upper_bound = 3 * len(data.dates)
    employee_metrics: dict[tuple[str, FairnessMetric], cp_model.IntVar] = {}

    def add_count_metric(
        employee_id: str,
        metric: FairnessMetric,
        terms: list[cp_model.IntVar],
    ) -> cp_model.IntVar:
        variable = model.new_int_var(
            0,
            metric_upper_bound,
            _var_name(f"fairness_{metric.value}", employee_id),
        )
        model.add(variable == sum(terms))
        employee_metrics[(employee_id, metric)] = variable
        return variable

    consecutive_patterns_set = frozenset(consecutive_patterns)
    single_patterns_set = frozenset(single_patterns)
    for employee in data.source.employees:
        employee_id = employee.employee_id
        if employee.employment_type is EmploymentType.FULL_TIME:
            add_count_metric(
                employee_id,
                FairnessMetric.ATTENDANCE_DAYS,
                [
                    feasibility.daily_patterns[(employee_id, day, pattern)]
                    for day in data.dates
                    for pattern in DailyPattern
                    if pattern is not DailyPattern.OFF
                    and (employee_id, day, pattern)
                    in feasibility.daily_patterns
                ],
            )
            add_count_metric(
                employee_id,
                FairnessMetric.CONSECUTIVE_DOUBLES,
                [
                    feasibility.daily_patterns[(employee_id, day, pattern)]
                    for day in data.dates
                    for pattern in consecutive_patterns_set
                ],
            )
            add_count_metric(
                employee_id,
                FairnessMetric.SINGLE_SHIFT_DAYS,
                [
                    feasibility.daily_patterns[(employee_id, day, pattern)]
                    for day in data.dates
                    for pattern in single_patterns_set
                ],
            )
            class_metric = (
                FairnessMetric.MORNING_EVENING_DAYS
                if employee.full_time_class is FullTimeClass.A
                else FairnessMetric.TRIPLE_DAYS
            )
            class_pattern = (
                DailyPattern.MORNING_EVENING
                if employee.full_time_class is FullTimeClass.A
                else DailyPattern.TRIPLE
            )
            add_count_metric(
                employee_id,
                class_metric,
                [
                    feasibility.daily_patterns[(employee_id, day, class_pattern)]
                    for day in data.dates
                ],
            )
        else:
            employee_metrics[(employee_id, FairnessMetric.TOTAL_SHIFTS)] = (
                feasibility.employee_shift_counts[employee_id]
            )

        for period, metric in (
            (Period.MORNING, FairnessMetric.MORNING_SHIFTS),
            (Period.AFTERNOON, FairnessMetric.AFTERNOON_SHIFTS),
            (Period.EVENING, FairnessMetric.EVENING_SHIFTS),
        ):
            add_count_metric(
                employee_id,
                metric,
                [
                    feasibility.slot_work[(employee_id, day, period)]
                    for day in data.dates
                ],
            )
        add_count_metric(
            employee_id,
            FairnessMetric.SUNDAY_SHIFTS,
            [
                feasibility.slot_work[(employee_id, day, period)]
                for day in data.dates
                if day.weekday() == 6
                for period in PERIODS_V1
            ],
        )
        add_count_metric(
            employee_id,
            FairnessMetric.HOLIDAY_SHIFTS,
            [
                feasibility.slot_work[(employee_id, day, period)]
                for day in data.dates
                if day in data.source.period.holidays
                for period in PERIODS_V1
            ],
        )

    full_time_classes = {
        FullTimeClass.A: (
            FairnessMetric.CONSECUTIVE_DOUBLES,
            FairnessMetric.SINGLE_SHIFT_DAYS,
            FairnessMetric.MORNING_EVENING_DAYS,
        ),
        FullTimeClass.B: (
            FairnessMetric.CONSECUTIVE_DOUBLES,
            FairnessMetric.SINGLE_SHIFT_DAYS,
            FairnessMetric.TRIPLE_DAYS,
        ),
    }

    class_quality = (
        _build_class_quality_model(data, model, employee_metrics)
        if include_class_quality
        else _ClassQualityModel(
            attendance_totals=MappingProxyType({}),
            quality_counts=MappingProxyType({}),
            ratios=MappingProxyType({}),
            gaps=MappingProxyType({}),
            max_gap=None,
            total_gap=0,
        )
    )

    individual_maximum_denominator = len(data.dates)
    individual_ratio_lookup = [
        (
            ratio_basis_points(candidate_numerator, candidate_denominator)
            or 0
        )
        if candidate_numerator <= candidate_denominator
        else 0
        for candidate_numerator in range(individual_maximum_denominator + 1)
        for candidate_denominator in range(individual_maximum_denominator + 1)
    ]

    employee_ratios: dict[
        tuple[str, FairnessMetric], cp_model.IntVar
    ] = {}
    employee_attendance_active: dict[str, cp_model.IntVar] = {}
    for employee in data.source.employees:
        if employee.employment_type is not EmploymentType.FULL_TIME:
            continue
        employee_id = employee.employee_id
        attendance = employee_metrics[
            (employee_id, FairnessMetric.ATTENDANCE_DAYS)
        ]
        active = model.new_bool_var(f"ratio_active[{employee_id}]")
        model.add(attendance >= 1).only_enforce_if(active)
        model.add(attendance == 0).only_enforce_if(active.Not())
        employee_attendance_active[employee_id] = active
        assert employee.full_time_class is not None
        for metric in full_time_classes[employee.full_time_class]:
            ratio_name = f"pattern_ratio_bp[{employee_id},{metric.value}]"
            ratio_index = model.new_int_var(
                0,
                (individual_maximum_denominator + 1) ** 2 - 1,
                f"{ratio_name}_index",
            )
            model.add(
                ratio_index
                == employee_metrics[(employee_id, metric)]
                * (individual_maximum_denominator + 1)
                + attendance
            )
            ratio = model.new_int_var(
                0,
                BASIS_POINTS_SCALE,
                ratio_name,
            )
            model.add_element(
                ratio_index,
                individual_ratio_lookup,
                ratio,
            )
            employee_ratios[(employee_id, metric)] = ratio

    ratio_gaps: dict[tuple[str, FairnessMetric], cp_model.IntVar] = {}
    for full_time_class, metrics in full_time_classes.items():
        groups: dict[str, list[Employee]] = defaultdict(list)
        for employee in data.source.employees:
            if employee.full_time_class is full_time_class:
                groups[employee.fairness_group].append(employee)
        for group, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            for metric in metrics:
                ratios = [
                    employee_ratios[(employee.employee_id, metric)]
                    for employee in members
                ]
                effective_mins: list[cp_model.IntVar] = []
                active_variables = [
                    employee_attendance_active[employee.employee_id]
                    for employee in members
                ]
                for employee, ratio, active in zip(
                    members, ratios, active_variables, strict=True
                ):
                    effective = model.new_int_var(
                        0,
                        BASIS_POINTS_SCALE,
                        f"ratio_effective_min[{employee.employee_id},{metric.value}]",
                    )
                    model.add(effective == ratio).only_enforce_if(active)
                    model.add(effective == BASIS_POINTS_SCALE).only_enforce_if(
                        active.Not()
                    )
                    effective_mins.append(effective)
                maximum = model.new_int_var(
                    0,
                    BASIS_POINTS_SCALE,
                    f"ratio_max[{full_time_class.value},{group},{metric.value}]",
                )
                minimum = model.new_int_var(
                    0,
                    BASIS_POINTS_SCALE,
                    f"ratio_min[{full_time_class.value},{group},{metric.value}]",
                )
                any_active = model.new_bool_var(
                    f"ratio_any_active[{full_time_class.value},{group},{metric.value}]"
                )
                gap = model.new_int_var(
                    0,
                    BASIS_POINTS_SCALE,
                    f"ratio_gap[{full_time_class.value},{group},{metric.value}]",
                )
                model.add_max_equality(maximum, ratios)
                model.add_min_equality(minimum, effective_mins)
                model.add_max_equality(any_active, active_variables)
                model.add(gap == maximum - minimum).only_enforce_if(
                    any_active
                )
                model.add(gap == 0).only_enforce_if(any_active.Not())
                ratio_gaps[(group, metric)] = gap
    ratio_max_gap: cp_model.IntVar | None = None
    if ratio_gaps:
        ratio_max_gap = model.new_int_var(
            0, BASIS_POINTS_SCALE, "full_time_pattern_ratio_max_gap"
        )
        model.add_max_equality(ratio_max_gap, list(ratio_gaps.values()))

    stage_members_and_metrics = {
        OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS: (
            tuple(
                employee
                for employee in data.source.employees
                if employee.employment_type is EmploymentType.FULL_TIME
            ),
            None,
        ),
        OptimizationStage.PART_TIME_GROUP_FAIRNESS: (
            tuple(
                employee
                for employee in data.source.employees
                if employee.employment_type is EmploymentType.PART_TIME
            ),
            (FairnessMetric.TOTAL_SHIFTS,),
        ),
        OptimizationStage.COMMON_GROUP_FAIRNESS: (
            tuple(data.source.employees),
            (
                FairnessMetric.MORNING_SHIFTS,
                FairnessMetric.AFTERNOON_SHIFTS,
                FairnessMetric.EVENING_SHIFTS,
                FairnessMetric.SUNDAY_SHIFTS,
                FairnessMetric.HOLIDAY_SHIFTS,
            ),
        ),
    }
    fairness_gaps: dict[
        OptimizationStage,
        Mapping[tuple[str, FairnessMetric], cp_model.IntVar],
    ] = {}
    fairness_objectives: dict[
        OptimizationStage, cp_model.LinearExpr | int
    ] = {}
    for stage, (employees, metrics) in stage_members_and_metrics.items():
        groups: dict[str, list[Employee]] = defaultdict(list)
        for employee in employees:
            groups[employee.fairness_group].append(employee)
        stage_gaps: dict[tuple[str, FairnessMetric], cp_model.IntVar] = {}
        for group, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            group_metrics = (
                full_time_classes[members[0].full_time_class]
                if metrics is None
                else metrics
            )
            for metric in group_metrics:
                member_values = [
                    employee_metrics[(employee.employee_id, metric)]
                    for employee in members
                ]
                maximum = model.new_int_var(
                    0,
                    metric_upper_bound,
                    f"fairness_max[{stage.value},{group},{metric.value}]",
                )
                minimum = model.new_int_var(
                    0,
                    metric_upper_bound,
                    f"fairness_min[{stage.value},{group},{metric.value}]",
                )
                gap = model.new_int_var(
                    0,
                    metric_upper_bound,
                    f"fairness_gap[{stage.value},{group},{metric.value}]",
                )
                model.add_max_equality(maximum, member_values)
                model.add_min_equality(minimum, member_values)
                model.add(gap == maximum - minimum)
                stage_gaps[(group, metric)] = gap
        fairness_gaps[stage] = MappingProxyType(stage_gaps)
        fairness_objectives[stage] = sum(stage_gaps.values())

    return OptimizationModel(
        feasibility=feasibility,
        target_differences=MappingProxyType(target_differences),
        target_deviations=MappingProxyType(target_deviations),
        target_objective=sum(target_deviations.values()),
        part_time_objective=sum(part_time_counts),
        consecutive_double_variables=MappingProxyType(consecutive_variables),
        single_shift_variables=MappingProxyType(single_variables),
        secondary_pattern_variables=MappingProxyType(secondary_variables),
        consecutive_double_objective=sum(consecutive_variables.values()),
        single_shift_objective=sum(single_variables.values()),
        secondary_pattern_objective=sum(secondary_variables.values()),
        employee_fairness_metrics=MappingProxyType(employee_metrics),
        employee_pattern_ratio_basis_points=MappingProxyType(employee_ratios),
        employee_attendance_active=MappingProxyType(employee_attendance_active),
        class_attendance_totals=class_quality.attendance_totals,
        class_quality_counts=class_quality.quality_counts,
        class_quality_ratio_basis_points=class_quality.ratios,
        class_quality_ratio_gap_variables=class_quality.gaps,
        class_quality_ratio_max_gap_variable=class_quality.max_gap,
        class_quality_ratio_total_objective=class_quality.total_gap,
        ratio_fairness_gap_variables=MappingProxyType(ratio_gaps),
        ratio_fairness_max_gap_variable=ratio_max_gap,
        ratio_fairness_total_objective=sum(ratio_gaps.values()),
        fairness_gap_variables=MappingProxyType(fairness_gaps),
        fairness_objectives=MappingProxyType(fairness_objectives),
    )


def _attach_class_quality_model(
    data: NormalizedScheduleInput,
    built: OptimizationModel,
) -> OptimizationModel:
    class_quality = _build_class_quality_model(
        data,
        built.feasibility.model,
        built.employee_fairness_metrics,
    )
    return replace(
        built,
        class_attendance_totals=class_quality.attendance_totals,
        class_quality_counts=class_quality.quality_counts,
        class_quality_ratio_basis_points=class_quality.ratios,
        class_quality_ratio_gap_variables=class_quality.gaps,
        class_quality_ratio_max_gap_variable=class_quality.max_gap,
        class_quality_ratio_total_objective=class_quality.total_gap,
    )


def build_phase_four_model(data: NormalizedScheduleInput) -> OptimizationModel:
    """Compatibility alias for the former public builder name."""

    return build_optimization_model(data)


def _hard_minimum(employee: Employee) -> int:
    if employee.shift_mode is ShiftMode.EXACT:
        assert employee.required_shifts is not None
        return employee.required_shifts
    return employee.min_shifts or 0


def _hard_fixed_count(
    employee: Employee,
    precheck: PrecheckResult,
) -> int | None:
    minimum = _hard_minimum(employee)
    maximum = precheck.employee_capacities[employee.employee_id]
    return minimum if minimum == maximum else None


def _target_constant(
    data: NormalizedScheduleInput,
    precheck: PrecheckResult,
) -> tuple[int | None, ConstantProof | None]:
    target_employees = tuple(
        employee
        for employee in data.source.employees
        if employee.shift_mode is ShiftMode.TARGET
    )
    if not target_employees:
        return 0, ConstantProof.NO_TARGET_EMPLOYEES

    fixed_counts = {
        employee.employee_id: _hard_fixed_count(employee, precheck)
        for employee in target_employees
    }
    if all(value is not None for value in fixed_counts.values()):
        return (
            sum(
                abs(fixed_counts[employee.employee_id] - employee.target_shifts)
                for employee in target_employees
            ),
            ConstantProof.ALL_TARGET_COUNTS_HARD_FIXED,
        )
    return None, None


def _part_time_constant(
    data: NormalizedScheduleInput,
    precheck: PrecheckResult,
) -> tuple[int | None, ConstantProof | None]:
    part_time = tuple(
        employee
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    if not part_time:
        return 0, ConstantProof.NO_PART_TIME_EMPLOYEES

    fixed_part_time = tuple(
        _hard_fixed_count(employee, precheck) for employee in part_time
    )
    if all(value is not None for value in fixed_part_time):
        return (
            sum(value for value in fixed_part_time if value is not None),
            ConstantProof.ALL_PART_TIME_COUNTS_HARD_FIXED,
        )

    full_time = tuple(
        employee
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.FULL_TIME
    )
    fixed_full_time = tuple(
        _hard_fixed_count(employee, precheck) for employee in full_time
    )
    if all(value is not None for value in fixed_full_time):
        fixed_full_time_total = sum(
            value for value in fixed_full_time if value is not None
        )
        return (
            precheck.total_demand - fixed_full_time_total,
            ConstantProof.ALL_FULL_TIME_COUNTS_HARD_FIXED_BY_COVERAGE,
        )
    return None, None


def _objective_specs(
    data: NormalizedScheduleInput,
    built: OptimizationModel,
    precheck: PrecheckResult,
) -> tuple[_ObjectiveSpec, ...]:
    target_constant, target_proof = _target_constant(data, precheck)
    part_time_constant, part_time_proof = _part_time_constant(data, precheck)
    part_time_variables = tuple(
        built.feasibility.employee_shift_counts[employee.employee_id]
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    full_time_exists = any(
        employee.employment_type is EmploymentType.FULL_TIME
        for employee in data.source.employees
    )

    def pattern_constant(
        variables: Mapping[PatternKey, cp_model.IntVar],
    ) -> tuple[int | None, ConstantProof | None]:
        if not full_time_exists:
            return 0, ConstantProof.NO_FULL_TIME_EMPLOYEES
        if not variables:
            return 0, ConstantProof.NO_PATTERN_OPPORTUNITY
        return None, None

    consecutive_constant, consecutive_proof = pattern_constant(
        built.consecutive_double_variables
    )
    single_constant, single_proof = pattern_constant(
        built.single_shift_variables
    )
    secondary_constant, secondary_proof = pattern_constant(
        built.secondary_pattern_variables
    )
    ratio_gaps = built.ratio_fairness_gap_variables
    ratio_constant = None if ratio_gaps else 0
    ratio_proof = (
        None if ratio_gaps else ConstantProof.NO_COMPARABLE_FAIRNESS_GROUPS
    )
    class_quality_gaps = built.class_quality_ratio_gap_variables
    class_quality_constant = None if class_quality_gaps else 0
    class_quality_proof = (
        None
        if class_quality_gaps
        else ConstantProof.NO_COMPARABLE_FULL_TIME_CLASSES
    )
    fairness_specs: list[_ObjectiveSpec] = [
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP,
            direction=ObjectiveDirection.MINIMIZE,
            variables=(built.class_quality_ratio_max_gap_variable,)
            if built.class_quality_ratio_max_gap_variable is not None
            else (),
            expression=(
                built.class_quality_ratio_max_gap_variable
                if built.class_quality_ratio_max_gap_variable is not None
                else 0
            ),
            constant_value=class_quality_constant,
            constant_proof=class_quality_proof,
        ),
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_CLASS_QUALITY_RATIO_TOTAL_GAP,
            direction=ObjectiveDirection.MINIMIZE,
            variables=tuple(class_quality_gaps.values()),
            expression=built.class_quality_ratio_total_objective,
            constant_value=class_quality_constant,
            constant_proof=class_quality_proof,
        ),
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
            direction=ObjectiveDirection.MINIMIZE,
            variables=(built.ratio_fairness_max_gap_variable,)
            if built.ratio_fairness_max_gap_variable is not None
            else (),
            expression=(
                built.ratio_fairness_max_gap_variable
                if built.ratio_fairness_max_gap_variable is not None
                else 0
            ),
            constant_value=ratio_constant,
            constant_proof=ratio_proof,
        ),
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
            direction=ObjectiveDirection.MINIMIZE,
            variables=tuple(ratio_gaps.values()),
            expression=built.ratio_fairness_total_objective,
            constant_value=ratio_constant,
            constant_proof=ratio_proof,
        ),
    ]
    for fairness_stage in (
        OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,
        OptimizationStage.PART_TIME_GROUP_FAIRNESS,
        OptimizationStage.COMMON_GROUP_FAIRNESS,
    ):
        gaps = built.fairness_gap_variables[fairness_stage]
        constant_value = None if gaps else 0
        constant_proof = (
            None if gaps else ConstantProof.NO_COMPARABLE_FAIRNESS_GROUPS
        )
        fairness_specs.append(
            _ObjectiveSpec(
                stage=fairness_stage,
                direction=ObjectiveDirection.MINIMIZE,
                variables=tuple(gaps.values()),
                expression=built.fairness_objectives[fairness_stage],
                constant_value=constant_value,
                constant_proof=constant_proof,
            )
        )
    return (
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_TARGET_DEVIATION,
            direction=ObjectiveDirection.MINIMIZE,
            variables=tuple(built.target_deviations.values()),
            expression=built.target_objective,
            constant_value=target_constant,
            constant_proof=target_proof,
        ),
        _ObjectiveSpec(
            stage=OptimizationStage.PART_TIME_USAGE,
            direction=ObjectiveDirection.MINIMIZE,
            variables=part_time_variables,
            expression=built.part_time_objective,
            constant_value=part_time_constant,
            constant_proof=part_time_proof,
        ),
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_CONSECUTIVE_DOUBLES,
            direction=ObjectiveDirection.MAXIMIZE,
            variables=tuple(built.consecutive_double_variables.values()),
            expression=built.consecutive_double_objective,
            constant_value=consecutive_constant,
            constant_proof=consecutive_proof,
        ),
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_SINGLE_SHIFT_DAYS,
            direction=ObjectiveDirection.MINIMIZE,
            variables=tuple(built.single_shift_variables.values()),
            expression=built.single_shift_objective,
            constant_value=single_constant,
            constant_proof=single_proof,
        ),
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_SECONDARY_PATTERNS,
            direction=ObjectiveDirection.MINIMIZE,
            variables=tuple(built.secondary_pattern_variables.values()),
            expression=built.secondary_pattern_objective,
            constant_value=secondary_constant,
            constant_proof=secondary_proof,
        ),
        *fairness_specs,
    )


def _solve_once(
    model: cp_model.CpModel,
    config: LexicographicSolverConfig,
) -> _SolverRun:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = config.num_search_workers
    solver.parameters.random_seed = config.random_seed
    if config.max_time_seconds_per_stage is not None:
        solver.parameters.max_time_in_seconds = config.max_time_seconds_per_stage
    raw_status = solver.solve(model)
    try:
        wall_time = solver.wall_time
    except RuntimeError:  # Supports deterministic mocked UNKNOWN tests.
        wall_time = 0.0
    return _SolverRun(
        solver=solver,
        raw_status=raw_status,
        raw_status_name=solver.status_name(raw_status),
        wall_time_seconds=wall_time,
    )


def _snapshot(
    data: NormalizedScheduleInput,
    built: OptimizationModel,
    solver: cp_model.CpSolver,
) -> _SolutionSnapshot:
    assignments, daily_patterns = extract_model_solution(
        built.feasibility,
        solver,
    )
    shift_counts = {
        employee_id: solver.value(variable)
        for employee_id, variable in built.feasibility.employee_shift_counts.items()
    }
    deviations = {
        employee_id: solver.value(variable)
        for employee_id, variable in built.target_deviations.items()
    }
    part_time_total = sum(
        shift_counts[employee.employee_id]
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    return _SolutionSnapshot(
        assignments=assignments,
        daily_patterns=daily_patterns,
        employee_shift_counts=MappingProxyType(shift_counts),
        target_deviations=MappingProxyType(deviations),
        part_time_total=part_time_total,
    )


def _empty_result(
    status: FeasibilityStatus,
    precheck: PrecheckResult,
    stages: tuple[OptimizationStageResult, ...] = (),
) -> LexicographicResult:
    return LexicographicResult(
        status=status,
        assignments=(),
        daily_patterns=MappingProxyType({}),
        employee_shift_counts=MappingProxyType({}),
        target_deviations=MappingProxyType({}),
        part_time_total=None,
        stages=stages,
        precheck=precheck,
        implemented_objective_prefix_optimal=False,
    )


def _result_from_snapshot(
    status: FeasibilityStatus,
    snapshot: _SolutionSnapshot,
    stages: list[OptimizationStageResult],
    precheck: PrecheckResult,
    *,
    implemented_objective_prefix_optimal: bool = False,
) -> LexicographicResult:
    return LexicographicResult(
        status=status,
        assignments=snapshot.assignments,
        daily_patterns=snapshot.daily_patterns,
        employee_shift_counts=snapshot.employee_shift_counts,
        target_deviations=snapshot.target_deviations,
        part_time_total=snapshot.part_time_total,
        stages=tuple(stages),
        precheck=precheck,
        implemented_objective_prefix_optimal=implemented_objective_prefix_optimal,
    )


def solve_lexicographic(
    data: NormalizedScheduleInput,
    config: LexicographicSolverConfig | None = None,
) -> LexicographicResult:
    """Optimize the implemented v1 objective prefix with exact value locks."""

    config = config or LexicographicSolverConfig()
    precheck = run_prechecks(data)
    if precheck.status is PrecheckStatus.PRECHECK_INFEASIBLE:
        return _empty_result(FeasibilityStatus.PRECHECK_INFEASIBLE, precheck)

    # Class-level ratio constraints are attached only after the first six
    # formal layers are locked.  They are irrelevant before then and can make
    # those earlier CP-SAT proofs substantially more expensive.
    built = build_optimization_model(data, include_class_quality=False)
    stages: list[OptimizationStageResult] = []
    hard_run = _solve_once(built.feasibility.model, config)
    if hard_run.raw_status == cp_model.INFEASIBLE:
        stages.append(
            OptimizationStageResult(
                stage=OptimizationStage.HARD_FEASIBILITY,
                direction=ObjectiveDirection.NONE,
                status=OptimizationStageStatus.INFEASIBLE,
                objective_value=None,
                raw_solver_status=hard_run.raw_status_name,
                wall_time_seconds=hard_run.wall_time_seconds,
                locked=False,
            )
        )
        return _empty_result(
            FeasibilityStatus.INFEASIBLE,
            precheck,
            tuple(stages),
        )
    if hard_run.raw_status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        stages.append(
            OptimizationStageResult(
                stage=OptimizationStage.HARD_FEASIBILITY,
                direction=ObjectiveDirection.NONE,
                status=OptimizationStageStatus.UNKNOWN,
                objective_value=None,
                raw_solver_status=hard_run.raw_status_name,
                wall_time_seconds=hard_run.wall_time_seconds,
                locked=False,
            )
        )
        return _empty_result(
            FeasibilityStatus.UNKNOWN,
            precheck,
            tuple(stages),
        )

    stages.append(
        OptimizationStageResult(
            stage=OptimizationStage.HARD_FEASIBILITY,
            direction=ObjectiveDirection.NONE,
            status=OptimizationStageStatus.FEASIBLE,
            objective_value=None,
            raw_solver_status=hard_run.raw_status_name,
            wall_time_seconds=hard_run.wall_time_seconds,
            locked=False,
        )
    )
    snapshot = _snapshot(data, built, hard_run.solver)

    objective_specs = list(_objective_specs(data, built, precheck)[:5])
    for objective in objective_specs:
        if objective.constant_value is not None:
            stages.append(
                OptimizationStageResult(
                    stage=objective.stage,
                    direction=objective.direction,
                    status=OptimizationStageStatus.SKIPPED_CONSTANT,
                    objective_value=objective.constant_value,
                    raw_solver_status="NOT_RUN",
                    wall_time_seconds=0.0,
                    locked=False,
                    constant_proof=objective.constant_proof,
                )
            )
            if objective.stage is OptimizationStage.FULL_TIME_SECONDARY_PATTERNS:
                built = _attach_class_quality_model(data, built)
                objective_specs.extend(
                    _objective_specs(data, built, precheck)[5:]
                )
            continue

        if objective.direction is ObjectiveDirection.MAXIMIZE:
            built.feasibility.model.maximize(objective.expression)
        else:
            built.feasibility.model.minimize(objective.expression)
        run = _solve_once(built.feasibility.model, config)
        if run.raw_status == cp_model.OPTIMAL:
            objective_value = sum(
                run.solver.value(variable) for variable in objective.variables
            )
            built.feasibility.model.add(
                objective.expression == objective_value
            )
            stages.append(
                OptimizationStageResult(
                    stage=objective.stage,
                    direction=objective.direction,
                    status=OptimizationStageStatus.OPTIMAL,
                    objective_value=objective_value,
                    raw_solver_status=run.raw_status_name,
                    wall_time_seconds=run.wall_time_seconds,
                    locked=True,
                )
            )
            snapshot = _snapshot(data, built, run.solver)
            if objective.stage is OptimizationStage.FULL_TIME_SECONDARY_PATTERNS:
                built = _attach_class_quality_model(data, built)
                objective_specs.extend(
                    _objective_specs(data, built, precheck)[5:]
                )
            continue

        if run.raw_status == cp_model.FEASIBLE:
            objective_value = sum(
                run.solver.value(variable) for variable in objective.variables
            )
            stages.append(
                OptimizationStageResult(
                    stage=objective.stage,
                    direction=objective.direction,
                    status=OptimizationStageStatus.FEASIBLE,
                    objective_value=objective_value,
                    raw_solver_status=run.raw_status_name,
                    wall_time_seconds=run.wall_time_seconds,
                    locked=False,
                )
            )
            snapshot = _snapshot(data, built, run.solver)
            return _result_from_snapshot(
                FeasibilityStatus.FEASIBLE,
                snapshot,
                stages,
                precheck,
            )

        stage_status = (
            OptimizationStageStatus.INFEASIBLE
            if run.raw_status == cp_model.INFEASIBLE
            else OptimizationStageStatus.UNKNOWN
        )
        stages.append(
            OptimizationStageResult(
                stage=objective.stage,
                direction=objective.direction,
                status=stage_status,
                objective_value=None,
                raw_solver_status=run.raw_status_name,
                wall_time_seconds=run.wall_time_seconds,
                locked=False,
            )
        )
        return _result_from_snapshot(
            FeasibilityStatus.FEASIBLE,
            snapshot,
            stages,
            precheck,
        )

    return _result_from_snapshot(
        FeasibilityStatus.FEASIBLE,
        snapshot,
        stages,
        precheck,
        implemented_objective_prefix_optimal=True,
    )
