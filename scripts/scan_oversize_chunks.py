from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chunk_size_guard import inspect_chunk


def _flatten_chunk_payload(payload: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    if isinstance(payload, list):
        chunks.extend([item for item in payload if isinstance(item, dict)])
    elif isinstance(payload, dict):
        raw_chunks = payload.get("chunks")
        if isinstance(raw_chunks, list):
            chunks.extend([item for item in raw_chunks if isinstance(item, dict)])
        else:
            for value in payload.values():
                if isinstance(value, list):
                    chunks.extend([item for item in value if isinstance(item, dict)])
    return chunks


def _read_v2_material_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _load_v2_project_sources(project_dir: Path) -> list[tuple[str, str, list[dict[str, Any]]]]:
    manifest_path = project_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    materials = manifest.get("materials")
    if not isinstance(materials, dict):
        return []

    sources: list[tuple[str, str, list[dict[str, Any]]]] = []
    for material_id, entry in materials.items():
        if not isinstance(entry, dict):
            continue
        relative_path = entry.get("relative_path") or entry.get("file")
        if not relative_path:
            continue
        material_path = project_dir / str(relative_path)
        chunks = _read_v2_material_jsonl(material_path)
        if not chunks:
            continue
        sources.append((project_dir.name, str(material_path), chunks))
    return sources


def _load_legacy_source(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    return _flatten_chunk_payload(payload)


def _iter_chunk_sources(root: Path) -> list[tuple[str, str, list[dict[str, Any]]]]:
    sources: list[tuple[str, str, list[dict[str, Any]]]] = []
    v2_projects: set[str] = set()

    for project_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if not (project_dir / "manifest.json").exists():
            continue
        v2_projects.add(project_dir.name)
        sources.extend(_load_v2_project_sources(project_dir))

    for path in sorted(root.glob("*.json")):
        project_id = path.name[: -len("_chunks.json")] if path.name.endswith("_chunks.json") else path.stem
        if path.name.endswith("_chunks.json") and project_id in v2_projects:
            continue
        chunks = _load_legacy_source(path)
        if chunks:
            sources.append((project_id, str(path), chunks))

    return sources


def _resolve_material_id(chunk: dict[str, Any]) -> str:
    material_id = str(chunk.get("material_id") or "").strip()
    if material_id:
        return material_id
    chunk_id = str(chunk.get("chunk_id") or "").strip()
    if "_chunk_" in chunk_id:
        return chunk_id.split("_chunk_")[0]
    return chunk_id or "unknown-material"


def _resolve_source_path(chunk: dict[str, Any], fallback: str) -> str:
    for key in ("source_path", "source_file", "relative_path", "source_pdf", "document_path"):
        value = str(chunk.get(key) or "").strip()
        if value:
            return value
    return fallback


def build_report(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    materials: dict[tuple[str, str], dict[str, Any]] = {}
    scanned_chunk_count = 0

    if not root.exists():
        return {
            "root": str(root),
            "thresholds": {},
            "scanned_chunk_count": 0,
            "oversize_chunk_count": 0,
            "oversize_material_count": 0,
            "materials": [],
        }

    for project_id, fallback_source_path, chunks in _iter_chunk_sources(root):
        for chunk in chunks:
            scanned_chunk_count += 1
            metrics = inspect_chunk(chunk)
            if not metrics["is_oversize"]:
                continue
            material_id = _resolve_material_id(chunk)
            key = (project_id, material_id)
            entry = materials.setdefault(
                key,
                {
                    "project_id": project_id,
                    "material_id": material_id,
                    "oversize_chunk_count": 0,
                    "max_char": 0,
                    "max_token": 0,
                    "source_path": _resolve_source_path(chunk, fallback_source_path),
                },
            )
            entry["oversize_chunk_count"] += 1
            entry["max_char"] = max(int(entry["max_char"]), int(metrics["char_count"]))
            entry["max_token"] = max(int(entry["max_token"]), int(metrics["token_count"]))
            if not str(entry.get("source_path") or "").strip():
                entry["source_path"] = _resolve_source_path(chunk, fallback_source_path)

    material_rows = sorted(
        materials.values(),
        key=lambda item: (
            -int(item["oversize_chunk_count"]),
            -int(item["max_char"]),
            str(item["project_id"]),
            str(item["material_id"]),
        ),
    )
    return {
        "root": str(root),
        "thresholds": {
            "max_chars": int(inspect_chunk({"content": ""})["max_chars"]),
            "max_tokens": int(inspect_chunk({"content": ""})["max_tokens"]),
        },
        "scanned_chunk_count": scanned_chunk_count,
        "oversize_chunk_count": sum(int(item["oversize_chunk_count"]) for item in material_rows),
        "oversize_material_count": len(material_rows),
        "materials": material_rows,
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan chunk_store for oversize historical chunks.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("output/chunk_store"),
        help="Chunk store root directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/oversize_materials_report.json"),
        help="Report JSON output path.",
    )
    args = parser.parse_args(argv)

    report = build_report(args.root)
    write_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
