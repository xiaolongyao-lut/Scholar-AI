from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from contextual_chunker import CONTEXTUAL_SUMMARY_FIELDS, batch_contextualize

DEFAULT_CHUNK_STORE_ROOT = Path("output") / "chunk_store"
DEFAULT_SUMMARIES_ROOT = Path("output") / "contextual_summaries"
DEFAULT_LIVE_MISS_LOG = Path("output") / "contextual_miss.jsonl"
DEFAULT_ARCHIVE_DIR = Path("output") / "contextual_miss_archive"
DEFAULT_REPORT_DIR = Path("eval_reports")


def _project_dir(project_id: str, chunk_store_root: Path) -> Path:
    return Path(chunk_store_root) / str(project_id)


def _load_manifest(project_dir: Path) -> dict[str, Any]:
    manifest_path = project_dir / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"materials": {}}
    if isinstance(payload, dict) and isinstance(payload.get("materials"), dict):
        return payload
    return {"materials": {}}


def _read_material_jsonl(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    chunks.append(payload)
    except OSError:
        return []
    return chunks


def _summary_output_path(project_id: str, material_id: str, summaries_root: Path) -> Path:
    return Path(summaries_root) / str(project_id) / f"{material_id}.json"


def _load_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if tuple(payload.keys()) != CONTEXTUAL_SUMMARY_FIELDS:
        return None
    return payload


def _read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip().lstrip("\ufeff")
                if not stripped or not stripped.startswith("{"):
                    continue
                try:
                    payload = json.loads(stripped)
                except (TypeError, ValueError):
                    continue
                if isinstance(payload, dict):
                    records.append(payload)
    except OSError:
        return []
    return records


def _write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def validate_project_contextual_coverage(
    project_id: str,
    *,
    chunk_store_root: Path = DEFAULT_CHUNK_STORE_ROOT,
    summaries_root: Path = DEFAULT_SUMMARIES_ROOT,
) -> dict[str, Any]:
    project_dir = _project_dir(project_id, chunk_store_root)
    manifest = _load_manifest(project_dir)
    materials = manifest.get("materials", {})
    if not isinstance(materials, dict):
        materials = {}

    with tempfile.TemporaryDirectory(prefix="contextual-miss-") as temp_dir:
        validation_miss_log = Path(temp_dir) / "validation_miss.jsonl"
        missing_summary_material_ids: list[str] = []
        invalid_summary_material_ids: list[str] = []
        unreadable_material_ids: list[str] = []
        total_chunks = 0
        validated_materials = 0
        summary_artifact_count = 0

        for material_id, entry in materials.items():
            material_id = str(material_id)
            if not isinstance(entry, dict):
                unreadable_material_ids.append(material_id)
                continue

            summary_path = _summary_output_path(project_id, material_id, summaries_root)
            summary_payload = _load_summary(summary_path)
            if summary_payload is None:
                if summary_path.exists():
                    invalid_summary_material_ids.append(material_id)
                else:
                    missing_summary_material_ids.append(material_id)

            relative_path = entry.get("relative_path") or entry.get("file")
            if not relative_path:
                unreadable_material_ids.append(material_id)
                continue
            chunks = _read_material_jsonl(project_dir / str(relative_path))
            if not chunks:
                unreadable_material_ids.append(material_id)
                continue

            total_chunks += len(chunks)
            batch_contextualize(
                chunks,
                project_id=project_id,
                summaries_root=summaries_root,
                miss_log_path=validation_miss_log,
            )
            validated_materials += 1
            if summary_payload is not None:
                summary_artifact_count += 1

        validation_miss_rows = _read_jsonl_records(validation_miss_log)

    status = "pass"
    if missing_summary_material_ids or invalid_summary_material_ids or unreadable_material_ids or validation_miss_rows:
        status = "fail"

    return {
        "validated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "project_id": str(project_id),
        "material_count": len(materials),
        "validated_material_count": validated_materials,
        "summary_artifact_count": summary_artifact_count,
        "total_chunk_count": total_chunks,
        "missing_summary_material_ids": missing_summary_material_ids,
        "invalid_summary_material_ids": invalid_summary_material_ids,
        "unreadable_material_ids": unreadable_material_ids,
        "validation_miss_count": len(validation_miss_rows),
        "validation_miss_rows": validation_miss_rows[:20],
        "status": status,
    }


def archive_and_reset_live_miss_log(
    live_miss_log: Path = DEFAULT_LIVE_MISS_LOG,
    *,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
) -> dict[str, Any]:
    live_miss_log = Path(live_miss_log)
    archive_dir = Path(archive_dir)
    rows = _read_jsonl_records(live_miss_log)
    blank_project_count = sum(1 for row in rows if not str(row.get("project_id") or "").strip())
    archive_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_path = archive_dir / f"contextual_miss_{ts}.jsonl"
    if live_miss_log.exists():
        text = live_miss_log.read_text(encoding="utf-8")
        _write_text_atomic(archive_path, text)
    _write_text_atomic(live_miss_log, "")

    return {
        "performed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_path": str(live_miss_log),
        "archive_path": str(archive_path),
        "row_count": len(rows),
        "blank_project_count": blank_project_count,
        "status": "archived-and-reset" if rows else "reset-empty-window",
    }


def _default_report_path(project_id: str, report_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return Path(report_dir) / f"contextual_miss_validation_{project_id}_{stamp}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate contextual summary coverage and optionally reset the live miss log.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--chunk-store-root", type=Path, default=DEFAULT_CHUNK_STORE_ROOT)
    parser.add_argument("--summaries-root", type=Path, default=DEFAULT_SUMMARIES_ROOT)
    parser.add_argument("--live-miss-log", type=Path, default=DEFAULT_LIVE_MISS_LOG)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument(
        "--archive-live-log",
        action="store_true",
        help="Archive the current live miss log and reset it to an empty file after validation passes.",
    )
    args = parser.parse_args(argv)

    report = validate_project_contextual_coverage(
        args.project_id,
        chunk_store_root=args.chunk_store_root,
        summaries_root=args.summaries_root,
    )
    cleanup: dict[str, Any] = {
        "requested": bool(args.archive_live_log),
        "performed": False,
        "reason": "validation_failed" if report["status"] != "pass" else "not_requested",
    }
    if args.archive_live_log and report["status"] == "pass":
        cleanup = archive_and_reset_live_miss_log(args.live_miss_log, archive_dir=args.archive_dir)
        cleanup["requested"] = True
        cleanup["performed"] = True
        cleanup["reason"] = "fresh_window_started"
    report["live_miss_log_cleanup"] = cleanup

    report_path = args.report_path or _default_report_path(str(args.project_id), DEFAULT_REPORT_DIR)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(
        f"status={report['status']} material_count={report['material_count']} "
        f"summary_artifact_count={report['summary_artifact_count']} validation_miss_count={report['validation_miss_count']}"
    )
    print(f"report={report_path}")
    if cleanup.get("performed"):
        print(f"live_miss_log_reset={cleanup['archive_path']}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
