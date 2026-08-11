"""UTF-8 JSON document I/O with recoverable atomic replacement."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def read_json_object(path: str | Path) -> dict[str, Any]:
    """Read a UTF-8 JSON object and reject non-object roots."""

    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("JSON root must be an object")
    return dict(payload)


def write_json_object_atomic(
    path: str | Path,
    payload: Mapping[str, Any],
) -> Path:
    """Atomically replace one user-owned JSON document."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
            temporary = Path(output.name)
        os.replace(temporary, target)
        temporary = None
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
