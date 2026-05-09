from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from routers import resources_router as rr
from chunk_size_guard import inspect_chunk
from scripts.scan_oversize_chunks import build_report


def _load_report(report_path: Path) -> dict[str, Any]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid oversize report: {report_path}")
    return payload


def _group_targets(report: dict[str, Any]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for row in report.get("materials", []):
        if not isinstance(row, dict):
            continue
        project_id = str(row.get("project_id") or "").strip()
        material_id = str(row.get("material_id") or "").strip()
        if not project_id or not material_id:
            continue
        grouped.setdefault(project_id, [])
        if material_id not in grouped[project_id]:
            grouped[project_id].append(material_id)
    return grouped


def _preflight_targets(targets: dict[str, list[str]]) -> list[str]:
    blockers: list[str] = []
    for project_id, material_ids in targets.items():
        doc_store = rr._load_doc_store(project_id)
        chunk_store = rr._load_chunk_store(project_id)
        for material_id in material_ids:
            doc = doc_store.get(material_id)
            content = str((doc or {}).get("content") or "").strip()
            chunks = chunk_store.get(material_id) or []
            recovered = _recover_content_from_chunks(chunks)
            if not content and not recovered:
                blockers.append(f"{project_id}/{material_id}: missing source content in doc_store")
                continue
            if not chunks and not content:
                blockers.append(f"{project_id}/{material_id}: missing current chunk_store entry")
    return blockers


def _recover_content_from_chunks(chunks: list[dict[str, Any]]) -> str:
    ordered = sorted(chunks, key=lambda item: int(item.get("chunk_index") or 0))
    recovered_parts: list[str] = []
    for chunk in ordered:
        text = str(chunk.get("raw_content") or chunk.get("content") or "").strip()
        if text:
            recovered_parts.append(text)
    return "\n\n".join(recovered_parts)


def _resolve_source_document(
    project_id: str,
    material_id: str,
    doc_store: dict[str, Any],
    chunk_store: dict[str, list[dict[str, Any]]],
) -> tuple[str, str, bool]:
    document = doc_store.get(material_id) or {}
    title = str(document.get("title") or "").strip()
    content = str(document.get("content") or "").strip()
    if content:
        return title or material_id, content, False

    chunks = chunk_store.get(material_id) or []
    recovered = _recover_content_from_chunks(chunks).strip()
    if recovered:
        if not title and chunks:
            title = str(chunks[0].get("title") or material_id).strip()
        return title or material_id, recovered, True

    raise RuntimeError(f"Directed reslice blocked: {project_id}/{material_id}: missing source content")


def _load_existing_reslice_marks(project_id: str) -> dict[str, str]:
    project_dir = rr._chunk_store_dir(project_id)
    manifest = rr._load_manifest(project_dir)
    materials = manifest.get("materials")
    if not isinstance(materials, dict):
        return {}
    marks: dict[str, str] = {}
    for material_id, entry in materials.items():
        if not isinstance(entry, dict):
            continue
        stamp = str(entry.get("resliced_at") or "").strip()
        if stamp:
            marks[str(material_id)] = stamp
    return marks


def _mark_manifest_entries(project_id: str, stamps: dict[str, str]) -> None:
    project_dir = rr._chunk_store_dir(project_id)
    manifest = rr._load_manifest(project_dir)
    materials = manifest.get("materials")
    if not isinstance(materials, dict):
        raise RuntimeError(f"Invalid chunk manifest for project {project_id}")
    for material_id, resliced_at in stamps.items():
        entry = materials.get(material_id)
        if isinstance(entry, dict):
            entry["resliced_at"] = resliced_at
    rr._atomic_write_text(
        project_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )


def _normalize_chunk_sequence(material_id: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    next_index = 0
    for chunk in chunks:
        current = dict(chunk)
        current["material_id"] = material_id
        current["chunk_index"] = next_index
        current["chunk_id"] = f"{material_id}_chunk_{next_index}"
        current["char_count"] = len(str(current.get("content") or ""))
        normalized.append(current)
        next_index += 1
    return normalized


def _expand_oversize_chunk(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    raw_text = str(chunk.get("raw_content") or chunk.get("content") or "").strip()
    if not raw_text:
        return [dict(chunk)]

    split_segments = rr._split_text_into_chunks(raw_text)
    if len(split_segments) <= 1:
        return [dict(chunk)]

    title = str(chunk.get("title") or chunk.get("material_title") or chunk.get("material_id") or "").strip()
    section_title = str(chunk.get("section_title") or "正文").strip() or "正文"
    chunk_type = str(chunk.get("chunk_type") or "narrative").strip() or "narrative"
    expanded: list[dict[str, Any]] = []
    for segment in split_segments:
        raw_segment = str(segment or "").strip()
        if not raw_segment:
            continue
        expanded.append(
            {
                **dict(chunk),
                "content": f"[文献: {title}][章节: {section_title}][类型: {chunk_type}]\n{raw_segment}",
                "raw_content": raw_segment,
                "embedding": None,
            }
        )
    return expanded or [dict(chunk)]


def _rechunk_material(material_id: str, title: str, content: str) -> list[dict[str, Any]]:
    initial_chunks = rr._chunk_document(material_id, title, content)
    expanded: list[dict[str, Any]] = []
    for chunk in initial_chunks:
        if inspect_chunk(chunk)["is_oversize"]:
            expanded.extend(_expand_oversize_chunk(chunk))
        else:
            expanded.append(dict(chunk))
    return _normalize_chunk_sequence(material_id, expanded)


def reslice_from_report(
    report_path: Path,
    chunk_store_root: Path | None = None,
    *,
    resliced_at: str | None = None,
) -> dict[str, Any]:
    report = _load_report(report_path)
    targets = _group_targets(report)
    if not targets:
        root = chunk_store_root or Path(str(report.get("root") or "output/chunk_store"))
        return {
            "report_path": str(report_path),
            "chunk_store_root": str(root),
            "resliced_material_count": 0,
            "blocked_material_count": 0,
            "remaining_targeted_oversize_count": 0,
            "resliced_at": None,
        }

    blockers = _preflight_targets(targets)
    if blockers:
        raise RuntimeError("Directed reslice blocked: " + "; ".join(blockers))

    reslice_stamp = resliced_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    resliced_material_count = 0
    fallback_material_count = 0

    for project_id, material_ids in targets.items():
        doc_store = rr._load_doc_store(project_id)
        chunk_store = rr._load_chunk_store(project_id)
        existing_marks = _load_existing_reslice_marks(project_id)
        for material_id in material_ids:
            title, content, used_fallback = _resolve_source_document(project_id, material_id, doc_store, chunk_store)
            chunk_store[material_id] = _rechunk_material(material_id, title, content)
            resliced_material_count += 1
            if used_fallback:
                fallback_material_count += 1
        rr._save_chunk_store(project_id, chunk_store)
        for material_id in material_ids:
            existing_marks[material_id] = reslice_stamp
        _mark_manifest_entries(project_id, existing_marks)

    root = chunk_store_root or Path(str(report.get("root") or "output/chunk_store"))
    verification = build_report(root)
    target_keys = {(project_id, material_id) for project_id, items in targets.items() for material_id in items}
    remaining_targeted = [
        row
        for row in verification.get("materials", [])
        if isinstance(row, dict)
        and (str(row.get("project_id") or ""), str(row.get("material_id") or "")) in target_keys
    ]
    return {
        "report_path": str(report_path),
        "chunk_store_root": str(root),
        "resliced_material_count": resliced_material_count,
        "blocked_material_count": 0,
        "fallback_material_count": fallback_material_count,
        "remaining_targeted_oversize_count": len(remaining_targeted),
        "remaining_targeted_materials": remaining_targeted,
        "resliced_at": reslice_stamp,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Directed reslice for oversize materials only.")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("output/oversize_materials_report.json"),
        help="Oversize materials report JSON path.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("output/chunk_store"),
        help="Chunk store root directory for post-reslice verification.",
    )
    args = parser.parse_args(argv)

    summary = reslice_from_report(report_path=args.report, chunk_store_root=args.root)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

