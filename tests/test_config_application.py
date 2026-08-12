from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from clinic_shift_scheduler.config_application import ConfigApplication
from clinic_shift_scheduler.errors import InputValidationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ConfigApplicationTests(unittest.TestCase):
    def test_load_edit_atomic_save_and_reopen_preserve_contract(self) -> None:
        source = REPOSITORY_ROOT / "config.json"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.json"
            target.write_bytes(source.read_bytes())
            application = ConfigApplication()
            session = application.open_document(target)

            self.assertFalse(session.is_dirty)
            session.draft.input_file = "排班輸入_2026-09.json"
            session.draft.progress_update_seconds = 7.5
            session.draft.diagnostic_time_mode = "定值"
            session.draft.diagnostic_fixed_seconds = 45.0
            self.assertTrue(session.is_dirty)

            application.save(session)
            self.assertFalse(session.is_dirty)
            reopened = application.open_document(target)
            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(reopened.draft.input_file, "排班輸入_2026-09.json")
        self.assertEqual(reopened.draft.progress_update_seconds, 7.5)
        self.assertEqual(reopened.draft.diagnostic_time_mode, "定值")
        self.assertEqual(reopened.draft.diagnostic_fixed_seconds, 45.0)
        self.assertIn("__檔案說明__", payload)
        self.assertIn(
            "__模式選項說明__",
            payload["使用者設定"]["候選診斷"]["診斷時間上限"],
        )
        self.assertEqual(
            payload["預設設定"]["進度更新秒數"],
            5,
        )

    def test_invalid_draft_does_not_overwrite_existing_config(self) -> None:
        source = REPOSITORY_ROOT / "config.json"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.json"
            target.write_bytes(source.read_bytes())
            original = target.read_bytes()
            application = ConfigApplication()
            session = application.open_document(target)
            session.draft.candidate_export_count = (
                session.draft.candidate_search_limit + 1
            )

            with self.assertRaises(InputValidationError):
                application.save(session)

            self.assertEqual(target.read_bytes(), original)
            self.assertTrue(session.is_dirty)

    def test_restore_defaults_only_changes_user_draft(self) -> None:
        source = REPOSITORY_ROOT / "config.json"
        application = ConfigApplication()
        session = application.open_document(source)
        original_default = session.document.default_config
        session.draft.progress_update_seconds = 99

        session.restore_defaults()

        self.assertEqual(
            session.draft.progress_update_seconds,
            original_default.progress_update_seconds,
        )
        self.assertEqual(session.document.default_config, original_default)


if __name__ == "__main__":
    unittest.main()
