"""Compatibility import hook for the reorganized literature assistant workspace.

This keeps legacy top-level imports working while the implementation files live
under ``literature_assistant/core``.
"""

from __future__ import annotations

try:
    from literature_assistant.bootstrap import configure_runtime_paths
except Exception as exc:
    import os
    import warnings

    message = (
        "Literature Assistant sitecustomize warning: "
        f"bootstrap import failed: {exc.__class__.__name__}: {exc}"
    )
    if os.environ.get("LITASSIST_BOOTSTRAP_STRICT", "").strip() == "1":
        raise RuntimeError(message) from exc
    warnings.warn(message, RuntimeWarning, stacklevel=1)
    configure_runtime_paths = None

if configure_runtime_paths is not None:
    configure_runtime_paths()
