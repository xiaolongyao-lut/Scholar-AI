from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from contextual_chunker import (
    CONTEXTUAL_SUMMARY_FIELDS,
    DEFAULT_ARK_MODEL,
    DEFAULT_ARK_URL,
    summarize_document_json_async,
)


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


def _load_existing_summary(path: Path) -> dict[str, Any] | None:
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


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    ordered = {field: summary[field] for field in CONTEXTUAL_SUMMARY_FIELDS}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")


def precompute_contextual_summaries(
    project_id: str,
    material_ids: list[str] | None = None,
    *,
    chunk_store_root: Path = Path("output") / "chunk_store",
    summaries_root: Path = Path("output") / "contextual_summaries",
    api_key: str | None = None,
    base_url: str = DEFAULT_ARK_URL,
    model: str = DEFAULT_ARK_MODEL,
    limit: int | None = None,
    dry_run: bool = False,
) -> list[Path]:
    project_dir = _project_dir(project_id, chunk_store_root)
    manifest = _load_manifest(project_dir)
    materials = manifest.get("materials", {})
    if not isinstance(materials, dict):
        return []

    target_material_ids = [str(mid) for mid in (material_ids or materials.keys())]
    written: list[Path] = []
    pending: list[tuple[str, dict[str, Any], Path]] = []

    for material_id in target_material_ids:
        entry = materials.get(material_id)
        if not isinstance(entry, dict):
            continue
        output_path = _summary_output_path(project_id, material_id, summaries_root)
        if _load_existing_summary(output_path) is not None:
            written.append(output_path)
            continue
        pending.append((material_id, entry, output_path))

    if limit is not None:
        pending = pending[: max(0, int(limit))]

    if dry_run:
        from llm_pricing import estimate_cost_usd

        total_in = total_out = 0
        skipped = 0
        for _material_id, entry, _output_path in pending:
            relative_path = entry.get("relative_path") or entry.get("file")
            if not relative_path:
                skipped += 1
                continue
            chunks = _read_material_jsonl(project_dir / str(relative_path))
            if not chunks:
                skipped += 1
                continue
            doc_text = "\n".join(str(c.get("content") or "") for c in chunks)[:6000]
            total_in += max(1, len(doc_text) // 4 + 200)
            total_out += 500
        usd = estimate_cost_usd(model, prompt_tokens=total_in, completion_tokens=total_out)
        print(f"[dry-run] cached={len(written)} pending={len(pending)} skipped={skipped}")
        print(f"[dry-run] model={model}")
        print(f"[dry-run] est_input_tokens={total_in} est_output_tokens={total_out} est_usd={usd:.4f}")
        return written

    total = len(pending)
    for idx, (material_id, entry, output_path) in enumerate(pending, start=1):
        relative_path = entry.get("relative_path") or entry.get("file")
        if not relative_path:
            continue
        chunks = _read_material_jsonl(project_dir / str(relative_path))
        if not chunks:
            continue
        summary = asyncio.run(
            summarize_document_json_async(
                chunks,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
        )
        if not isinstance(summary, dict):
            print(f"[{idx}/{total}] FAILED {material_id}")
            continue
        _write_summary(output_path, summary)
        written.append(output_path)
        print(f"[{idx}/{total}] wrote {output_path.name}")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Precompute offline contextual summary artifacts.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--material-ids", nargs="*")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N pending materials.")
    parser.add_argument("--dry-run", action="store_true", help="Estimate token usage and USD cost without calling API.")
    args = parser.parse_args(argv)

    written = precompute_contextual_summaries(
        args.project_id,
        material_ids=list(args.material_ids or []),
        limit=args.limit,
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        print(f"wrote {len(written)} contextual summaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
