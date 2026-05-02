from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "literature_assistant" / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from routers.resources_router import load_project_chunks_for_rag


def _chunk_content(chunk: Mapping[str, Any]) -> str:
    return str(
        chunk.get("content")
        or chunk.get("raw_content")
        or chunk.get("text")
        or chunk.get("source_text")
        or ""
    ).strip()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return str(value)


def _normalize_export_chunk(project_id: str, chunk: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    content = _chunk_content(chunk)
    if not content:
        return None

    material_id = str(chunk.get("material_id") or "").strip() or None
    chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or f"{material_id or 'chunk'}_{index}").strip()
    if not chunk_id:
        return None

    return {
        "project_id": project_id,
        "chunk_id": chunk_id,
        "material_id": material_id,
        "title": str(chunk.get("title") or chunk.get("source") or material_id or chunk_id).strip(),
        "section_title": str(chunk.get("section_title") or chunk.get("section") or "").strip() or None,
        "page": _json_safe(chunk.get("page")),
        "content": content,
        "source_labels": _json_safe(chunk.get("source_labels") or ["project_chunks"]),
        "source_hint": str(chunk.get("source_hint") or "project_chunks").strip(),
    }


def export_project_chunks(project_id: str, output_path: Path) -> dict[str, Any]:
    """Export one project's normalized chunks to JSONL for TOLF comparison.

    Args:
        project_id: Existing writing project id.
        output_path: JSONL destination path. Parent directories are created.

    Returns:
        Summary payload with exported row count and output path.

    Raises:
        ValueError: If ``project_id`` is empty.
    """
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be a non-empty string")

    rows: list[dict[str, Any]] = []
    for index, chunk in enumerate(load_project_chunks_for_rag(normalized_project_id)):
        if not isinstance(chunk, Mapping):
            continue
        normalized = _normalize_export_chunk(normalized_project_id, chunk, index)
        if normalized is not None:
            rows.append(normalized)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "status": "ok",
        "project_id": normalized_project_id,
        "chunk_count": len(rows),
        "output": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export project chunks as JSONL for TOLF context comparison.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    print(json.dumps(export_project_chunks(args.project_id, Path(args.output)), ensure_ascii=False))


if __name__ == "__main__":
    main()
