from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from clinic_shift_scheduler.run_lock import (
    ScheduleRunLockUnavailableError,
    schedule_run_lock,
)


class ScheduleRunLockTests(unittest.TestCase):
    def test_other_process_cannot_lock_same_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_directory = root / "output"
            ready = root / "ready"
            script = """
import sys
import time
from pathlib import Path
from clinic_shift_scheduler.run_lock import schedule_run_lock

with schedule_run_lock(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text("ready", encoding="utf-8")
    time.sleep(30)
"""
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(output_directory),
                    str(ready),
                ]
            )
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), "lock holder did not start")

                with self.assertRaises(ScheduleRunLockUnavailableError):
                    with schedule_run_lock(output_directory):
                        self.fail("the same output directory was locked twice")
            finally:
                self._stop_process(process)

            with schedule_run_lock(output_directory):
                pass

    def test_exception_releases_lock_for_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_directory = Path(temporary) / "output"
            with self.assertRaisesRegex(RuntimeError, "run failed"):
                with schedule_run_lock(output_directory):
                    raise RuntimeError("run failed")

            with schedule_run_lock(output_directory) as acquired:
                self.assertTrue(acquired.path.is_file())

    def test_different_output_directories_do_not_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with schedule_run_lock(root / "first"):
                with schedule_run_lock(root / "second"):
                    pass

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
