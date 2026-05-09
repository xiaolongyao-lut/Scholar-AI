"""Thin CLI wrapper for the core skill-flow adapter implementation."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from literature_assistant.bootstrap import configure_runtime_paths

configure_runtime_paths()

from literature_assistant.core.skills.skill_flow_adapter import (  # noqa: E402
    SkillFlowAdapter,
    SyncReport,
    ExportedSkillRecord,
    build_arg_parser,
    main,
)


__all__ = [
    "ExportedSkillRecord",
    "SkillFlowAdapter",
    "SyncReport",
    "build_arg_parser",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())