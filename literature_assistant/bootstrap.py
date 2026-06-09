"""Runtime bootstrap for all literature assistant entry points.

The bootstrap makes path setup explicit so user-facing commands do not depend on
the caller's current working directory or an already-activated virtualenv.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
CORE_ROOT = PACKAGE_ROOT / "core"


def _warn_or_raise_bootstrap_failure(context: str, exc: BaseException) -> None:
    """Surface bootstrap failures without breaking ordinary Python startup.

    Args:
        context: Short label for the failed bootstrap phase.
        exc: Original exception raised by the phase.
    """
    if not context:
        raise ValueError("context must be non-empty")
    message = f"Literature Assistant bootstrap warning: {context}: {exc.__class__.__name__}: {exc}"
    if os.environ.get("LITASSIST_BOOTSTRAP_STRICT", "").strip() == "1":
        raise RuntimeError(message) from exc
    warnings.warn(message, RuntimeWarning, stacklevel=2)


def configure_runtime_paths() -> None:
    """Expose repository and core paths for legacy and package imports."""

    for path in (str(REPO_ROOT), str(CORE_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)

    os.environ.setdefault("LITERATURE_ASSISTANT_REPO_ROOT", str(REPO_ROOT))
    os.environ.setdefault("LITERATURE_ASSISTANT_CORE_ROOT", str(CORE_ROOT))

    try:
        from literature_assistant.core.project_paths import (
            APP_PROFILE_ROOT,
            WORKSPACE_OUTPUT_ROOT,
            WORKSPACE_RUNTIME_STATE_ROOT,
            ensure_project_directories,
        )
    except Exception as exc:
        _warn_or_raise_bootstrap_failure("project path initialization failed", exc)
        return

    ensure_project_directories()
    os.environ.setdefault("LITERATURE_ASSISTANT_OUTPUT_ROOT", str(WORKSPACE_OUTPUT_ROOT))
    os.environ.setdefault("LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT", str(WORKSPACE_RUNTIME_STATE_ROOT))
    os.environ.setdefault("LITERATURE_ASSISTANT_APP_PROFILE_ROOT", str(APP_PROFILE_ROOT))
    os.environ.setdefault("MODEL_CALL_GATEWAY_CACHE_DIR", str(WORKSPACE_OUTPUT_ROOT / "model_gateway_cache"))
    os.environ.setdefault("MODEL_CALL_GATEWAY_METRICS_PATH", str(WORKSPACE_OUTPUT_ROOT / "gateway_metrics.jsonl"))
    os.environ.setdefault("RERANK_DISK_CACHE_DIR", str(WORKSPACE_OUTPUT_ROOT / "rerank_cache"))
