from __future__ import annotations

import subprocess
import sys
import unittest


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_frontend_contract_imports_do_not_load_native_or_output_dependencies(
        self,
    ) -> None:
        script = """
import sys
import clinic_shift_scheduler
from clinic_shift_scheduler import (
    CancellationToken,
    ScheduleApplicationRequest,
    SchedulerConfigDocument,
    WeeklyAuthoringDocument,
)
import clinic_shift_scheduler.output
import clinic_shift_scheduler.result_metrics
import clinic_shift_scheduler.result_validation
blocked = [name for name in ('ortools', 'openpyxl', 'reportlab') if name in sys.modules]
if blocked:
    raise SystemExit('unexpected eager imports: ' + ', '.join(blocked))
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)


if __name__ == "__main__":
    unittest.main()
