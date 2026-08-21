"""Load the packaged QSS resource with centralized palette substitution."""

from __future__ import annotations

from importlib.resources import files

from .palette import stylesheet_tokens


def load_application_stylesheet() -> str:
    resources = files(__package__)
    template = resources.joinpath("application.qss").read_text(
        encoding="utf-8"
    )
    for name, value in sorted(
        stylesheet_tokens().items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        template = template.replace(f"${name}", value)
    return template
