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


def _resolve_user_data_root() -> Path:
    """Return the writable root for installed-app data and logs.

    Order: explicit env > runtime_hook env (set when frozen) > %APPDATA% when
    running as a packaged binary > the dev repo workspace.

    Why: PyInstaller's runtime_hook.py wires ``LITERATURE_ASSISTANT_USER_ROOT``
    to ``%APPDATA%/LiteratureAssistant`` so the installed app does not try to
    write under ``Program Files``. In dev, we keep using the repo-local
    ``workspace_artifacts/`` tree.
    """
    explicit = os.environ.get("LITERATURE_ASSISTANT_USER_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    import sys
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return (Path(appdata) / "LiteratureAssistant").resolve()
        return (Path(sys.executable).parent / "user-data").resolve()

    return (REPO_ROOT / "workspace_artifacts").resolve()


USER_DATA_ROOT = _resolve_user_data_root()
# When frozen, workspace_artifacts moves to %APPDATA%/LiteratureAssistant/;
# in dev it stays at the repo root. Either way, every other anchor below is
# derived from this so logs + project data live in one place.
WORKSPACE_ARTIFACTS_ROOT = USER_DATA_ROOT
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


def wiki_runtime_root(*parts: str) -> Path:
    """Return a path under the wiki runtime-state workspace."""

    return WORKSPACE_RUNTIME_STATE_ROOT.joinpath("wiki", *parts)


def wiki_runtime_db_path() -> Path:
    """Return the canonical SQLite path for wiki runtime registries."""

    return wiki_runtime_root("wiki.db")


def wiki_query_index_path() -> Path:
    """Return the canonical SQLite FTS path for wiki query index state."""

    return wiki_runtime_root("wiki_query_index.db")


def wiki_manifest_path() -> Path:
    """Return the canonical wiki retrieval manifest path."""

    return wiki_runtime_root("retrieval_manifest.json")


def wiki_graph_path() -> Path:
    """Return the canonical human-readable wiki graph path."""

    return wiki_runtime_root("graph.json")


def wiki_graph_db_path() -> Path:
    """Return the canonical SQLite path for wiki graph queries."""

    return wiki_runtime_root("graph.db")


def wiki_review_queue_path() -> Path:
    """Return the canonical wiki review queue path."""

    return wiki_runtime_root("review_queue.jsonl")


def wiki_trace_path(*parts: str) -> Path:
    """Return a path for wiki query traces under runtime-state artifacts."""

    return wiki_runtime_root("traces", *parts)


def wiki_observability_path(*parts: str) -> Path:
    """Return a path for local wiki observability JSONL artifacts."""

    return wiki_runtime_root("observability", *parts)


def wiki_generated_root(*parts: str) -> Path:
    """Return a path under generated wiki pages."""

    return WORKSPACE_GENERATED_ROOT.joinpath("wiki", *parts)


def wiki_page_path(kind: str, slug: str) -> Path:
    """Return the generated markdown path for a wiki page kind and slug."""

    kind_text = str(kind).strip().strip("/\\")
    slug_text = str(slug).strip().strip("/\\")
    if not kind_text or not slug_text:
        raise ValueError("kind and slug are required")
    return wiki_generated_root(kind_text, f"{slug_text}.md")


def project_data_path(project_id: str, *parts: str) -> Path:
    """Return a path under the per-project data workspace.

    Used by chunk store / doc store so that multiple knowledge bases write
    into one ``<user_root>/projects/{safe_id}/`` tree instead of scattering
    ``.scholarai/`` under each source folder.
    """
    safe_id = "".join(c for c in str(project_id) if c.isalnum() or c in "_-")
    if not safe_id:
        safe_id = "_default"
    return WORKSPACE_ARTIFACTS_ROOT.joinpath("projects", safe_id, *parts)


def logs_path(*parts: str) -> Path:
    """Return a path under the unified application log folder."""
    return WORKSPACE_RUNTIME_STATE_ROOT.joinpath("logs", *parts)


def ensure_project_directories() -> None:
    """Create stable workspace roots required by user-facing entry points."""

    for path in (
        WORKSPACE_AI_ROOT,
        WORKSPACE_ARTIFACTS_ROOT,
        WORKSPACE_GENERATED_ROOT,
        WORKSPACE_OUTPUT_ROOT,
        WORKSPACE_REFERENCES_ROOT,
        WORKSPACE_RUNTIME_STATE_ROOT,
        wiki_runtime_root(),
        wiki_trace_path(),
        wiki_observability_path(),
        wiki_generated_root(),
        WORKSPACE_TESTS_ROOT,
        APP_PROFILE_ROOT,
    ):
        ensure_directory(path)
