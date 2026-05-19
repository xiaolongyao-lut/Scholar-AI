"""Compatibility import hook for the reorganized literature assistant workspace.

This keeps legacy top-level imports working while the implementation files live
under ``literature_assistant/core``.
"""

from __future__ import annotations

try:
    from literature_assistant.bootstrap import configure_runtime_paths
except Exception:
    configure_runtime_paths = None

if configure_runtime_paths is not None:
    configure_runtime_paths()
