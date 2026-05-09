"""Compatibility import hook for directly executed evaluation scripts."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "literature_assistant" / "core"

if CORE.is_dir():
    core_path = str(CORE)
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
