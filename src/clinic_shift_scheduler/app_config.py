"""User-facing configuration for the one-command scheduling entry point."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


APP_CONFIG_VERSION = "1"
SUPPORTED_CANDIDATE_EXPORT_FORMATS = frozenset({"json", "excel", "pdf"})
DIAGNOSTIC_TIME_MODES = frozenset({"定值", "比例"})


def _require_object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} 必須是 JSON object")
    return value


def _reject_unknown_fields(
    payload: Mapping[str, Any],
    allowed: set[str],
    field: str,
) -> None:
    unknown = sorted(
        key
        for key in set(payload) - allowed
        if not (key.startswith("__") and key.endswith("__"))
    )
    if unknown:
        raise ValueError(f"{field} 含有未知欄位：{', '.join(unknown)}")


@dataclass(frozen=True, slots=True)
class DiagnosticTimeSettings:
    mode: str = "比例"
    fixed_seconds: float | None = None
    scheduling_time_ratio: float | None = 0.2

    def __post_init__(self) -> None:
        if self.mode not in DIAGNOSTIC_TIME_MODES:
            raise ValueError("診斷時間上限.模式只接受『定值』或『比例』")
        if self.mode == "定值":
            if (
                isinstance(self.fixed_seconds, bool)
                or not isinstance(self.fixed_seconds, (int, float))
                or self.fixed_seconds <= 0
            ):
                raise ValueError("定值模式必須提供大於 0 的診斷時間上限.秒數")
            if self.scheduling_time_ratio is not None:
                raise ValueError("定值模式不可提供診斷時間上限.排班時間比例")
        else:
            if self.fixed_seconds is not None:
                raise ValueError("比例模式不可提供診斷時間上限.秒數")
            if (
                isinstance(self.scheduling_time_ratio, bool)
                or not isinstance(self.scheduling_time_ratio, (int, float))
                or self.scheduling_time_ratio <= 0
            ):
                raise ValueError(
                    "比例模式必須提供大於 0 的診斷時間上限.排班時間比例"
                )


@dataclass(frozen=True, slots=True)
class CandidateDiagnosticSettings:
    enabled: bool = True
    search_limit: int = 100
    time: DiagnosticTimeSettings = field(default_factory=DiagnosticTimeSettings)
    export_count: int = 0
    export_formats: tuple[str, ...] = ("json",)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("候選診斷.啟用必須是布林值")
        if (
            isinstance(self.search_limit, bool)
            or not isinstance(self.search_limit, int)
            or self.search_limit <= 0
        ):
            raise ValueError(
                "候選診斷.搜尋上限必須是正整數"
            )
        if (
            isinstance(self.export_count, bool)
            or not isinstance(self.export_count, int)
            or self.export_count < 0
        ):
            raise ValueError(
                "候選診斷.額外輸出候選班表份數上限必須是非負整數"
            )
        if self.export_count > self.search_limit:
            raise ValueError(
                "候選診斷.額外輸出候選班表份數上限不可超過搜尋上限"
            )
        if not self.enabled and self.export_count:
            raise ValueError(
                "停用候選診斷時，額外輸出候選班表份數上限必須為 0"
            )
        if len(set(self.export_formats)) != len(self.export_formats):
            raise ValueError("候選診斷.輸出格式不可重複")
        unsupported = sorted(
            set(self.export_formats) - SUPPORTED_CANDIDATE_EXPORT_FORMATS
        )
        if unsupported:
            raise ValueError(
                "候選診斷.輸出格式包含不支援的值："
                + ", ".join(unsupported)
            )
        if self.export_count and not self.export_formats:
            raise ValueError("輸出候選班表時，候選診斷.輸出格式不可留空")


@dataclass(frozen=True, slots=True)
class SchedulerAppConfig:
    input_file: str
    overwrite: bool = True
    progress_update_seconds: float = 5.0
    candidate_diagnostic: CandidateDiagnosticSettings = field(
        default_factory=CandidateDiagnosticSettings
    )
    config_version: str = APP_CONFIG_VERSION

    def __post_init__(self) -> None:
        if self.config_version != APP_CONFIG_VERSION:
            raise ValueError(
                f"不支援的設定版本：{self.config_version!r}；"
                f"目前必須為 {APP_CONFIG_VERSION!r}"
            )
        if not isinstance(self.input_file, str) or not self.input_file.strip():
            raise ValueError("輸入檔名必須是非空白檔名")
        input_path = Path(self.input_file)
        if input_path.is_absolute() or input_path.name != self.input_file:
            raise ValueError("輸入檔名只能填寫 input 資料夾內的檔名")
        if input_path.suffix.lower() != ".json":
            raise ValueError("輸入檔名必須是 JSON 檔案")
        if not isinstance(self.overwrite, bool):
            raise ValueError("覆寫既有結果必須是布林值")
        if (
            isinstance(self.progress_update_seconds, bool)
            or not isinstance(self.progress_update_seconds, (int, float))
            or self.progress_update_seconds <= 0
        ):
            raise ValueError("進度更新秒數必須大於 0")


def parse_scheduler_config(payload: Mapping[str, Any]) -> SchedulerAppConfig:
    """Validate and normalize a user-facing configuration object."""

    _reject_unknown_fields(
        payload,
        {"使用者設定", "預設設定"},
        "config",
    )
    if "使用者設定" not in payload:
        raise ValueError("config.使用者設定為必填")
    if "預設設定" not in payload:
        raise ValueError("config.預設設定為必填")
    settings = _require_object(payload["使用者設定"], "使用者設定")
    _require_object(payload["預設設定"], "預設設定")
    _reject_unknown_fields(
        settings,
        {
            "設定版本",
            "輸入檔名",
            "覆寫既有結果",
            "進度更新秒數",
            "候選診斷",
        },
        "使用者設定",
    )
    if "輸入檔名" not in settings:
        raise ValueError("使用者設定.輸入檔名為必填")

    candidate_payload = _require_object(
        settings.get("候選診斷", {}),
        "候選診斷",
    )
    _reject_unknown_fields(
        candidate_payload,
        {
            "啟用",
            "搜尋上限",
            "診斷時間上限",
            "額外輸出候選班表份數上限",
            "輸出格式",
        },
        "候選診斷",
    )
    time_payload = _require_object(
        candidate_payload.get(
            "診斷時間上限",
            {"模式": "比例", "排班時間比例": 0.2},
        ),
        "候選診斷.診斷時間上限",
    )
    _reject_unknown_fields(
        time_payload,
        {"模式", "秒數", "排班時間比例"},
        "候選診斷.診斷時間上限",
    )
    time_mode = time_payload.get("模式", "比例")
    time = DiagnosticTimeSettings(
        mode=time_mode,
        fixed_seconds=time_payload.get("秒數"),
        scheduling_time_ratio=time_payload.get(
            "排班時間比例",
            0.2 if time_mode == "比例" else None,
        ),
    )

    raw_formats = candidate_payload.get("輸出格式", ["JSON"])
    if not isinstance(raw_formats, list) or not all(
        isinstance(item, str) for item in raw_formats
    ):
        raise ValueError("候選診斷.輸出格式必須是字串陣列")
    normalized_formats = tuple(item.lower() for item in raw_formats)

    diagnostic = CandidateDiagnosticSettings(
        enabled=candidate_payload.get("啟用", True),
        search_limit=candidate_payload.get("搜尋上限", 100),
        time=time,
        export_count=candidate_payload.get(
            "額外輸出候選班表份數上限",
            0,
        ),
        export_formats=normalized_formats,
    )
    return SchedulerAppConfig(
        config_version=settings.get("設定版本", APP_CONFIG_VERSION),
        input_file=settings["輸入檔名"],
        overwrite=settings.get("覆寫既有結果", True),
        progress_update_seconds=settings.get("進度更新秒數", 5.0),
        candidate_diagnostic=diagnostic,
    )


def load_scheduler_config(path: str | Path) -> SchedulerAppConfig:
    """Read one UTF-8 JSON configuration file."""

    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    return parse_scheduler_config(_require_object(payload, "config"))
