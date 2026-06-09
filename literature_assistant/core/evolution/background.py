"""
Fire-and-forget hook for evolution capture sites.

Capture writes (inspiration / discussion / RAG / runtime / skill) must not
gate the user-visible response. Each site already has best-effort try/except
guards; this module wraps the call in a daemon thread so the request
handler returns immediately and capture proceeds in the background.

Why threading, not FastAPI `BackgroundTasks`:
    - BackgroundTasks only fires *after* the response is sent for FastAPI
      request handlers; helper functions deep in the call chain
      (writing_runtime, capture inside RAG helpers) are not always
      reachable from a request handler signature.
    - Threading lets every capture site fire-and-forget regardless of
      whether the surrounding call is async, sync, or detached from any
      request lifecycle (e.g. terminal-state runtime jobs).
    - SQLite store is concurrency-hardened by WAL +
      busy_timeout + insert-race fallback), so concurrent capture writes
      from threads are safe.

Kill switch:
    Set env `EVOLUTION_BACKGROUND_CAPTURE_DISABLED=1` to force every call to
    run inline (synchronous). Useful for tests that need to observe writes
    deterministically without polling.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

logger = logging.getLogger("EvolutionBackgroundCapture")


def _inline_mode() -> bool:
    """True when the caller explicitly disabled threading (tests / debug)."""

    raw = str(os.getenv("EVOLUTION_BACKGROUND_CAPTURE_DISABLED", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def run_capture_in_background(
    fn: Callable[..., Any],
    *args: Any,
    label: str = "capture",
    **kwargs: Any,
) -> threading.Thread | None:
    """Run `fn(*args, **kwargs)` in a daemon thread; never raises.

    Returns the started Thread (so tests can join) or None when running
    inline. Failures inside `fn` are caught and logged — they never bubble
    out of the background hook.
    """

    if _inline_mode():
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("inline capture %s failed: %s", label, exc)
        return None

    def _runner() -> None:
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("background capture %s failed: %s", label, exc)

    thread = threading.Thread(target=_runner, name=f"evo-capture-{label}", daemon=True)
    thread.start()
    return thread
