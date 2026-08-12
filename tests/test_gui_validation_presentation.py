from __future__ import annotations

import unittest

from clinic_shift_scheduler.events import DiagnosticIssue
from clinic_shift_scheduler.gui.validation_presentation import (
    format_validation_issue,
    humanize_issue_path,
)


class GuiValidationPresentationTests(unittest.TestCase):
    def test_employee_path_is_converted_to_one_based_human_label(self) -> None:
        self.assertEqual(
            humanize_issue_path("$.employees[2].available_slots[4].roles"),
            "員工資料第 3 筆／兼職可排時段第 5 筆／職務資格",
        )

    def test_known_issue_uses_chinese_message_without_losing_raw_issue(self) -> None:
        issue = DiagnosticIssue(
            code="unsupported_part_time_target",
            path="$.employees[1].shift_mode",
            message="part-time v1 supports only EXACT or RANGE",
        )

        rendered = format_validation_issue(issue)

        self.assertIn("班次模式", rendered)
        self.assertIn("兼職人員只支援", rendered)
        self.assertEqual(issue.message, "part-time v1 supports only EXACT or RANGE")


if __name__ == "__main__":
    unittest.main()
