"""Access to the bundled v1 JSON Schema artifact."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


SCHEMA_VERSION = "v1"
SCHEMA_FILE = "clinic-shift-scheduler.v1.schema.json"
WEEKLY_AUTHORING_SCHEMA_VERSION = "weekly-v1"
WEEKLY_AUTHORING_SCHEMA_FILE = (
    "clinic-shift-scheduler.weekly-v1.schema.json"
)
APP_CONFIG_SCHEMA_VERSION = "1"
APP_CONFIG_SCHEMA_FILE = "clinic-shift-scheduler.config-v1.schema.json"


def _load_schema(filename: str) -> dict[str, Any]:
    resource = files("clinic_shift_scheduler.schemas").joinpath(filename)
    return json.loads(resource.read_text(encoding="utf-8"))


def load_v1_schema() -> dict[str, Any]:
    return _load_schema(SCHEMA_FILE)


def load_weekly_authoring_schema() -> dict[str, Any]:
    """Load the bundled user-editable weekly-v1 Schema."""

    return _load_schema(WEEKLY_AUTHORING_SCHEMA_FILE)


def load_app_config_schema() -> dict[str, Any]:
    """Load the bundled user config v1 Schema."""

    return _load_schema(APP_CONFIG_SCHEMA_FILE)
