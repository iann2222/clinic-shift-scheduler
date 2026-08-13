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
from .events import CancellationToken
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
    FORMAL_STAGE_POLICY_BY_STAGE,
    FULL_TIME_PATTERN_METRICS,
    GROUP_FAIRNESS_EMPLOYMENT_TYPES,
    GROUP_FAIRNESS_METRICS,
    GROUP_FAIRNESS_STAGES,
    PREFERENCE_RATIO_MAX_STAGE_BY_METRIC,
    PREFERENCE_REGRET_STAGES,
    SUNDAY_FAIRNESS_METRICS,
    SUNDAY_FAIRNESS_STAGES,
)
from .precheck import PrecheckResult, PrecheckStatus, run_prechecks
from .ratio_fairness import (
    BASIS_POINTS_SCALE,
    ratio_basis_points,
)
from .shift_bounds import hard_minimum_shifts
from .solver_contracts import (
    Assignment,
    FeasibilityStatus,
    LexicographicResult,
    PersonDayKey,
)


@dataclass(frozen=True, slots=True)
class OptimizationModel:
    feasibility: FeasibilityModel
    target_differences: Mapping[str, cp_model.IntVar]
    target_deviations: Mapping[str, cp_model.IntVar]
    target_objective: cp_model.LinearExpr | int
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
        target_differences=MappingProxyType(target_differences),
        target_deviations=MappingProxyType(target_deviations),
        target_objective=sum(target_deviations.values()),
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
            direction=FORMAL_STAGE_POLICY_BY_STAGE[
                OptimizationStage.FULL_TIME_TARGET_DEVIATION
            ].direction,
            variables=tuple(built.target_deviations.values()),
            expression=built.target_objective,
            constant_value=target_constant,
            constant_proof=target_proof,
        ),
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


def _solve_once(
    model: cp_model.CpModel,
    config: LexicographicSolverConfig,
    cancellation: CancellationToken | None = None,
) -> _SolverRun:
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = config.num_search_workers
    solver.parameters.random_seed = config.random_seed
    if config.max_time_seconds_per_stage is not None:
        solver.parameters.max_time_in_seconds = config.max_time_seconds_per_stage
    monitor: threading.Thread | None = None
    finished = threading.Event()
    if cancellation is not None:

        def stop_when_cancelled() -> None:
            while not finished.is_set():
                if cancellation.wait(0.05):
                    solver.stop_search()
                    return

        monitor = threading.Thread(
            target=stop_when_cancelled,
            name="cp-sat-cancellation-monitor",
            daemon=True,
        )
        monitor.start()
    try:
        raw_status = solver.solve(model)
    finally:
        finished.set()
        if monitor is not None:
            monitor.join(timeout=0.1)
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
    cancellation: CancellationToken | None = None,
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
        run = (
            _solve_once(built.feasibility.model, config)
            if cancellation is None
            else _solve_once(built.feasibility.model, config, cancellation)
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
        if status is not OptimizationStageStatus.OPTIMAL:
            break
    return tuple(results), last_run


def solve_lexicographic(
    data: NormalizedScheduleInput,
    config: LexicographicSolverConfig | None = None,
    *,
    precheck_result: PrecheckResult | None = None,
    cancellation: CancellationToken | None = None,
) -> LexicographicResult:
    """Solve revised class-specific preferences with fair normalized regrets."""

    config = config or LexicographicSolverConfig()
    precheck = precheck_result or run_prechecks(data)
    if precheck.status is PrecheckStatus.PRECHECK_INFEASIBLE:
        return _empty_result(FeasibilityStatus.PRECHECK_INFEASIBLE, precheck)

    built = build_optimization_model(data)
    stages: list[OptimizationStageResult] = []
    benchmarks: list[PreferenceBenchmarkResult] = []
    class_pattern_locks: list[ClassPatternLockResult] = []
    hard_run = (
        _solve_once(built.feasibility.model, config)
        if cancellation is None
        else _solve_once(built.feasibility.model, config, cancellation)
    )
    if hard_run.raw_status == cp_model.INFEASIBLE:
        stages.append(
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
            )
        )
        return _empty_result(
            FeasibilityStatus.INFEASIBLE, precheck, tuple(stages)
        )
    if hard_run.raw_status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        stages.append(
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
            )
        )
        return _empty_result(
            FeasibilityStatus.UNKNOWN, precheck, tuple(stages)
        )

    stages.append(
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
            run = (
                _solve_once(built.feasibility.model, config)
                if cancellation is None
                else _solve_once(built.feasibility.model, config, cancellation)
            )
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
            data, built, rank, config, cancellation
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
