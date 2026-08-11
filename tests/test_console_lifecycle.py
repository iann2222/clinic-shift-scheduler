from __future__ import annotations

import unittest
from unittest.mock import patch

from clinic_shift_scheduler.console_lifecycle import (
    pause_after_run_if_needed,
    should_pause_after_run,
)


class ConsoleLifecycleTests(unittest.TestCase):
    def test_only_standalone_frozen_windows_console_pauses(self) -> None:
        self.assertTrue(
            should_pause_after_run(
                frozen=True,
                platform_name="nt",
                console_process_count=1,
                no_pause=False,
            )
        )
        self.assertFalse(
            should_pause_after_run(
                frozen=False,
                platform_name="nt",
                console_process_count=1,
                no_pause=False,
            )
        )
        self.assertFalse(
            should_pause_after_run(
                frozen=True,
                platform_name="posix",
                console_process_count=1,
                no_pause=False,
            )
        )
        self.assertFalse(
            should_pause_after_run(
                frozen=True,
                platform_name="nt",
                console_process_count=2,
                no_pause=False,
            )
        )

    def test_no_pause_override_disables_waiting(self) -> None:
        self.assertFalse(
            should_pause_after_run(
                frozen=True,
                platform_name="nt",
                console_process_count=1,
                no_pause=True,
            )
        )

    def test_pause_prompt_is_only_read_when_needed(self) -> None:
        prompts: list[str] = []

        with patch(
            "clinic_shift_scheduler.console_lifecycle.should_pause_after_run",
            return_value=True,
        ):
            pause_after_run_if_needed(input_function=lambda prompt: prompts.append(prompt) or "")
        self.assertEqual(len(prompts), 1)
        self.assertIn("按 Enter", prompts[0])

        prompts.clear()
        with patch(
            "clinic_shift_scheduler.console_lifecycle.should_pause_after_run",
            return_value=False,
        ):
            pause_after_run_if_needed(input_function=lambda prompt: prompts.append(prompt) or "")
        self.assertEqual(prompts, [])


if __name__ == "__main__":
    unittest.main()
