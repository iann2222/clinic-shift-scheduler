"""Translate formal validation diagnostics for non-technical GUI users."""

from __future__ import annotations

import re

from ..events import DiagnosticIssue


_MESSAGES = {
    "empty_list": "至少需要新增一筆資料。",
    "duplicate_employee_id": "員工 ID 不可重複。",
    "unknown_employee_id": "找不到這筆資料所參照的員工。",
    "unknown_role": "使用了不存在或已刪除的職務。",
    "unqualified_available_role": "可排職務不在該員工的職務資格內。",
    "incompatible_fairness_group": "同一公平分組不可混合不同聘用類別或 A／B 類別。",
    "invalid_full_time_class": "兼職人員不可設定 A／B 正職類別。",
    "unsupported_part_time_target": "兼職人員只支援固定班次或班次範圍。",
    "invalid_shift_fields": "班次模式與所填班次欄位不一致。",
    "invalid_shift_range": "最低班次不可大於最高班次。",
    "target_outside_bounds": "目標班次必須位於已設定的最低與最高班次之間。",
    "date_out_of_range": "日期不在目前排班月份內。",
    "missing_demand": "開診時段的每一種職務都必須明確填寫需求人數。",
    "demand_on_closed_date": "休診日期不可同時存在人力需求。",
    "conflicting_duplicate": "同一項資料重複出現且內容互相衝突。",
    "invalid_draft": "輸入內容無法組成正式排班文件。",
    "missing_key": "缺少必要欄位。",
    "unknown_key": "包含不支援的欄位。",
    "invalid_type": "欄位資料類型不正確。",
    "invalid_value": "欄位值不在允許範圍內。",
    "empty_text": "此欄位不可留空。",
}

_FIELD_LABELS = {
    "employees": "員工資料",
    "employee_id": "員工 ID",
    "name": "姓名",
    "employment_type": "聘用類別",
    "full_time_class": "正職類別",
    "roles": "職務資格",
    "fairness_group": "公平分組",
    "shift_mode": "班次模式",
    "required_shifts": "固定班次",
    "target_shifts": "目標班次",
    "min_shifts": "最低班次",
    "max_shifts": "最高班次",
    "available_slots": "兼職可排時段",
    "leave_requests": "請假資料",
    "unavailable_slots": "不可排時段",
    "weekly_demands": "每週人力需求",
    "date_overrides": "特定日期調整",
    "period": "月份",
    "holidays": "假日",
    "date": "日期",
    "staffing": "人力需求",
}


def format_validation_issue(issue: DiagnosticIssue) -> str:
    location = humanize_issue_path(issue.path)
    message = _MESSAGES.get(issue.code, issue.message)
    return f"{location}：{message}"


def humanize_issue_path(path: str) -> str:
    if path == "$":
        return "整份輸入資料"
    parts: list[str] = []
    for name, raw_index in re.findall(r"([A-Za-z_]+)(?:\[(\d+)\])?", path):
        label = _FIELD_LABELS.get(name, name)
        if raw_index:
            label = f"{label}第 {int(raw_index) + 1} 筆"
        parts.append(label)
    return "／".join(parts) if parts else path
