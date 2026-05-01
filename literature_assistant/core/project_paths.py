"""Shared filesystem anchors for the reorganized literature assistant.

The core package lives below ``literature_assistant/core`` while runtime assets,
frontend builds, external references, and generated artifacts remain anchored at
the repository root.
"""

from __future__ import annotations

import os
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parent
LITERATURE_ASSISTANT_ROOT = CORE_ROOT.parent
REPO_ROOT = LITERATURE_ASSISTANT_ROOT.parent
FRONTEND_ROOT = REPO_ROOT / "frontend"
WORKSPACE_ARTIFACTS_ROOT = REPO_ROOT / "workspace_artifacts"
WORKSPACE_AI_ROOT = REPO_ROOT / "workspace_ai"
WORKSPACE_TESTS_ROOT = REPO_ROOT / "workspace_tests"
WORKSPACE_GENERATED_ROOT = WORKSPACE_ARTIFACTS_ROOT / "generated"
WORKSPACE_REFERENCES_ROOT = REPO_ROOT / "workspace_references"
EXTERNAL_REFERENCES_ROOT = REPO_ROOT / "github"
LEGACY_OUTPUT_ROOT = REPO_ROOT / "output"


def _configured_path(env_var: str, default_path: Path) -> Path:
    """Resolve an absolute path from an env override or a repo-local default."""

    raw_value = os.environ.get(env_var, "").strip()
    if raw_value:
        return Path(raw_value).expanduser().resolve()
    return default_path.resolve()


WORKSPACE_RUNTIME_STATE_ROOT = _configured_path(
    "LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT",
    WORKSPACE_ARTIFACTS_ROOT / "runtime_state",
)
WORKSPACE_OUTPUT_ROOT = _configured_path(
    "LITERATURE_ASSISTANT_OUTPUT_ROOT",
    WORKSPACE_GENERATED_ROOT / "output",
)
APP_PROFILE_ROOT = _configured_path(
    "LITERATURE_ASSISTANT_APP_PROFILE_ROOT",
    WORKSPACE_RUNTIME_STATE_ROOT / "app-profile",
)


def ensure_directory(path: Path) -> Path:
    """Create and return a directory used by runtime code."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def generated_path(*parts: str) -> Path:
    """Return a path under the generated artifact workspace."""

    return WORKSPACE_GENERATED_ROOT.joinpath(*parts)


def output_path(*parts: str) -> Path:
    """Return a path under the canonical runtime output workspace."""

    return WORKSPACE_OUTPUT_ROOT.joinpath(*parts)


def runtime_state_path(*parts: str) -> Path:
    """Return a path under the runtime-state artifact workspace."""

    return WORKSPACE_RUNTIME_STATE_ROOT.joinpath(*parts)


def app_profile_path(*parts: str) -> Path:
    """Return a path under the browser profile runtime workspace."""

    return APP_PROFILE_ROOT.joinpath(*parts)


def ensure_project_directories() -> None:
    """Create stable workspace roots required by user-facing entry points."""

    for path in (
        WORKSPACE_AI_ROOT,
        WORKSPACE_ARTIFACTS_ROOT,
        WORKSPACE_GENERATED_ROOT,
        WORKSPACE_OUTPUT_ROOT,
        WORKSPACE_REFERENCES_ROOT,
        WORKSPACE_RUNTIME_STATE_ROOT,
        WORKSPACE_TESTS_ROOT,
        APP_PROFILE_ROOT,
    ):
        ensure_directory(path)
