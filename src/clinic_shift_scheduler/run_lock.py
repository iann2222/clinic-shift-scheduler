"""Operating-system lock that serializes runs sharing one output directory."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Iterator


RUN_LOCK_FILENAME = ".clinic-shift-scheduler.lock"


class ScheduleRunLockUnavailableError(RuntimeError):
    """Raised when another process owns the requested scheduling lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"schedule output is already in use: {path}")


@dataclass(frozen=True, slots=True)
class ScheduleRunLock:
    """Information about the lock held for one scheduling run."""

    path: Path


@contextmanager
def schedule_run_lock(
    output_directory: str | Path,
) -> Iterator[ScheduleRunLock]:
    """Hold a non-blocking process lock for the complete scheduling run."""

    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / RUN_LOCK_FILENAME
    stream = path.open("a+b")
    try:
        _ensure_lockable_byte(stream)
        try:
            _try_lock(stream)
        except OSError as error:
            raise ScheduleRunLockUnavailableError(path) from error
        try:
            _write_owner_metadata(stream)
            yield ScheduleRunLock(path=path)
        finally:
            _unlock(stream)
    finally:
        stream.close()


def _ensure_lockable_byte(stream: BinaryIO) -> None:
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"\0")
        stream.flush()
    stream.seek(0)


def _write_owner_metadata(stream: BinaryIO) -> None:
    payload = json.dumps(
        {
            "pid": os.getpid(),
            "acquired_at": datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    stream.seek(0)
    stream.truncate()
    stream.write(payload)
    stream.flush()
    stream.seek(0)


if os.name == "nt":
    import msvcrt

    def _try_lock(stream: BinaryIO) -> None:
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(stream: BinaryIO) -> None:
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(stream: BinaryIO) -> None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(stream: BinaryIO) -> None:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
