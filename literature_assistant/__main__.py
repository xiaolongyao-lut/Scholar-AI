"""Command entry for literature assistant workspace checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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


def _wiki_status_report() -> dict[str, object]:
    from literature_assistant.core.routers.wiki_router import wiki_status

    return wiki_status(user_id=None).model_dump()


def _wiki_doctor_report() -> dict[str, object]:
    from literature_assistant.core.routers.wiki_router import wiki_doctor

    return wiki_doctor().model_dump()


def _wiki_migration_dry_run_report(
    input_path: str,
    *,
    source_type: str,
    max_candidates: int,
) -> dict[str, object]:
    from literature_assistant.core.wiki.migration import evidence_refs_migration_dry_run_from_jsonl

    report = evidence_refs_migration_dry_run_from_jsonl(
        Path(input_path),
        source_type=source_type,
        max_candidates=max_candidates,
    )
    return report.to_dict()


def _wiki_backup_report(
    *,
    archive_path: str | None,
    write: bool,
    include_query_index: bool,
    include_review_queue: bool,
) -> dict[str, object]:
    from literature_assistant.core.wiki.backup import build_wiki_backup_plan

    report = build_wiki_backup_plan(
        archive_path=Path(archive_path) if archive_path else None,
        include_query_index=include_query_index,
        include_review_queue=include_review_queue,
        dry_run=not write,
    )
    return report.to_dict()


def _print_json(payload: dict[str, object] | dict[str, str]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m literature_assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("paths", help="Print canonical workspace paths.")

    wiki_parser = subparsers.add_parser("wiki", help="Wiki status and doctor diagnostics.")
    wiki_subparsers = wiki_parser.add_subparsers(dest="wiki_command", required=True)
    wiki_subparsers.add_parser("status", help="Print wiki status contract JSON.")
    wiki_subparsers.add_parser("doctor", help="Run wiki doctor in dry-run mode and print JSON.")
    migration_parser = wiki_subparsers.add_parser(
        "migration-dry-run",
        help="Plan evidence_refs to wiki registry migration without writing.",
    )
    migration_parser.add_argument("--input", required=True, help="JSONL file with evidence_refs or EvidenceReference rows.")
    migration_parser.add_argument("--source-type", default="rag_evidence", help="Source type label for would-import rows.")
    migration_parser.add_argument("--max-candidates", type=int, default=500, help="Maximum candidates to include.")

    backup_parser = wiki_subparsers.add_parser("backup", help="Plan or create a local wiki backup zip.")
    backup_parser.add_argument("--archive", default=None, help="Destination .zip path. Defaults under workspace_artifacts/backups.")
    backup_parser.add_argument("--write", action="store_true", help="Create the zip archive. Omit for dry-run.")
    backup_parser.add_argument("--no-query-index", action="store_true", help="Skip derived query index database.")
    backup_parser.add_argument("--no-review-queue", action="store_true", help="Skip review queue artifact.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "paths":
        _print_json(_path_report())
        return 0

    if args.command == "wiki":
        if args.wiki_command == "status":
            _print_json(_wiki_status_report())
            return 0
        if args.wiki_command == "doctor":
            _print_json(_wiki_doctor_report())
            return 0
        if args.wiki_command == "migration-dry-run":
            _print_json(
                _wiki_migration_dry_run_report(
                    args.input,
                    source_type=args.source_type,
                    max_candidates=args.max_candidates,
                )
            )
            return 0
        if args.wiki_command == "backup":
            _print_json(
                _wiki_backup_report(
                    archive_path=args.archive,
                    write=args.write,
                    include_query_index=not args.no_query_index,
                    include_review_queue=not args.no_review_queue,
                )
            )
            return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
