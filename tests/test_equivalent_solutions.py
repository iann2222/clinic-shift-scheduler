from __future__ import annotations

import unittest
from unittest.mock import patch

import clinic_shift_scheduler.optimization as optimization
from clinic_shift_scheduler import (
    EquivalentSolutionDiagnosticConfig,
    EquivalentSolutionDiagnosticStatus,
    diagnose_equivalent_solutions,
    solve_lexicographic,
    validate_and_normalize,
)

from tests.fixtures import synthetic_schedule_input


def _a_employee(employee_id: str, required_shifts: int) -> dict:
    return {
        "employee_id": employee_id,
        "name": employee_id,
        "employment_type": "full_time",
        "full_time_class": "A",
        "roles": ["assistant"],
        "fairness_group": "A_TEST",
        "shift_mode": "EXACT",
        "required_shifts": required_shifts,
    }


class EquivalentSolutionDiagnosticTests(unittest.TestCase):
    def _two_assignment_result(self):
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-01",
            roles=["assistant"],
            employees=[_a_employee("A1", 1), _a_employee("A2", 1)],
            positive_demands={
                ("2024-10-01", "morning", "assistant"): 1,
                ("2024-10-01", "afternoon", "assistant"): 1,
            },
        )
        return solve_lexicographic(validate_and_normalize(payload))

    def test_exact_count_excludes_the_formal_assignment(self) -> None:
        result = self._two_assignment_result()

        diagnostic = diagnose_equivalent_solutions(
            result,
            EquivalentSolutionDiagnosticConfig(
                max_alternatives=100,
                max_time_seconds=30,
            ),
        )

        self.assertIs(
            diagnostic.status,
            EquivalentSolutionDiagnosticStatus.EXACT_COUNT,
        )
        self.assertEqual(diagnostic.alternative_count, 1)
        self.assertTrue(diagnostic.is_exact)

        repeated = diagnose_equivalent_solutions(
            result,
            EquivalentSolutionDiagnosticConfig(max_time_seconds=30),
        )
        self.assertIs(
            repeated.status,
            EquivalentSolutionDiagnosticStatus.EXACT_COUNT,
        )
        self.assertEqual(repeated.alternative_count, 1)

    def test_stops_at_bound_without_claiming_exact_count(self) -> None:
        payload = synthetic_schedule_input(
            start_date="2024-10-01",
            end_date="2024-10-03",
            roles=["assistant"],
            employees=[
                _a_employee("A1", 1),
                _a_employee("A2", 1),
                _a_employee("A3", 1),
            ],
            positive_demands={
                (day, "morning", "assistant"): 1
                for day in (
                    "2024-10-01",
                    "2024-10-02",
                    "2024-10-03",
                )
            },
        )
        result = solve_lexicographic(validate_and_normalize(payload))

        diagnostic = diagnose_equivalent_solutions(
            result,
            EquivalentSolutionDiagnosticConfig(
                max_alternatives=2,
                max_time_seconds=30,
            ),
        )

        self.assertIs(
            diagnostic.status,
            EquivalentSolutionDiagnosticStatus.AT_LEAST_LIMIT,
        )
        self.assertEqual(diagnostic.alternative_count, 2)
        self.assertFalse(diagnostic.is_exact)

    def test_time_limit_reports_only_a_lower_bound(self) -> None:
        result = self._two_assignment_result()
        with patch.object(
            optimization,
            "perf_counter",
            side_effect=(0.0, 31.0, 31.0),
        ):
            diagnostic = diagnose_equivalent_solutions(
                result,
                EquivalentSolutionDiagnosticConfig(
                    max_alternatives=100,
                    max_time_seconds=30,
                ),
            )

        self.assertIs(
            diagnostic.status,
            EquivalentSolutionDiagnosticStatus.TIME_LIMIT,
        )
        self.assertEqual(diagnostic.alternative_count, 0)

    def test_keyboard_interrupt_preserves_partial_diagnostic(self) -> None:
        result = self._two_assignment_result()
        with patch.object(
            optimization.cp_model.CpSolver,
            "solve",
            side_effect=KeyboardInterrupt,
        ):
            diagnostic = diagnose_equivalent_solutions(result)

        self.assertIs(
            diagnostic.status,
            EquivalentSolutionDiagnosticStatus.INTERRUPTED,
        )
        self.assertEqual(diagnostic.alternative_count, 0)

    def test_config_rejects_nonpositive_limits(self) -> None:
        with self.assertRaises(ValueError):
            EquivalentSolutionDiagnosticConfig(max_alternatives=0)
        with self.assertRaises(ValueError):
            EquivalentSolutionDiagnosticConfig(max_time_seconds=0)


if __name__ == "__main__":
    unittest.main()
