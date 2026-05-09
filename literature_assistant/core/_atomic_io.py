"""Shared atomic file IO helpers.

Single owner of the atomic-write pattern used by runtime persistence layers
(credentials store, MCP server store, future stores). All writers must go
through this module to keep semantics aligned:

    same-directory tempfile  ->  fsync  ->  os.replace  ->  unlink stragglers

Originally lived inside ``credential_store._atomic_write_json``; extracted
in MCP integration Phase 1A to avoid copy-paste drift between stores
(plan v0.3 §14 #5).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


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


__all__ = ["atomic_write_json"]
