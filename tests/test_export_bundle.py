from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clinic_shift_scheduler.exporters.bundle import (
    FormalExportCommitError,
    export_formal_result_bundle,
)


class FormalExportBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = SimpleNamespace(
            source=SimpleNamespace(
                period=SimpleNamespace(start_date=date(2026, 8, 1))
            )
        )
        self.output = object()

    @staticmethod
    def _writer(suffix: str, content: str):
        def write(_data, _output, *, output_directory, filename_stem, **_kwargs):
            target = Path(output_directory) / f"{filename_stem}{suffix}"
            target.write_text(content, encoding="utf-8")
            return target

        return write

    @staticmethod
    def _pdf_writer(excel_path, *, output_path=None, **_kwargs):
        target = (
            Path(output_path)
            if output_path
            else Path(excel_path).with_suffix(".pdf")
        )
        target.write_text("new-pdf", encoding="utf-8")
        return target

    def test_success_commits_complete_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_directory = Path(temporary) / "output"
            with patch(
                "clinic_shift_scheduler.exporters.bundle.export_result_json",
                side_effect=self._writer(".json", "new-json"),
            ), patch(
                "clinic_shift_scheduler.exporters.bundle.export_result_excel",
                side_effect=self._writer(".xlsx", "new-excel"),
            ), patch(
                "clinic_shift_scheduler.exporters.bundle.export_schedule_pdf_from_excel",
                side_effect=self._pdf_writer,
            ):
                result = export_formal_result_bundle(
                    self.data,
                    self.output,
                    output_directory=output_directory,
                )

            self.assertEqual(
                result.json_path.read_text(encoding="utf-8"),
                "new-json",
            )
            self.assertEqual(
                result.excel_path.read_text(encoding="utf-8"),
                "new-excel",
            )
            self.assertEqual(result.pdf_path.read_text(encoding="utf-8"), "new-pdf")
            self.assertEqual(
                tuple(output_directory.glob(".排班結果_*.staging-*")),
                (),
            )

    def test_generation_failure_leaves_no_partial_new_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_directory = Path(temporary) / "output"

            def fail_pdf(*_args, **_kwargs):
                raise RuntimeError("pdf failed")

            with patch(
                "clinic_shift_scheduler.exporters.bundle.export_result_json",
                side_effect=self._writer(".json", "new-json"),
            ), patch(
                "clinic_shift_scheduler.exporters.bundle.export_result_excel",
                side_effect=self._writer(".xlsx", "new-excel"),
            ), patch(
                "clinic_shift_scheduler.exporters.bundle.export_schedule_pdf_from_excel",
                side_effect=fail_pdf,
            ):
                with self.assertRaisesRegex(
                    FormalExportCommitError,
                    "pdf failed",
                ):
                    export_formal_result_bundle(
                        self.data,
                        self.output,
                        output_directory=output_directory,
                    )

            self.assertEqual(tuple(output_directory.glob("排班結果_*")), ())

    def test_generation_failure_preserves_existing_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_directory = Path(temporary) / "output"
            output_directory.mkdir()
            stem = "排班結果_2026-08.result-v1"
            existing = {
                suffix: output_directory / f"{stem}{suffix}"
                for suffix in (".json", ".xlsx", ".pdf")
            }
            for suffix, path in existing.items():
                path.write_text(f"old{suffix}", encoding="utf-8")

            def fail_pdf(*_args, **_kwargs):
                raise RuntimeError("pdf failed")

            with patch(
                "clinic_shift_scheduler.exporters.bundle.export_result_json",
                side_effect=self._writer(".json", "new-json"),
            ), patch(
                "clinic_shift_scheduler.exporters.bundle.export_result_excel",
                side_effect=self._writer(".xlsx", "new-excel"),
            ), patch(
                "clinic_shift_scheduler.exporters.bundle.export_schedule_pdf_from_excel",
                side_effect=fail_pdf,
            ):
                with self.assertRaisesRegex(
                    FormalExportCommitError,
                    "pdf failed",
                ):
                    export_formal_result_bundle(
                        self.data,
                        self.output,
                        output_directory=output_directory,
                        overwrite=True,
                    )

            for suffix, path in existing.items():
                self.assertEqual(path.read_text(encoding="utf-8"), f"old{suffix}")

    def test_commit_failure_rolls_back_every_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_directory = Path(temporary) / "output"
            output_directory.mkdir()
            stem = "排班結果_2026-08.result-v1"
            existing = {
                suffix: output_directory / f"{stem}{suffix}"
                for suffix in (".json", ".xlsx", ".pdf")
            }
            for suffix, path in existing.items():
                path.write_text(f"old{suffix}", encoding="utf-8")
            real_replace = os.replace

            failed = False

            def fail_second_commit(source, target):
                nonlocal failed
                source_path = Path(source)
                target_path = Path(target)
                if (
                    not failed
                    and source_path.suffix == ".xlsx"
                    and target_path.parent == output_directory
                ):
                    failed = True
                    raise OSError("commit failed")
                real_replace(source, target)

            with patch(
                "clinic_shift_scheduler.exporters.bundle.export_result_json",
                side_effect=self._writer(".json", "new-json"),
            ), patch(
                "clinic_shift_scheduler.exporters.bundle.export_result_excel",
                side_effect=self._writer(".xlsx", "new-excel"),
            ), patch(
                "clinic_shift_scheduler.exporters.bundle.export_schedule_pdf_from_excel",
                side_effect=self._pdf_writer,
            ), patch(
                "clinic_shift_scheduler.exporters.bundle.os.replace",
                side_effect=fail_second_commit,
            ):
                with self.assertRaisesRegex(
                    FormalExportCommitError,
                    "commit failed",
                ):
                    export_formal_result_bundle(
                        self.data,
                        self.output,
                        output_directory=output_directory,
                        overwrite=True,
                    )

            for suffix, path in existing.items():
                self.assertEqual(path.read_text(encoding="utf-8"), f"old{suffix}")


if __name__ == "__main__":
    unittest.main()
