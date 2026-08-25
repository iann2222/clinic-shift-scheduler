"""Strict v1 lexicographic objectives through group fairness.

Formal independent output validation remains outside this module's scope.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
import signal
import threading
from time import perf_counter
from types import MappingProxyType
from typing import Mapping

from ortools.sat.python import cp_model

from .class_preferences import (
    ClassPreferenceMetric,
    PreferenceDirection,
    PreferenceRank,
    class_opportunity_days,
)
from .daily_patterns import PATTERN_PERIODS, DailyPattern
from .enums import EmploymentType, FullTimeClass, PERIODS_V1, Period, ShiftMode
from .events import (
    CancellationToken,
    ExecutionPhase,
    PreservationToken,
    ProgressCallback,
    ProgressEvent,
    ProgressEventKind,
)
from .feasibility import (
    FeasibilityModel,
    build_feasibility_model,
    extract_model_solution,
)
from .models import Employee, NormalizedScheduleInput
from .optimization_contracts import (
    ClassPatternLockResult,
    ConstantProof,
    EquivalentSolutionDiagnosticConfig,
    EquivalentSolutionDiagnosticResult,
    EquivalentSolutionDiagnosticStatus,
    FairnessMetric,
    LexicographicSolverConfig,
    ObjectiveDirection,
    OptimizationStage,
    OptimizationStageResult,
    OptimizationStageStatus,
    PreferenceBenchmarkResult,
)
from .optimization_policy import (
    CLASS_PREFERENCES,
    CLASS_REMAINING_PATTERN_METRICS,
    COMMON_GROUP_FAIRNESS_WEIGHTS,
    FORMAL_OBJECTIVE_STAGES,
    FORMAL_STAGE_POLICIES,
    FORMAL_STAGE_POLICY_BY_STAGE,
    FORMAL_STAGE_SEQUENCE,
    FULL_TIME_PATTERN_METRICS,
    GROUP_FAIRNESS_EMPLOYMENT_TYPES,
    GROUP_FAIRNESS_METRICS,
    GROUP_FAIRNESS_STAGES,
    PREFERENCE_RATIO_MAX_STAGE_BY_METRIC,
    PREFERENCE_REGRET_STAGES,
    SUNDAY_FAIRNESS_METRICS,
    SUNDAY_FAIRNESS_STAGES,
    USER_FACING_OPTIMIZATION_FLOW,
)
from .precheck import PrecheckResult, PrecheckStatus, run_prechecks
from .ratio_fairness import (
    BASIS_POINTS_SCALE,
    ratio_basis_points,
    relative_deviation_basis_points,
)
from .shift_bounds import hard_minimum_shifts
from .solver_contracts import (
    Assignment,
    FeasibilityStatus,
    LexicographicResult,
    OptimizationStopSnapshot,
    OptimizationTelemetry,
    PersonDayKey,
    SchedulePreservationInfo,
)


@dataclass(frozen=True, slots=True)
class OptimizationModel:
    feasibility: FeasibilityModel
    target_deviations: Mapping[str, cp_model.IntVar]
    target_relative_deviation_basis_points: Mapping[str, cp_model.IntVar]
    target_relative_fairness_gaps: Mapping[str, cp_model.IntVar]
    target_overall_deviation_basis_points: cp_model.IntVar | None
    target_max_regret_variable: cp_model.IntVar | None
    target_total_regret_objective: cp_model.LinearExpr | int
    part_time_objective: cp_model.LinearExpr | int
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
    best_objective_bound: float | None = None
    num_conflicts: int | None = None
    num_branches: int | None = None
    progress_snapshot: Mapping[str, int | float | None] | None = None


@dataclass(frozen=True, slots=True)
class _SolveProgressContext:
    activity: str
    label: str
    direction: ObjectiveDirection
    current: int
    total: int
    optimization_started_at: float
    details: Mapping[str, object]


class _SolverProgressState:
    """Small lock-protected state updated by native CP-SAT callbacks."""

    def __init__(self, direction: ObjectiveDirection) -> None:
        self._direction = direction
        self._lock = threading.Lock()
        self._started_at = perf_counter()
        self._incumbent: float | None = None
        self._best_bound: float | None = None
        self._solutions_found = 0
        self._last_solution_at: float | None = None
        self._last_bound_update_at: float | None = None

    def record_solution(self, objective_value: float | None) -> None:
        now = perf_counter()
        with self._lock:
            self._solutions_found += 1
            improved = self._incumbent is None
            if objective_value is not None and self._incumbent is not None:
                improved = (
                    objective_value > self._incumbent
                    if self._direction is ObjectiveDirection.MAXIMIZE
                    else objective_value < self._incumbent
                )
            if improved:
                self._last_solution_at = now
            self._incumbent = objective_value

    def record_bound(self, best_bound: float) -> None:
        now = perf_counter()
        with self._lock:
            if self._best_bound != best_bound:
                self._best_bound = best_bound
                self._last_bound_update_at = now

    def snapshot(self) -> dict[str, int | float | None]:
        now = perf_counter()
        with self._lock:
            incumbent = self._incumbent
            best_bound = self._best_bound
            absolute_gap = (
                None
                if incumbent is None or best_bound is None
                else abs(incumbent - best_bound)
            )
            relative_gap = (
                None
                if absolute_gap is None
                else absolute_gap / max(abs(incumbent), 1.0)
            )
            return {
                "incumbent": incumbent,
                "best_bound": best_bound,
                "absolute_gap": absolute_gap,
                "relative_gap": relative_gap,
                "solutions_found": self._solutions_found,
                "stage_elapsed_seconds": now - self._started_at,
                "seconds_since_last_solution": (
                    None
                    if self._last_solution_at is None
                    else now - self._last_solution_at
                ),
                "seconds_since_bound_update": (
                    None
                    if self._last_bound_update_at is None
                    else now - self._last_bound_update_at
                ),
            }


class _IncumbentProgressCallback(cp_model.CpSolverSolutionCallback):
    def __init__(
        self,
        state: _SolverProgressState,
        *,
        has_objective: bool,
    ) -> None:
        super().__init__()
        self._state = state
        self._has_objective = has_objective

    def on_solution_callback(self) -> None:
        objective_value = (
            float(self.objective_value) if self._has_objective else None
        )
        self._state.record_solution(objective_value)


@dataclass(frozen=True, slots=True)
class _SolutionSnapshot:
    assignments: tuple[Assignment, ...]
    daily_patterns: Mapping[PersonDayKey, DailyPattern]
    employee_shift_counts: Mapping[str, int]
    target_deviations: Mapping[str, int]
    part_time_total: int


def _var_name(prefix: str, employee_id: str) -> str:
    return f"{prefix}[{employee_id}]"


def build_optimization_model(
    data: NormalizedScheduleInput,
) -> OptimizationModel:
    """Add all currently implemented objectives to the shared hard model."""

    feasibility = build_feasibility_model(data)
    model = feasibility.model
    target_deviations: dict[str, cp_model.IntVar] = {}
    target_relative_deviations: dict[str, cp_model.IntVar] = {}
    target_deviation_upper_bounds: dict[str, int] = {}
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
        target_deviations[employee.employee_id] = deviation
        target_deviation_upper_bounds[employee.employee_id] = deviation_upper_bound
        lookup = [
            relative_deviation_basis_points(value, employee.target_shifts)
            for value in range(deviation_upper_bound + 1)
        ]
        relative_deviation = model.new_int_var(
            0,
            max(lookup, default=0),
            _var_name("target_relative_deviation_bp", employee.employee_id),
        )
        model.add_element(deviation, lookup, relative_deviation)
        target_relative_deviations[employee.employee_id] = relative_deviation

    target_employees = tuple(
        employee
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
        and employee.shift_mode is ShiftMode.TARGET
    )
    target_overall_deviation_bp: cp_model.IntVar | None = None
    target_fairness_gaps: dict[str, cp_model.IntVar] = {}
    target_fairness_gap_upper_bounds: list[int] = []
    target_max_regret: cp_model.IntVar | None = None
    target_total_regret: cp_model.LinearExpr | int = 0
    if target_employees:
        total_deviation_upper_bound = sum(
            target_deviation_upper_bounds[employee.employee_id]
            for employee in target_employees
        )
        total_target_units = sum(
            max(employee.target_shifts or 0, 1)
            for employee in target_employees
        )
        overall_lookup = [
            relative_deviation_basis_points(value, total_target_units)
            for value in range(total_deviation_upper_bound + 1)
        ]
        target_overall_deviation_bp = model.new_int_var(
            0,
            max(overall_lookup, default=0),
            "part_time_target_overall_deviation_bp",
        )
        total_deviation = model.new_int_var(
            0,
            total_deviation_upper_bound,
            "part_time_target_total_deviation",
        )
        model.add(
            total_deviation
            == sum(
                target_deviations[employee.employee_id]
                for employee in target_employees
            )
        )
        model.add_element(
            total_deviation,
            overall_lookup,
            target_overall_deviation_bp,
        )
        target_groups: dict[str, list[Employee]] = defaultdict(list)
        for employee in target_employees:
            target_groups[employee.fairness_group].append(employee)
        for group, members in sorted(target_groups.items()):
            if len(members) < 2:
                continue
            member_values = [
                target_relative_deviations[employee.employee_id]
                for employee in members
            ]
            upper_bound = max(
                relative_deviation_basis_points(
                    target_deviation_upper_bounds[employee.employee_id],
                    employee.target_shifts or 0,
                )
                for employee in members
            )
            maximum = model.new_int_var(
                0, upper_bound, f"part_time_target_max[{group}]"
            )
            minimum = model.new_int_var(
                0, upper_bound, f"part_time_target_min[{group}]"
            )
            gap = model.new_int_var(
                0, upper_bound, f"part_time_target_gap[{group}]"
            )
            model.add_max_equality(maximum, member_values)
            model.add_min_equality(minimum, member_values)
            model.add(gap == maximum - minimum)
            target_fairness_gaps[group] = gap
            target_fairness_gap_upper_bounds.append(upper_bound)
        regret_components = [
            target_overall_deviation_bp,
            *target_fairness_gaps.values(),
        ]
        target_max_regret = model.new_int_var(
            0,
            max(
                [
                    max(overall_lookup, default=0),
                    *target_fairness_gap_upper_bounds,
                ]
            ),
            "part_time_target_max_regret",
        )
        model.add_max_equality(target_max_regret, regret_components)
        target_total_regret = sum(regret_components)

    part_time_counts = tuple(
        feasibility.employee_shift_counts[employee.employee_id]
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    consecutive_patterns = (
        DailyPattern.MORNING_AFTERNOON,
        DailyPattern.AFTERNOON_EVENING,
    )
    single_patterns = (
        DailyPattern.MORNING_ONLY,
        DailyPattern.AFTERNOON_ONLY,
        DailyPattern.EVENING_ONLY,
    )

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

    class_remaining_pattern_values: dict[FullTimeClass, cp_model.IntVar] = {}
    for full_time_class, metric in CLASS_REMAINING_PATTERN_METRICS.items():
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
        for metric in FULL_TIME_PATTERN_METRICS[employee.full_time_class]:
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
    preference_ratio_gaps: dict[
        OptimizationStage,
        dict[tuple[str, FairnessMetric], cp_model.IntVar],
    ] = {
        OptimizationStage.FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_MAX_GAP: {},
        OptimizationStage.FULL_TIME_PREFERENCE_RANK2_PERSON_RATIO_MAX_GAP: {},
        OptimizationStage.FULL_TIME_REMAINING_PATTERN_RATIO_MAX_GAP: {},
    }
    for full_time_class, metrics in FULL_TIME_PATTERN_METRICS.items():
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
                    PREFERENCE_RATIO_MAX_STAGE_BY_METRIC[
                        (full_time_class, metric)
                    ]
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

    fairness_gaps: dict[
        OptimizationStage,
        Mapping[tuple[str, FairnessMetric], cp_model.IntVar],
    ] = {}
    fairness_objectives: dict[
        OptimizationStage, cp_model.LinearExpr | int
    ] = {}
    for stage in GROUP_FAIRNESS_STAGES:
        employees = tuple(
            employee
            for employee in data.source.employees
            if employee.employment_type
            in GROUP_FAIRNESS_EMPLOYMENT_TYPES[stage]
            and not (
                stage is OptimizationStage.PART_TIME_GROUP_FAIRNESS
                and employee.shift_mode is ShiftMode.TARGET
            )
        )
        metrics = GROUP_FAIRNESS_METRICS[stage]
        groups: dict[str, list[Employee]] = defaultdict(list)
        for employee in employees:
            groups[employee.fairness_group].append(employee)
        stage_gaps: dict[tuple[str, FairnessMetric], cp_model.IntVar] = {}
        for group, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            group_metrics = (
                FULL_TIME_PATTERN_METRICS[members[0].full_time_class]
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
        if stage is OptimizationStage.COMMON_GROUP_FAIRNESS:
            fairness_objectives[stage] = sum(
                COMMON_GROUP_FAIRNESS_WEIGHTS[metric] * gap
                for (_group, metric), gap in stage_gaps.items()
            )
        else:
            fairness_objectives[stage] = sum(stage_gaps.values())

    full_time_members = tuple(
        employee
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.FULL_TIME
    )
    sunday_gaps: dict[tuple[str, FairnessMetric], cp_model.IntVar] = {}
    sunday_max_gap: cp_model.IntVar | None = None
    if len(full_time_members) >= 2:
        for metric in SUNDAY_FAIRNESS_METRICS:
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
    for stage in SUNDAY_FAIRNESS_STAGES:
        fairness_gaps[stage] = immutable_sunday_gaps
    fairness_objectives[SUNDAY_FAIRNESS_STAGES[0]] = (
        sunday_max_gap if sunday_max_gap is not None else 0
    )
    fairness_objectives[SUNDAY_FAIRNESS_STAGES[1]] = sum(
        sunday_gaps.values()
    )

    return OptimizationModel(
        feasibility=feasibility,
        target_deviations=MappingProxyType(target_deviations),
        target_relative_deviation_basis_points=MappingProxyType(
            target_relative_deviations
        ),
        target_relative_fairness_gaps=MappingProxyType(target_fairness_gaps),
        target_overall_deviation_basis_points=target_overall_deviation_bp,
        target_max_regret_variable=target_max_regret,
        target_total_regret_objective=target_total_regret,
        part_time_objective=sum(part_time_counts),
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


def _hard_fixed_count(
    employee: Employee,
    precheck: PrecheckResult,
) -> int | None:
    minimum = hard_minimum_shifts(employee)
    maximum = precheck.employee_capacities[employee.employee_id]
    return minimum if minimum == maximum else None


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


def _formal_objective_specs(
    data: NormalizedScheduleInput,
    built: OptimizationModel,
    precheck: PrecheckResult,
) -> tuple[_ObjectiveSpec, ...]:
    """Return the revised class-specific formal objective sequence."""

    part_time_constant, part_time_proof = _part_time_constant(data, precheck)
    part_time_variables = tuple(
        built.feasibility.employee_shift_counts[employee.employee_id]
        for employee in data.source.employees
        if employee.employment_type is EmploymentType.PART_TIME
    )
    specs: list[_ObjectiveSpec] = [
        _ObjectiveSpec(
            stage=OptimizationStage.PART_TIME_USAGE,
            direction=FORMAL_STAGE_POLICY_BY_STAGE[
                OptimizationStage.PART_TIME_USAGE
            ].direction,
            variables=part_time_variables,
            expression=built.part_time_objective,
            constant_value=part_time_constant,
            constant_proof=part_time_proof,
        ),
    ]

    for rank in PreferenceRank:
        maximum_stage, total_stage = PREFERENCE_REGRET_STAGES[rank]
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
                    direction=FORMAL_STAGE_POLICY_BY_STAGE[
                        maximum_stage
                    ].direction,
                    variables=(maximum,) if maximum is not None else (),
                    expression=maximum if maximum is not None else 0,
                    constant_value=constant,
                    constant_proof=proof,
                ),
                _ObjectiveSpec(
                    stage=total_stage,
                    direction=FORMAL_STAGE_POLICY_BY_STAGE[
                        total_stage
                    ].direction,
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
                direction=FORMAL_STAGE_POLICY_BY_STAGE[
                    OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP
                ].direction,
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
                direction=FORMAL_STAGE_POLICY_BY_STAGE[
                    OptimizationStage.FULL_TIME_FIRST_PREFERENCE_RATIO_TOTAL_GAP
                ].direction,
                variables=tuple(first_preference_gaps.values()),
                expression=sum(first_preference_gaps.values()),
                constant_value=ratio_constant,
                constant_proof=ratio_proof,
            ),
            _ObjectiveSpec(
                stage=OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
                direction=FORMAL_STAGE_POLICY_BY_STAGE[
                    OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP
                ].direction,
                variables=tuple(all_ratio_gaps.values()),
                expression=built.ratio_fairness_total_objective,
                constant_value=ratio_constant,
                constant_proof=ratio_proof,
            ),
        )
    )

    for stage in GROUP_FAIRNESS_STAGES:
        if stage is OptimizationStage.PART_TIME_GROUP_FAIRNESS:
            target_constant = (
                None if built.target_max_regret_variable is not None else 0
            )
            target_proof = (
                None
                if built.target_max_regret_variable is not None
                else ConstantProof.NO_TARGET_EMPLOYEES
            )
            specs.extend(
                (
                    _ObjectiveSpec(
                        stage=OptimizationStage.PART_TIME_TARGET_MAX_REGRET,
                        direction=FORMAL_STAGE_POLICY_BY_STAGE[
                            OptimizationStage.PART_TIME_TARGET_MAX_REGRET
                        ].direction,
                        variables=(built.target_max_regret_variable,)
                        if built.target_max_regret_variable is not None
                        else (),
                        expression=(
                            built.target_max_regret_variable
                            if built.target_max_regret_variable is not None
                            else 0
                        ),
                        constant_value=target_constant,
                        constant_proof=target_proof,
                    ),
                    _ObjectiveSpec(
                        stage=OptimizationStage.PART_TIME_TARGET_TOTAL_REGRET,
                        direction=FORMAL_STAGE_POLICY_BY_STAGE[
                            OptimizationStage.PART_TIME_TARGET_TOTAL_REGRET
                        ].direction,
                        variables=(
                            *built.target_relative_deviation_basis_points.values(),
                            *built.target_relative_fairness_gaps.values(),
                        ),
                        expression=built.target_total_regret_objective,
                        constant_value=target_constant,
                        constant_proof=target_proof,
                    ),
                )
            )
        gaps = built.fairness_gap_variables[stage]
        specs.append(
            _ObjectiveSpec(
                stage=stage,
                direction=FORMAL_STAGE_POLICY_BY_STAGE[stage].direction,
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
    for stage in SUNDAY_FAIRNESS_STAGES:
        gaps = built.fairness_gap_variables[stage]
        specs.append(
            _ObjectiveSpec(
                stage=stage,
                direction=FORMAL_STAGE_POLICY_BY_STAGE[stage].direction,
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
    result = tuple(specs)
    if tuple(item.stage for item in result) != FORMAL_OBJECTIVE_STAGES:
        raise RuntimeError(
            "optimizer objective specs do not match the formal v1 policy"
        )
    return result


def _safe_solver_stat(solver: cp_model.CpSolver, name: str) -> int | None:
    try:
        value = getattr(solver, name)
        return int(value() if callable(value) else value)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _safe_solver_float(
    solver: cp_model.CpSolver,
    name: str,
) -> float | None:
    try:
        value = getattr(solver, name)
        return float(value() if callable(value) else value)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _emit_solver_progress(
    callback: ProgressCallback | None,
    context: _SolveProgressContext | None,
    state: _SolverProgressState,
) -> None:
    if callback is None or context is None:
        return
    details = dict(context.details)
    details.update(state.snapshot())
    details["activity"] = context.activity
    details["total_elapsed_seconds"] = (
        perf_counter() - context.optimization_started_at
    )
    try:
        callback(
            ProgressEvent(
                phase=ExecutionPhase.OPTIMIZATION,
                kind=ProgressEventKind.HEARTBEAT,
                message=context.label,
                elapsed_seconds=float(details["total_elapsed_seconds"]),
                current=context.current,
                total=context.total,
                details=details,
            )
        )
    except Exception:
        # Progress is observational. A disconnected UI must not change the
        # mathematical result or interrupt a long-running solve.
        return


def _solve_once(
    model: cp_model.CpModel,
    config: LexicographicSolverConfig,
    cancellation: CancellationToken | None = None,
    *,
    preservation: PreservationToken | None = None,
    progress: ProgressCallback | None = None,
    progress_context: _SolveProgressContext | None = None,
    progress_interval_seconds: float = 5.0,
) -> _SolverRun:
    if progress_interval_seconds <= 0:
        raise ValueError("progress_interval_seconds must be greater than 0")
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = config.num_search_workers
    solver.parameters.random_seed = config.random_seed
    if config.max_time_seconds_per_stage is not None:
        solver.parameters.max_time_in_seconds = config.max_time_seconds_per_stage
    monitor: threading.Thread | None = None
    reporter: threading.Thread | None = None
    finished = threading.Event()
    direction = (
        ObjectiveDirection.NONE
        if progress_context is None
        else progress_context.direction
    )
    state = _SolverProgressState(direction)
    has_objective = direction is not ObjectiveDirection.NONE
    solution_callback = _IncumbentProgressCallback(
        state,
        has_objective=has_objective,
    )
    if has_objective:
        solver.best_bound_callback = state.record_bound

    if progress is not None and progress_context is not None:
        _emit_solver_progress(progress, progress_context, state)

        def report_progress() -> None:
            while not finished.wait(progress_interval_seconds):
                _emit_solver_progress(progress, progress_context, state)

        reporter = threading.Thread(
            target=report_progress,
            name="cp-sat-progress-reporter",
            daemon=True,
        )
        reporter.start()
    if cancellation is not None or preservation is not None:

        def stop_when_requested() -> None:
            while not finished.is_set():
                if cancellation is not None and cancellation.is_cancelled:
                    solver.stop_search()
                    return
                if preservation is not None and preservation.is_requested:
                    solver.stop_search()
                    return
                finished.wait(0.05)

        monitor = threading.Thread(
            target=stop_when_requested,
            name="cp-sat-stop-monitor",
            daemon=True,
        )
        monitor.start()
    try:
        raw_status = solver.solve(model, solution_callback)
    finally:
        finished.set()
        if monitor is not None:
            monitor.join(timeout=0.1)
        if reporter is not None:
            reporter.join(timeout=progress_interval_seconds)
        if has_objective:
            try:
                state.record_bound(float(solver.best_objective_bound))
            except (AttributeError, RuntimeError):
                pass
        _emit_solver_progress(progress, progress_context, state)
    try:
        wall_time = solver.wall_time
    except RuntimeError:  # Supports deterministic mocked UNKNOWN tests.
        wall_time = 0.0
    return _SolverRun(
        solver=solver,
        raw_status=raw_status,
        raw_status_name=solver.status_name(raw_status),
        wall_time_seconds=wall_time,
        best_objective_bound=(
            None
            if not has_objective
            else _safe_solver_float(solver, "best_objective_bound")
        ),
        num_conflicts=_safe_solver_stat(solver, "num_conflicts"),
        num_branches=_safe_solver_stat(solver, "num_branches"),
        progress_snapshot=MappingProxyType(state.snapshot()),
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


def _user_step_details(stage: OptimizationStage) -> dict[str, object]:
    for index, step in enumerate(USER_FACING_OPTIMIZATION_FLOW, start=1):
        if stage in step.stages:
            return {
                "user_step_index": index,
                "user_step_total": len(USER_FACING_OPTIMIZATION_FLOW),
                "user_step_title": step.title,
            }
    raise RuntimeError(f"formal stage has no user-facing step: {stage.value}")


def _formal_progress_context(
    stage: OptimizationStage,
    *,
    optimization_started_at: float,
    has_feasible_solution: bool,
    completed_stages: int,
    time_to_first_feasible_schedule: float | None,
) -> _SolveProgressContext:
    stage_index = FORMAL_STAGE_SEQUENCE.index(stage) + 1
    policy = FORMAL_STAGE_POLICY_BY_STAGE[stage]
    details: dict[str, object] = {
        "formal_stage": stage.value,
        "formal_stage_name": policy.display_name,
        "formal_stage_index": stage_index,
        "formal_stage_total": len(FORMAL_STAGE_POLICIES),
        "formal_stages_completed": completed_stages,
        "has_feasible_solution": has_feasible_solution,
    }
    if time_to_first_feasible_schedule is not None:
        details["time_to_first_feasible_schedule"] = (
            time_to_first_feasible_schedule
        )
    details.update(_user_step_details(stage))
    return _SolveProgressContext(
        activity="formal_stage",
        label=(
            f"正式流程 {stage_index}/{len(FORMAL_STAGE_POLICIES)}："
            f"{policy.display_name}"
        ),
        direction=policy.direction,
        current=stage_index,
        total=len(FORMAL_STAGE_POLICIES),
        optimization_started_at=optimization_started_at,
        details=MappingProxyType(details),
    )


def _emit_activity_event(
    callback: ProgressCallback | None,
    context: _SolveProgressContext,
    kind: ProgressEventKind,
    *,
    message: str | None = None,
    extra_details: Mapping[str, object] | None = None,
) -> None:
    if callback is None:
        return
    details = dict(context.details)
    if extra_details is not None:
        details.update(extra_details)
    details["activity"] = context.activity
    details["total_elapsed_seconds"] = (
        perf_counter() - context.optimization_started_at
    )
    callback(
        ProgressEvent(
            phase=ExecutionPhase.OPTIMIZATION,
            kind=kind,
            message=message or context.label,
            elapsed_seconds=float(details["total_elapsed_seconds"]),
            current=context.current,
            total=context.total,
            details=details,
        )
    )


def _problem_telemetry(
    data: NormalizedScheduleInput,
    built: OptimizationModel,
) -> OptimizationTelemetry:
    employees = tuple(data.source.employees)
    full_time_count = sum(
        item.employment_type is EmploymentType.FULL_TIME for item in employees
    )
    qualified_capacity = sum(
        len(item.roles) * len(data.dates) * len(PERIODS_V1)
        for item in employees
    )
    assignment_variables = len(built.feasibility.x)
    return OptimizationTelemetry(
        days=len(data.dates),
        employees=len(employees),
        full_time_employees=full_time_count,
        part_time_employees=len(employees) - full_time_count,
        assignment_variables=assignment_variables,
        availability_ratio=(
            assignment_variables / qualified_capacity
            if qualified_capacity
            else 0.0
        ),
        demand_units=sum(data.demands.values()),
    )


def _empty_result(
    status: FeasibilityStatus,
    precheck: PrecheckResult,
    stages: tuple[OptimizationStageResult, ...] = (),
    optimization_telemetry: OptimizationTelemetry | None = None,
    preservation_info: SchedulePreservationInfo | None = None,
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
        optimization_telemetry=optimization_telemetry,
        preservation_info=preservation_info,
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
    optimization_telemetry: OptimizationTelemetry | None = None,
    preservation_info: SchedulePreservationInfo | None = None,
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
        optimization_telemetry=optimization_telemetry,
        preservation_info=preservation_info,
        _locked_model=locked_model,
    )


def _discover_preference_benchmarks(
    data: NormalizedScheduleInput,
    built: OptimizationModel,
    rank: PreferenceRank,
    config: LexicographicSolverConfig,
    cancellation: CancellationToken | None = None,
    *,
    preservation: PreservationToken | None = None,
    progress: ProgressCallback | None = None,
    progress_interval_seconds: float = 5.0,
    optimization_started_at: float | None = None,
    formal_stages_completed: int = 0,
    time_to_first_feasible_schedule: float | None = None,
) -> tuple[
    tuple[PreferenceBenchmarkResult, ...],
    _SolverRun | None,
    _SolveProgressContext | None,
]:
    """Prove independent per-class ideals without locking either class first."""

    optimization_started_at = optimization_started_at or perf_counter()
    definitions = tuple(
        item for item in CLASS_PREFERENCES if item.rank is rank
    )
    results: list[PreferenceBenchmarkResult] = []
    last_run: _SolverRun | None = None
    last_context: _SolveProgressContext | None = None
    for benchmark_index, definition in enumerate(definitions, start=1):
        if preservation is not None and preservation.is_requested:
            break
        rank_label = "一" if rank is PreferenceRank.FIRST else "二"
        direction = (
            ObjectiveDirection.MAXIMIZE
            if definition.direction is PreferenceDirection.MAXIMIZE
            else ObjectiveDirection.MINIMIZE
        )
        upcoming_stage = PREFERENCE_REGRET_STAGES[rank][0]
        details: dict[str, object] = {
            "rank": rank.value,
            "full_time_class": definition.full_time_class.value,
            "benchmark_index": benchmark_index,
            "benchmark_total": len(definitions),
            "formal_stages_completed": formal_stages_completed,
            "formal_stage_total": len(FORMAL_STAGE_POLICIES),
            "has_feasible_solution": True,
        }
        if time_to_first_feasible_schedule is not None:
            details["time_to_first_feasible_schedule"] = (
                time_to_first_feasible_schedule
            )
        details.update(_user_step_details(upcoming_stage))
        context = _SolveProgressContext(
            activity="preference_benchmark",
            label=(
                f"計算 {definition.full_time_class.value} 類"
                f"第{rank_label}偏好基準 "
                f"({benchmark_index}/{len(definitions)})"
            ),
            direction=direction,
            current=benchmark_index,
            total=len(definitions),
            optimization_started_at=optimization_started_at,
            details=MappingProxyType(details),
        )
        last_context = context
        _emit_activity_event(progress, context, ProgressEventKind.STEP_STARTED)
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
            _emit_activity_event(
                progress,
                context,
                ProgressEventKind.STEP_COMPLETED,
                message=f"{context.label}：無可比較機會，已略過",
                extra_details={"benchmark_status": "SKIPPED_CONSTANT"},
            )
            continue
        expression = built.class_preference_values[
            (definition.full_time_class, rank)
        ]
        if definition.direction is PreferenceDirection.MAXIMIZE:
            built.feasibility.model.maximize(expression)
        else:
            built.feasibility.model.minimize(expression)
        if cancellation is None and progress is None and preservation is None:
            run = _solve_once(built.feasibility.model, config)
        else:
            run = _solve_once(
                built.feasibility.model,
                config,
                cancellation,
                preservation=preservation,
                progress=progress,
                progress_context=context,
                progress_interval_seconds=progress_interval_seconds,
            )
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
        _emit_activity_event(
            progress,
            context,
            ProgressEventKind.STEP_COMPLETED,
            message=f"{context.label}：{status.value}",
            extra_details={
                "benchmark_status": status.value,
                "benchmark_ideal_value": ideal_value,
                "best_objective_bound": run.best_objective_bound,
                "num_conflicts": run.num_conflicts,
                "num_branches": run.num_branches,
                "stage_elapsed_seconds": run.wall_time_seconds,
            },
        )
        if status is not OptimizationStageStatus.OPTIMAL:
            break
    return tuple(results), last_run, last_context


def solve_lexicographic(
    data: NormalizedScheduleInput,
    config: LexicographicSolverConfig | None = None,
    *,
    precheck_result: PrecheckResult | None = None,
    cancellation: CancellationToken | None = None,
    preservation: PreservationToken | None = None,
    progress: ProgressCallback | None = None,
    progress_interval_seconds: float = 5.0,
) -> LexicographicResult:
    """Solve revised class-specific preferences with fair normalized regrets."""

    if progress_interval_seconds <= 0:
        raise ValueError("progress_interval_seconds must be greater than 0")
    config = config or LexicographicSolverConfig()
    precheck = precheck_result or run_prechecks(data)
    if precheck.status is PrecheckStatus.PRECHECK_INFEASIBLE:
        return _empty_result(FeasibilityStatus.PRECHECK_INFEASIBLE, precheck)

    optimization_started_at = perf_counter()
    built = build_optimization_model(data)
    base_telemetry = _problem_telemetry(data, built)
    stages: list[OptimizationStageResult] = []
    benchmarks: list[PreferenceBenchmarkResult] = []
    class_pattern_locks: list[ClassPatternLockResult] = []
    formal_stages_completed = 0
    time_to_first_feasible_schedule: float | None = None

    def current_telemetry(*, proven: bool = False) -> OptimizationTelemetry:
        elapsed = perf_counter() - optimization_started_at
        return replace(
            base_telemetry,
            time_to_first_feasible_schedule=time_to_first_feasible_schedule,
            time_to_proven_formal_optimum=elapsed if proven else None,
            total_optimization_seconds=elapsed,
        )

    def append_completed_stage(
        stage_result: OptimizationStageResult,
        context: _SolveProgressContext,
    ) -> None:
        nonlocal formal_stages_completed
        stages.append(stage_result)
        formal_stages_completed += 1
        _emit_activity_event(
            progress,
            context,
            ProgressEventKind.STEP_COMPLETED,
            message=(
                f"正式流程已完成 {formal_stages_completed}/"
                f"{len(FORMAL_STAGE_POLICIES)}："
                f"{FORMAL_STAGE_POLICY_BY_STAGE[stage_result.stage].display_name}"
            ),
            extra_details={
                "formal_stages_completed": formal_stages_completed,
                "has_feasible_solution": (
                    time_to_first_feasible_schedule is not None
                ),
                "time_to_first_feasible_schedule": (
                    time_to_first_feasible_schedule
                ),
                "stage_status": stage_result.status.value,
                "objective_value": stage_result.objective_value,
                "best_objective_bound": stage_result.best_objective_bound,
                "num_conflicts": stage_result.num_conflicts,
                "num_branches": stage_result.num_branches,
                "stage_elapsed_seconds": stage_result.wall_time_seconds,
            },
        )

    def preservation_requested() -> bool:
        return preservation is not None and preservation.is_requested

    def stop_snapshot(
        activity: str,
        *,
        context: _SolveProgressContext | None,
        run: _SolverRun | None,
    ) -> OptimizationStopSnapshot:
        details = {} if context is None else dict(context.details)
        observed = (
            {}
            if run is None or run.progress_snapshot is None
            else dict(run.progress_snapshot)
        )

        def optional_int(value: object) -> int | None:
            return None if value is None else int(value)

        def optional_float(value: object) -> float | None:
            return None if value is None else float(value)

        best_bound = observed.get("best_bound")
        if best_bound is None and run is not None:
            best_bound = run.best_objective_bound
        stage_elapsed = observed.get("stage_elapsed_seconds")
        if stage_elapsed is None and run is not None:
            stage_elapsed = run.wall_time_seconds
        return OptimizationStopSnapshot(
            activity=activity,
            objective_direction=(
                None
                if context is None
                or context.direction is ObjectiveDirection.NONE
                else context.direction.value
            ),
            user_step_index=optional_int(details.get("user_step_index")),
            user_step_total=optional_int(details.get("user_step_total")),
            user_step_title=(
                None
                if details.get("user_step_title") is None
                else str(details["user_step_title"])
            ),
            formal_stage_index=optional_int(
                details.get("formal_stage_index")
            ),
            formal_stage_total=optional_int(
                details.get("formal_stage_total")
            ),
            formal_stages_completed=formal_stages_completed,
            benchmark_index=optional_int(details.get("benchmark_index")),
            benchmark_total=optional_int(details.get("benchmark_total")),
            incumbent=optional_float(observed.get("incumbent")),
            best_objective_bound=optional_float(best_bound),
            absolute_gap=optional_float(observed.get("absolute_gap")),
            relative_gap=optional_float(observed.get("relative_gap")),
            solutions_found=optional_int(observed.get("solutions_found")),
            stage_elapsed_seconds=optional_float(stage_elapsed),
            optimization_elapsed_seconds=(
                perf_counter() - optimization_started_at
            ),
            seconds_since_last_solution=optional_float(
                observed.get("seconds_since_last_solution")
            ),
            seconds_since_bound_update=optional_float(
                observed.get("seconds_since_bound_update")
            ),
            time_to_first_feasible_schedule=(
                time_to_first_feasible_schedule
            ),
        )

    def preservation_info(
        activity: str,
        *,
        stage: OptimizationStage | None = None,
        rank: PreferenceRank | None = None,
        full_time_class: FullTimeClass | None = None,
        used_current_incumbent: bool = False,
        context: _SolveProgressContext | None = None,
        run: _SolverRun | None = None,
    ) -> SchedulePreservationInfo:
        if context is None and stage is not None:
            context = _formal_progress_context(
                stage,
                optimization_started_at=optimization_started_at,
                has_feasible_solution=(
                    time_to_first_feasible_schedule is not None
                ),
                completed_stages=formal_stages_completed,
                time_to_first_feasible_schedule=(
                    time_to_first_feasible_schedule
                ),
            )
        return SchedulePreservationInfo(
            activity=activity,
            formal_stage=None if stage is None else stage.value,
            preference_rank=None if rank is None else rank.value,
            full_time_class=(
                None if full_time_class is None else full_time_class.value
            ),
            used_current_incumbent=used_current_incumbent,
            optimization_stop_snapshot=stop_snapshot(
                activity,
                context=context,
                run=run,
            ),
        )

    hard_context = _formal_progress_context(
        OptimizationStage.HARD_FEASIBILITY,
        optimization_started_at=optimization_started_at,
        has_feasible_solution=False,
        completed_stages=formal_stages_completed,
        time_to_first_feasible_schedule=None,
    )
    _emit_activity_event(progress, hard_context, ProgressEventKind.STEP_STARTED)
    if cancellation is None and progress is None and preservation is None:
        hard_run = _solve_once(built.feasibility.model, config)
    else:
        hard_run = _solve_once(
            built.feasibility.model,
            config,
            cancellation,
            preservation=preservation,
            progress=progress,
            progress_context=hard_context,
            progress_interval_seconds=progress_interval_seconds,
        )
    if hard_run.raw_status == cp_model.INFEASIBLE:
        append_completed_stage(
            OptimizationStageResult(
                stage=OptimizationStage.HARD_FEASIBILITY,
                direction=FORMAL_STAGE_POLICY_BY_STAGE[
                    OptimizationStage.HARD_FEASIBILITY
                ].direction,
                status=OptimizationStageStatus.INFEASIBLE,
                objective_value=None,
                raw_solver_status=hard_run.raw_status_name,
                wall_time_seconds=hard_run.wall_time_seconds,
                locked=False,
                best_objective_bound=hard_run.best_objective_bound,
                num_conflicts=hard_run.num_conflicts,
                num_branches=hard_run.num_branches,
            ),
            hard_context,
        )
        return _empty_result(
            FeasibilityStatus.INFEASIBLE,
            precheck,
            tuple(stages),
            current_telemetry(),
        )
    if hard_run.raw_status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        append_completed_stage(
            OptimizationStageResult(
                stage=OptimizationStage.HARD_FEASIBILITY,
                direction=FORMAL_STAGE_POLICY_BY_STAGE[
                    OptimizationStage.HARD_FEASIBILITY
                ].direction,
                status=OptimizationStageStatus.UNKNOWN,
                objective_value=None,
                raw_solver_status=hard_run.raw_status_name,
                wall_time_seconds=hard_run.wall_time_seconds,
                locked=False,
                best_objective_bound=hard_run.best_objective_bound,
                num_conflicts=hard_run.num_conflicts,
                num_branches=hard_run.num_branches,
            ),
            hard_context,
        )
        return _empty_result(
            FeasibilityStatus.UNKNOWN,
            precheck,
            tuple(stages),
            current_telemetry(),
            (
                preservation_info(
                    "formal_stage",
                    stage=OptimizationStage.HARD_FEASIBILITY,
                    context=hard_context,
                    run=hard_run,
                )
                if preservation_requested()
                else None
            ),
        )

    time_to_first_feasible_schedule = perf_counter() - optimization_started_at
    append_completed_stage(
        OptimizationStageResult(
            stage=OptimizationStage.HARD_FEASIBILITY,
            direction=FORMAL_STAGE_POLICY_BY_STAGE[
                OptimizationStage.HARD_FEASIBILITY
            ].direction,
            status=OptimizationStageStatus.FEASIBLE,
            objective_value=None,
            raw_solver_status=hard_run.raw_status_name,
            wall_time_seconds=hard_run.wall_time_seconds,
            locked=False,
            best_objective_bound=hard_run.best_objective_bound,
            num_conflicts=hard_run.num_conflicts,
            num_branches=hard_run.num_branches,
        ),
        hard_context,
    )
    snapshot = _snapshot(data, built, hard_run.solver)
    last_solver: cp_model.CpSolver | None = hard_run.solver
    if preservation_requested():
        return _result_from_snapshot(
            FeasibilityStatus.FEASIBLE,
            snapshot,
            stages,
            precheck,
            implemented_objective_prefix_optimal=True,
            optimization_telemetry=current_telemetry(),
            preservation_info=preservation_info(
                "formal_stage",
                stage=OptimizationStage.HARD_FEASIBILITY,
                used_current_incumbent=True,
                context=hard_context,
                run=hard_run,
            ),
        )

    def execute_specs(
        specs: tuple[_ObjectiveSpec, ...] | list[_ObjectiveSpec],
    ) -> LexicographicResult | None:
        nonlocal last_solver, snapshot
        for objective in specs:
            if preservation_requested():
                return _result_from_snapshot(
                    FeasibilityStatus.FEASIBLE,
                    snapshot,
                    stages,
                    precheck,
                    preference_benchmarks=tuple(benchmarks),
                    class_pattern_locks=tuple(class_pattern_locks),
                    implemented_objective_prefix_optimal=True,
                    optimization_telemetry=current_telemetry(),
                    preservation_info=preservation_info(
                        "stage_boundary",
                        stage=objective.stage,
                    ),
                )
            context = _formal_progress_context(
                objective.stage,
                optimization_started_at=optimization_started_at,
                has_feasible_solution=True,
                completed_stages=formal_stages_completed,
                time_to_first_feasible_schedule=(
                    time_to_first_feasible_schedule
                ),
            )
            _emit_activity_event(
                progress, context, ProgressEventKind.STEP_STARTED
            )
            if objective.constant_value is not None:
                append_completed_stage(
                    OptimizationStageResult(
                        stage=objective.stage,
                        direction=objective.direction,
                        status=OptimizationStageStatus.SKIPPED_CONSTANT,
                        objective_value=objective.constant_value,
                        raw_solver_status="NOT_RUN",
                        wall_time_seconds=0.0,
                        locked=False,
                        constant_proof=objective.constant_proof,
                    ),
                    context,
                )
                if preservation_requested():
                    return _result_from_snapshot(
                        FeasibilityStatus.FEASIBLE,
                        snapshot,
                        stages,
                        precheck,
                        preference_benchmarks=tuple(benchmarks),
                        class_pattern_locks=tuple(class_pattern_locks),
                        implemented_objective_prefix_optimal=True,
                        optimization_telemetry=current_telemetry(),
                        preservation_info=preservation_info(
                            "formal_stage",
                            stage=objective.stage,
                            context=context,
                        ),
                    )
                continue
            if objective.direction is ObjectiveDirection.MAXIMIZE:
                built.feasibility.model.maximize(objective.expression)
            else:
                built.feasibility.model.minimize(objective.expression)
            if cancellation is None and progress is None and preservation is None:
                run = _solve_once(built.feasibility.model, config)
            else:
                run = _solve_once(
                    built.feasibility.model,
                    config,
                    cancellation,
                    preservation=preservation,
                    progress=progress,
                    progress_context=context,
                    progress_interval_seconds=progress_interval_seconds,
                )
            if run.raw_status == cp_model.OPTIMAL:
                objective_value = int(run.solver.value(objective.expression))
                built.feasibility.model.add(
                    objective.expression == objective_value
                )
                append_completed_stage(
                    OptimizationStageResult(
                        stage=objective.stage,
                        direction=objective.direction,
                        status=OptimizationStageStatus.OPTIMAL,
                        objective_value=objective_value,
                        raw_solver_status=run.raw_status_name,
                        wall_time_seconds=run.wall_time_seconds,
                        locked=True,
                        best_objective_bound=run.best_objective_bound,
                        num_conflicts=run.num_conflicts,
                        num_branches=run.num_branches,
                    ),
                    context,
                )
                snapshot = _snapshot(data, built, run.solver)
                last_solver = run.solver
                if preservation_requested():
                    return _result_from_snapshot(
                        FeasibilityStatus.FEASIBLE,
                        snapshot,
                        stages,
                        precheck,
                        preference_benchmarks=tuple(benchmarks),
                        class_pattern_locks=tuple(class_pattern_locks),
                        implemented_objective_prefix_optimal=True,
                        optimization_telemetry=current_telemetry(),
                        preservation_info=preservation_info(
                            "formal_stage",
                            stage=objective.stage,
                            used_current_incumbent=True,
                            context=context,
                            run=run,
                        ),
                    )
                continue
            used_current_incumbent = False
            if run.raw_status == cp_model.FEASIBLE:
                objective_value = int(run.solver.value(objective.expression))
                append_completed_stage(
                    OptimizationStageResult(
                        stage=objective.stage,
                        direction=objective.direction,
                        status=OptimizationStageStatus.FEASIBLE,
                        objective_value=objective_value,
                        raw_solver_status=run.raw_status_name,
                        wall_time_seconds=run.wall_time_seconds,
                        locked=False,
                        best_objective_bound=run.best_objective_bound,
                        num_conflicts=run.num_conflicts,
                        num_branches=run.num_branches,
                    ),
                    context,
                )
                snapshot = _snapshot(data, built, run.solver)
                last_solver = run.solver
                used_current_incumbent = True
            else:
                append_completed_stage(
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
                        best_objective_bound=run.best_objective_bound,
                        num_conflicts=run.num_conflicts,
                        num_branches=run.num_branches,
                    ),
                    context,
                )
            return _result_from_snapshot(
                FeasibilityStatus.FEASIBLE,
                snapshot,
                stages,
                precheck,
                preference_benchmarks=tuple(benchmarks),
                class_pattern_locks=tuple(class_pattern_locks),
                implemented_objective_prefix_optimal=(
                    preservation_requested() and not used_current_incumbent
                ),
                optimization_telemetry=current_telemetry(),
                preservation_info=(
                    preservation_info(
                        "formal_stage",
                        stage=objective.stage,
                        used_current_incumbent=used_current_incumbent,
                        context=context,
                        run=run,
                    )
                    if preservation_requested()
                    else None
                ),
            )
        return None

    base_specs = _formal_objective_specs(data, built, precheck)[:1]
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
        if preservation_requested():
            return _result_from_snapshot(
                FeasibilityStatus.FEASIBLE,
                snapshot,
                stages,
                precheck,
                preference_benchmarks=tuple(benchmarks),
                class_pattern_locks=tuple(class_pattern_locks),
                implemented_objective_prefix_optimal=True,
                optimization_telemetry=current_telemetry(),
                preservation_info=preservation_info(
                    "stage_boundary",
                    stage=PREFERENCE_REGRET_STAGES[rank][0],
                    rank=rank,
                ),
            )
        discovered, last_run, last_benchmark_context = (
            _discover_preference_benchmarks(
                data,
                built,
                rank,
                config,
                cancellation,
                preservation=preservation,
                progress=progress,
                progress_interval_seconds=progress_interval_seconds,
                optimization_started_at=optimization_started_at,
                formal_stages_completed=formal_stages_completed,
                time_to_first_feasible_schedule=(
                    time_to_first_feasible_schedule
                ),
            )
        )
        if preservation_requested():
            completed_discovered = tuple(
                item
                for item in discovered
                if item.status
                in (
                    OptimizationStageStatus.OPTIMAL,
                    OptimizationStageStatus.SKIPPED_CONSTANT,
                )
            )
            benchmarks.extend(completed_discovered)
            interrupted = next(
                (
                    item
                    for item in discovered
                    if item.status
                    not in (
                        OptimizationStageStatus.OPTIMAL,
                        OptimizationStageStatus.SKIPPED_CONSTANT,
                    )
                ),
                None,
            )
            return _result_from_snapshot(
                FeasibilityStatus.FEASIBLE,
                snapshot,
                stages,
                precheck,
                preference_benchmarks=tuple(benchmarks),
                class_pattern_locks=tuple(class_pattern_locks),
                implemented_objective_prefix_optimal=True,
                optimization_telemetry=current_telemetry(),
                preservation_info=preservation_info(
                    "preference_benchmark",
                    rank=rank,
                    full_time_class=(
                        None
                        if interrupted is None
                        else interrupted.full_time_class
                    ),
                    context=last_benchmark_context,
                    run=last_run,
                ),
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
                optimization_telemetry=current_telemetry(),
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
            for full_time_class, metric in CLASS_REMAINING_PATTERN_METRICS.items():
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
    proven_telemetry = current_telemetry(proven=True)
    if progress is not None:
        progress(
            ProgressEvent(
                phase=ExecutionPhase.OPTIMIZATION,
                kind=ProgressEventKind.INFORMATION,
                message="正式 16 階段皆已完成並證明最佳值",
                elapsed_seconds=proven_telemetry.total_optimization_seconds,
                current=len(FORMAL_STAGE_POLICIES),
                total=len(FORMAL_STAGE_POLICIES),
                details={
                    "activity": "formal_optimization_completed",
                    "formal_stages_completed": len(FORMAL_STAGE_POLICIES),
                    "formal_stage_total": len(FORMAL_STAGE_POLICIES),
                    "has_feasible_solution": True,
                    "time_to_first_feasible_schedule": (
                        time_to_first_feasible_schedule
                    ),
                    "time_to_proven_formal_optimum": (
                        proven_telemetry.time_to_proven_formal_optimum
                    ),
                    "total_elapsed_seconds": (
                        proven_telemetry.total_optimization_seconds
                    ),
                },
            )
        )
    return _result_from_snapshot(
        FeasibilityStatus.FEASIBLE,
        snapshot,
        stages,
        precheck,
        preference_benchmarks=tuple(benchmarks),
        class_pattern_locks=tuple(class_pattern_locks),
        implemented_objective_prefix_optimal=True,
        locked_model=built,
        optimization_telemetry=proven_telemetry,
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
    cancellation: CancellationToken | None = None,
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
    interrupted = bool(cancellation and cancellation.is_cancelled)
    active_solver: cp_model.CpSolver | None = None
    cancellation_monitor: threading.Thread | None = None
    cancellation_monitor_stop = threading.Event()
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

    if cancellation is not None:

        def monitor_cancellation() -> None:
            nonlocal interrupted
            while not cancellation_monitor_stop.is_set():
                if cancellation.wait(0.05):
                    interrupted = True
                    if active_solver is not None:
                        active_solver.stop_search()
                    return

        cancellation_monitor = threading.Thread(
            target=monitor_cancellation,
            name="candidate-diagnostic-cancellation-monitor",
            daemon=True,
        )
        cancellation_monitor.start()

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
        cancellation_monitor_stop.set()
        if cancellation_monitor is not None:
            cancellation_monitor.join(timeout=1.0)
        if handles_sigint:
            signal.signal(signal.SIGINT, previous_sigint_handler)
