"""Access to the bundled v1 JSON Schema artifact."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


SCHEMA_VERSION = "v1"
SCHEMA_FILE = "clinic-shift-scheduler.v1.schema.json"


def load_v1_schema() -> dict[str, Any]:
    resource = files("clinic_shift_scheduler.schemas").joinpath(SCHEMA_FILE)
    return json.loads(resource.read_text(encoding="utf-8"))

