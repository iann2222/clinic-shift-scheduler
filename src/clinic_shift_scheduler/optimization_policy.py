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


@dataclass(frozen=True, slots=True)
class ClassPolicySummary:
    """User-facing summary of one full-time class policy."""

    title: str
    summary: str
    preferences: tuple[str, ...]
    hard_rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UserFacingPolicyStep:
    """One readable flow step backed by formal optimization stages."""

    title: str
    description: str
    stages: tuple[OptimizationStage, ...]


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
        OptimizationStage.PART_TIME_TARGET_MAX_REGRET,
        ObjectiveDirection.MINIMIZE,
        "兼職 TARGET 最大正規化損失",
    ),
    FormalStagePolicy(
        OptimizationStage.PART_TIME_TARGET_TOTAL_REGRET,
        ObjectiveDirection.MINIMIZE,
        "兼職 TARGET 正規化損失總和",
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


CLASS_POLICY_SUMMARIES: Mapping[
    FullTimeClass, ClassPolicySummary
] = MappingProxyType(
    {
        FullTimeClass.A: ClassPolicySummary(
            title="A 類正職",
            summary="以取得連續雙班為主要偏好，無法連排時仍盡量避免只上一節。",
            preferences=(
                "第一偏好：早＋午或午＋晚的連續雙班",
                "第二偏好：早＋晚拆班",
                "最後接受：單節出勤日",
            ),
            hard_rules=("每天最多兩節，禁止早＋午＋晚三節班",),
        ),
        FullTimeClass.B: ClassPolicySummary(
            title="B 類正職",
            summary="最重視避免單節出勤，再盡量安排連續雙班；三節班只作為備用班型。",
            preferences=(
                "第一偏好：盡量減少單節出勤日",
                "第二偏好：早＋午或午＋晚的連續雙班",
                "備用班型：早＋午＋晚三節班",
            ),
            hard_rules=(
                "禁止只有早＋晚的拆班",
                "每人每月單節出勤日最多三天",
            ),
        ),
    }
)


USER_FACING_OPTIMIZATION_FLOW: tuple[UserFacingPolicyStep, ...] = (
    UserFacingPolicyStep(
        "先確認班表合法且能完整補足需求",
        "滿足開診需求、職務資格、可排時段、請假、班次上下限與每日合法班型。",
        (OptimizationStage.HARD_FEASIBILITY,),
    ),
    UserFacingPolicyStep(
        "盡量減少兼職總使用量",
        "在同一個完整模型中優先使用正職，必要時再由兼職補足需求。",
        (OptimizationStage.PART_TIME_USAGE,),
    ),
    UserFacingPolicyStep(
        "共同保護 A／B 類的第一偏好",
        "A 類爭取連續雙班，B 類減少單節日；先控制兩類最大相對損失，再降低損失總和。",
        (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET,
        ),
    ),
    UserFacingPolicyStep(
        "共同保護 A／B 類的第二偏好",
        "A 類爭取早晚拆班，B 類爭取連續雙班；完成後鎖定類別層級品質，再分配個人負擔。",
        (
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_MAX_REGRET,
            OptimizationStage.FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET,
        ),
    ),
    UserFacingPolicyStep(
        "平衡正職個人的班型比例",
        "在各自類別與公平分組內，先縮小最明顯的比例差，再改善第一偏好及整體比例差。",
        (
            OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
            OptimizationStage.FULL_TIME_FIRST_PREFERENCE_RATIO_TOTAL_GAP,
            OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
        ),
    ),
    UserFacingPolicyStep(
        "平衡正職個人的班型次數",
        "以整數次數公平作為比例公平之後的細部調整。",
        (OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,),
    ),
    UserFacingPolicyStep(
        "照顧兼職的目標班次",
        "同時降低兼職 TARGET 偏差與相對偏差不公平，不把軟性目標當成必須剛好達成的硬限制。",
        (
            OptimizationStage.PART_TIME_TARGET_MAX_REGRET,
            OptimizationStage.PART_TIME_TARGET_TOTAL_REGRET,
        ),
    ),
    UserFacingPolicyStep(
        "平衡其他兼職工作量",
        "對非 TARGET 兼職，在相同公平分組內縮小實際總節數差距。",
        (OptimizationStage.PART_TIME_GROUP_FAIRNESS,),
    ),
    UserFacingPolicyStep(
        "改善共同班次公平",
        "平衡早、午、晚、週日與假日節數；其中週日節數的權重較高。",
        (OptimizationStage.COMMON_GROUP_FAIRNESS,),
    ),
    UserFacingPolicyStep(
        "最後改善全體正職週日公平",
        "再比較全體正職的週日節數與週日出勤天數，挑選更平均的同品質班表。",
        (
            OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP,
            OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP,
        ),
    ),
)
