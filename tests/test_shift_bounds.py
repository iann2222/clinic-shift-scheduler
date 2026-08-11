from __future__ import annotations

import unittest

from clinic_shift_scheduler.shift_bounds import (
    hard_maximum_within_capacity,
    hard_minimum_shifts,
)
from clinic_shift_scheduler.validation import validate_and_normalize

from tests.fixtures import minimal_valid_input


class ShiftBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = validate_and_normalize(minimal_valid_input())

    def test_exact_count_is_both_minimum_and_capacity_limit(self) -> None:
        employee = self.data.employees["FT001"]

        self.assertEqual(hard_minimum_shifts(employee), 2)
        self.assertEqual(hard_maximum_within_capacity(employee, 5), 2)
        self.assertEqual(hard_maximum_within_capacity(employee, 1), 1)

    def test_target_without_explicit_bounds_only_uses_physical_capacity(self) -> None:
        employee = self.data.employees["FT002"]

        self.assertEqual(hard_minimum_shifts(employee), 0)
        self.assertEqual(hard_maximum_within_capacity(employee, 4), 4)

    def test_range_applies_explicit_minimum_and_maximum(self) -> None:
        employee = self.data.employees["PT001"]

        self.assertEqual(hard_minimum_shifts(employee), 0)
        self.assertEqual(hard_maximum_within_capacity(employee, 5), 2)


if __name__ == "__main__":
    unittest.main()
