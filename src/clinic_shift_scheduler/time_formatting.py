"""Shared human-readable elapsed-time formatting."""

from __future__ import annotations


def format_seconds(value: float) -> str:
    """Format seconds with at most one decimal place."""

    number = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{number} 秒"


def format_seconds_with_minutes(value: float) -> str:
    """Format seconds plus an approximate whole-minute breakdown."""

    rounded_total_seconds = int(value + 0.5)
    minutes, remaining_seconds = divmod(rounded_total_seconds, 60)
    return (
        f"{format_seconds(value)}"
        f"（約 {minutes} 分 {remaining_seconds} 秒）"
    )
