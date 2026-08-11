"""Strict v1 lexicographic objectives through group fairness.

Formal independent output validation remains outside this module's scope.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
import signal
import threading
from time import perf_counter
from types import MappingProxyType
from typing import Mapping

from ortools.sat.python import cp_model

from .class_preferences import (
    CLASS_PREFERENCES,
    ClassPreferenceMetric,
    PreferenceDirection,
    PreferenceRank,
    class_opportunity_days,
)
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
    FULL_TIME_CONSECUTIVE_RATIO_MAX_GAP = (
        "full_time_consecutive_ratio_max_gap"
    )
    FULL_TIME_CONSECUTIVE_RATIO_TOTAL_GAP = (
        "full_time_consecutive_ratio_total_gap"
    )
    FULL_TIME_SINGLE_SHIFT_DAYS = "full_time_single_shift_days"
    FULL_TIME_SECONDARY_PATTERNS = "full_time_secondary_patterns"
    FULL_TIME_CLASS_QUALITY_RATIO_MAX_GAP = (
        "full_time_class_quality_ratio_max_gap"
    )
    FULL_TIME_CLASS_QUALITY_RATIO_TOTAL_GAP = (
        "full_time_class_quality_ratio_total_gap"
    )
    FULL_TIME_PREFERENCE_RANK1_MAX_REGRET = (
        "full_time_preference_rank1_max_regret"
    )
    FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET = (
        "full_time_preference_rank1_total_regret"
    )
    FULL_TIME_PREFERENCE_RANK2_MAX_REGRET = (
        "full_time_preference_rank2_max_regret"
    )
    FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET = (
        "full_time_preference_rank2_total_regret"
    )
    FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_MAX_GAP = (
        "full_time_preference_rank1_person_ratio_max_gap"
    )
    FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_TOTAL_GAP = (
        "full_time_preference_rank1_person_ratio_total_gap"
    )
    FULL_TIME_PREFERENCE_RANK2_PERSON_RATIO_MAX_GAP = (
        "full_time_preference_rank2_person_ratio_max_gap"
    )
    FULL_TIME_PREFERENCE_RANK2_PERSON_RATIO_TOTAL_GAP = (
        "full_time_preference_rank2_person_ratio_total_gap"
    )
    FULL_TIME_REMAINING_PATTERN_RATIO_MAX_GAP = (
        "full_time_remaining_pattern_ratio_max_gap"
    )
    FULL_TIME_REMAINING_PATTERN_RATIO_TOTAL_GAP = (
        "full_time_remaining_pattern_ratio_total_gap"
    )
    FULL_TIME_PATTERN_RATIO_MAX_GAP = "full_time_pattern_ratio_max_gap"
    FULL_TIME_FIRST_PREFERENCE_RATIO_TOTAL_GAP = (
        "full_time_first_preference_ratio_total_gap"
    )
    FULL_TIME_PATTERN_RATIO_TOTAL_GAP = "full_time_pattern_ratio_total_gap"
    FULL_TIME_PATTERN_INTEGER_FAIRNESS = "full_time_pattern_integer_fairness"
    PART_TIME_GROUP_FAIRNESS = "part_time_group_fairness"
    COMMON_GROUP_FAIRNESS = "common_group_fairness"
    FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP = (
        "full_time_sunday_fairness_max_gap"
    )
    FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP = (
        "full_time_sunday_fairness_total_gap"
    )


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
    SUNDAY_ATTENDANCE_DAYS = "sunday_attendance_days"
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
    NO_COMPARABLE_FULL_TIME_EMPLOYEES = (
        "NO_COMPARABLE_FULL_TIME_EMPLOYEES"
    )
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


class EquivalentSolutionDiagnosticStatus(StrEnum):
    """Proof status for bounded enumeration of equal-quality alternatives."""

    EXACT_COUNT = "EXACT_COUNT"
    AT_LEAST_LIMIT = "AT_LEAST_LIMIT"
    TIME_LIMIT = "TIME_LIMIT"
    INTERRUPTED = "INTERRUPTED"


@dataclass(frozen=True, slots=True)
class EquivalentSolutionDiagnosticConfig:
    """Optional post-output search limits for equal-quality assignments."""

    max_alternatives: int = 100
    max_time_seconds: float | None = None
    scheduling_time_ratio: float = 0.2
    num_search_workers: int = 1
    random_seed: int = 0

    def __post_init__(self) -> None:
        if self.max_alternatives <= 0:
            raise ValueError("max_alternatives must be greater than 0")
        if self.max_time_seconds is not None and self.max_time_seconds <= 0:
            raise ValueError("max_time_seconds must be greater than 0")
        if (
            isinstance(self.scheduling_time_ratio, bool)
            or not isinstance(self.scheduling_time_ratio, (int, float))
            or self.scheduling_time_ratio <= 0
        ):
            raise ValueError("scheduling_time_ratio must be greater than 0")
        if self.num_search_workers <= 0:
            raise ValueError("num_search_workers must be greater than 0")


@dataclass(frozen=True, slots=True)
class EquivalentSolutionDiagnosticResult:
    """Bounded count of alternatives excluding the formal assignment."""

    status: EquivalentSolutionDiagnosticStatus
    alternative_count: int
    search_limit: int
    time_limit_seconds: float
    wall_time_seconds: float

    @property
    def is_exact(self) -> bool:
        return self.status is EquivalentSolutionDiagnosticStatus.EXACT_COUNT


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
class PreferenceBenchmarkResult:
    full_time_class: FullTimeClass
    rank: PreferenceRank
    metric: ClassPreferenceMetric
    direction: PreferenceDirection
    status: OptimizationStageStatus
    ideal_value: int | None
    locked_actual_value: int | None
    opportunity_days: int
    raw_solver_status: str
    wall_time_seconds: float


@dataclass(frozen=True, slots=True)
class ClassPatternLockResult:
    full_time_class: FullTimeClass
    metric: FairnessMetric
    locked_value: int


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
    class_preference_values: Mapping[
        tuple[FullTimeClass, PreferenceRank], cp_model.IntVar
    ]
    class_remaining_pattern_values: Mapping[FullTimeClass, cp_model.IntVar]
    class_preference_regret_basis_points: Mapping[
        tuple[FullTimeClass, PreferenceRank], cp_model.IntVar
    ]
    class_preference_max_regret_variables: Mapping[
        PreferenceRank, cp_model.IntVar
    ]
    class_preference_total_regret_objectives: Mapping[
        PreferenceRank, cp_model.LinearExpr | int
    ]
    employee_fairness_metrics: Mapping[
        tuple[str, FairnessMetric], cp_model.IntVar
    ]
    employee_pattern_ratio_basis_points: Mapping[
        tuple[str, FairnessMetric], cp_model.IntVar
    ]
    employee_attendance_active: Mapping[str, cp_model.IntVar]
    global_consecutive_ratio_gap_variable: cp_model.IntVar | None
    global_consecutive_ratio_pairwise_gap_variables: Mapping[
        tuple[str, str], cp_model.IntVar
    ]
    global_consecutive_ratio_total_objective: cp_model.LinearExpr | int
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
    preference_ratio_gap_variables: Mapping[
        OptimizationStage,
        Mapping[tuple[str, FairnessMetric], cp_model.IntVar],
    ]
    preference_ratio_max_gap_variables: Mapping[
        OptimizationStage, cp_model.IntVar | None
    ]
    preference_ratio_total_objectives: Mapping[
        OptimizationStage, cp_model.LinearExpr | int
    ]
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
    preference_benchmarks: tuple[PreferenceBenchmarkResult, ...]
    class_pattern_locks: tuple[ClassPatternLockResult, ...]
    precheck: PrecheckResult
    implemented_objective_prefix_optimal: bool
    _locked_model: OptimizationModel | None = field(
        default=None,
        repr=False,
        compare=False,
    )

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
            FairnessMetric.SUNDAY_ATTENDANCE_DAYS,
            [
                feasibility.daily_patterns[(employee_id, day, pattern)]
                for day in data.dates
                if day.weekday() == 6
                for pattern in DailyPattern
                if pattern is not DailyPattern.OFF
                and (employee_id, day, pattern)
                in feasibility.daily_patterns
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

    preference_metric_map = {
        ClassPreferenceMetric.CONSECUTIVE_DOUBLES: (
            FairnessMetric.CONSECUTIVE_DOUBLES
        ),
        ClassPreferenceMetric.SINGLE_SHIFT_DAYS: (
            FairnessMetric.SINGLE_SHIFT_DAYS
        ),
        ClassPreferenceMetric.MORNING_EVENING_DAYS: (
            FairnessMetric.MORNING_EVENING_DAYS
        ),
    }
    class_preference_values: dict[
        tuple[FullTimeClass, PreferenceRank], cp_model.IntVar
    ] = {}
    for definition in CLASS_PREFERENCES:
        members = tuple(
            employee
            for employee in data.source.employees
            if employee.full_time_class is definition.full_time_class
        )
        value = model.new_int_var(
            0,
            len(members) * len(data.dates),
            (
                "class_preference_value"
                f"[{definition.full_time_class.value},{definition.rank.value}]"
            ),
        )
        model.add(
            value
            == sum(
                employee_metrics[
                    (
                        employee.employee_id,
                        preference_metric_map[definition.metric],
                    )
                ]
                for employee in members
            )
        )
        class_preference_values[
            (definition.full_time_class, definition.rank)
        ] = value

    remaining_pattern_metrics = {
        FullTimeClass.A: FairnessMetric.SINGLE_SHIFT_DAYS,
        FullTimeClass.B: FairnessMetric.TRIPLE_DAYS,
    }
    class_remaining_pattern_values: dict[FullTimeClass, cp_model.IntVar] = {}
    for full_time_class, metric in remaining_pattern_metrics.items():
        members = tuple(
            employee
            for employee in data.source.employees
            if employee.full_time_class is full_time_class
        )
        value = model.new_int_var(
            0,
            len(members) * len(data.dates),
            f"class_remaining_pattern_value[{full_time_class.value}]",
        )
        model.add(
            value
            == sum(
                employee_metrics[(employee.employee_id, metric)]
                for employee in members
            )
        )
        class_remaining_pattern_values[full_time_class] = value

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

    full_time_employees = tuple(
        employee
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.FULL_TIME
    )
    global_consecutive_gap: cp_model.IntVar | None = None
    global_consecutive_pairwise_gaps: dict[
        tuple[str, str], cp_model.IntVar
    ] = {}
    if len(full_time_employees) >= 2:
        ratios = [
            employee_ratios[
                (employee.employee_id, FairnessMetric.CONSECUTIVE_DOUBLES)
            ]
            for employee in full_time_employees
        ]
        active_variables = [
            employee_attendance_active[employee.employee_id]
            for employee in full_time_employees
        ]
        effective_mins: list[cp_model.IntVar] = []
        for employee, ratio, active in zip(
            full_time_employees,
            ratios,
            active_variables,
            strict=True,
        ):
            effective = model.new_int_var(
                0,
                BASIS_POINTS_SCALE,
                f"global_consecutive_effective_min[{employee.employee_id}]",
            )
            model.add(effective == ratio).only_enforce_if(active)
            model.add(effective == BASIS_POINTS_SCALE).only_enforce_if(
                active.Not()
            )
            effective_mins.append(effective)
        maximum = model.new_int_var(
            0,
            BASIS_POINTS_SCALE,
            "global_consecutive_ratio_max",
        )
        minimum = model.new_int_var(
            0,
            BASIS_POINTS_SCALE,
            "global_consecutive_ratio_min",
        )
        any_active = model.new_bool_var("global_consecutive_ratio_any_active")
        global_consecutive_gap = model.new_int_var(
            0,
            BASIS_POINTS_SCALE,
            "full_time_consecutive_ratio_max_gap",
        )
        model.add_max_equality(maximum, ratios)
        model.add_min_equality(minimum, effective_mins)
        model.add_max_equality(any_active, active_variables)
        model.add(global_consecutive_gap == maximum - minimum).only_enforce_if(
            any_active
        )
        model.add(global_consecutive_gap == 0).only_enforce_if(any_active.Not())

        for left_index, left in enumerate(full_time_employees):
            for right in full_time_employees[left_index + 1 :]:
                left_id = left.employee_id
                right_id = right.employee_id
                difference = model.new_int_var(
                    -BASIS_POINTS_SCALE,
                    BASIS_POINTS_SCALE,
                    f"global_consecutive_difference[{left_id},{right_id}]",
                )
                absolute_difference = model.new_int_var(
                    0,
                    BASIS_POINTS_SCALE,
                    f"global_consecutive_absolute_difference[{left_id},{right_id}]",
                )
                pair_active = model.new_bool_var(
                    f"global_consecutive_pair_active[{left_id},{right_id}]"
                )
                pair_gap = model.new_int_var(
                    0,
                    BASIS_POINTS_SCALE,
                    f"global_consecutive_pair_gap[{left_id},{right_id}]",
                )
                model.add(
                    difference
                    == employee_ratios[
                        (left_id, FairnessMetric.CONSECUTIVE_DOUBLES)
                    ]
                    - employee_ratios[
                        (right_id, FairnessMetric.CONSECUTIVE_DOUBLES)
                    ]
                )
                model.add_abs_equality(absolute_difference, difference)
                model.add_min_equality(
                    pair_active,
                    [
                        employee_attendance_active[left_id],
                        employee_attendance_active[right_id],
                    ],
                )
                model.add(pair_gap == absolute_difference).only_enforce_if(
                    pair_active
                )
                model.add(pair_gap == 0).only_enforce_if(pair_active.Not())
                global_consecutive_pairwise_gaps[(left_id, right_id)] = pair_gap

    ratio_gaps: dict[tuple[str, FairnessMetric], cp_model.IntVar] = {}
    preference_ratio_gaps: dict[
        OptimizationStage,
        dict[tuple[str, FairnessMetric], cp_model.IntVar],
    ] = {
        OptimizationStage.FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_MAX_GAP: {},
        OptimizationStage.FULL_TIME_PREFERENCE_RANK2_PERSON_RATIO_MAX_GAP: {},
        OptimizationStage.FULL_TIME_REMAINING_PATTERN_RATIO_MAX_GAP: {},
    }
    preference_ratio_stage = {
        (FullTimeClass.A, FairnessMetric.CONSECUTIVE_DOUBLES): (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_MAX_GAP
        ),
        (FullTimeClass.B, FairnessMetric.SINGLE_SHIFT_DAYS): (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_MAX_GAP
        ),
        (FullTimeClass.A, FairnessMetric.MORNING_EVENING_DAYS): (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_PERSON_RATIO_MAX_GAP
        ),
        (FullTimeClass.B, FairnessMetric.CONSECUTIVE_DOUBLES): (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_PERSON_RATIO_MAX_GAP
        ),
        (FullTimeClass.A, FairnessMetric.SINGLE_SHIFT_DAYS): (
            OptimizationStage.FULL_TIME_REMAINING_PATTERN_RATIO_MAX_GAP
        ),
        (FullTimeClass.B, FairnessMetric.TRIPLE_DAYS): (
            OptimizationStage.FULL_TIME_REMAINING_PATTERN_RATIO_MAX_GAP
        ),
    }
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
                preference_ratio_gaps[
                    preference_ratio_stage[(full_time_class, metric)]
                ][(group, metric)] = gap
    ratio_max_gap: cp_model.IntVar | None = None
    if ratio_gaps:
        ratio_max_gap = model.new_int_var(
            0, BASIS_POINTS_SCALE, "full_time_pattern_ratio_max_gap"
        )
        model.add_max_equality(ratio_max_gap, list(ratio_gaps.values()))

    preference_ratio_max_gaps: dict[
        OptimizationStage, cp_model.IntVar | None
    ] = {}
    preference_ratio_totals: dict[
        OptimizationStage, cp_model.LinearExpr | int
    ] = {}
    for stage, gaps in preference_ratio_gaps.items():
        maximum: cp_model.IntVar | None = None
        if gaps:
            maximum = model.new_int_var(
                0,
                BASIS_POINTS_SCALE,
                f"{stage.value}_value",
            )
            model.add_max_equality(maximum, list(gaps.values()))
        preference_ratio_max_gaps[stage] = maximum
        preference_ratio_totals[stage] = sum(gaps.values())

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

    full_time_members = tuple(
        employee
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.FULL_TIME
    )
    sunday_gaps: dict[tuple[str, FairnessMetric], cp_model.IntVar] = {}
    sunday_max_gap: cp_model.IntVar | None = None
    if len(full_time_members) >= 2:
        for metric in (
            FairnessMetric.SUNDAY_SHIFTS,
            FairnessMetric.SUNDAY_ATTENDANCE_DAYS,
        ):
            member_values = [
                employee_metrics[(employee.employee_id, metric)]
                for employee in full_time_members
            ]
            maximum = model.new_int_var(
                0,
                metric_upper_bound,
                f"fairness_max[all_full_time,{metric.value}]",
            )
            minimum = model.new_int_var(
                0,
                metric_upper_bound,
                f"fairness_min[all_full_time,{metric.value}]",
            )
            gap = model.new_int_var(
                0,
                metric_upper_bound,
                f"fairness_gap[all_full_time,{metric.value}]",
            )
            model.add_max_equality(maximum, member_values)
            model.add_min_equality(minimum, member_values)
            model.add(gap == maximum - minimum)
            sunday_gaps[("ALL_FULL_TIME", metric)] = gap
        sunday_max_gap = model.new_int_var(
            0,
            metric_upper_bound,
            "full_time_sunday_fairness_max_gap",
        )
        model.add_max_equality(sunday_max_gap, list(sunday_gaps.values()))
    immutable_sunday_gaps = MappingProxyType(sunday_gaps)
    fairness_gaps[
        OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP
    ] = immutable_sunday_gaps
    fairness_gaps[
        OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP
    ] = immutable_sunday_gaps
    fairness_objectives[
        OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP
    ] = sunday_max_gap if sunday_max_gap is not None else 0
    fairness_objectives[
        OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP
    ] = sum(sunday_gaps.values())

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
        class_preference_values=MappingProxyType(class_preference_values),
        class_remaining_pattern_values=MappingProxyType(
            class_remaining_pattern_values
        ),
        class_preference_regret_basis_points=MappingProxyType({}),
        class_preference_max_regret_variables=MappingProxyType({}),
        class_preference_total_regret_objectives=MappingProxyType({}),
        employee_fairness_metrics=MappingProxyType(employee_metrics),
        employee_pattern_ratio_basis_points=MappingProxyType(employee_ratios),
        employee_attendance_active=MappingProxyType(employee_attendance_active),
        global_consecutive_ratio_gap_variable=global_consecutive_gap,
        global_consecutive_ratio_pairwise_gap_variables=MappingProxyType(
            global_consecutive_pairwise_gaps
        ),
        global_consecutive_ratio_total_objective=sum(
            global_consecutive_pairwise_gaps.values()
        ),
        class_attendance_totals=class_quality.attendance_totals,
        class_quality_counts=class_quality.quality_counts,
        class_quality_ratio_basis_points=class_quality.ratios,
        class_quality_ratio_gap_variables=class_quality.gaps,
        class_quality_ratio_max_gap_variable=class_quality.max_gap,
        class_quality_ratio_total_objective=class_quality.total_gap,
        ratio_fairness_gap_variables=MappingProxyType(ratio_gaps),
        ratio_fairness_max_gap_variable=ratio_max_gap,
        ratio_fairness_total_objective=sum(ratio_gaps.values()),
        preference_ratio_gap_variables=MappingProxyType(
            {
                stage: MappingProxyType(gaps)
                for stage, gaps in preference_ratio_gaps.items()
            }
        ),
        preference_ratio_max_gap_variables=MappingProxyType(
            preference_ratio_max_gaps
        ),
        preference_ratio_total_objectives=MappingProxyType(
            preference_ratio_totals
        ),
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


def _attach_preference_regret_model(
    data: NormalizedScheduleInput,
    built: OptimizationModel,
    benchmarks: tuple[PreferenceBenchmarkResult, ...],
    rank: PreferenceRank,
) -> OptimizationModel:
    model = built.feasibility.model
    regret_basis_points = dict(built.class_preference_regret_basis_points)
    max_regrets = dict(built.class_preference_max_regret_variables)
    total_regrets = dict(built.class_preference_total_regret_objectives)
    active_regrets: list[cp_model.IntVar] = []
    for definition in CLASS_PREFERENCES:
        if definition.rank is not rank:
            continue
        benchmark = next(
            item
            for item in benchmarks
            if item.full_time_class is definition.full_time_class
            and item.rank is rank
        )
        if benchmark.opportunity_days == 0:
            continue
        assert benchmark.ideal_value is not None
        actual = built.class_preference_values[
            (definition.full_time_class, rank)
        ]
        regret_days = model.new_int_var(
            0,
            benchmark.opportunity_days,
            (
                "class_preference_regret_days"
                f"[{definition.full_time_class.value},{rank.value}]"
            ),
        )
        if definition.direction is PreferenceDirection.MAXIMIZE:
            model.add(regret_days == benchmark.ideal_value - actual)
        else:
            model.add(regret_days == actual - benchmark.ideal_value)
        lookup = [
            ratio_basis_points(value, benchmark.opportunity_days) or 0
            for value in range(benchmark.opportunity_days + 1)
        ]
        regret_bp = model.new_int_var(
            0,
            BASIS_POINTS_SCALE,
            (
                "class_preference_regret_bp"
                f"[{definition.full_time_class.value},{rank.value}]"
            ),
        )
        model.add_element(regret_days, lookup, regret_bp)
        regret_basis_points[(definition.full_time_class, rank)] = regret_bp
        active_regrets.append(regret_bp)

    if active_regrets:
        maximum = model.new_int_var(
            0,
            BASIS_POINTS_SCALE,
            f"class_preference_max_regret[{rank.value}]",
        )
        model.add_max_equality(maximum, active_regrets)
        max_regrets[rank] = maximum
        total_regrets[rank] = sum(active_regrets)
    return replace(
        built,
        class_preference_regret_basis_points=MappingProxyType(
            regret_basis_points
        ),
        class_preference_max_regret_variables=MappingProxyType(max_regrets),
        class_preference_total_regret_objectives=MappingProxyType(
            total_regrets
        ),
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
    global_consecutive_gap = built.global_consecutive_ratio_gap_variable
    global_consecutive_pairwise_gaps = (
        built.global_consecutive_ratio_pairwise_gap_variables
    )
    global_consecutive_constant = (
        None if global_consecutive_gap is not None else 0
    )
    global_consecutive_proof = (
        None
        if global_consecutive_gap is not None
        else ConstantProof.NO_COMPARABLE_FULL_TIME_EMPLOYEES
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
            stage=OptimizationStage.FULL_TIME_CONSECUTIVE_RATIO_MAX_GAP,
            direction=ObjectiveDirection.MINIMIZE,
            variables=(global_consecutive_gap,)
            if global_consecutive_gap is not None
            else (),
            expression=(
                global_consecutive_gap
                if global_consecutive_gap is not None
                else 0
            ),
            constant_value=global_consecutive_constant,
            constant_proof=global_consecutive_proof,
        ),
        _ObjectiveSpec(
            stage=OptimizationStage.FULL_TIME_CONSECUTIVE_RATIO_TOTAL_GAP,
            direction=ObjectiveDirection.MINIMIZE,
            variables=tuple(global_consecutive_pairwise_gaps.values()),
            expression=built.global_consecutive_ratio_total_objective,
            constant_value=global_consecutive_constant,
            constant_proof=global_consecutive_proof,
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


def _formal_objective_specs(
    data: NormalizedScheduleInput,
    built: OptimizationModel,
    precheck: PrecheckResult,
) -> tuple[_ObjectiveSpec, ...]:
    """Return the revised class-specific formal objective sequence."""

    target_constant, target_proof = _target_constant(data, precheck)
    part_time_constant, part_time_proof = _part_time_constant(data, precheck)
    part_time_variables = tuple(
        built.feasibility.employee_shift_counts[employee.employee_id]
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    specs: list[_ObjectiveSpec] = [
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
    ]

    regret_stages = {
        PreferenceRank.FIRST: (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET,
        ),
        PreferenceRank.SECOND: (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET,
        ),
    }
    for rank in PreferenceRank:
        maximum_stage, total_stage = regret_stages[rank]
        maximum = built.class_preference_max_regret_variables.get(rank)
        regrets = tuple(
            value
            for (full_time_class, item_rank), value in (
                built.class_preference_regret_basis_points.items()
            )
            if item_rank is rank
        )
        constant = None if maximum is not None else 0
        proof = (
            None
            if maximum is not None
            else ConstantProof.NO_COMPARABLE_FULL_TIME_CLASSES
        )
        specs.extend(
            (
                _ObjectiveSpec(
                    stage=maximum_stage,
                    direction=ObjectiveDirection.MINIMIZE,
                    variables=(maximum,) if maximum is not None else (),
                    expression=maximum if maximum is not None else 0,
                    constant_value=constant,
                    constant_proof=proof,
                ),
                _ObjectiveSpec(
                    stage=total_stage,
                    direction=ObjectiveDirection.MINIMIZE,
                    variables=regrets,
                    expression=built.class_preference_total_regret_objectives.get(
                        rank, 0
                    ),
                    constant_value=constant,
                    constant_proof=proof,
                ),
            )
        )

    all_ratio_gaps = built.ratio_fairness_gap_variables
    first_preference_gaps = built.preference_ratio_gap_variables[
        OptimizationStage.FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_MAX_GAP
    ]
    ratio_constant = None if all_ratio_gaps else 0
    ratio_proof = (
        None
        if all_ratio_gaps
        else ConstantProof.NO_COMPARABLE_FAIRNESS_GROUPS
    )
    specs.extend(
        (
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
                stage=(
                    OptimizationStage.FULL_TIME_FIRST_PREFERENCE_RATIO_TOTAL_GAP
                ),
                direction=ObjectiveDirection.MINIMIZE,
                variables=tuple(first_preference_gaps.values()),
                expression=sum(first_preference_gaps.values()),
                constant_value=ratio_constant,
                constant_proof=ratio_proof,
            ),
            _ObjectiveSpec(
                stage=OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
                direction=ObjectiveDirection.MINIMIZE,
                variables=tuple(all_ratio_gaps.values()),
                expression=built.ratio_fairness_total_objective,
                constant_value=ratio_constant,
                constant_proof=ratio_proof,
            ),
        )
    )

    for stage in (
        OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,
        OptimizationStage.PART_TIME_GROUP_FAIRNESS,
        OptimizationStage.COMMON_GROUP_FAIRNESS,
    ):
        gaps = built.fairness_gap_variables[stage]
        specs.append(
            _ObjectiveSpec(
                stage=stage,
                direction=ObjectiveDirection.MINIMIZE,
                variables=tuple(gaps.values()),
                expression=built.fairness_objectives[stage],
                constant_value=None if gaps else 0,
                constant_proof=(
                    None
                    if gaps
                    else ConstantProof.NO_COMPARABLE_FAIRNESS_GROUPS
                ),
            )
        )
    for stage in (
        OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP,
        OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP,
    ):
        gaps = built.fairness_gap_variables[stage]
        specs.append(
            _ObjectiveSpec(
                stage=stage,
                direction=ObjectiveDirection.MINIMIZE,
                variables=tuple(gaps.values()),
                expression=built.fairness_objectives[stage],
                constant_value=None if gaps else 0,
                constant_proof=(
                    None
                    if gaps
                    else ConstantProof.NO_COMPARABLE_FULL_TIME_EMPLOYEES
                ),
            )
        )
    return tuple(specs)


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
        preference_benchmarks=(),
        class_pattern_locks=(),
        precheck=precheck,
        implemented_objective_prefix_optimal=False,
    )


def _result_from_snapshot(
    status: FeasibilityStatus,
    snapshot: _SolutionSnapshot,
    stages: list[OptimizationStageResult],
    precheck: PrecheckResult,
    *,
    preference_benchmarks: tuple[PreferenceBenchmarkResult, ...] = (),
    class_pattern_locks: tuple[ClassPatternLockResult, ...] = (),
    implemented_objective_prefix_optimal: bool = False,
    locked_model: OptimizationModel | None = None,
) -> LexicographicResult:
    return LexicographicResult(
        status=status,
        assignments=snapshot.assignments,
        daily_patterns=snapshot.daily_patterns,
        employee_shift_counts=snapshot.employee_shift_counts,
        target_deviations=snapshot.target_deviations,
        part_time_total=snapshot.part_time_total,
        stages=tuple(stages),
        preference_benchmarks=preference_benchmarks,
        class_pattern_locks=class_pattern_locks,
        precheck=precheck,
        implemented_objective_prefix_optimal=implemented_objective_prefix_optimal,
        _locked_model=locked_model,
    )


def _discover_preference_benchmarks(
    data: NormalizedScheduleInput,
    built: OptimizationModel,
    rank: PreferenceRank,
    config: LexicographicSolverConfig,
) -> tuple[tuple[PreferenceBenchmarkResult, ...], _SolverRun | None]:
    """Prove independent per-class ideals without locking either class first."""

    results: list[PreferenceBenchmarkResult] = []
    last_run: _SolverRun | None = None
    for definition in CLASS_PREFERENCES:
        if definition.rank is not rank:
            continue
        opportunity_days = class_opportunity_days(
            data, definition.full_time_class
        )
        if opportunity_days == 0:
            results.append(
                PreferenceBenchmarkResult(
                    full_time_class=definition.full_time_class,
                    rank=rank,
                    metric=definition.metric,
                    direction=definition.direction,
                    status=OptimizationStageStatus.SKIPPED_CONSTANT,
                    ideal_value=0,
                    locked_actual_value=None,
                    opportunity_days=0,
                    raw_solver_status="NOT_RUN",
                    wall_time_seconds=0.0,
                )
            )
            continue
        expression = built.class_preference_values[
            (definition.full_time_class, rank)
        ]
        if definition.direction is PreferenceDirection.MAXIMIZE:
            built.feasibility.model.maximize(expression)
        else:
            built.feasibility.model.minimize(expression)
        run = _solve_once(built.feasibility.model, config)
        last_run = run
        status = (
            OptimizationStageStatus.OPTIMAL
            if run.raw_status == cp_model.OPTIMAL
            else OptimizationStageStatus.FEASIBLE
            if run.raw_status == cp_model.FEASIBLE
            else OptimizationStageStatus.INFEASIBLE
            if run.raw_status == cp_model.INFEASIBLE
            else OptimizationStageStatus.UNKNOWN
        )
        ideal_value = (
            run.solver.value(expression)
            if run.raw_status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else None
        )
        results.append(
            PreferenceBenchmarkResult(
                full_time_class=definition.full_time_class,
                rank=rank,
                metric=definition.metric,
                direction=definition.direction,
                status=status,
                ideal_value=ideal_value,
                locked_actual_value=None,
                opportunity_days=opportunity_days,
                raw_solver_status=run.raw_status_name,
                wall_time_seconds=run.wall_time_seconds,
            )
        )
        if status is not OptimizationStageStatus.OPTIMAL:
            break
    return tuple(results), last_run


def _solve_lexicographic_legacy(
    data: NormalizedScheduleInput,
    config: LexicographicSolverConfig | None = None,
) -> LexicographicResult:
    """Optimize the implemented v1 objective prefix with exact value locks."""

    config = config or LexicographicSolverConfig()
    precheck = run_prechecks(data)
    if precheck.status is PrecheckStatus.PRECHECK_INFEASIBLE:
        return _empty_result(FeasibilityStatus.PRECHECK_INFEASIBLE, precheck)

    # Class-level ratio constraints are attached only after the secondary
    # pattern layer is locked.  They are irrelevant before then and can make
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

    initial_specs = _objective_specs(data, built, precheck)
    secondary_index = next(
        index
        for index, objective in enumerate(initial_specs)
        if objective.stage is OptimizationStage.FULL_TIME_SECONDARY_PATTERNS
    )
    objective_specs = list(initial_specs[: secondary_index + 1])
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
                    _objective_specs(data, built, precheck)[
                        secondary_index + 1 :
                    ]
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
                    _objective_specs(data, built, precheck)[
                        secondary_index + 1 :
                    ]
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


def solve_lexicographic(
    data: NormalizedScheduleInput,
    config: LexicographicSolverConfig | None = None,
) -> LexicographicResult:
    """Solve revised class-specific preferences with fair normalized regrets."""

    config = config or LexicographicSolverConfig()
    precheck = run_prechecks(data)
    if precheck.status is PrecheckStatus.PRECHECK_INFEASIBLE:
        return _empty_result(FeasibilityStatus.PRECHECK_INFEASIBLE, precheck)

    built = build_optimization_model(data, include_class_quality=False)
    stages: list[OptimizationStageResult] = []
    benchmarks: list[PreferenceBenchmarkResult] = []
    class_pattern_locks: list[ClassPatternLockResult] = []
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
            FeasibilityStatus.INFEASIBLE, precheck, tuple(stages)
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
            FeasibilityStatus.UNKNOWN, precheck, tuple(stages)
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
    last_solver: cp_model.CpSolver | None = hard_run.solver

    def execute_specs(
        specs: tuple[_ObjectiveSpec, ...] | list[_ObjectiveSpec],
    ) -> LexicographicResult | None:
        nonlocal last_solver, snapshot
        for objective in specs:
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
                continue
            if objective.direction is ObjectiveDirection.MAXIMIZE:
                built.feasibility.model.maximize(objective.expression)
            else:
                built.feasibility.model.minimize(objective.expression)
            run = _solve_once(built.feasibility.model, config)
            if run.raw_status == cp_model.OPTIMAL:
                objective_value = int(run.solver.value(objective.expression))
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
                last_solver = run.solver
                continue
            if run.raw_status == cp_model.FEASIBLE:
                objective_value = int(run.solver.value(objective.expression))
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
                last_solver = run.solver
            else:
                stages.append(
                    OptimizationStageResult(
                        stage=objective.stage,
                        direction=objective.direction,
                        status=(
                            OptimizationStageStatus.INFEASIBLE
                            if run.raw_status == cp_model.INFEASIBLE
                            else OptimizationStageStatus.UNKNOWN
                        ),
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
                preference_benchmarks=tuple(benchmarks),
                class_pattern_locks=tuple(class_pattern_locks),
            )
        return None

    base_specs = _formal_objective_specs(data, built, precheck)[:2]
    incomplete = execute_specs(base_specs)
    if incomplete is not None:
        return incomplete

    rank_stage_pairs = {
        PreferenceRank.FIRST: (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET,
        ),
        PreferenceRank.SECOND: (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET,
        ),
    }
    for rank in PreferenceRank:
        discovered, last_run = _discover_preference_benchmarks(
            data, built, rank, config
        )
        benchmarks.extend(discovered)
        if any(
            item.status
            not in (
                OptimizationStageStatus.OPTIMAL,
                OptimizationStageStatus.SKIPPED_CONSTANT,
            )
            for item in discovered
        ):
            if last_run is not None and last_run.raw_status in (
                cp_model.FEASIBLE,
                cp_model.OPTIMAL,
            ):
                snapshot = _snapshot(data, built, last_run.solver)
            return _result_from_snapshot(
                FeasibilityStatus.FEASIBLE,
                snapshot,
                stages,
                precheck,
                preference_benchmarks=tuple(benchmarks),
                class_pattern_locks=tuple(class_pattern_locks),
            )
        built = _attach_preference_regret_model(
            data, built, tuple(benchmarks), rank
        )
        wanted = set(rank_stage_pairs[rank])
        rank_specs = tuple(
            item
            for item in _formal_objective_specs(data, built, precheck)
            if item.stage in wanted
        )
        incomplete = execute_specs(rank_specs)
        if incomplete is not None:
            return incomplete
        assert last_solver is not None
        for definition in CLASS_PREFERENCES:
            if definition.rank is not rank:
                continue
            key = (definition.full_time_class, rank)
            locked_actual = int(
                last_solver.value(built.class_preference_values[key])
            )
            built.feasibility.model.add(
                built.class_preference_values[key] == locked_actual
            )
            for index, benchmark in enumerate(benchmarks):
                if (
                    benchmark.full_time_class is definition.full_time_class
                    and benchmark.rank is rank
                ):
                    benchmarks[index] = replace(
                        benchmark,
                        locked_actual_value=locked_actual,
                    )
                    break
        if rank is PreferenceRank.SECOND:
            for full_time_class, metric in (
                (FullTimeClass.A, FairnessMetric.SINGLE_SHIFT_DAYS),
                (FullTimeClass.B, FairnessMetric.TRIPLE_DAYS),
            ):
                variable = built.class_remaining_pattern_values[
                    full_time_class
                ]
                locked_value = int(last_solver.value(variable))
                built.feasibility.model.add(variable == locked_value)
                class_pattern_locks.append(
                    ClassPatternLockResult(
                        full_time_class=full_time_class,
                        metric=metric,
                        locked_value=locked_value,
                    )
                )

    completed = {item.stage for item in stages}
    remaining_specs = tuple(
        item
        for item in _formal_objective_specs(data, built, precheck)
        if item.stage not in completed
    )
    incomplete = execute_specs(remaining_specs)
    if incomplete is not None:
        return incomplete
    return _result_from_snapshot(
        FeasibilityStatus.FEASIBLE,
        snapshot,
        stages,
        precheck,
        preference_benchmarks=tuple(benchmarks),
        class_pattern_locks=tuple(class_pattern_locks),
        implemented_objective_prefix_optimal=True,
        locked_model=built,
    )


def _add_assignment_exclusion(
    model: cp_model.CpModel,
    variables: tuple[cp_model.IntVar, ...],
    signature: tuple[bool, ...],
) -> None:
    """Exclude exactly one core-x assignment, ignoring auxiliary variables."""

    if len(variables) != len(signature):
        raise ValueError("assignment signature length does not match x variables")
    if not variables:
        model.add(0 == 1)
        return
    matching_literals = tuple(
        variable if value else variable.Not()
        for variable, value in zip(variables, signature, strict=True)
    )
    model.add(sum(matching_literals) <= len(matching_literals) - 1)


def diagnose_equivalent_solutions(
    result: LexicographicResult,
    config: EquivalentSolutionDiagnosticConfig | None = None,
    *,
    progress: Callable[[int], None] | None = None,
    candidate_found: (
        Callable[[int, tuple[Assignment, ...]], None] | None
    ) = None,
) -> EquivalentSolutionDiagnosticResult:
    """Count distinct equal-quality assignments up to a bound and time limit.

    The formal assignment itself is excluded.  Every formal objective and
    class-level value lock remains in the retained CP-SAT model, while the
    final objective is cleared so the model becomes a pure satisfaction
    problem.  Distinctness is defined only by the core x variables.
    """

    config = config or EquivalentSolutionDiagnosticConfig()
    if not result.implemented_objective_prefix_optimal:
        raise ValueError("equivalent-solution diagnosis requires an optimal prefix")
    built = result._locked_model
    if built is None:
        raise ValueError("locked optimization model is unavailable")

    model = built.feasibility.model.clone()
    model.clear_objective()
    x_items = tuple(
        (
            key,
            model.get_int_var_from_proto_index(variable.index),
        )
        for key, variable in built.feasibility.x.items()
    )
    variables = tuple(variable for _, variable in x_items)
    selected_keys = {
        (item.employee_id, item.date, item.period, item.role)
        for item in result.assignments
    }
    selected_signature = tuple(key in selected_keys for key, _ in x_items)
    _add_assignment_exclusion(model, variables, selected_signature)

    time_limit_seconds = config.max_time_seconds
    if time_limit_seconds is None:
        measured_solver_seconds = sum(
            item.wall_time_seconds for item in result.stages
        ) + sum(
            item.wall_time_seconds for item in result.preference_benchmarks
        )
        time_limit_seconds = max(
            measured_solver_seconds * config.scheduling_time_ratio,
            0.001,
        )

    started = perf_counter()
    alternative_count = 0
    interrupted = False
    active_solver: cp_model.CpSolver | None = None
    previous_sigint_handler = None
    handles_sigint = threading.current_thread() is threading.main_thread()

    if handles_sigint:
        previous_sigint_handler = signal.getsignal(signal.SIGINT)

        def stop_diagnostic(_signum: int, _frame: object) -> None:
            nonlocal interrupted
            interrupted = True
            if active_solver is not None:
                active_solver.stop_search()

        signal.signal(signal.SIGINT, stop_diagnostic)

    try:
        while alternative_count < config.max_alternatives:
            if interrupted:
                return EquivalentSolutionDiagnosticResult(
                    status=EquivalentSolutionDiagnosticStatus.INTERRUPTED,
                    alternative_count=alternative_count,
                    search_limit=config.max_alternatives,
                    time_limit_seconds=time_limit_seconds,
                    wall_time_seconds=perf_counter() - started,
                )
            remaining = time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                return EquivalentSolutionDiagnosticResult(
                    status=EquivalentSolutionDiagnosticStatus.TIME_LIMIT,
                    alternative_count=alternative_count,
                    search_limit=config.max_alternatives,
                    time_limit_seconds=time_limit_seconds,
                    wall_time_seconds=perf_counter() - started,
                )

            solver = cp_model.CpSolver()
            active_solver = solver
            solver.parameters.num_search_workers = config.num_search_workers
            solver.parameters.random_seed = config.random_seed
            solver.parameters.max_time_in_seconds = remaining
            try:
                raw_status = solver.solve(model)
            except KeyboardInterrupt:
                interrupted = True
                continue
            finally:
                active_solver = None

            if interrupted:
                continue
            if raw_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                signature = tuple(
                    bool(solver.value(variable)) for variable in variables
                )
                _add_assignment_exclusion(model, variables, signature)
                alternative_count += 1
                if candidate_found is not None:
                    assignments = tuple(
                        Assignment(employee_id, day, period, role)
                        for (
                            (employee_id, day, period, role),
                            _variable,
                        ), selected in zip(x_items, signature, strict=True)
                        if selected
                    )
                    candidate_found(alternative_count, assignments)
                if progress is not None:
                    progress(alternative_count)
                continue
            if raw_status == cp_model.INFEASIBLE:
                return EquivalentSolutionDiagnosticResult(
                    status=EquivalentSolutionDiagnosticStatus.EXACT_COUNT,
                    alternative_count=alternative_count,
                    search_limit=config.max_alternatives,
                    time_limit_seconds=time_limit_seconds,
                    wall_time_seconds=perf_counter() - started,
                )
            return EquivalentSolutionDiagnosticResult(
                status=EquivalentSolutionDiagnosticStatus.TIME_LIMIT,
                alternative_count=alternative_count,
                search_limit=config.max_alternatives,
                time_limit_seconds=time_limit_seconds,
                wall_time_seconds=perf_counter() - started,
            )

        return EquivalentSolutionDiagnosticResult(
            status=EquivalentSolutionDiagnosticStatus.AT_LEAST_LIMIT,
            alternative_count=alternative_count,
            search_limit=config.max_alternatives,
            time_limit_seconds=time_limit_seconds,
            wall_time_seconds=perf_counter() - started,
        )
    finally:
        if handles_sigint:
            signal.signal(signal.SIGINT, previous_sigint_handler)
