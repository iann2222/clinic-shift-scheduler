from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from clinic_shift_scheduler.application_paths import application_root


class ApplicationPathTests(unittest.TestCase):
    def test_source_execution_uses_repository_root_above_src(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "src" / "run_scheduler.py"

            self.assertEqual(
                application_root(entry, frozen=False),
                root.resolve(),
            )

    def test_frozen_execution_uses_executable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "ClinicShiftScheduler"
            executable = release / "ClinicShiftScheduler.exe"

            self.assertEqual(
                application_root(
                    "ignored.py",
                    frozen=True,
                    executable=executable,
                ),
                release.resolve(),
            )


if __name__ == "__main__":
    unittest.main()
