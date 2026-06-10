from __future__ import annotations

import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def test_pyproject_declares_python_311_runtime_floor() -> None:
    """Project metadata must match runtime imports that use Python 3.11 APIs."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert data["project"]["requires-python"] == ">=3.11"
    assert data["tool"]["mypy"]["python_version"] == "3.11"
    assert data["tool"]["black"]["target-version"] == ["py311"]


def test_pyproject_declares_0183_release_version() -> None:
    """Project metadata must advertise the packaged 0.1.8.3 release."""

    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert data["project"]["version"] == "0.1.8.3"
