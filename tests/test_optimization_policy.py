from __future__ import annotations

import unittest

from clinic_shift_scheduler.class_preferences import (
    ClassPreferenceMetric,
    PreferenceDirection,
    PreferenceRank,
)
from clinic_shift_scheduler.enums import EmploymentType, FullTimeClass
from clinic_shift_scheduler.optimization_contracts import (
    FairnessMetric,
    ObjectiveDirection,
    OptimizationStage,
)
from clinic_shift_scheduler.optimization_policy import (
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
)


class OptimizationPolicyTests(unittest.TestCase):
    def test_formal_stage_sequence_preserves_the_v1_contract(self) -> None:
        self.assertEqual(
            FORMAL_STAGE_SEQUENCE,
            (
                OptimizationStage.HARD_FEASIBILITY,
                OptimizationStage.PART_TIME_USAGE,
                OptimizationStage.FULL_TIME_PREFERENCE_RANK1_MAX_REGRET,
                OptimizationStage.FULL_TIME_PREFERENCE_RANK1_TOTAL_REGRET,
                OptimizationStage.FULL_TIME_PREFERENCE_RANK2_MAX_REGRET,
                OptimizationStage.FULL_TIME_PREFERENCE_RANK2_TOTAL_REGRET,
                OptimizationStage.FULL_TIME_PATTERN_RATIO_MAX_GAP,
                OptimizationStage.FULL_TIME_FIRST_PREFERENCE_RATIO_TOTAL_GAP,
                OptimizationStage.FULL_TIME_PATTERN_RATIO_TOTAL_GAP,
                OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS,
                OptimizationStage.PART_TIME_TARGET_MAX_REGRET,
                OptimizationStage.PART_TIME_TARGET_TOTAL_REGRET,
                OptimizationStage.PART_TIME_GROUP_FAIRNESS,
                OptimizationStage.COMMON_GROUP_FAIRNESS,
                OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_MAX_GAP,
                OptimizationStage.FULL_TIME_SUNDAY_FAIRNESS_TOTAL_GAP,
            ),
        )
        self.assertEqual(FORMAL_OBJECTIVE_STAGES, FORMAL_STAGE_SEQUENCE[1:])
        self.assertEqual(
            len(FORMAL_STAGE_POLICY_BY_STAGE),
            len(FORMAL_STAGE_POLICIES),
        )
        self.assertEqual(
            FORMAL_STAGE_POLICY_BY_STAGE[
                OptimizationStage.HARD_FEASIBILITY
            ].direction,
            ObjectiveDirection.NONE,
        )
        self.assertTrue(
            all(
                FORMAL_STAGE_POLICY_BY_STAGE[stage].direction
                is ObjectiveDirection.MINIMIZE
                for stage in FORMAL_OBJECTIVE_STAGES
            )
        )
        self.assertTrue(
            all(item.display_name.strip() for item in FORMAL_STAGE_POLICIES)
        )

    def test_class_preferences_preserve_asymmetric_a_b_policy(self) -> None:
        actual = {
            (item.full_time_class, item.rank): (
                item.metric,
                item.direction,
            )
            for item in CLASS_PREFERENCES
        }
        self.assertEqual(
            actual,
            {
                (FullTimeClass.A, PreferenceRank.FIRST): (
                    ClassPreferenceMetric.CONSECUTIVE_DOUBLES,
                    PreferenceDirection.MAXIMIZE,
                ),
                (FullTimeClass.B, PreferenceRank.FIRST): (
                    ClassPreferenceMetric.SINGLE_SHIFT_DAYS,
                    PreferenceDirection.MINIMIZE,
                ),
                (FullTimeClass.A, PreferenceRank.SECOND): (
                    ClassPreferenceMetric.MORNING_EVENING_DAYS,
                    PreferenceDirection.MAXIMIZE,
                ),
                (FullTimeClass.B, PreferenceRank.SECOND): (
                    ClassPreferenceMetric.CONSECUTIVE_DOUBLES,
                    PreferenceDirection.MAXIMIZE,
                ),
            },
        )
        self.assertEqual(
            set(PREFERENCE_REGRET_STAGES),
            set(PreferenceRank),
        )

    def test_pattern_and_remaining_metrics_are_complete(self) -> None:
        self.assertEqual(
            FULL_TIME_PATTERN_METRICS[FullTimeClass.A],
            (
                FairnessMetric.CONSECUTIVE_DOUBLES,
                FairnessMetric.SINGLE_SHIFT_DAYS,
                FairnessMetric.MORNING_EVENING_DAYS,
            ),
        )
        self.assertEqual(
            FULL_TIME_PATTERN_METRICS[FullTimeClass.B],
            (
                FairnessMetric.CONSECUTIVE_DOUBLES,
                FairnessMetric.SINGLE_SHIFT_DAYS,
                FairnessMetric.TRIPLE_DAYS,
            ),
        )
        self.assertEqual(
            CLASS_REMAINING_PATTERN_METRICS,
            {
                FullTimeClass.A: FairnessMetric.SINGLE_SHIFT_DAYS,
                FullTimeClass.B: FairnessMetric.TRIPLE_DAYS,
            },
        )
        expected_ratio_keys = {
            (full_time_class, metric)
            for full_time_class, metrics in FULL_TIME_PATTERN_METRICS.items()
            for metric in metrics
        }
        self.assertEqual(
            set(PREFERENCE_RATIO_MAX_STAGE_BY_METRIC),
            expected_ratio_keys,
        )

    def test_group_and_sunday_fairness_policy_is_complete(self) -> None:
        self.assertEqual(
            set(GROUP_FAIRNESS_EMPLOYMENT_TYPES),
            set(GROUP_FAIRNESS_STAGES),
        )
        self.assertEqual(
            set(GROUP_FAIRNESS_METRICS),
            set(GROUP_FAIRNESS_STAGES),
        )
        self.assertEqual(
            GROUP_FAIRNESS_EMPLOYMENT_TYPES[
                OptimizationStage.FULL_TIME_PATTERN_INTEGER_FAIRNESS
            ],
            frozenset({EmploymentType.FULL_TIME}),
        )
        common_metrics = GROUP_FAIRNESS_METRICS[
            OptimizationStage.COMMON_GROUP_FAIRNESS
        ]
        assert common_metrics is not None
        self.assertEqual(set(COMMON_GROUP_FAIRNESS_WEIGHTS), set(common_metrics))
        self.assertEqual(
            COMMON_GROUP_FAIRNESS_WEIGHTS[FairnessMetric.SUNDAY_SHIFTS],
            7,
        )
        self.assertTrue(
            all(
                weight == 3
                for metric, weight in COMMON_GROUP_FAIRNESS_WEIGHTS.items()
                if metric is not FairnessMetric.SUNDAY_SHIFTS
            )
        )
        self.assertEqual(
            SUNDAY_FAIRNESS_STAGES,
            FORMAL_OBJECTIVE_STAGES[-2:],
        )
        self.assertEqual(
            SUNDAY_FAIRNESS_METRICS,
            (
                FairnessMetric.SUNDAY_SHIFTS,
                FairnessMetric.SUNDAY_ATTENDANCE_DAYS,
            ),
        )


if __name__ == "__main__":
    unittest.main()
