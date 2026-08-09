from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from clinic_shift_scheduler import (
    InputValidationError,
    expand_weekly_template,
    solve_lexicographic,
    validate_and_normalize_weekly,
)


EXAMPLE = (
    Path(__file__).parents[1]
    / "排班資料"
    / "匿名範本"
    / "排班輸入_匿名_2026-08.weekly-v1.json"
)


def load_example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class WeeklyAuthoringTests(unittest.TestCase):
    def assert_invalid(self, payload: dict, code: str) -> None:
        with self.assertRaises(InputValidationError) as caught:
            expand_weekly_template(payload)
        self.assertIn(code, {issue.code for issue in caught.exception.issues})

    def test_anonymous_example_expands_to_complete_canonical_v1(self) -> None:
        expanded = expand_weekly_template(load_example())
        normalized = validate_and_normalize_weekly(load_example())

        self.assertNotIn("authoring_version", expanded)
        self.assertNotIn("weekly_demands", expanded)
        self.assertEqual(expanded["period"]["closed_weekdays"], ["saturday"])
        self.assertEqual(len(expanded["demands"]), 156)
        self.assertEqual(sum(item["count"] for item in expanded["demands"]), 161)
        self.assertEqual(len(normalized.open_dates), 26)
        self.assertEqual({employee.name for employee in normalized.employees.values()}, {
            "甲", "乙", "丙", "丁", "戊", "己"
        })

    def test_anonymous_example_runs_through_phase_four(self) -> None:
        normalized = validate_and_normalize_weekly(load_example())
        result = solve_lexicographic(normalized)

        self.assertTrue(result.is_feasible)
        self.assertEqual(len(result.assignments), 161)
        self.assertEqual(result.part_time_total, 8)

    def test_closed_date_override_removes_that_days_demands(self) -> None:
        payload = load_example()
        payload["date_overrides"] = [
            {"date": "2026-08-03", "is_open": False}
        ]

        expanded = expand_weekly_template(payload)

        self.assertEqual(expanded["period"]["closed_dates"], ["2026-08-03"])
        self.assertEqual(len(expanded["demands"]), 150)
        self.assertEqual(sum(item["count"] for item in expanded["demands"]), 155)

    def test_open_date_override_replaces_full_daily_staffing(self) -> None:
        payload = load_example()
        staffing = deepcopy(payload["weekly_demands"][0]["staffing"])
        staffing["morning"]["nursing"] = 2
        payload["date_overrides"] = [
            {"date": "2026-08-03", "is_open": True, "staffing": staffing}
        ]

        expanded = expand_weekly_template(payload)

        target = next(
            item
            for item in expanded["demands"]
            if item["date"] == "2026-08-03"
            and item["period"] == "morning"
            and item["role"] == "nursing"
        )
        self.assertEqual(target["count"], 2)
        self.assertEqual(sum(item["count"] for item in expanded["demands"]), 162)

    def test_every_weekday_must_be_defined_exactly_once(self) -> None:
        missing = load_example()
        missing["weekly_demands"].pop()
        self.assert_invalid(missing, "incomplete_weekdays")

        duplicate = load_example()
        duplicate["weekly_demands"][1]["weekdays"] = ["monday"]
        self.assert_invalid(duplicate, "duplicate_weekday")

    def test_open_template_requires_all_periods_and_roles(self) -> None:
        payload = load_example()
        del payload["weekly_demands"][0]["staffing"]["morning"]["nursing"]

        self.assert_invalid(payload, "incomplete_weekly_staffing")

    def test_closed_template_rejects_staffing_and_closed_weekday_cannot_reopen(self) -> None:
        closed_with_staffing = load_example()
        closed_with_staffing["weekly_demands"][1]["staffing"] = deepcopy(
            closed_with_staffing["weekly_demands"][0]["staffing"]
        )
        self.assert_invalid(closed_with_staffing, "closed_with_staffing")

        reopen = load_example()
        reopen["date_overrides"] = [
            {
                "date": "2026-08-01",
                "is_open": True,
                "staffing": deepcopy(reopen["weekly_demands"][0]["staffing"]),
            }
        ]
        self.assert_invalid(reopen, "unsupported_open_override")


if __name__ == "__main__":
    unittest.main()
