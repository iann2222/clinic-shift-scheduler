"""Lightweight optimization contracts shared outside the CP-SAT adapter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .class_preferences import (
    ClassPreferenceMetric,
    PreferenceDirection,
    PreferenceRank,
)
from .enums import FullTimeClass


class OptimizationStage(StrEnum):
    HARD_FEASIBILITY = "hard_feasibility"
    FULL_TIME_TARGET_DEVIATION = "full_time_target_deviation"
    PART_TIME_USAGE = "part_time_usage"
    FULL_TIME_PREFERENCE_RANK1_MAX_REGRET = "full_time_preference_rank1_max_regret"
    FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET = "full_time_preference_rank1_total_regret"
    FULL_TIME_PREFERENCE_RANK2_MAX_REGRET = "full_time_preference_rank2_max_regret"
    FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET = "full_time_preference_rank2_total_regret"
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
    FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP = "full_time_sunday_fairness_max_gap"
    FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP = "full_time_sunday_fairness_total_gap"


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
    NO_COMPARABLE_FULL_TIME_EMPLOYEES = "NO_COMPARABLE_FULL_TIME_EMPLOYEES"
    NO_COMPARABLE_FULL_TIME_CLASSES = "NO_COMPARABLE_FULL_TIME_CLASSES"
    NO_COMPARABLE_FAIRNESS_GROUPS = "NO_COMPARABLE_FAIRNESS_GROUPS"


@dataclass(frozen=True, slots=True)
class LexicographicSolverConfig:
    max_time_seconds_per_stage: float | None = None
    num_search_workers: int = 1
    random_seed: int = 0

    def __post_init__(self) -> None:
        if self.max_time_seconds_per_stage is not None and self.max_time_seconds_per_stage <= 0:
            raise ValueError("max_time_seconds_per_stage must be greater than 0")
        if self.num_search_workers <= 0:
            raise ValueError("num_search_workers must be greater than 0")


class EquivalentSolutionDiagnosticStatus(StrEnum):
    EXACT_COUNT = "EXACT_COUNT"
    AT_LEAST_LIMIT = "AT_LEAST_LIMIT"
    TIME_LIMIT = "TIME_LIMIT"
    INTERRUPTED = "INTERRUPTED"


@dataclass(frozen=True, slots=True)
class EquivalentSolutionDiagnosticConfig:
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
