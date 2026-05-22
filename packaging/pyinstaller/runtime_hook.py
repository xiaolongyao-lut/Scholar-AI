# -*- coding: utf-8 -*-
"""PyInstaller runtime hook for Literature Assistant.

Runs early in the frozen-bundle bootstrap to:
- Set ``LITERATURE_ASSISTANT_USER_ROOT`` so ``project_paths._resolve_repo_root()``
  redirects workspace artifacts / runtime state to ``%APPDATA%/LiteratureAssistant``
  instead of the read-only ``Program Files`` install directory.
- Add the bundled core package directory to ``sys.path`` so legacy
  ``from python_adapter_server import app`` style imports continue to resolve
  inside the onedir bundle.

Reference: docs/plans/runbooks/windows-exe-release-standard.md
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_user_data_root() -> Path:
    """Pick a writable user-data directory for the frozen application."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        root = Path(appdata) / "LiteratureAssistant"
    else:
        root = Path(sys.executable).parent / "user-data"
    root.mkdir(parents=True, exist_ok=True)
    return root


if getattr(sys, "frozen", False):
    os.environ.setdefault(
        "LITERATURE_ASSISTANT_USER_ROOT",
        str(_resolve_user_data_root()),
    )

    bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    core_dir = bundle_dir / "literature_assistant" / "core"
    if core_dir.is_dir():
        core_path = str(core_dir)
        if core_path not in sys.path:
            sys.path.insert(0, core_path)
