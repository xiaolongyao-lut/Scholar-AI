"""Command entry for literature assistant workspace checks."""

from __future__ import annotations

import argparse
import json

from literature_assistant.bootstrap import configure_runtime_paths


configure_runtime_paths()

from project_paths import (  # noqa: E402
    CORE_ROOT,
    EXTERNAL_REFERENCES_ROOT,
    FRONTEND_ROOT,
    REPO_ROOT,
    WORKSPACE_ARTIFACTS_ROOT,
    WORKSPACE_GENERATED_ROOT,
    WORKSPACE_OUTPUT_ROOT,
    WORKSPACE_REFERENCES_ROOT,
    WORKSPACE_RUNTIME_STATE_ROOT,
)


def _path_report() -> dict[str, str]:
    return {
        "repo_root": str(REPO_ROOT),
        "core_root": str(CORE_ROOT),
        "frontend_root": str(FRONTEND_ROOT),
        "external_references_root": str(EXTERNAL_REFERENCES_ROOT),
        "workspace_artifacts_root": str(WORKSPACE_ARTIFACTS_ROOT),
        "workspace_generated_root": str(WORKSPACE_GENERATED_ROOT),
        "workspace_output_root": str(WORKSPACE_OUTPUT_ROOT),
        "workspace_runtime_state_root": str(WORKSPACE_RUNTIME_STATE_ROOT),
        "workspace_references_root": str(WORKSPACE_REFERENCES_ROOT),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m literature_assistant")
    parser.add_argument(
        "command",
        choices=("paths",),
        help="Diagnostic command to run.",
    )
    args = parser.parse_args()

    if args.command == "paths":
        print(json.dumps(_path_report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
