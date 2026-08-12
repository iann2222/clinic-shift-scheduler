from __future__ import annotations

import os
import unittest
from datetime import date
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from clinic_shift_scheduler.authoring_application import AuthoringApplication
from clinic_shift_scheduler.enums import Period
from clinic_shift_scheduler.gui.models import (
    DateOverrideTableModel,
    WeeklyDemandTableModel,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WEEKLY_EXAMPLE = (
    REPOSITORY_ROOT
    / "input"
    / "匿名範本"
    / "排班輸入_匿名_2026-08.json"
)


class WeeklyDemandTableModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.application = AuthoringApplication()

    def test_model_uses_three_period_rows_and_dynamic_role_columns(self) -> None:
        draft = self.application.open_document(WEEKLY_EXAMPLE).draft
        model = WeeklyDemandTableModel(draft)

        self.assertEqual(model.rowCount(), len(draft.weekly_demands) * 3)
        self.assertEqual(model.columnCount(), 3 + len(draft.roles))
        self.assertEqual(
            model.headerData(3, Qt.Orientation.Horizontal),
            draft.roles[0],
        )
        self.assertEqual(model.data(model.index(0, 0)), "平日")
        self.assertEqual(model.data(model.index(0, 2)), "早上")

    def test_closed_group_can_be_opened_with_explicit_zero_demands(self) -> None:
        draft = self.application.open_document(WEEKLY_EXAMPLE).draft
        saturday_index = next(
            index
            for index, rule in enumerate(draft.weekly_demands)
            if not rule.is_open
        )
        model = WeeklyDemandTableModel(draft)
        changed: list[bool] = []
        model.draft_changed.connect(lambda: changed.append(True))
        row = saturday_index * 3

        self.assertTrue(
            model.setData(
                model.index(row, 1),
                Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )
        )

        rule = draft.weekly_demands[saturday_index]
        self.assertTrue(rule.is_open)
        self.assertIsNotNone(rule.staffing)
        assert rule.staffing is not None
        for period in draft.periods:
            self.assertEqual(
                rule.staffing.counts[period],
                {role: 0 for role in draft.roles},
            )
        self.assertTrue(changed)

    def test_role_count_edit_updates_only_selected_period_and_role(self) -> None:
        draft = self.application.open_document(WEEKLY_EXAMPLE).draft
        model = WeeklyDemandTableModel(draft)
        rule_index = next(
            index
            for index, rule in enumerate(draft.weekly_demands)
            if rule.is_open
        )
        row = rule_index * 3 + 1
        role_column = 3

        self.assertTrue(model.setData(model.index(row, role_column), 4))

        rule = draft.weekly_demands[rule_index]
        assert rule.staffing is not None
        self.assertEqual(
            rule.staffing.counts[Period.AFTERNOON][draft.roles[0]],
            4,
        )
        self.assertFalse(model.setData(model.index(row, role_column), -1))
        self.assertFalse(model.setData(model.index(row, role_column), "wrong"))

    def test_closed_role_cells_are_disabled_and_not_editable(self) -> None:
        draft = self.application.open_document(WEEKLY_EXAMPLE).draft
        model = WeeklyDemandTableModel(draft)
        closed_index = next(
            index
            for index, rule in enumerate(draft.weekly_demands)
            if not rule.is_open
        )
        index = model.index(closed_index * 3, 3)

        flags = model.flags(index)
        self.assertFalse(flags & Qt.ItemFlag.ItemIsEnabled)
        self.assertFalse(flags & Qt.ItemFlag.ItemIsEditable)
        self.assertFalse(model.setData(index, 1))


class DateOverrideTableModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.application = AuthoringApplication()

    def test_add_open_override_creates_three_editable_period_rows(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        session.draft.date_overrides = []
        model = DateOverrideTableModel(session.draft)

        model.add_override(date(2026, 8, 15), is_open=True)

        self.assertEqual(model.rowCount(), 3)
        self.assertEqual(model.data(model.index(0, 0)), "2026-08-15")
        self.assertEqual(model.data(model.index(0, 1)), "開診")
        self.assertTrue(
            model.flags(model.index(0, 3)) & Qt.ItemFlag.ItemIsEditable
        )
        self.assertTrue(model.setData(model.index(2, 3), 2))
        self.assertEqual(
            session.draft.date_overrides[0]
            .staffing.counts[Period.EVENING][session.draft.roles[0]],
            2,
        )

    def test_closed_override_has_no_staffing_and_can_be_removed_by_any_row(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        session.draft.date_overrides = []
        model = DateOverrideTableModel(session.draft)
        model.add_override(date(2026, 8, 15), is_open=False)

        self.assertIsNone(session.draft.date_overrides[0].staffing)
        self.assertFalse(
            model.flags(model.index(1, 3)) & Qt.ItemFlag.ItemIsEnabled
        )

        model.remove_override_at(2)
        self.assertEqual(model.rowCount(), 0)
        self.assertEqual(session.draft.date_overrides, [])

    def test_duplicate_and_out_of_month_overrides_are_rejected(self) -> None:
        session = self.application.open_document(WEEKLY_EXAMPLE)
        session.draft.date_overrides = []
        model = DateOverrideTableModel(session.draft)
        model.add_override(date(2026, 8, 15), is_open=False)

        with self.assertRaisesRegex(ValueError, "已有調整"):
            model.add_override(date(2026, 8, 15), is_open=True)
        with self.assertRaisesRegex(ValueError, "排班月份內"):
            model.add_override(date(2026, 9, 1), is_open=False)


if __name__ == "__main__":
    unittest.main()
