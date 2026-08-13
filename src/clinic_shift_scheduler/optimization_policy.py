"""Declarative, solver-independent definition of the formal v1 policy.

This module defines *what* the optimization policy is.  CP-SAT expression
construction and assignment-based metric recomputation remain independent
implementations in ``optimization`` and ``result_metrics`` respectively.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .class_preferences import (
    ClassPreferenceDefinition,
    ClassPreferenceMetric,
    PreferenceDirection,
    PreferenceRank,
)
from .enums import EmploymentType, FullTimeClass
from .optimization_contracts import (
    FairnessMetric,
    ObjectiveDirection,
    OptimizationStage,
)


@dataclass(frozen=True, slots=True)
class FormalStagePolicy:
    stage: OptimizationStage
    direction: ObjectiveDirection
    display_name: str


CLASS_PREFERENCES: tuple[ClassPreferenceDefinition, ...] = (
    ClassPreferenceDefinition(
        FullTimeClass.A,
        PreferenceRank.FIRST,
        ClassPreferenceMetric.CONSECUTIVE_DOUBLES,
        PreferenceDirection.MAXIMIZE,
    ),
    ClassPreferenceDefinition(
        FullTimeClass.B,
        PreferenceRank.FIRST,
        ClassPreferenceMetric.SINGLE_SHIFT_DAYS,
        PreferenceDirection.MINIMIZE,
    ),
    ClassPreferenceDefinition(
        FullTimeClass.A,
        PreferenceRank.SECOND,
        ClassPreferenceMetric.MORNING_EVENING_DAYS,
        PreferenceDirection.MAXIMIZE,
    ),
    ClassPreferenceDefinition(
        FullTimeClass.B,
        PreferenceRank.SECOND,
        ClassPreferenceMetric.CONSECUTIVE_DOUBLES,
        PreferenceDirection.MAXIMIZE,
    ),
)


def preference_definition(
    full_time_class: FullTimeClass,
    rank: PreferenceRank,
) -> ClassPreferenceDefinition:
    return next(
        item
        for item in CLASS_PREFERENCES
        if item.full_time_class is full_time_class and item.rank is rank
    )


FORMAL_STAGE_POLICIES: tuple[FormalStagePolicy, ...] = (
    FormalStagePolicy(
        OptimizationStage.HARD_FEASIBILITY,
        ObjectiveDirection.NONE,
        "硬性限制與可行性",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_TARGET_DEVIATION,
        ObjectiveDirection.MINIMIZE,
        "正職 TARGET 偏差",
    ),
    FormalStagePolicy(
        OptimizationStage.PART_TIME_USAGE,
        ObjectiveDirection.MINIMIZE,
        "兼職總使用量",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
        ObjectiveDirection.MINIMIZE,
        "A/B 主要偏好最大正規化 regret",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET,
        ObjectiveDirection.MINIMIZE,
        "A/B 主要偏好正規化 regret 總和",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_PREFERENCE_RANK2_MAX_REGRET,
        ObjectiveDirection.MINIMIZE,
        "A/B 次要偏好最大正規化 regret",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET,
        ObjectiveDirection.MINIMIZE,
        "A/B 次要偏好正規化 regret 總和",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
        ObjectiveDirection.MINIMIZE,
        "正職個人班型比例最大 gap",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_FIRST_PREFERENCE_RATIO_TOTAL_GAP,
        ObjectiveDirection.MINIMIZE,
        "正職第一偏好比例 gap 總和",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
        ObjectiveDirection.MINIMIZE,
        "正職班型比例 gap 總和",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,
        ObjectiveDirection.MINIMIZE,
        "正職班型整數公平",
    ),
    FormalStagePolicy(
        OptimizationStage.PART_TIME_GROUP_FAIRNESS,
        ObjectiveDirection.MINIMIZE,
        "兼職群組公平",
    ),
    FormalStagePolicy(
        OptimizationStage.COMMON_GROUP_FAIRNESS,
        ObjectiveDirection.MINIMIZE,
        "共同群組公平",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP,
        ObjectiveDirection.MINIMIZE,
        "全體正職週日最大 gap",
    ),
    FormalStagePolicy(
        OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP,
        ObjectiveDirection.MINIMIZE,
        "全體正職週日 gap 總和",
    ),
)

FORMAL_STAGE_SEQUENCE: tuple[OptimizationStage, ...] = tuple(
    item.stage for item in FORMAL_STAGE_POLICIES
)
FORMAL_OBJECTIVE_POLICIES: tuple[FormalStagePolicy, ...] = (
    FORMAL_STAGE_POLICIES[1:]
)
FORMAL_OBJECTIVE_STAGES: tuple[OptimizationStage, ...] = tuple(
    item.stage for item in FORMAL_OBJECTIVE_POLICIES
)
FORMAL_STAGE_POLICY_BY_STAGE: Mapping[
    OptimizationStage, FormalStagePolicy
] = MappingProxyType({item.stage: item for item in FORMAL_STAGE_POLICIES})

PREFERENCE_REGRET_STAGES: Mapping[
    PreferenceRank, tuple[OptimizationStage, OptimizationStage]
] = MappingProxyType(
    {
        PreferenceRank.FIRST: (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET,
        ),
        PreferenceRank.SECOND: (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET,
        ),
    }
)

FULL_TIME_PATTERN_METRICS: Mapping[
    FullTimeClass, tuple[FairnessMetric, ...]
] = MappingProxyType(
    {
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
)

CLASS_REMAINING_PATTERN_METRICS: Mapping[
    FullTimeClass, FairnessMetric
] = MappingProxyType(
    {
        FullTimeClass.A: FairnessMetric.SINGLE_SHIFT_DAYS,
        FullTimeClass.B: FairnessMetric.TRIPLE_DAYS,
    }
)

PREFERENCE_RATIO_MAX_STAGE_BY_METRIC: Mapping[
    tuple[FullTimeClass, FairnessMetric], OptimizationStage
] = MappingProxyType(
    {
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
)

PREFERENCE_RATIO_TOTAL_STAGE_BY_MAX_STAGE: Mapping[
    OptimizationStage, OptimizationStage
] = MappingProxyType(
    {
        OptimizationStage.FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_MAX_GAP: (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_PERSON_RATIO_TOTAL_GAP
        ),
        OptimizationStage.FULL_TIME_PREFERENCE_RANK2_PERSON_RATIO_MAX_GAP: (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_PERSON_RATIO_TOTAL_GAP
        ),
        OptimizationStage.FULL_TIME_REMAINING_PATTERN_RATIO_MAX_GAP: (
            OptimizationStage.FULL_TIME_REMAINING_PATTERN_RATIO_TOTAL_GAP
        ),
    }
)

GROUP_FAIRNESS_STAGES: tuple[OptimizationStage, ...] = (
    OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,
    OptimizationStage.PART_TIME_GROUP_FAIRNESS,
    OptimizationStage.COMMON_GROUP_FAIRNESS,
)
GROUP_FAIRNESS_EMPLOYMENT_TYPES: Mapping[
    OptimizationStage, frozenset[EmploymentType]
] = MappingProxyType(
    {
        OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS: frozenset(
            {EmploymentType.FULL_TIME}
        ),
        OptimizationStage.PART_TIME_GROUP_FAIRNESS: frozenset(
            {EmploymentType.PART_TIME}
        ),
        OptimizationStage.COMMON_GROUP_FAIRNESS: frozenset(EmploymentType),
    }
)
GROUP_FAIRNESS_METRICS: Mapping[
    OptimizationStage, tuple[FairnessMetric, ...] | None
] = MappingProxyType(
    {
        # None means use the A/B-specific FULL_TIME_PATTERN_METRICS.
        OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS: None,
        OptimizationStage.PART_TIME_GROUP_FAIRNESS: (
            FairnessMetric.TOTAL_SHIFTS,
        ),
        OptimizationStage.COMMON_GROUP_FAIRNESS: (
            FairnessMetric.MORNING_SHIFTS,
            FairnessMetric.AFTERNOON_SHIFTS,
            FairnessMetric.EVENING_SHIFTS,
            FairnessMetric.SUNDAY_SHIFTS,
            FairnessMetric.HOLIDAY_SHIFTS,
        ),
    }
)

COMMON_GROUP_FAIRNESS_WEIGHTS: Mapping[FairnessMetric, int] = MappingProxyType(
    {
        FairnessMetric.MORNING_SHIFTS: 3,
        FairnessMetric.AFTERNOON_SHIFTS: 3,
        FairnessMetric.EVENING_SHIFTS: 3,
        FairnessMetric.SUNDAY_SHIFTS: 7,
        FairnessMetric.HOLIDAY_SHIFTS: 3,
    }
)

SUNDAY_FAIRNESS_STAGES: tuple[OptimizationStage, ...] = (
    OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP,
    OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP,
)
SUNDAY_FAIRNESS_METRICS: tuple[FairnessMetric, ...] = (
    FairnessMetric.SUNDAY_SHIFTS,
    FairnessMetric.SUNDAY_ATTENDANCE_DAYS,
)
