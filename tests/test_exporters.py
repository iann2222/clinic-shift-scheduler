from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import load_workbook

from clinic_shift_scheduler import (
    ExportFileExistsError,
    FeasibilityStatus,
    FormalExportError,
    RESULT_CONTRACT_NAME,
    RESULT_CONTRACT_VERSION,
    WORKSHEET_NAMES,
    build_output_paths,
    build_result_document,
    build_workbook,
    export_result_excel,
    export_result_json,
    finalize_schedule_output,
    solve_lexicographic,
    validate_and_normalize,
)

from tests.fixtures import minimal_valid_input


class JsonExporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = validate_and_normalize(minimal_valid_input())
        cls.result = solve_lexicographic(cls.data)
        cls.output = finalize_schedule_output(cls.data, cls.result)
        assert cls.output.status is FeasibilityStatus.OPTIMAL

    def test_output_paths_use_stable_month_and_contract_version(self) -> None:
        paths = build_output_paths(self.data)

        self.assertEqual(paths.directory, Path("output"))
        self.assertEqual(paths.stem, "排班結果_2024-10.result-v1")
        self.assertEqual(paths.json, Path("output/排班結果_2024-10.result-v1.json"))
        self.assertEqual(paths.excel, Path("output/排班結果_2024-10.result-v1.xlsx"))

    def test_result_document_contains_the_versioned_formal_contract(self) -> None:
        generated_at = datetime(2024, 10, 2, 3, 4, 5, tzinfo=UTC)
        document = build_result_document(
            self.data,
            self.output,
            generated_at=generated_at,
        )

        self.assertEqual(
            document["contract"],
            {"name": RESULT_CONTRACT_NAME, "version": RESULT_CONTRACT_VERSION},
        )
        self.assertEqual(RESULT_CONTRACT_VERSION, "1.2")
        self.assertEqual(document["input_schema_version"], "v1")
        self.assertEqual(document["generated_at"], "2024-10-02T03:04:05Z")
        self.assertEqual(document["month"], "2024-10")
        self.assertEqual(document["status"], "OPTIMAL")
        self.assertEqual(document["validation"]["status"], "PASS")
        self.assertNotIn("recomputed", document["validation"])
        self.assertEqual(
            document["objective_vector"],
            document["statistics"]["overall"]["objective_vector"],
        )
        self.assertEqual(len(document["stage_records"]), 13)
        self.assertEqual(len(document["assignments"]), 5)
        self.assertIn("individual", document["statistics"])
        self.assertIn("fairness_groups", document["statistics"])
        self.assertIn("full_time_class_quality", document["statistics"])
        self.assertEqual(
            len(document["statistics"]["full_time_class_quality"]), 2
        )
        self.assertIn(
            "class_quality_ratio_gaps_basis_points",
            document["statistics"]["overall"],
        )
        full_time_group = next(
            item
            for item in document["statistics"]["fairness_groups"]
            if item["employment_type"] == "full_time"
        )
        self.assertIn("ratio_basis_points", full_time_group)
        self.assertIn("ratio_gaps_basis_points", full_time_group)
        self.assertIn("rows", document["monthly_schedule"])

    def test_naive_generation_timestamp_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_result_document(
                self.data,
                self.output,
                generated_at=datetime(2024, 10, 2, 3, 4, 5),
            )

    def test_invalid_or_incomplete_result_cannot_be_formally_exported(self) -> None:
        invalid_output = replace(
            self.output,
            status=FeasibilityStatus.VALIDATION_FAILED,
            monthly_schedule=None,
        )

        with self.assertRaises(FormalExportError):
            build_result_document(self.data, invalid_output)

    def test_json_write_is_utf8_atomic_and_refuses_implicit_overwrite(self) -> None:
        generated_at = datetime(2024, 10, 2, 3, 4, 5, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            target = export_result_json(
                self.data,
                self.output,
                output_directory=directory,
                generated_at=generated_at,
            )
            document = json.loads(target.read_text(encoding="utf-8"))

            self.assertEqual(target.name, "排班結果_2024-10.result-v1.json")
            self.assertEqual(document["status"], "OPTIMAL")
            self.assertTrue(target.read_bytes().endswith(b"\n"))
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
            with self.assertRaises(ExportFileExistsError):
                export_result_json(
                    self.data,
                    self.output,
                    output_directory=directory,
                    generated_at=generated_at,
                )

            replaced = export_result_json(
                self.data,
                self.output,
                output_directory=directory,
                overwrite=True,
                generated_at=generated_at,
            )
            self.assertEqual(replaced, target)


class ExcelExporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = validate_and_normalize(minimal_valid_input())
        cls.result = solve_lexicographic(cls.data)
        cls.output = finalize_schedule_output(cls.data, cls.result)
        assert cls.output.status is FeasibilityStatus.OPTIMAL

    def test_workbook_has_expected_sheets_and_horizontal_schedule(self) -> None:
        workbook = build_workbook(self.data, self.output)
        try:
            self.assertEqual(tuple(workbook.sheetnames), WORKSHEET_NAMES)
            sheet = workbook["月班表"]
            schedule = self.output.monthly_schedule
            self.assertEqual(sheet["A1"].value, "日期")
            self.assertEqual(sheet["A2"].value, "星期")
            self.assertEqual(sheet["B1"].value, schedule.dates[0])
            self.assertEqual(sheet["B2"].value, "二")
            self.assertEqual(sheet["A3"].value, "早上櫃台")
            self.assertEqual(sheet["B3"].value, schedule.rows[0].cells[0].display)
            self.assertEqual(sheet.freeze_panes, "B3")
            self.assertEqual(sheet["B1"].number_format, "m/d")
        finally:
            workbook.close()

    def test_statistics_and_solver_sheets_use_formal_output_values(self) -> None:
        workbook = build_workbook(self.data, self.output)
        try:
            individual = workbook["個人統計"]
            headers = {
                cell.value: cell.column
                for cell in individual[1]
                if cell.value is not None
            }
            first = self.output.individual_statistics[0]
            self.assertEqual(individual.cell(2, headers["employee_id"]).value, first.employee_id)
            self.assertEqual(individual.cell(2, headers["姓名"]).value, first.name)
            self.assertEqual(individual.cell(2, headers["總班次"]).value, first.total_shifts)

            groups = workbook["群組統計"]
            self.assertEqual(groups["A1"].value, "類別統計")
            self.assertEqual(groups["A2"].value, "類別")
            self.assertEqual(groups["A3"].value, self.output.category_statistics[0].category)
            self.assertTrue(
                any(
                    isinstance(groups.cell(row, 4).value, str)
                    and "比例 (bp)" in groups.cell(row, 4).value
                    for row in range(1, groups.max_row + 1)
                )
            )
            self.assertTrue(
                any(
                    groups.cell(row, 1).value == "A／B 類別品質順位比例"
                    for row in range(1, groups.max_row + 1)
                )
            )

            solver = workbook["求解資訊"]
            self.assertEqual(solver["A1"].value, "正式結果")
            self.assertEqual(solver["B4"].value, self.output.status.value)
            values = {
                solver.cell(row, 1).value: solver.cell(row, 2).value
                for row in range(1, solver.max_row + 1)
            }
            self.assertEqual(values["Validation"], "PASS")
            self.assertEqual(
                values["full_time_target_deviation"],
                self.output.overall_statistics.objective_vector[
                    "full_time_target_deviation"
                ],
            )
        finally:
            workbook.close()

    def test_closed_date_cells_are_visually_distinct(self) -> None:
        payload = minimal_valid_input()
        payload["period"]["end_date"] = "2024-10-02"
        payload["period"]["closed_dates"] = ["2024-10-02"]
        data = validate_and_normalize(payload)
        output = finalize_schedule_output(data, solve_lexicographic(data))
        workbook = build_workbook(data, output)
        try:
            sheet = workbook["月班表"]
            self.assertEqual(sheet["C3"].value, "休診")
            self.assertEqual(sheet["C3"].fill.fgColor.rgb[-6:], "D9D9D9")
            self.assertNotEqual(
                sheet["B3"].fill.fgColor.rgb,
                sheet["C3"].fill.fgColor.rgb,
            )
        finally:
            workbook.close()

    def test_excel_write_reopens_and_refuses_implicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = export_result_excel(
                self.data,
                self.output,
                output_directory=directory,
            )
            reopened = load_workbook(target, read_only=False, data_only=False)
            try:
                self.assertEqual(tuple(reopened.sheetnames), WORKSHEET_NAMES)
                self.assertEqual(reopened["月班表"]["A1"].value, "日期")
                self.assertEqual(reopened["月班表"].freeze_panes, "B3")
            finally:
                reopened.close()
            self.assertEqual(target.name, "排班結果_2024-10.result-v1.xlsx")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
            with self.assertRaises(ExportFileExistsError):
                export_result_excel(
                    self.data,
                    self.output,
                    output_directory=directory,
                )
            self.assertEqual(
                export_result_excel(
                    self.data,
                    self.output,
                    output_directory=directory,
                    overwrite=True,
                ),
                target,
            )

    def test_invalid_result_cannot_be_exported_to_excel(self) -> None:
        invalid_output = replace(
            self.output,
            status=FeasibilityStatus.VALIDATION_FAILED,
            monthly_schedule=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FormalExportError):
                export_result_excel(
                    self.data,
                    invalid_output,
                    output_directory=directory,
                )
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
