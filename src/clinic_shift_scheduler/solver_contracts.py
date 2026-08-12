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
    _locked_model: Any | None = field(default=None, repr=False, compare=False)

    @property
    def is_feasible(self) -> bool:
        return self.status in (
            FeasibilityStatus.FEASIBLE,
            FeasibilityStatus.OPTIMAL,
        )
