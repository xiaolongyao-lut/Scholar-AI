"""CLI regression tests for the integrated pipeline entrypoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_integrated_pipeline_help_stays_side_effect_free() -> None:
    """The help path should not trigger embedding probe warnings."""

    script_path = Path(__file__).resolve().parent.parent / "integrated_pipeline.py"
    if not script_path.is_file():
        raise AssertionError(f"Missing CLI script: {script_path}")

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "文献处理器 - 模块化流水线总控" in result.stdout
    assert "Embedding key probe failed" not in result.stdout
    assert "Embedding key probe failed" not in result.stderr
