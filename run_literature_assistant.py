"""Stable command wrapper for the reorganized literature assistant workspace."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CORE = ROOT / "literature_assistant" / "core"

for path in (str(ROOT), str(CORE)):
    if path not in sys.path:
        sys.path.insert(0, path)

if __name__ == "__main__":
    runpy.run_module("literature_assistant", run_name="__main__")
