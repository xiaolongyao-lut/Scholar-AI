"""Shared atomic file IO helpers.

Single owner of the atomic-write pattern used by runtime persistence layers
(credentials store, MCP server store, future stores). All writers must go
through this module to keep semantics aligned:

    same-directory tempfile  ->  fsync  ->  os.replace  ->  unlink stragglers

Originally lived inside ``credential_store._atomic_write_json``; extracted
to avoid copy-paste drift between stores.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any


class CrossProcessFileLock:
    """Small cross-platform exclusive lock for runtime JSON stores.

    Why:
        Atomic replace prevents torn writes but not lost updates when two app
        instances read-modify-write the same runtime document concurrently.
        A sidecar lock serializes that critical section across processes.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._handle: Any | None = None

    def __enter__(self) -> "CrossProcessFileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            handle.close()
            raise
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def atomic_write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    """Atomically write JSON to ``path``.

    The temp file lives in the same directory as ``path`` so that
    ``os.replace`` is guaranteed to be atomic on Windows + POSIX. Parent
    directories are created if missing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=indent)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if Path(tmp_name).exists():
                Path(tmp_name).unlink()
        except OSError:
            pass


__all__ = ["CrossProcessFileLock", "atomic_write_json"]
