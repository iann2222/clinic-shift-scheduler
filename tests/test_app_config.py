from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from clinic_shift_scheduler import (
    APP_CONFIG_VERSION,
    load_scheduler_config,
    parse_scheduler_config,
)
from clinic_shift_scheduler.app_config import (
    default_scheduler_config,
    scheduler_config_to_user_settings,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _config(user_settings: dict) -> dict:
    return {
        "__使用者設定分隔線__": "===== 使用者設定 =====",
        "使用者設定": user_settings,
        "__預設設定分隔線__": "===== 預設設定 =====",
        "預設設定": {
            "設定版本": APP_CONFIG_VERSION,
            "輸入檔名": "排班輸入_2026-08.json",
        },
    }


class SchedulerAppConfigTests(unittest.TestCase):
    def test_repository_default_settings_come_from_typed_defaults(self) -> None:
        payload = json.loads(
            (REPOSITORY_ROOT / "config.json").read_text(encoding="utf-8")
        )
        expected = scheduler_config_to_user_settings(
            default_scheduler_config("排班輸入_2026-08.json")
        )

        self.assertEqual(payload["預設設定"], expected)
        self.assertEqual(
            payload["使用者設定"]["候選診斷"][
                "額外輸出候選班表份數上限"
            ],
            3,
        )

    def test_typed_settings_round_trip_through_user_json(self) -> None:
        original = default_scheduler_config("排班輸入_2026-09.json")
        payload = _config(scheduler_config_to_user_settings(original))

        self.assertEqual(parse_scheduler_config(payload), original)

    def test_loads_complete_user_config(self) -> None:
        payload = _config({
            "設定版本": APP_CONFIG_VERSION,
            "輸入檔名": "排班輸入_2026-08.json",
            "覆寫既有結果": True,
            "進度更新秒數": 5,
            "當前最佳班表輸出": {
                "輸出格式": ["JSON", "PDF"],
            },
            "候選診斷": {
                "啟用": True,
                "搜尋上限": 100,
                "診斷時間上限": {"模式": "定值", "秒數": 30},
                "額外輸出候選班表份數上限": 3,
                "輸出格式": ["JSON", "Excel", "PDF"],
            },
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            config = load_scheduler_config(path)

        self.assertEqual(config.input_file, "排班輸入_2026-08.json")
        self.assertEqual(config.progress_update_seconds, 5)
        self.assertEqual(
            config.preservation_output.export_formats,
            ("json", "pdf"),
        )
        self.assertEqual(config.candidate_diagnostic.time.mode, "定值")
        self.assertEqual(config.candidate_diagnostic.time.fixed_seconds, 30)
        self.assertEqual(config.candidate_diagnostic.export_count, 3)
        self.assertEqual(
            config.candidate_diagnostic.export_formats,
            ("json", "excel", "pdf"),
        )

    def test_accepts_human_readable_mode_descriptions(self) -> None:
        config = parse_scheduler_config(
            _config({
                "輸入檔名": "排班輸入_2026-08.json",
                "候選診斷": {
                    "診斷時間上限": {
                        "模式": "比例",
                        "__模式選項說明__": {
                            "比例": "依排班時間比例計算",
                            "定值": "使用固定秒數",
                        },
                        "排班時間比例": 0.2,
                    }
                },
            })
        )

        self.assertEqual(config.candidate_diagnostic.time.mode, "比例")

    def test_ratio_diagnostic_time_uses_scheduling_duration(self) -> None:
        config = parse_scheduler_config(
            _config({
                "輸入檔名": "排班輸入_2026-08.json",
                "候選診斷": {
                    "診斷時間上限": {
                        "模式": "比例",
                        "排班時間比例": 0.35,
                    }
                },
            })
        )

        self.assertEqual(config.candidate_diagnostic.time.mode, "比例")
        self.assertEqual(
            config.candidate_diagnostic.time.scheduling_time_ratio,
            0.35,
        )

    def test_rejects_unknown_fields_and_unsafe_input_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "未知欄位"):
            parse_scheduler_config(
                _config({
                    "輸入檔名": "排班輸入_2026-08.json",
                    "typo": True,
                })
            )
        with self.assertRaisesRegex(ValueError, "input 資料夾"):
            parse_scheduler_config(_config({"輸入檔名": "../private.json"}))

    def test_rejects_inconsistent_candidate_settings(self) -> None:
        with self.assertRaisesRegex(ValueError, "不可超過搜尋上限"):
            parse_scheduler_config(
                _config({
                    "輸入檔名": "排班輸入_2026-08.json",
                    "候選診斷": {
                        "搜尋上限": 2,
                        "額外輸出候選班表份數上限": 3,
                    },
                })
            )
        with self.assertRaisesRegex(ValueError, "停用候選診斷"):
            parse_scheduler_config(
                _config({
                    "輸入檔名": "排班輸入_2026-08.json",
                    "候選診斷": {
                        "啟用": False,
                        "額外輸出候選班表份數上限": 1,
                    },
                })
            )

    def test_time_modes_reject_mixed_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "比例模式不可提供"):
            parse_scheduler_config(
                _config({
                    "輸入檔名": "排班輸入_2026-08.json",
                    "候選診斷": {
                        "診斷時間上限": {
                            "模式": "比例",
                            "秒數": 30,
                            "排班時間比例": 0.2,
                        }
                    },
                })
            )
        with self.assertRaisesRegex(ValueError, "定值模式不可提供"):
            parse_scheduler_config(
                _config({
                    "輸入檔名": "排班輸入_2026-08.json",
                    "候選診斷": {
                        "診斷時間上限": {
                            "模式": "定值",
                            "秒數": 30,
                            "排班時間比例": 0.2,
                        }
                    },
                })
            )


if __name__ == "__main__":
    unittest.main()
