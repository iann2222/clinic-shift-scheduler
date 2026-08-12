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
    }
