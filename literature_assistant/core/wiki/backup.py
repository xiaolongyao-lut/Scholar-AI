from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from literature_assistant.core.project_paths import (
    WORKSPACE_ARTIFACTS_ROOT,
    wiki_generated_root,
    wiki_graph_db_path,
    wiki_graph_path,
    wiki_manifest_path,
    wiki_query_index_path,
    wiki_review_queue_path,
    wiki_runtime_db_path,
)
from literature_assistant.core.wiki.page_store import atomic_write_text


MANIFEST_NAME = "wiki_backup_manifest.json"


@dataclass(frozen=True)
class WikiBackupFile:
    """One file selected for a local wiki backup archive."""

    role: str
    source_path: Path
    archive_path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "source_path": str(self.source_path),
            "archive_path": self.archive_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class WikiBackupPlan:
    """A deterministic local-only plan for backing up wiki artifacts."""

    ok: bool
    would_write: bool
    archive_path: Path
    manifest_path: Path | None
    files: tuple[WikiBackupFile, ...]
    missing: tuple[dict[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "would_write": self.would_write,
            "archive_path": str(self.archive_path),
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "file_count": len(self.files),
            "files": [file.to_dict() for file in self.files],
            "missing": list(self.missing),
            "warnings": list(self.warnings),
            "metadata": self.metadata,
        }


def build_wiki_backup_plan(
    *,
    archive_path: Path | None = None,
    runtime_root: Path | None = None,
    generated_wiki_root: Path | None = None,
    include_query_index: bool = True,
    include_review_queue: bool = True,
    include_missing: bool = True,
    dry_run: bool = True,
) -> WikiBackupPlan:
    """Return a backup plan, optionally writing a local zip archive.

    Args:
        archive_path: Destination zip path. Defaults under workspace artifacts.
        runtime_root: Optional wiki runtime root for tests or isolated dry-runs.
        generated_wiki_root: Optional generated wiki page root.
        include_query_index: Include the derived FTS query index if present.
        include_review_queue: Include the review queue if present.
        include_missing: Keep missing expected artifacts in the report.
        dry_run: When true, only report selected files and never create a zip.

    Raises:
        ValueError: If archive_path is a directory or has no ``.zip`` suffix.
    """

    target_archive = _resolve_archive_path(archive_path)
    selected, missing = _collect_wiki_backup_files(
        runtime_root=runtime_root,
        generated_wiki_root=generated_wiki_root,
        include_query_index=include_query_index,
        include_review_queue=include_review_queue,
        include_missing=include_missing,
    )
    warnings = []
    if not selected:
        warnings.append("no wiki artifacts found to back up")
    manifest_path = None if dry_run else target_archive.with_suffix(".manifest.json")
    plan = WikiBackupPlan(
        ok=bool(selected),
        would_write=not dry_run,
        archive_path=target_archive,
        manifest_path=manifest_path,
        files=tuple(selected),
        missing=tuple(missing),
        warnings=tuple(warnings),
        metadata={
            "kind": "wiki-backup",
            "created_at": _utc_now_iso(),
            "include_query_index": include_query_index,
            "include_review_queue": include_review_queue,
        },
    )
    if dry_run:
        return plan
    _write_backup_archive(plan)
    return plan


def _collect_wiki_backup_files(
    *,
    runtime_root: Path | None,
    generated_wiki_root: Path | None,
    include_query_index: bool,
    include_review_queue: bool,
    include_missing: bool,
) -> tuple[list[WikiBackupFile], list[dict[str, str]]]:
    files: list[WikiBackupFile] = []
    missing: list[dict[str, str]] = []
    runtime = Path(runtime_root) if runtime_root is not None else None
    runtime_targets: list[tuple[str, Path, str]] = [
        ("registry_db", _runtime_path(runtime, "wiki.db", wiki_runtime_db_path()), "runtime/wiki.db"),
        ("retrieval_manifest", _runtime_path(runtime, "retrieval_manifest.json", wiki_manifest_path()), "runtime/retrieval_manifest.json"),
        ("graph_json", _runtime_path(runtime, "graph.json", wiki_graph_path()), "runtime/graph.json"),
        ("graph_db", _runtime_path(runtime, "graph.db", wiki_graph_db_path()), "runtime/graph.db"),
    ]
    if include_query_index:
        runtime_targets.append(("query_index_db", _runtime_path(runtime, "wiki_query_index.db", wiki_query_index_path()), "runtime/wiki_query_index.db"))
    if include_review_queue:
        runtime_targets.append(("review_queue", _runtime_path(runtime, "review_queue.jsonl", wiki_review_queue_path()), "runtime/review_queue.jsonl"))

    for role, source_path, archive_path in runtime_targets:
        allowed_root = runtime if runtime is not None else source_path.parent
        _append_file_or_missing(
            files,
            missing,
            role,
            source_path,
            archive_path,
            include_missing=include_missing,
            allowed_root=allowed_root,
        )

    page_root = Path(generated_wiki_root) if generated_wiki_root is not None else wiki_generated_root()
    if page_root.exists():
        for page_path in sorted(path for path in page_root.rglob("*") if path.is_file()):
            relative = page_path.relative_to(page_root).as_posix()
            _append_file_or_missing(
                files,
                missing,
                "wiki_page",
                page_path,
                f"generated/wiki/{relative}",
                include_missing=include_missing,
                allowed_root=page_root,
            )
    elif include_missing:
        missing.append({"role": "wiki_pages", "source_path": str(page_root)})

    return files, missing


def _runtime_path(runtime_root: Path | None, filename: str, default_path: Path) -> Path:
    return runtime_root / filename if runtime_root is not None else default_path


def _append_file_or_missing(
    files: list[WikiBackupFile],
    missing: list[dict[str, str]],
    role: str,
    source_path: Path,
    archive_path: str,
    *,
    include_missing: bool,
    allowed_root: Path,
) -> None:
    if source_path.exists() and source_path.is_file():
        resolved_source = source_path.resolve()
        try:
            resolved_source.relative_to(Path(allowed_root).resolve())
        except ValueError:
            if include_missing:
                missing.append({"role": role, "source_path": str(source_path), "reason": "outside_allowed_root"})
            return
        files.append(
            WikiBackupFile(
                role=role,
                source_path=source_path,
                archive_path=archive_path,
                size_bytes=source_path.stat().st_size,
                sha256=_sha256_file(source_path),
            )
        )
    elif include_missing:
        missing.append({"role": role, "source_path": str(source_path)})


def _write_backup_archive(plan: WikiBackupPlan) -> None:
    if not plan.files:
        raise ValueError("cannot write wiki backup archive without files")
    plan.archive_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_payload = plan.to_dict()
    with zipfile.ZipFile(plan.archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        with tempfile.TemporaryDirectory(prefix="wiki-backup-sqlite-") as temp_dir:
            temp_root = Path(temp_dir)
            for selected in plan.files:
                archive_source = _sqlite_snapshot(selected.source_path, temp_root) if _looks_like_sqlite(selected) else selected.source_path
                archive.write(archive_source, selected.archive_path)
    if plan.manifest_path is not None:
        atomic_write_text(
            plan.manifest_path,
            json.dumps(manifest_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )


def _resolve_archive_path(archive_path: Path | None) -> Path:
    if archive_path is None:
        return WORKSPACE_ARTIFACTS_ROOT.joinpath("backups", f"wiki-backup-{_timestamp()}.zip").resolve()
    resolved = Path(archive_path).expanduser().resolve()
    if resolved.exists() and resolved.is_dir():
        raise ValueError("archive_path must be a .zip file path, not a directory")
    if resolved.suffix.lower() != ".zip":
        raise ValueError("archive_path must use a .zip suffix")
    return resolved


def _sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_sqlite(file_entry: WikiBackupFile) -> bool:
    return file_entry.role.endswith("_db") or file_entry.source_path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}


def _sqlite_snapshot(source_path: Path, temp_root: Path) -> Path:
    snapshot_path = temp_root / source_path.name
    source_conn = sqlite3.connect(str(source_path), timeout=10.0)
    snapshot_conn = sqlite3.connect(str(snapshot_path), timeout=10.0)
    try:
        source_conn.backup(snapshot_conn)
    finally:
        snapshot_conn.close()
        source_conn.close()
    return snapshot_path


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
