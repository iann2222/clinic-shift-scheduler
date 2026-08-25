"""Solver result contracts without CP-SAT or native dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Mapping

from .daily_patterns import DailyPattern
from .enums import Period
from .optimization_contracts import (
    ClassPatternLockResult,
    OptimizationStageResult,
    PreferenceBenchmarkResult,
)
from .precheck import PrecheckResult


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


PersonDayKey = tuple[str, date]
PersonPeriodKey = tuple[str, date, Period]


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


@dataclass(frozen=True, slots=True)
class OptimizationTelemetry:
    """Non-sensitive problem-shape and wall-clock data for one optimization."""

    days: int
    employees: int
    full_time_employees: int
    part_time_employees: int
    assignment_variables: int
    availability_ratio: float
    demand_units: int
    time_to_first_feasible_schedule: float | None = None
    time_to_proven_formal_optimum: float | None = None
    total_optimization_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class OptimizationStopSnapshot:
    """Observed solver progress when preservation stopped optimization."""

    activity: str
    objective_direction: str | None = None
    user_step_index: int | None = None
    user_step_total: int | None = None
    user_step_title: str | None = None
    formal_stage_index: int | None = None
    formal_stage_total: int | None = None
    formal_stages_completed: int | None = None
    benchmark_index: int | None = None
    benchmark_total: int | None = None
    incumbent: float | None = None
    best_objective_bound: float | None = None
    absolute_gap: float | None = None
    relative_gap: float | None = None
    solutions_found: int | None = None
    stage_elapsed_seconds: float | None = None
    optimization_elapsed_seconds: float | None = None
    seconds_since_last_solution: float | None = None
    seconds_since_bound_update: float | None = None
    time_to_first_feasible_schedule: float | None = None


@dataclass(frozen=True, slots=True)
class SchedulePreservationInfo:
    """Where a user stopped optimization to keep the best legal snapshot."""

    activity: str
    formal_stage: str | None = None
    preference_rank: str | None = None
    full_time_class: str | None = None
    used_current_incumbent: bool = False
    optimization_stop_snapshot: OptimizationStopSnapshot | None = None


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
    optimization_telemetry: OptimizationTelemetry | None = None
    preservation_info: SchedulePreservationInfo | None = None
    _locked_model: Any | None = field(default=None, repr=False, compare=False)

    @property
    def is_feasible(self) -> bool:
        return self.status in (
            FeasibilityStatus.FEASIBLE,
            FeasibilityStatus.OPTIMAL,
        )
