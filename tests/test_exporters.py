from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from clinic_shift_scheduler import (
    ExportFileExistsError,
    FeasibilityStatus,
    FormalExportError,
    RESULT_CONTRACT_NAME,
    RESULT_CONTRACT_VERSION,
    build_output_paths,
    build_result_document,
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
        self.assertEqual(len(document["stage_records"]), 10)
        self.assertEqual(len(document["assignments"]), 5)
        self.assertIn("individual", document["statistics"])
        self.assertIn("fairness_groups", document["statistics"])
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


if __name__ == "__main__":
    unittest.main()
