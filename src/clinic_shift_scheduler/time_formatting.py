"""Shared human-readable elapsed-time formatting."""

from __future__ import annotations


def format_seconds(value: float) -> str:
    """Format seconds with at most one decimal place."""

    number = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{number} 秒"


def format_duration(value: float) -> str:
    """Format whole elapsed seconds as 秒 / 分 秒 / 小時 分 秒.

    小於一分鐘只顯示秒；一小時內顯示分與秒；一小時以上顯示小時、分與秒。
    """

    total_seconds = int(value + 0.5)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours} 小時 {minutes} 分 {seconds} 秒"
    if minutes:
        return f"{minutes} 分 {seconds} 秒"
    return f"{seconds} 秒"


def format_seconds_with_minutes(value: float) -> str:
    """Format seconds plus an approximate whole-minute breakdown."""

    rounded_total_seconds = int(value + 0.5)
    minutes, remaining_seconds = divmod(rounded_total_seconds, 60)
    return (
        f"{format_seconds(value)}"
        f"（約 {minutes} 分 {remaining_seconds} 秒）"
    )
