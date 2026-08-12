"""Human-facing labels that never alter formal domain keys."""

from __future__ import annotations


_ROLE_LABELS = {
    "reception": "櫃台",
    "nursing": "跟診",
}
_ROLE_KEYS = {label: key for key, label in _ROLE_LABELS.items()}


def role_display_name(role: str) -> str:
    return _ROLE_LABELS.get(role, role)


def role_key_from_display(label: str) -> str:
    return _ROLE_KEYS.get(label.strip(), label.strip())
