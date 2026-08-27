"""Low-saturation colors shared by the desktop input editor."""

from __future__ import annotations


BACKGROUND = "#F4F6F8"
SURFACE = "#FFFFFF"
SIDEBAR = "#E9EEF2"
PRIMARY = "#3E6575"
PRIMARY_HOVER = "#345765"
PRIMARY_SOFT = "#DCE8EC"
TEXT = "#263238"
TEXT_MUTED = "#617078"
BORDER = "#CDD6DB"
SUCCESS = "#3C7257"
WARNING = "#8B6828"
ERROR = "#9B4646"

# Execution-page status indicator colors (deliberately more vivid than the
# low-saturation UI palette so the small dot remains distinguishable).
STATUS_NEUTRAL = "#9CA3A8"
STATUS_RUNNING = "#4A7FA5"
STATUS_SUCCESS = "#4E9268"
STATUS_WARNING = "#CB9A3E"
STATUS_ERROR = "#C15B54"
STATUS_CANCELLED = "#767D82"


def stylesheet_tokens() -> dict[str, str]:
    return {
        "BACKGROUND": BACKGROUND,
        "SURFACE": SURFACE,
        "SIDEBAR": SIDEBAR,
        "PRIMARY": PRIMARY,
        "PRIMARY_HOVER": PRIMARY_HOVER,
        "PRIMARY_SOFT": PRIMARY_SOFT,
        "TEXT": TEXT,
        "TEXT_MUTED": TEXT_MUTED,
        "BORDER": BORDER,
        "SUCCESS": SUCCESS,
        "WARNING": WARNING,
        "ERROR": ERROR,
        "STATUS_NEUTRAL": STATUS_NEUTRAL,
        "STATUS_RUNNING": STATUS_RUNNING,
        "STATUS_SUCCESS": STATUS_SUCCESS,
        "STATUS_WARNING": STATUS_WARNING,
        "STATUS_ERROR": STATUS_ERROR,
        "STATUS_CANCELLED": STATUS_CANCELLED,
    }
