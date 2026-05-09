from __future__ import annotations

import argparse
import gc
import json
import tempfile
from pathlib import Path
from typing import Any, Sequence

from literature_assistant.core.wiki.backup import build_wiki_backup_plan
from literature_assistant.core.wiki.compiler import WikiCompiler
from literature_assistant.core.wiki.doctor import WikiDoctor
from literature_assistant.core.wiki.migration import evidence_refs_migration_dry_run
from literature_assistant.core.wiki.page_store import WikiPageStore
from literature_assistant.core.wiki.page_store import render_page
from literature_assistant.core.wiki.query import WikiQueryIndex, build_wiki_index, save_exploration
from literature_assistant.core.wiki.source_registry import (
    ChunkInput,
    SourceRecord,
    WikiRegistry,
    derive_chunk_id,
    derive_source_id,
    sha256_text,
    utc_now_iso,
)


def run_wave15_end_to_end_dry_run() -> dict[str, Any]:
    """Run source -> compile dry-run -> doctor -> query-save in a temp workspace."""

    with tempfile.TemporaryDirectory(prefix="wiki-wave15-e2e-") as temp_dir:
        root = Path(temp_dir)
        registry = WikiRegistry(root / "runtime" / "wiki.db")
        page_store = WikiPageStore(root / "generated" / "wiki")
        query_index = WikiQueryIndex(root / "runtime" / "wiki_query_index.db")
        payload: dict[str, Any]

        source_text = (
            "Laser welding improves joint stability when process windows are controlled. "
            "Shielding gas and pulse energy affect melt pool consistency."
        )
        source_hash = sha256_text(source_text)
        source_id = derive_source_id("paper", "Wave 15 Dry Run Paper", source_hash)
        registry.upsert_source(
            SourceRecord(
                source_id=source_id,
                source_type="paper",
                title="Wave 15 Dry Run Paper",
                source_hash=source_hash,
                source_path=root / "raw" / "wave15-paper.md",
            ),
            now_iso=utc_now_iso(),
        )
        registry.register_chunks(
            source_id,
            source_hash,
            [
                ChunkInput(
                    text="Laser welding improves joint stability when process windows are controlled.",
                    chunk_index=0,
                    page="1",
                    section="Results",
                ),
                ChunkInput(
                    text="Shielding gas and pulse energy affect melt pool consistency.",
                    chunk_index=1,
                    page="2",
                    section="Process",
                ),
            ],
            now_iso=utc_now_iso(),
        )
        evidence_refs = [
            {
                "chunk_id": derive_chunk_id(source_hash, 0),
                "material_id": "wave15-paper",
                "source_id": source_id,
                "text": "Laser welding improves joint stability when process windows are controlled.",
                "compressed_text": "Laser welding improves joint stability.",
                "quote": "Laser welding improves joint stability",
                "label": "wave15-dry-run",
            }
        ]

        try:
            migration = evidence_refs_migration_dry_run(evidence_refs, registry=registry)
            compile_preview = WikiCompiler(registry, page_store).compile_source(source_id, dry_run=True)
            compile_write = WikiCompiler(registry, page_store).compile_source(source_id, dry_run=False)
            source_page = page_store.read_page(Path("sources/wave-15-dry-run-paper.md"))
            if source_page:
                page_store.write_rendered(
                    render_page(
                        Path("sources/wave-15-dry-run-paper.md"),
                        {
                            "id": source_id,
                            "kind": "source",
                            "title": "Wave 15 Dry Run Paper",
                            "status": "draft",
                            "source_type": "paper",
                            "source_hash": source_hash,
                            "chunk_count": 2,
                        },
                        source_page.split("<!-- literature-assistant:auto:start -->", 1)[-1].split(
                            "<!-- literature-assistant:auto:end -->",
                            1,
                        )[0].strip(),
                    )
                )
            build_wiki_index(page_store, query_index)
            query_hits = query_index.search("laser welding stability", limit=3)
            exploration_refs = [
                {
                    **evidence_refs[0],
                    "source_id": "sources/wave-15-dry-run-paper",
                }
            ]
            exploration = save_exploration(
                "How does laser welding affect stability?",
                "Laser welding can improve joint stability when the process window is controlled.",
                exploration_refs,
                page_store,
                source_ids=("sources/wave-15-dry-run-paper",),
            )
            build_wiki_index(page_store, query_index)
            doctor = WikiDoctor(page_store, registry=registry, query_index=query_index).run()
            backup_plan = build_wiki_backup_plan(
                archive_path=root / "backup" / "wiki-wave15-dry-run.zip",
                runtime_root=root / "runtime",
                generated_wiki_root=root / "generated" / "wiki",
                dry_run=True,
            )
            payload = {
                "mode": "temp_workspace_no_runtime_artifacts",
                "migration": migration.to_dict(),
                "compile_preview": compile_preview.__dict__,
                "compile_write": compile_write.__dict__,
                "query_hit_count": len(query_hits),
                "query_hits": [
                    {
                        "page_path": hit.page_path.as_posix(),
                        "title": hit.title,
                        "source": hit.source,
                    }
                    for hit in query_hits
                ],
                "exploration": {
                    "success": exploration.success,
                    "relative_path": exploration.relative_path.as_posix() if exploration.relative_path else None,
                    "content_hash": exploration.content_hash,
                    "error": exploration.error,
                },
                "doctor": doctor.to_dict(),
                "backup_plan": backup_plan.to_dict(),
            }
        finally:
            query_index.close()
            gc.collect()

        return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Wave 15 wiki end-to-end dry-run in a temp workspace.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args(argv)
    payload = run_wave15_end_to_end_dry_run()
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if payload["exploration"]["success"] and payload["query_hit_count"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
