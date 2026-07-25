# -*- coding: utf-8 -*-
"""Contract tests for query-scoped evidence-pack generation."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import routers.resources_router as resources_router
import routers.agent_bridge_router as agent_bridge_router
import routers.intelligent_chat_router as intelligent_chat_router
from literature_assistant.core import academic_english_resources
from literature_assistant.core import product_docs_knowledge
from literature_assistant.core.source_vault import SourceChunkInput, SourceVault, derive_chunk_id
from literature_assistant.core.skill_package_knowledge import search_skill_package
from literature_assistant.core.wiki.page_store import WikiPageStore, render_page
from literature_assistant.core.wiki.query import WikiQueryIndex, build_wiki_index
from python_adapter_server import app


def _client() -> TestClient:
    """Return the shared FastAPI test client for evidence-pack contracts."""

    return TestClient(app)


def _create_project(client: TestClient, title: str = "Evidence Pack Project") -> dict[str, Any]:
    """Create a project through the public resources API."""

    response = client.post("/resources/project", json={"title": title})
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["project_id"], str)
    return payload


def _write_chunk_fixture(project_id: str) -> None:
    """Persist chunks with private fields that must never reach evidence packs."""

    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_pack": [
                {
                    "chunk_id": "pack_chunk_1",
                    "material_id": "mat_pack",
                    "title": "AlSi10Mg porosity fatigue evidence",
                    "summary": "The alloy has a documented surface-related fatigue risk.",
                    "content": "AlSi10Mg porosity affects fatigue crack initiation near the surface. Fig. 1 shows the weld surface morphology.",
                    "abstract": "SHOULD_NOT_LEAK_ABSTRACT",
                    "ocr_text": "SHOULD_NOT_LEAK_OCR",
                    "raw_ocr_blocks": [{"text": "SHOULD_NOT_LEAK_BLOCK"}],
                    "private_note": "SHOULD_NOT_LEAK_PRIVATE",
                    "page": 9,
                    "chunk_index": 1,
                    "chunk_type": "body",
                    "source_relative_path": "papers/alsi10mg.pdf",
                    "source_labels": ["bm25", "layout_pdf"],
                    "anchor_kind": "text",
                    "bbox_unit": "normalized_ratio",
                    "figure_candidate": "figure:porosity-1",
                    "image_paths": ["figure_assets/extracted/porosity/p0009_img001.png"],
                    "locator": {
                        "page": 9,
                        "chunk_index": 1,
                        "bbox": [0.11, 0.22, 0.33, 0.44],
                        "bbox_unit": "normalized_ratio",
                        "text": "SHOULD_NOT_LEAK_LOCATOR_TEXT",
                    },
                },
                {
                    "chunk_id": "pack_chunk_2",
                    "material_id": "mat_pack",
                    "title": "Unrelated corrosion note",
                    "content": "Corrosion electrolyte setup.",
                    "abstract": "SHOULD_NOT_LEAK_SECOND_ABSTRACT",
                    "page": 2,
                },
            ]
        },
    )


def _seed_academic_english_output(root: Path) -> None:
    """Create a minimal generated academic-English package for evidence-pack tests."""

    root.mkdir(parents=True, exist_ok=True)
    text = "Evidence-bound claim scope and hedging keep academic prose aligned with source support. " * 12
    chunk = {
        "chunk_id": "chunk-evidence-bound-claim-scope",
        "source_id": "academic-habits",
        "source_type": "markdown_policy",
        "source_path": "references/english_discourse_habits.md",
        "source_hash": "a" * 64,
        "title": "Evidence Bound Claim Scope",
        "section": "claims",
        "text": text,
        "summary": "Evidence-bound claim scope and hedging.",
        "content_hash": "b" * 64,
        "span_start": 10,
        "span_end": 10 + len(text),
        "rhetorical_moves": ["hedging"],
        "features": ["evidence_bound"],
        "keywords": ["evidence-bound", "claim", "scope", "hedging"],
    }
    (root / "chunks.jsonl").write_text(json.dumps(chunk, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "phrases.jsonl").write_text("", encoding="utf-8")
    (root / "academic_english_habits.json").write_text(
        json.dumps(
            {
                "knowledge_type": "academic_english_habits",
                "purpose": "Academic English discourse policy.",
                "policy_markdown": "MODEL_CONTEXT_SHOULD_STAY_BEHIND_RESOURCE_READ",
                "policy_loaded": True,
                "policy_content_hash": "c" * 64,
                "policy_char_count": 48,
                "source_label": "references/english_discourse_habits.md",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "builder_version": "0.2.0",
                "built_at": "2026-06-24T00:00:00+00:00",
                "counts": {"chunks": 1, "phrases": 0},
                "knowledge_sources": {
                    "academic_english_habits": {
                        "source_label": "references/english_discourse_habits.md",
                        "loaded": True,
                        "load_status": "loaded",
                        "content_hash": "c" * 64,
                        "char_count": 48,
                    }
                },
                "output_artifacts": {
                    "chunks_jsonl": {
                        "exists": True,
                        "bytes": (root / "chunks.jsonl").stat().st_size,
                        "sha256": "d" * 64,
                        "status": "written",
                        "rows": 1,
                    },
                    "phrases_jsonl": {
                        "exists": True,
                        "bytes": 0,
                        "sha256": "e" * 64,
                        "status": "written",
                        "rows": 0,
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _seed_source_vault(tmp_path: Path, project_id: str) -> tuple[SourceVault, str]:
    """Create one project-linked Source Vault chunk for evidence-pack tests."""

    vault = SourceVault(
        db_path=tmp_path / "source_vault" / "source_vault.sqlite3",
        storage_root=tmp_path / "source_vault",
    )
    source = vault.upsert_source_bytes(
        b"source vault original bytes",
        filename="source-vault-paper.pdf",
        source_type="pdf",
        title="Source Vault Evidence Paper",
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        project_id=project_id,
        now_iso="2026-06-24T00:00:00Z",
    ).source
    vault.register_chunks(
        source.source_id,
        [
            SourceChunkInput(
                text=(
                    "Source Vault molten pool evidence stays behind bounded resource reads. "
                    "MODEL_CONTEXT_SHOULD_STAY_BEHIND_SOURCE_VAULT_RESOURCE_READ. "
                    "Molten pool porosity fatigue context is project scoped."
                ),
                chunk_index=0,
                page=3,
                span_start=40,
                span_end=207,
                section="results",
            )
        ],
        now_iso="2026-06-24T00:01:00Z",
    )
    return vault, derive_chunk_id(source.source_hash, "chunker-v1", 0)


def test_evidence_pack_build_returns_mcp_safe_lexical_pack() -> None:
    """POST evidence-pack/build returns refs, scores, and explicit rerank fallback."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "section_id": "intro",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_pack_ref"].startswith("evidence_pack:")
    assert payload["project_id"] == project_id
    assert payload["query"] == "AlSi10Mg porosity fatigue"
    assert payload["section_id"] == "intro"
    assert payload["retrieval_method"] == "lexical"
    assert payload["rerank_status"] == "unavailable"
    diagnostics = payload["retrieval_diagnostics"]
    assert diagnostics["retrieval_method"] == "lexical"
    assert diagnostics["embedding_status"] == "unavailable"
    assert diagnostics["rerank_status"] == "unavailable"
    assert "not invoked" in diagnostics["fallback_reason"]
    assert diagnostics["project_weight"] == 1.0
    assert diagnostics["wiki_weight"] == 0.0
    assert diagnostics["locator_coverage"] == {
        "schema_version": "scholar-ai-evidence-locator-coverage/v1",
        "total_refs": 1,
        "project_ref_count": 1,
        "non_project_ref_count": 0,
        "material_locator_count": 1,
        "page_locator_count": 1,
        "bbox_locator_count": 1,
        "invalid_bbox_count": 0,
        "missing_locator_count": 0,
        "page_coverage_ratio": 1.0,
        "bbox_coverage_ratio": 1.0,
        "bbox_unit_counts": {"normalized_ratio": 1},
        "source_label_count": 1,
        "source_label_coverage_ratio": 1.0,
        "figure_table_locator_count": 1,
        "coverage_state": "layout_complete",
        "risk_level": "none",
        "sample_figure_table_ids": ["figure:porosity-1"],
        "sample_invalid_bbox_ref_ids": [],
        "sample_missing_ref_ids": [],
        "notes": [
            "Every project ref has material, page, and bbox locators.",
            "Some project refs are linked to figure/table candidates for layout-aware review.",
        ],
    }
    assert diagnostics["reasoning_trace"]
    assert any("lexical" in item.lower() for item in diagnostics["reasoning_trace"])
    assert diagnostics["notes"]
    outcome = payload["outcome"]
    assert outcome["schema_version"] == "scholar-ai-tool-outcome/v1"
    assert outcome["status"] == "degraded"
    assert outcome["quality"] == "refs_only"
    assert outcome["next_action"]["kind"] == "read_resource"
    assert outcome["next_action"]["endpoint"] == (
        f"/api/agent-bridge/resource/chunk:pack_chunk_1?project_id={project_id}"
    )
    attempts = {attempt["stage"]: attempt for attempt in outcome["attempts"]}
    assert attempts["chunk_load"]["status"] == "success"
    assert attempts["chunk_load"]["metadata"]["chunk_count"] == 2
    assert attempts["retrieval"]["metadata"]["retrieval_method"] == "lexical"
    assert attempts["retrieval"]["metadata"]["returned_ref_count"] == 1
    assert attempts["rerank"]["status"] == "skipped"
    assert attempts["rerank"]["error_class"] == "rerank_unavailable"
    assert attempts["locator_coverage"]["status"] == "success"
    assert attempts["locator_coverage"]["metadata"]["coverage_state"] == "layout_complete"
    assert attempts["locator_coverage"]["metadata"]["bbox_coverage_ratio"] == 1.0
    assert attempts["qrels_quality_gate"]["status"] == "skipped"
    assert payload["total"] == 1
    assert payload["truncated"] is False
    ref = payload["evidence_refs"][0]
    assert set(ref) == {
        "project_id",
        "source_type",
        "ref_id",
        "read_endpoint",
        "chunk_id",
        "material_id",
        "page",
        "locator",
        "lexical_score",
        "rerank_score",
        "citation_anchor",
        "figure_candidate",
        "figure_candidate_detail",
        "image_paths",
        "source_labels",
        "summary",
        "suitable_for_body",
        "source_title",
        "source_path",
        "joint_score",
        "quote",
        "anchor_kind",
        "content_hash",
        "locator_hash",
        "chunk_hash",
        "embedding_input_hash",
        "hash_version",
    }
    assert ref["project_id"] == project_id
    assert ref["source_type"] == "project"
    assert ref["ref_id"] == "chunk:pack_chunk_1"
    assert ref["read_endpoint"] == f"/api/agent-bridge/resource/chunk:pack_chunk_1?project_id={project_id}"
    assert ref["chunk_id"] == "pack_chunk_1"
    assert ref["material_id"] == "mat_pack"
    assert ref["page"] == 9
    assert ref["locator"] == {
        "material_id": "mat_pack",
        "chunk_id": "pack_chunk_1",
        "page": 9,
        "chunk_index": 1,
        "bbox": [0.11, 0.22, 0.33, 0.44],
        "bbox_unit": "normalized_ratio",
    }
    assert ref["lexical_score"] > 0
    assert ref["rerank_score"] is None
    assert ref["citation_anchor"]
    assert ref["figure_candidate"] == "figure:porosity-1"
    assert ref["image_paths"] == ["figure_assets/extracted/porosity/p0009_img001.png"]
    assert ref["figure_candidate_detail"]["id"] == "figure:porosity-1"
    assert ref["figure_candidate_detail"]["label"] == "图 1"
    assert ref["figure_candidate_detail"]["page"] == 9
    assert ref["figure_candidate_detail"]["chunk_id"] == "pack_chunk_1"
    assert ref["figure_candidate_detail"]["asset_path"] == "figure_assets/extracted/porosity/p0009_img001.png"
    assert ref["figure_candidate_detail"]["source"] == "chunk_image_paths"
    assert ref["source_labels"] == ["bm25", "layout_pdf"]
    assert ref["suitable_for_body"] is True
    assert ref["source_title"] == "AlSi10Mg porosity fatigue evidence"
    assert ref["source_path"] == "papers/alsi10mg.pdf"
    assert ref["joint_score"] is None
    assert ref["quote"] == "AlSi10Mg porosity affects fatigue crack initiation near the surface."
    assert ref["quote"] != ref["summary"]
    stored_chunk = resources_router._load_chunk_store(project_id)["mat_pack"][0]  # type: ignore[attr-defined]
    assert ref["anchor_kind"] == "text"
    for hash_field in ("content_hash", "locator_hash", "chunk_hash", "embedding_input_hash", "hash_version"):
        assert ref[hash_field] == stored_chunk[hash_field]
    assert len(ref["summary"]) <= 300

    receipt_scope = asyncio.run(
        intelligent_chat_router._sidebar_receipt_evidence_scope(
            request=intelligent_chat_router.IntelligentChatRequest(
                query="AlSi10Mg porosity fatigue",
                tier="balanced",
                project_id=project_id,
                generated_in="mcp_sidebar",
                evidence_pack_ref=payload["evidence_pack_ref"],
            ),
            project_id=project_id,
        )
    )
    assert receipt_scope["top_evidence_refs"][0]["quote"] == ref["quote"]
    assert receipt_scope["top_evidence_refs"][0]["summary"] == ref["summary"]

    serialized = str(payload)
    assert "content" not in ref
    assert "abstract" not in serialized
    assert "SHOULD_NOT_LEAK" not in serialized
    assert "ocr" not in serialized.lower()
    assert "private_note" not in serialized


def test_evidence_pack_build_uses_selective_material_load_for_text_query(
    monkeypatch: Any,
) -> None:
    client = _client()
    project_id = _create_project(client, title="Selective Evidence Pack Project")["project_id"]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_ping": [
                {
                    "chunk_id": "ping_method_chunk",
                    "material_id": "mat_ping",
                    "title": "Ping process parameters",
                    "content": "Circular oscillation used amplitude 1.0 mm at 150 Hz.",
                    "raw_content": "Circular oscillation used amplitude 1.0 mm at 150 Hz.",
                    "chunk_type": "body",
                    "page": 2,
                }
            ],
            "mat_noise": [
                {
                    "chunk_id": "noise_chunk",
                    "material_id": "mat_noise",
                    "title": "Unrelated evidence",
                    "content": "Hardness mapping used a separate specimen.",
                    "chunk_type": "body",
                    "page": 8,
                }
            ],
        },
    )

    def _unexpected_full_load(_project_id: str) -> dict[str, list[dict[str, Any]]]:
        raise AssertionError("healthy text evidence-pack build must not load the full chunk store")

    monkeypatch.setattr(resources_router, "_load_chunk_store", _unexpected_full_load)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "circular oscillation amplitude 1.0 mm 150 Hz",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    refs = response.json()["evidence_refs"]
    assert refs
    assert refs[0]["chunk_id"] == "ping_method_chunk"


def test_evidence_pack_build_fts_miss_preserves_nonempty_store_outcome() -> None:
    """A current zero-hit FTS result must not look like an empty project."""

    client = _client()
    project_id = _create_project(client, title="Evidence Pack Miss Project")["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "qzxv blorf unmatched sentinel",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_refs"] == []
    assert payload["outcome"]["reason"] == (
        "Project chunks were indexed, but this query returned no evidence refs."
    )
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["chunk_load"]["status"] == "success"
    assert attempts["chunk_load"]["error_class"] == ""
    assert attempts["retrieval"]["error_class"] == "retrieval_empty"


def test_ping_deep_method_quote_survives_search_pack_and_sidebar_receipt() -> None:
    """A method sentence beyond the old prefix window remains exact end to end."""

    client = _client()
    project = _create_project(client, title="Ping Deep Quote Project")
    project_id = project["project_id"]
    target_sentence = (
        "For a 3 mm plate, the laser followed circular oscillation with an amplitude "
        "of 1.0 mm at 150 Hz and zero defocus while evaluating focus and surface formation."
    )
    source_text = (
        "Prior experimental context remains outside this method record. " * 18
    ) + target_sentence
    assert source_text.index("1.0 mm") > 1100
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_ping": [
                {
                    "chunk_id": "mat_ping_chunk_19",
                    "material_id": "mat_ping",
                    "title": "Ping laser oscillation method",
                    "summary": "A paraphrased overview of the closest processing configuration.",
                    "content": source_text,
                    "raw_content": source_text,
                    "page": 4,
                    "chunk_index": 19,
                    "chunk_type": "body",
                    "anchor_kind": "text",
                    "source_labels": ["layout_pdf"],
                }
            ]
        },
    )
    query = "circular oscillation amplitude 1.0 mm 150 Hz"

    search_response = client.get(
        "/resources/chunks/search-refs",
        params={"project_id": project_id, "query": query, "top_k": 5},
    )
    assert search_response.status_code == 200
    search_ref = search_response.json()["refs"][0]
    search_quote = search_ref["metadata"]["quote"]
    assert search_ref["chunk_id"] == "mat_ping_chunk_19"
    assert "1.0 mm" in search_quote
    assert "150 Hz" in search_quote
    assert search_quote in source_text
    assert len(search_quote) <= 320
    assert not search_quote.endswith("…")

    pack_response = client.post(
        "/api/evidence-pack/build",
        json={"project_id": project_id, "query": query, "top_k": 5},
    )
    assert pack_response.status_code == 200
    pack = pack_response.json()
    pack_ref = next(
        ref for ref in pack["evidence_refs"] if ref["chunk_id"] == "mat_ping_chunk_19"
    )
    assert pack_ref["quote"] == search_quote
    assert pack_ref["quote"] != pack_ref["summary"]

    receipt_scope = asyncio.run(
        intelligent_chat_router._sidebar_receipt_evidence_scope(
            request=intelligent_chat_router.IntelligentChatRequest(
                query=query,
                tier="balanced",
                project_id=project_id,
                generated_in="mcp_sidebar",
                evidence_pack_ref=pack["evidence_pack_ref"],
            ),
            project_id=project_id,
        )
    )
    receipt_ref = next(
        ref
        for ref in receipt_scope["top_evidence_refs"]
        if ref["chunk_id"] == "mat_ping_chunk_19"
    )
    assert receipt_ref["quote"] == search_quote


def test_evidence_pack_build_adds_source_label_fallback_for_project_refs() -> None:
    """Project refs without chunk labels still expose deterministic provenance."""

    client = _client()
    project = _create_project(client, title="Evidence Pack Source Label Fallback")
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "Corrosion electrolyte setup",
            "top_k": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    ref = payload["evidence_refs"][0]
    assert ref["chunk_id"] == "pack_chunk_2"
    assert ref["source_labels"] == ["lexical", "project_chunks"]
    coverage = payload["retrieval_diagnostics"]["locator_coverage"]
    assert coverage["source_label_count"] == 1
    assert coverage["source_label_coverage_ratio"] == 1.0


def test_evidence_pack_project_chunk_selection_uses_gateway_when_fts_is_valid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Evidence-pack project refs should share the Gateway candidate arm."""

    import routers.evidence_router as evidence_router
    from chunk_fts_index import rebuild_chunk_fts_index
    from chunk_hashing import compute_chunk_store_version

    store = {
        "mat_gateway": [
            {
                "chunk_id": "pack_gateway_1",
                "material_id": "mat_gateway",
                "title": "Gateway evidence pack paper",
                "content": "AlSi10Mg keyhole porosity evidence at laser power 2000 W.",
                "raw_content": "AlSi10Mg keyhole porosity evidence at laser power 2000 W.",
                "page": 4,
                "bbox": [0.1, 0.2, 0.3, 0.4],
            }
        ]
    }
    db_path = tmp_path / "chunks.sqlite3"
    rebuild_chunk_fts_index(
        db_path=db_path,
        project_id="proj_gateway_pack",
        store=store,
        chunk_store_version=compute_chunk_store_version(store),
    )
    monkeypatch.setattr(evidence_router._resources_router, "_ensure_project_chunks", lambda _project_id: store)
    monkeypatch.setattr(evidence_router._resources_router, "_chunk_fts_index_path", lambda _project_id: db_path)
    monkeypatch.setattr(
        evidence_router,
        "_select_search_ref_chunks",
        lambda *_args, **_kwargs: pytest.fail("legacy evidence-pack selector must not run when Gateway FTS is valid"),
    )

    selected = evidence_router._select_project_evidence_chunks(
        project_id="proj_gateway_pack",
        all_chunks=list(store["mat_gateway"]),
        query="AlSi10Mg keyhole porosity laser power 2000 W",
        top_k=1,
    )

    assert selected
    assert selected[0][1]["chunk_id"] == "pack_gateway_1"
    assert selected[0][1]["retrieval_sources"] == ["lexical"]


def test_evidence_pack_project_chunk_selection_supplements_underfilled_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gateway-ranked evidence keeps priority but lexical fallback can fill top_k."""

    import routers.evidence_router as evidence_router

    all_chunks = [
        {
            "chunk_id": "pack_gateway_1",
            "material_id": "mat_gateway_1",
            "title": "Gateway first paper",
            "content": "AlSi10Mg porosity fatigue crack initiation evidence.",
        },
        {
            "chunk_id": "pack_gateway_2",
            "material_id": "mat_gateway_2",
            "title": "Gateway supplement paper",
            "content": "Oscillating laser strategies reduce porosity in AlSi10Mg processing.",
        },
    ]

    def _gateway_hits(**_kwargs: Any) -> list[dict[str, Any]]:
        return [{**all_chunks[0], "score": 0.95, "retrieval_sources": ["lexical"]}]

    monkeypatch.setattr(evidence_router._resources_router, "_search_chunks_via_gateway", _gateway_hits)

    selected = evidence_router._select_project_evidence_chunks(
        project_id="proj_gateway_pack_supplement",
        all_chunks=all_chunks,
        query="AlSi10Mg porosity fatigue laser oscillation",
        top_k=2,
    )

    assert [chunk["chunk_id"] for _score, chunk in selected] == [
        "pack_gateway_1",
        "pack_gateway_2",
    ]


def test_evidence_pack_integrity_gate_passes_visual_pack_with_pixel_assets() -> None:
    """Evidence-pack gate validates query-scoped image refs, not export readiness."""

    client = _client()
    project = _create_project(client, title="Evidence Pack Integrity Visual Project")
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    build_response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg 外观 图片 表面形貌",
            "top_k": 5,
        },
    )
    assert build_response.status_code == 200
    pack = build_response.json()

    gate_response = client.post(
        "/api/evidence-pack/integrity-gate",
        json={
            "project_id": project_id,
            "query": pack["query"],
            "evidence_pack_ref": pack["evidence_pack_ref"],
            "evidence_refs": pack["evidence_refs"],
            "retrieval_diagnostics": pack["retrieval_diagnostics"],
        },
    )

    assert gate_response.status_code == 200
    gate = gate_response.json()
    assert gate["schema_version"] == "scholar_ai_evidence_pack_integrity_gate_v1"
    assert gate["gate_config_hash"].startswith("sha256:")
    assert gate["summary"]["gate_config_hash"] == gate["gate_config_hash"]
    assert gate["provenance"]["gate_config_hash"] == gate["gate_config_hash"]
    assert gate["status"] == "passed"
    assert gate["project_id"] == project_id
    assert gate["visual_intent"]["requires_image_evidence"] is True
    assert "外观" in gate["visual_intent"]["matched_terms"]
    assert gate["summary"]["evidence_ref_count"] >= 1
    assert gate["summary"]["project_ref_count"] >= 1
    assert gate["summary"]["image_ref_count"] == 1
    assert gate["summary"]["whole_page_image_ref_count"] == 0
    assert gate["summary"]["retrieval_method"] == "lexical"
    checks = {check["check_id"]: check for check in gate["checks"]}
    assert checks["visual_image_evidence"]["status"] == "passed"
    assert checks["image_asset_quality"]["status"] == "passed"
    image_sample = next(item for item in gate["sample_refs"] if item["has_image"] is True)
    assert image_sample["source_title"] == "AlSi10Mg porosity fatigue evidence"
    assert image_sample["page"] == 9
    assert image_sample["image_assets"] == [
        "figure_assets/extracted/porosity/p0009_img001.png"
    ]
    assert gate["provenance"]["raw_chunk_text_exposed"] is False
    assert gate["provenance"]["private_chain_of_thought_exposed"] is False


def test_evidence_pack_integrity_gate_restores_refs_from_pack_ref() -> None:
    """A returned evidence_pack_ref is enough to re-check the bounded pack."""

    client = _client()
    project = _create_project(client, title="Evidence Pack Ref Restore Project")
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    build_response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg 外观 图片 表面形貌",
            "top_k": 5,
        },
    )
    assert build_response.status_code == 200
    pack = build_response.json()

    gate_response = client.post(
        "/api/evidence-pack/integrity-gate",
        json={
            "project_id": project_id,
            "evidence_pack_ref": pack["evidence_pack_ref"],
        },
    )

    assert gate_response.status_code == 200
    gate = gate_response.json()
    assert gate["status"] == "passed"
    assert gate["query"] == pack["query"]
    assert gate["visual_intent"]["requires_image_evidence"] is True
    assert gate["summary"]["evidence_ref_count"] == len(pack["evidence_refs"])
    assert gate["summary"]["evidence_pack_restore_status"] == "restored"
    assert gate["summary"]["retrieval_method"] == pack["retrieval_diagnostics"]["retrieval_method"]
    assert gate["gate_config_hash"].startswith("sha256:")
    assert gate["sample_refs"][0]["ref_id"] == pack["evidence_refs"][0]["ref_id"]
    assert gate["provenance"]["restored_from_persisted_build"] is True


def test_evidence_pack_qrels_review_bundle_is_candidate_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Selected evidence packs should generate reviewable candidate qrels only."""

    import routers.evidence_router as evidence_router

    monkeypatch.setattr(evidence_router, "wiki_review_queue_path", lambda: tmp_path / "review_queue.jsonl")
    client = _client()
    project = _create_project(client, title="Evidence Pack Qrels Bundle Project")
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    build_response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue surface morphology",
            "top_k": 3,
        },
    )
    assert build_response.status_code == 200
    pack = build_response.json()

    bundle_response = client.post(
        "/api/evidence-pack/qrels-review-bundle",
        json={
            "project_id": project_id,
            "evidence_pack_ref": pack["evidence_pack_ref"],
            "max_chunks_per_section": 2,
        },
    )

    assert bundle_response.status_code == 200
    payload = bundle_response.json()
    assert payload["schema_version"] == "scholar-ai-qrels-review-bundle/v1"
    assert payload["candidate_only"] is True
    assert payload["candidate_qrels_count"] >= 1
    assert payload["qrels_status"]["status"] == "candidate"
    assert payload["qrels_status"]["semantic_quality_claim_allowed"] is False
    assert payload["outcome"]["next_action"]["kind"] == "review_qrels"
    assert payload["provenance"]["canonical_qrels_promoted"] is False
    assert payload["review_queue_item"]["source"] == "qrels"
    assert payload["review_queue_item"]["metadata"]["allowed_judgments"] == [
        "relevant",
        "partial",
        "offtopic",
        "unknown",
    ]
    assert Path(payload["qrels_candidate_path"]).is_file()
    assert Path(payload["judgment_template_path"]).is_file()
    qrels_text = Path(payload["qrels_candidate_path"]).read_text(encoding="utf-8")
    assert "review_required: true" in qrels_text


def test_evidence_pack_integrity_gate_blocks_visual_pack_without_pixel_assets() -> None:
    """Visual questions must not pass when the supplied evidence refs lack images."""

    client = _client()
    response = client.post(
        "/api/evidence-pack/integrity-gate",
        json={
            "project_id": "project-no-image",
            "query": "AlSi10Mg 激光焊接 外观 图片",
            "evidence_refs": [
                {
                    "project_id": "project-no-image",
                    "source_type": "project",
                    "ref_id": "chunk:no_image_1",
                    "read_endpoint": "/api/agent-bridge/resource/chunk:no_image_1?project_id=project-no-image",
                    "chunk_id": "no_image_1",
                    "material_id": "mat_no_image",
                    "page": 4,
                    "locator": {"page": 4, "bbox": [0.1, 0.1, 0.2, 0.2]},
                    "lexical_score": 4.0,
                    "citation_anchor": "mat_no_image_no_image_1",
                    "summary": "The text mentions weld appearance but no extracted figure asset is linked.",
                    "source_title": "No image paper",
                    "source_path": "papers/no-image.pdf",
                }
            ],
        },
    )

    assert response.status_code == 200
    gate = response.json()
    assert gate["status"] == "blocked"
    assert gate["visual_intent"]["requires_image_evidence"] is True
    assert gate["summary"]["image_ref_count"] == 0
    checks = {check["check_id"]: check for check in gate["checks"]}
    assert checks["visual_image_evidence"]["status"] == "blocked"
    assert checks["visual_image_evidence"]["severity"] == "block"
    assert "pixel-backed image assets" in checks["visual_image_evidence"]["reason"]
    assert any("pixel-backed figure candidates" in action for action in gate["next_actions"])


def test_evidence_pack_build_uses_doc_store_source_path_when_chunk_lacks_it() -> None:
    """Project refs keep file provenance even when legacy chunks omit it."""

    client = _client()
    project = _create_project(client, title="Evidence Pack Doc Store Source Project")
    project_id = project["project_id"]
    resources_router._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_doc_source": {
                "title": "Doc store source paper.pdf",
                "content": "AlSi10Mg laser welding surface morphology evidence.",
                "source_relative_path": "1230/Doc store source paper.pdf",
            }
        },
    )
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_doc_source": [
                {
                    "chunk_id": "chunk_doc_source_1",
                    "material_id": "mat_doc_source",
                    "title": "Doc store source paper.pdf",
                    "content": "AlSi10Mg laser welding surface morphology evidence.",
                    "page": 3,
                    "chunk_index": 1,
                }
            ]
        },
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg laser welding surface morphology",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    ref = response.json()["evidence_refs"][0]
    assert ref["material_id"] == "mat_doc_source"
    assert ref["source_title"] == "Doc store source paper.pdf"
    assert ref["source_path"] == "1230/Doc store source paper.pdf"


def test_evidence_pack_build_blends_pixel_backed_visual_refs_for_appearance_query() -> None:
    """Visual evidence packs should preserve real chunk image assets."""

    client = _client()
    project = _create_project(client, title="Evidence Pack Visual Project")
    project_id = project["project_id"]
    text_chunks = [
        {
            "chunk_id": f"pack_text_hit_{index}",
            "material_id": f"mat_pack_text_{index}",
            "title": f"AlSi10Mg laser welding process evidence {index}",
            "content": "AlSi10Mg laser welding process parameters and porosity suppression.",
            "page": index + 1,
            "chunk_index": index,
        }
        for index in range(5)
    ]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            **{f"mat_pack_text_{index}": [chunk] for index, chunk in enumerate(text_chunks)},
            "mat_pack_page_list": [
                {
                    "chunk_id": "pack_visual_page_list_1",
                    "material_id": "mat_pack_page_list",
                    "title": "AlSi10Mg laser welding figure list",
                    "content": "Figure 7. Weld upper surface appearance and bead formation results.",
                    "raw_content": "Figure 7. Weld upper surface appearance and bead formation results.",
                    "page": 3,
                    "chunk_index": 12,
                    "chunk_type": "figure_caption",
                    "bbox": [0.0, 0.0, 1.0, 1.0],
                    "image_paths": [
                        "figure_assets/extracted/Ping/p0003_page_list.png",
                    ],
                }
            ],
            "mat_pack_cross": [
                {
                    "chunk_id": "pack_visual_cross_section_1",
                    "material_id": "mat_pack_cross",
                    "title": "AlSi10Mg laser welding cross-section figure",
                    "content": "Figure 6. Weld cross-section morphology and penetration depth.",
                    "raw_content": "Figure 6. Weld cross-section morphology and penetration depth.",
                    "page": 9,
                    "chunk_index": 67,
                    "chunk_type": "figure_caption",
                    "bbox": [0.1, 0.2, 0.7, 0.4],
                    "image_paths": [
                        "figure_assets/extracted/Ping/p0009_img001.jpeg",
                    ],
                }
            ],
            "mat_pack_visual": [
                {
                    "chunk_id": "pack_visual_surface_1",
                    "material_id": "mat_pack_visual",
                    "title": "AlSi10Mg laser welding appearance figure",
                    "content": "Figure 7. Weld upper surface appearance and bead formation results.",
                    "raw_content": "Figure 7. Weld upper surface appearance and bead formation results.",
                    "page": 10,
                    "chunk_index": 68,
                    "chunk_type": "figure_caption",
                    "bbox": [0.1, 0.2, 0.7, 0.4],
                    "image_paths": [
                        "figure_assets/extracted/Ping/p0010_img001.jpeg",
                    ],
                }
            ],
        },
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg 外观 上表面 图片",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    refs = response.json()["evidence_refs"]
    visual_refs = [ref for ref in refs if ref["image_paths"]]
    assert [ref["chunk_id"] for ref in visual_refs] == ["pack_visual_surface_1"]
    assert "pack_visual_page_list_1" not in {ref["chunk_id"] for ref in visual_refs}
    assert visual_refs[0]["source_labels"] == ["visual_image_asset"]
    assert visual_refs[0]["figure_candidate_detail"]["asset_path"] == (
        "figure_assets/extracted/Ping/p0010_img001.jpeg"
    )


def test_evidence_pack_build_expands_body_linked_figure_to_caption_asset() -> None:
    """Evidence packs should keep body context while carrying linked caption pixels."""

    client = _client()
    project = _create_project(client, title="Evidence Pack Linked Visual Project")
    project_id = project["project_id"]
    chunk_store = {
        "mat_pack_surface": [
            {
                "chunk_id": "pack_surface_body_ref",
                "material_id": "mat_pack_surface",
                "title": "AlSi10Mg weld surface discussion",
                "content": "AlSi10Mg 上表面焊缝外观和形貌。图3显示了焊缝表面形貌随功率的变化。",
                "raw_content": "图3显示了焊缝表面形貌随功率的变化。",
                "page": 10,
                "chunk_index": 20,
                "chunk_type": "body",
                "bbox": [0.15, 0.62, 0.68, 0.12],
                "linked_figure_ids": ["figure:surface-pack:3"],
            },
            {
                "chunk_id": "pack_surface_caption_fig3",
                "material_id": "mat_pack_surface",
                "title": "AlSi10Mg weld surface figure",
                "content": "图3. 焊缝表面形貌。",
                "raw_content": "图3. 焊缝表面形貌。",
                "page": 10,
                "chunk_index": 21,
                "chunk_type": "figure_caption",
                "bbox": [0.12, 0.18, 0.72, 0.32],
                "figure_id": "figure:surface-pack:3",
                "image_paths": ["figure_assets/extracted/surface/p0010_cap001.png"],
            },
        ],
        "mat_pack_text": [
            {
                "chunk_id": f"pack_surface_text_{index}",
                "material_id": "mat_pack_text",
                "title": f"AlSi10Mg process evidence {index}",
                "content": "AlSi10Mg laser welding process parameters and porosity suppression.",
                "page": index + 1,
                "chunk_index": index,
            }
            for index in range(3)
        ],
    }
    resources_router._save_chunk_store(project_id, chunk_store)  # type: ignore[attr-defined]

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg 上表面 焊缝 外观 形貌 图片",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    refs_by_chunk = {ref["chunk_id"]: ref for ref in response.json()["evidence_refs"]}
    ref = refs_by_chunk["pack_surface_body_ref"]
    assert ref["image_paths"] == ["figure_assets/extracted/surface/p0010_cap001.png"]
    assert ref["figure_candidate"] == "figure:surface-pack:3"
    assert ref["figure_candidate_detail"]["source"] == "linked_caption_chunk"
    assert "visual_linked_caption_asset" in ref["source_labels"]
    assert "visual_image_asset" in ref["source_labels"]

    persisted = resources_router._load_chunk_store(project_id)  # type: ignore[attr-defined]
    assert "image_paths" not in persisted["mat_pack_surface"][0]
    assert persisted["mat_pack_surface"][0]["linked_figure_ids"] == ["figure:surface-pack:3"]


def test_evidence_pack_build_blends_project_figure_asset_files_without_mutating_chunks() -> None:
    """Evidence packs should use derived project figure files as image evidence."""

    client = _client()
    project = _create_project(client, title="Evidence Pack Derived Visual Project")
    project_id = project["project_id"]
    chunk_store = {
        "mat_pack_surface": [
            {
                "chunk_id": "pack_surface_asset_chunk",
                "material_id": "mat_pack_surface",
                "title": "AlSi10Mg laser welding surface figure",
                "content": "Figure 7. Weld upper surface appearance, morphology, and bead formation.",
                "raw_content": "Figure 7. Weld upper surface appearance, morphology, and bead formation.",
                "page": 12,
                "chunk_index": 8,
                "chunk_type": "figure_caption",
                "bbox": [0.12, 0.18, 0.52, 0.34],
            }
        ],
        "mat_pack_text": [
            {
                "chunk_id": f"pack_text_only_{index}",
                "material_id": "mat_pack_text",
                "title": f"AlSi10Mg process evidence {index}",
                "content": "AlSi10Mg laser welding process parameters and porosity suppression.",
                "page": index + 1,
                "chunk_index": index,
            }
            for index in range(4)
        ],
    }
    resources_router._save_chunk_store(project_id, chunk_store)  # type: ignore[attr-defined]
    asset_path = resources_router.project_data_path(  # type: ignore[attr-defined]
        project_id,
        "figure_assets",
        "mat_pack_surface",
        "pack_surface_asset_chunk-Figure7-feedface.jpg",
    )
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"derived project figure asset")

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg 外观 上表面 图片",
            "top_k": 4,
        },
    )

    assert response.status_code == 200
    refs = response.json()["evidence_refs"]
    refs_by_chunk = {ref["chunk_id"]: ref for ref in refs}
    ref = refs_by_chunk["pack_surface_asset_chunk"]
    assert ref["image_paths"] == [
        "figure_assets/mat_pack_surface/pack_surface_asset_chunk-Figure7-feedface.jpg"
    ]
    assert ref["figure_candidate_detail"]["source"] == "project_figure_asset"
    assert ref["figure_candidate_detail"]["asset_path"] == (
        "figure_assets/mat_pack_surface/pack_surface_asset_chunk-Figure7-feedface.jpg"
    )
    assert "visual_project_figure_asset" in ref["source_labels"]
    assert "visual_image_asset" in ref["source_labels"]

    assert "image_paths" not in chunk_store["mat_pack_surface"][0]
    assert "asset_path" not in chunk_store["mat_pack_surface"][0]


def test_evidence_pack_build_reports_invalid_bbox_locator_gap() -> None:
    """Evidence-pack diagnostics must retain invalid bbox repair signals."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_pack_invalid_bbox": [
                {
                    "chunk_id": "pack_chunk_invalid_bbox",
                    "material_id": "mat_pack_invalid_bbox",
                    "title": "AlSi10Mg invalid bbox evidence",
                    "summary": "AlSi10Mg evidence with invalid bbox metadata.",
                    "content": "AlSi10Mg evidence with invalid bbox metadata.",
                    "page": 6,
                    "locator": {
                        "material_id": "mat_pack_invalid_bbox",
                        "chunk_id": "pack_chunk_invalid_bbox",
                        "page": 6,
                        "bbox": [0.1, 0.2, 1.5, 0.3],
                        "bbox_unit": "normalized_ratio",
                    },
                }
            ]
        },
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg invalid bbox",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    coverage = payload["retrieval_diagnostics"]["locator_coverage"]
    assert coverage["coverage_state"] == "page_located"
    assert coverage["risk_level"] == "warn"
    assert coverage["page_locator_count"] == 1
    assert coverage["bbox_locator_count"] == 0
    assert coverage["invalid_bbox_count"] == 1
    assert coverage["sample_invalid_bbox_ref_ids"] == ["chunk:pack_chunk_invalid_bbox"]
    assert payload["evidence_refs"][0]["locator"] == {
        "material_id": "mat_pack_invalid_bbox",
        "chunk_id": "pack_chunk_invalid_bbox",
        "page": 6,
    }
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["locator_coverage"]["status"] == "degraded"
    assert attempts["locator_coverage"]["error_class"] == "locator_coverage_page_located"
    assert attempts["locator_coverage"]["metadata"]["invalid_bbox_count"] == 1
    serialized = str(payload)
    assert "1.5" not in serialized
    assert "[0.1, 0.2, 1.5, 0.3]" not in serialized


def test_evidence_pack_build_reports_hybrid_rerank_when_retriever_returns_dense_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence-pack build should expose actual dense/rerank participation."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    class _HybridRetriever:
        def __init__(self, use_reranker: bool | None = None) -> None:
            self.use_reranker = use_reranker

        async def search(
            self,
            raw_data: dict[str, Any],
            query: str,
            top_k: int = 10,
            focus_keywords: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            chunks = raw_data["chunks"]
            hit = dict(chunks[0])
            hit["hybrid_score"] = 0.87
            hit["rerank_score"] = 0.93
            hit["source_labels"] = ["bm25", "dense", "rerank"]
            return [hit]

    import routers.evidence_router as evidence_router

    monkeypatch.setattr(
        evidence_router,
        "_resolve_hybrid_retriever_class",
        lambda: _HybridRetriever,
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "section_id": "intro",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval_method"] == "hybrid_rerank"
    assert payload["rerank_status"] == "active"
    assert payload["retrieval_diagnostics"]["qrels_status"]["status"] == "missing"
    assert payload["retrieval_diagnostics"]["qrels_status"]["semantic_quality_claim_allowed"] is False
    diagnostics = payload["retrieval_diagnostics"]
    assert diagnostics["retrieval_method"] == "hybrid_rerank"
    assert diagnostics["embedding_status"] == "active"
    assert diagnostics["rerank_status"] == "active"
    assert diagnostics["fallback_reason"] == ""
    assert any("HybridRetrieverWithRerank" in item for item in diagnostics["reasoning_trace"])
    outcome = payload["outcome"]
    assert outcome["status"] == "success"
    assert outcome["quality"] == "refs_only"
    attempts = {attempt["stage"]: attempt for attempt in outcome["attempts"]}
    assert attempts["retrieval"]["metadata"]["retrieval_method"] == "hybrid_rerank"
    assert attempts["rerank"]["status"] == "success"
    assert attempts["rerank"]["error_class"] == ""
    ref = payload["evidence_refs"][0]
    assert ref["ref_id"] == "chunk:pack_chunk_1"
    assert ref["rerank_score"] == 0.93
    assert "content" not in ref


def test_evidence_pack_build_hybrid_refs_recover_locator_from_chunk_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hybrid hits stripped by retriever/cache should recover source locators."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_hybrid_locator": [
                {
                    "chunk_id": "pack_hybrid_locator",
                    "material_id": "mat_hybrid_locator",
                    "title": "Hybrid locator recovery paper",
                    "content": "AlSi10Mg surface morphology evidence with source page.",
                    "page": 7,
                    "chunk_index": 4,
                    "bbox": [0.12, 0.18, 0.42, 0.52],
                }
            ]
        },
    )

    class _HybridRetriever:
        def __init__(self, use_reranker: bool | None = None) -> None:
            self.use_reranker = use_reranker

        async def search(
            self,
            raw_data: dict[str, Any],
            query: str,
            top_k: int = 10,
            focus_keywords: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            return [
                {
                    "chunk_id": "pack_hybrid_locator",
                    "material_id": "mat_hybrid_locator",
                    "title": "Hybrid locator recovery paper",
                    "content": "AlSi10Mg surface morphology evidence with source page.",
                    "chunk_index": 4,
                    "hybrid_score": 0.88,
                    "rerank_score": 0.91,
                    "source_labels": ["bm25", "dense", "rerank"],
                }
            ]

    import routers.evidence_router as evidence_router
    import routers.resources_router.endpoints_search_upload as search_upload

    def _fake_enrich_locator(
        enriched_project_id: str,
        chunk_store: dict[str, list[dict[str, Any]]],
        locator: dict[str, Any],
    ) -> dict[str, Any]:
        assert enriched_project_id == project_id
        assert "mat_hybrid_locator" in chunk_store
        return {
            **locator,
            "page": 7,
            "bbox": [0.12, 0.18, 0.42, 0.52],
            "bbox_unit": "normalized_ratio",
        }

    monkeypatch.setattr(
        evidence_router,
        "_resolve_hybrid_retriever_class",
        lambda: _HybridRetriever,
    )
    monkeypatch.setattr(search_upload, "enrich_chunk_locator_with_pdf", _fake_enrich_locator)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg hybrid locator",
            "top_k": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    ref = payload["evidence_refs"][0]
    assert ref["page"] == 7
    assert ref["locator"]["page"] == 7
    assert ref["locator"]["bbox"] == [0.12, 0.18, 0.42, 0.52]
    coverage = payload["retrieval_diagnostics"]["locator_coverage"]
    assert coverage["coverage_state"] == "layout_complete"
    assert coverage["risk_level"] == "none"


def test_evidence_pack_build_protects_visual_ref_after_hybrid_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Visual hybrid packs should keep a pixel-backed ref for integrity gates."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_pack_text": [
                {
                    "chunk_id": f"pack_text_{index}",
                    "material_id": "mat_pack_text",
                    "title": f"AlSi10Mg text evidence {index}",
                    "content": "AlSi10Mg laser welding parameters and porosity suppression.",
                    "page": index + 1,
                    "chunk_index": index,
                }
                for index in range(3)
            ],
            "mat_pack_visual": [
                {
                    "chunk_id": "pack_visual_surface",
                    "material_id": "mat_pack_visual",
                    "title": "AlSi10Mg laser welding upper surface figure",
                    "content": "Figure 7. Weld upper surface appearance and surface morphology.",
                    "raw_content": "Figure 7. Weld upper surface appearance and surface morphology.",
                    "page": 10,
                    "chunk_index": 7,
                    "chunk_type": "figure_caption",
                    "bbox": [0.11, 0.22, 0.66, 0.44],
                    "image_paths": ["figure_assets/extracted/surface/p0010_img001.png"],
                }
            ],
        },
    )

    class _HybridRetriever:
        def __init__(self, use_reranker: bool | None = None) -> None:
            self.use_reranker = use_reranker

        async def search(
            self,
            raw_data: dict[str, Any],
            query: str,
            top_k: int = 10,
            focus_keywords: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            hits = []
            for index, chunk in enumerate(raw_data["chunks"][:3]):
                hit = dict(chunk)
                hit["hybrid_score"] = 0.9 - index * 0.05
                hit["rerank_score"] = 0.8 - index * 0.05
                hit["source_labels"] = ["bm25", "dense", "rerank"]
                hits.append(hit)
            return hits

    import routers.evidence_router as evidence_router

    monkeypatch.setattr(
        evidence_router,
        "_resolve_hybrid_retriever_class",
        lambda: _HybridRetriever,
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg 外观 上表面 图片",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval_method"] == "hybrid_rerank"
    assert payload["rerank_status"] == "active"
    visual_refs = [ref for ref in payload["evidence_refs"] if ref["image_paths"]]
    assert [ref["chunk_id"] for ref in visual_refs] == ["pack_visual_surface"]
    assert "visual_image_asset" in visual_refs[0]["source_labels"]
    assert any(
        "Protected one pixel-backed visual ref" in item
        for item in payload["retrieval_diagnostics"]["reasoning_trace"]
    )

    gate_response = client.post(
        "/api/evidence-pack/integrity-gate",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg 外观 上表面 图片",
            "evidence_refs": payload["evidence_refs"],
            "retrieval_diagnostics": payload["retrieval_diagnostics"],
        },
    )
    assert gate_response.status_code == 200
    gate = gate_response.json()
    checks = {check["check_id"]: check for check in gate["checks"]}
    assert checks["visual_image_evidence"]["status"] == "passed"
    assert gate["summary"]["image_ref_count"] == 1


def test_evidence_pack_build_reports_rerank_fallback_without_claiming_active_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rerank fallback refs should remain visible without counting as active rerank."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    class _HybridRetriever:
        def __init__(self, use_reranker: bool | None = None) -> None:
            self.use_reranker = use_reranker

        async def search(
            self,
            raw_data: dict[str, Any],
            query: str,
            top_k: int = 10,
            focus_keywords: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            chunks = raw_data["chunks"]
            hit = dict(chunks[0])
            hit["hybrid_score"] = 0.84
            hit["source_labels"] = ["bm25", "dense_fallback", "rerank_fallback"]
            return [hit]

    import routers.evidence_router as evidence_router

    monkeypatch.setattr(
        evidence_router,
        "_resolve_hybrid_retriever_class",
        lambda: _HybridRetriever,
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg rerank fallback",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval_method"] == "hybrid"
    assert payload["rerank_status"] == "skipped"
    diagnostics = payload["retrieval_diagnostics"]
    assert diagnostics["retrieval_method"] == "hybrid"
    assert diagnostics["embedding_status"] == "skipped"
    assert diagnostics["rerank_status"] == "skipped"
    assert "rerank fallback" in diagnostics["fallback_reason"]
    assert payload["outcome"]["status"] == "degraded"
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["retrieval"]["metadata"]["retrieval_method"] == "hybrid"
    assert attempts["rerank"]["status"] == "skipped"
    ref = payload["evidence_refs"][0]
    assert ref["ref_id"] == "chunk:pack_chunk_1"
    assert "rerank_fallback" in ref["source_labels"]
    assert ref["rerank_score"] is None
    assert "content" not in ref


def test_evidence_pack_build_reports_wiki_project_joint_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Joint recall diagnostics should include wiki hits without faking chunk refs."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    def _wiki_searcher(query: str, limit: int) -> list[dict[str, Any]]:
        assert query == "AlSi10Mg porosity fatigue"
        assert limit >= 5
        return [
            {
                "doc_id": f"wiki:alsi10mg-{index}",
                "ref_id": f"wiki:synthesis/alsi10mg-{index}.md",
                "read_endpoint": f"/api/agent-bridge/resource/wiki:synthesis/alsi10mg-{index}.md",
                "title": f"AlSi10Mg wiki note {index}",
                "summary": f"Wiki note {index} about porosity and fatigue.",
                "page_path": f"synthesis/alsi10mg-{index}.md",
                "source": "wiki_fts",
                "chunk_id": f"wiki:synthesis/alsi10mg-{index}.md#hash{index}",
                "source_hash": f"source-hash-{index}",
                "content_hash": f"content-hash-{index}",
                "span_start": 0,
                "span_end": 120 + index,
            }
            for index in range(1, 8)
        ]

    import routers.evidence_router as evidence_router

    monkeypatch.setattr(
        evidence_router,
        "_resolve_wiki_joint_recall_searcher",
        lambda: _wiki_searcher,
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "section_id": "intro",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    diagnostics = payload["retrieval_diagnostics"]
    joint = diagnostics["joint_recall"]
    assert joint["enabled"] is True
    assert joint["status"] == "active"
    assert joint["fusion_method"] == "weighted_rrf"
    assert joint["project_weight"] == 0.4
    assert joint["wiki_weight"] == 0.6
    assert joint["project_hit_count"] == 1
    assert joint["wiki_hit_count"] == 7
    assert joint["source_counts"]["project"] >= 1
    assert joint["source_counts"]["wiki"] >= 1
    assert joint["source_counts"]["wiki"] <= 3
    assert joint["wiki_summaries"][0]["ref_id"] == "wiki:synthesis/alsi10mg-1.md"
    assert joint["wiki_summaries"][0]["read_endpoint"] == "/api/agent-bridge/resource/wiki:synthesis/alsi10mg-1.md"
    assert joint["wiki_summaries"][0]["chunk_id"] == "wiki:synthesis/alsi10mg-1.md#hash1"
    assert joint["wiki_summaries"][0]["source_hash"] == "source-hash-1"
    assert joint["wiki_summaries"][0]["content_hash"] == "content-hash-1"
    assert joint["wiki_summaries"][0]["span_start"] == 0
    assert joint["wiki_summaries"][0]["span_end"] == 121
    assert diagnostics["project_weight"] == 0.4
    assert diagnostics["wiki_weight"] == 0.6
    locator_coverage = diagnostics["locator_coverage"]
    assert locator_coverage["project_ref_count"] == 1
    assert locator_coverage["non_project_ref_count"] == len(payload["evidence_refs"]) - 1
    assert locator_coverage["coverage_state"] == "layout_complete"
    assert locator_coverage["bbox_coverage_ratio"] == 1.0
    assert any("wiki+project" in item.lower() for item in diagnostics["reasoning_trace"])
    refs = payload["evidence_refs"]
    assert any(ref["ref_id"] == "chunk:pack_chunk_1" and ref["source_type"] == "project" for ref in refs)
    wiki_refs = [ref for ref in refs if ref["source_type"] == "wiki"]
    assert wiki_refs
    assert len(wiki_refs) <= 3
    assert wiki_refs[0]["ref_id"].startswith("wiki:synthesis/alsi10mg-")
    assert wiki_refs[0]["read_endpoint"].startswith("/api/agent-bridge/resource/wiki:synthesis/alsi10mg-")
    assert wiki_refs[0]["material_id"] == "wiki"
    assert wiki_refs[0]["chunk_id"].startswith("wiki:synthesis/alsi10mg-")
    assert "#" in wiki_refs[0]["chunk_id"]
    assert wiki_refs[0]["source_title"].startswith("AlSi10Mg wiki note")
    assert wiki_refs[0]["source_path"].startswith("synthesis/alsi10mg-")
    assert wiki_refs[0]["joint_score"] is not None
    assert wiki_refs[0]["locator"] is None
    assert wiki_refs[0]["source_labels"] == ["wiki_joint_recall"]
    assert len(wiki_refs[0]["summary"]) <= 300
    serialized = str(payload)
    assert "Wiki note 1" in serialized
    assert "content" not in wiki_refs[0]
    assert "SHOULD_NOT_LEAK" not in serialized


def test_evidence_pack_build_adds_product_docs_shared_resource_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Product docs refs should enter evidence packs through bounded resource ids."""

    root = tmp_path / "repo"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (root / "README.md").write_text(
        "# Scholar AI\n\n"
        "Knowledge Runtime Pipeline turns authoritative sources into bounded refs.\n",
        encoding="utf-8",
    )
    (docs / "USAGE.md").write_text(
        "# Knowledge Runtime Pipeline\n\n"
        "Agent resource readers consume the same product_docs chunk refs that search returns. "
        + ("Bounded context keeps provenance small. " * 20)
        + "MODEL_CONTEXT_SHOULD_STAY_BEHIND_RESOURCE_READ.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_docs_knowledge, "REPO_ROOT", root)

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue Knowledge Runtime Pipeline Agent resource readers",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    refs = payload["evidence_refs"]
    product_refs = [ref for ref in refs if ref["source_type"] == "product_docs"]
    assert product_refs
    first = product_refs[0]
    assert first["project_id"] == project_id
    assert first["ref_id"].startswith("product_docs:chunk:")
    assert first["read_endpoint"] == f"/api/agent-bridge/resource/{first['ref_id']}"
    assert first["chunk_id"].startswith("product_docs:")
    assert first["material_id"] == "product_docs"
    assert first["locator"] is None
    assert first["source_path"] in {"README.md", "docs/USAGE.md"}
    assert len(first["summary"]) <= 300
    assert "content" not in first

    diagnostics = payload["retrieval_diagnostics"]
    knowledge_refs = diagnostics["joint_recall"]["knowledge_refs"]
    assert knowledge_refs["enabled"] is True
    assert knowledge_refs["status"] == "active"
    assert knowledge_refs["source_counts"]["product_docs"] >= 1
    summary = knowledge_refs["product_docs_summaries"][0]
    assert summary["ref_id"].startswith("product_docs:chunk:")
    assert summary["read_endpoint"] == f"/api/agent-bridge/resource/{summary['ref_id']}"
    assert summary["source_path"] in {"README.md", "docs/USAGE.md"}
    assert len(summary["source_hash"]) == 64
    assert len(summary["content_hash"]) == 64
    assert isinstance(summary["span_start"], int)
    assert isinstance(summary["span_end"], int)
    assert diagnostics["locator_coverage"]["non_project_ref_count"] >= 1
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["knowledge_refs"]["status"] == "success"
    assert attempts["knowledge_refs"]["metadata"]["source_counts"]["product_docs"] >= 1

    resource_response = client.get(first["read_endpoint"])
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "product_docs"
    assert resource["ref_id"] == first["ref_id"]
    assert resource["metadata"]["ref_id"] == first["ref_id"]
    assert resource["metadata"]["read_endpoint"] == first["read_endpoint"]
    assert resource["metadata"]["source_hash"] == summary["source_hash"]
    assert resource["metadata"]["content_hash"] == summary["content_hash"]
    assert "MODEL_CONTEXT_SHOULD_STAY_BEHIND_RESOURCE_READ" in resource["content"]

    serialized = str(payload)
    assert "MODEL_CONTEXT_SHOULD_STAY_BEHIND_RESOURCE_READ" not in serialized


def test_evidence_pack_build_adds_scoring_rules_shared_resource_refs() -> None:
    """Scoring rules should share the same bounded refs used by knowledge search."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue direct_evidence high_quality",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    refs = payload["evidence_refs"]
    scoring_refs = [ref for ref in refs if ref["source_type"] == "scoring_rules"]
    assert scoring_refs
    first = scoring_refs[0]
    assert first["project_id"] == project_id
    assert first["ref_id"].startswith("scoring_rules:section:")
    assert first["read_endpoint"] == f"/api/agent-bridge/resource/{first['ref_id']}"
    assert first["chunk_id"].startswith("scoring_rules:section:")
    assert first["material_id"] == "scoring_rules"
    assert first["locator"] is None
    assert first["source_path"] == "literature_assistant/core/config/scoring_rules.json"
    assert len(first["summary"]) <= 300
    assert "content" not in first

    diagnostics = payload["retrieval_diagnostics"]
    knowledge_refs = diagnostics["joint_recall"]["knowledge_refs"]
    assert knowledge_refs["enabled"] is True
    assert knowledge_refs["status"] == "active"
    assert knowledge_refs["source_counts"]["scoring_rules"] >= 1
    summary = knowledge_refs["scoring_rules_summaries"][0]
    assert summary["ref_id"].startswith("scoring_rules:section:")
    assert summary["read_endpoint"] == f"/api/agent-bridge/resource/{summary['ref_id']}"
    assert summary["source_path"] == "literature_assistant/core/config/scoring_rules.json"
    assert len(summary["source_hash"]) == 64
    assert len(summary["content_hash"]) == 64
    assert summary["section_id"] in {"weights", "thresholds"}
    assert isinstance(summary["span_start"], int)
    assert isinstance(summary["span_end"], int)
    assert diagnostics["locator_coverage"]["non_project_ref_count"] >= 1
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["knowledge_refs"]["status"] == "success"
    assert attempts["knowledge_refs"]["metadata"]["source_counts"]["scoring_rules"] >= 1

    resource_response = client.get(first["read_endpoint"], params={"max_chars": 500, "cursor": "0"})
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "scoring_rules"
    assert resource["ref_id"] == first["ref_id"]
    assert resource["metadata"]["ref_id"] == first["ref_id"]
    assert resource["metadata"]["read_endpoint"] == first["read_endpoint"]
    assert resource["metadata"]["source_hash"] == summary["source_hash"]
    assert resource["metadata"]["content_hash"] == summary["content_hash"]
    assert "direct_evidence" in resource["content"] or "high_quality" in resource["content"]


def test_evidence_pack_build_adds_academic_english_shared_resource_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Academic-English knowledge should enter evidence packs through shared bounded refs."""

    root = tmp_path / "english_discourse"
    _seed_academic_english_output(root)
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))

    search_hits = academic_english_resources.search_academic_english(
        "evidence-bound claim scope hedging",
        top_k=1,
    )
    assert search_hits
    expected_ref_id = search_hits[0]["ref_id"]

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue evidence-bound claim scope hedging",
            "top_k": 6,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    refs = payload["evidence_refs"]
    academic_refs = [ref for ref in refs if ref["source_type"] == "academic_english"]
    assert academic_refs
    first = academic_refs[0]
    assert first["project_id"] == project_id
    assert first["ref_id"] == expected_ref_id
    assert first["read_endpoint"] == f"/api/agent-bridge/resource/{first['ref_id']}"
    assert first["chunk_id"].startswith("academic_english:chunk:")
    assert first["material_id"] == "academic_english"
    assert first["locator"] is None
    assert first["source_path"] == "references/english_discourse_habits.md"
    assert len(first["summary"]) <= 300
    assert "content" not in first

    diagnostics = payload["retrieval_diagnostics"]
    knowledge_refs = diagnostics["joint_recall"]["knowledge_refs"]
    assert knowledge_refs["enabled"] is True
    assert knowledge_refs["status"] == "active"
    assert knowledge_refs["source_counts"]["academic_english"] >= 1
    summary = knowledge_refs["academic_english_summaries"][0]
    assert summary["ref_id"] == first["ref_id"]
    assert summary["read_endpoint"] == first["read_endpoint"]
    assert summary["source_path"] == first["source_path"]
    assert summary["resource_kind"] == "chunk"
    assert summary["policy_content_hash"] == "c" * 64
    assert summary["built_at"] == "2026-06-24T00:00:00+00:00"
    assert len(summary["source_hash"]) == 64
    assert len(summary["content_hash"]) == 64
    assert isinstance(summary["span_start"], int)
    assert isinstance(summary["span_end"], int)
    assert diagnostics["locator_coverage"]["non_project_ref_count"] >= 1
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["knowledge_refs"]["status"] == "success"
    assert attempts["knowledge_refs"]["metadata"]["source_counts"]["academic_english"] >= 1

    resource_response = client.get(first["read_endpoint"], params={"max_chars": 500, "cursor": "0"})
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "academic_english"
    assert resource["ref_id"] == first["ref_id"]
    assert resource["metadata"]["ref_id"] == first["ref_id"]
    assert resource["metadata"]["read_endpoint"] == first["read_endpoint"]
    assert resource["metadata"]["source_hash"] == summary["source_hash"]
    assert resource["metadata"]["content_hash"] == summary["content_hash"]
    assert "evidence-bound claim scope" in resource["content"].lower()

    serialized = str(payload)
    assert "MODEL_CONTEXT_SHOULD_STAY_BEHIND_RESOURCE_READ" not in serialized


def test_evidence_pack_build_adds_skill_package_shared_resource_refs() -> None:
    """Skill package knowledge should enter evidence packs through shared bounded refs."""

    search_hits = search_skill_package("academic-english-discourse", "discourse move evidence-bound", top_k=1)
    assert search_hits
    expected_ref_id = search_hits[0]["ref_id"]

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue discourse move evidence-bound",
            "top_k": 6,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    refs = payload["evidence_refs"]
    skill_refs = [ref for ref in refs if ref["source_type"] == "skill_package"]
    assert skill_refs
    first = skill_refs[0]
    assert first["project_id"] == project_id
    assert first["ref_id"] == expected_ref_id
    assert first["read_endpoint"] == f"/api/agent-bridge/resource/{first['ref_id']}"
    assert first["chunk_id"].startswith("skill_package:academic-english-discourse:chunk:")
    assert first["material_id"] == "skill_package"
    assert first["locator"] is None
    assert first["source_path"] in {"SKILL.md", "references/english_discourse_habits.md", "references/schema.md", "prompts/main.txt"}
    assert len(first["summary"]) <= 300
    assert "content" not in first

    diagnostics = payload["retrieval_diagnostics"]
    knowledge_refs = diagnostics["joint_recall"]["knowledge_refs"]
    assert knowledge_refs["enabled"] is True
    assert knowledge_refs["status"] == "active"
    assert knowledge_refs["source_counts"]["skill_package"] >= 1
    summary = knowledge_refs["skill_package_summaries"][0]
    assert summary["ref_id"] == first["ref_id"]
    assert summary["read_endpoint"] == first["read_endpoint"]
    assert summary["source_path"] == first["source_path"]
    assert summary["package_id"] == "academic-english-discourse"
    assert summary["source_role"] in {"manifest", "reference", "prompt"}
    assert len(summary["source_hash"]) == 64
    assert len(summary["content_hash"]) == 64
    assert len(summary["package_content_hash"]) == 64
    assert isinstance(summary["span_start"], int)
    assert isinstance(summary["span_end"], int)
    assert diagnostics["locator_coverage"]["non_project_ref_count"] >= 1
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["knowledge_refs"]["status"] == "success"
    assert attempts["knowledge_refs"]["metadata"]["source_counts"]["skill_package"] >= 1

    resource_response = client.get(first["read_endpoint"], params={"max_chars": 500, "cursor": "0"})
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "skill_package"
    assert resource["ref_id"] == first["ref_id"]
    assert resource["metadata"]["ref_id"] == first["ref_id"]
    assert resource["metadata"]["read_endpoint"] == first["read_endpoint"]
    assert resource["metadata"]["source_hash"] == summary["source_hash"]
    assert resource["metadata"]["content_hash"] == summary["content_hash"]
    assert "discourse" in resource["content"].lower() or "academic english" in resource["content"].lower()

    serialized = str(payload)
    assert "Build or refresh the local database with" not in serialized


def test_evidence_pack_build_adds_source_vault_shared_resource_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Source Vault chunks should share the search/resource/evidence-pack ref contract."""

    import routers.evidence_router as evidence_router

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    vault, chunk_id = _seed_source_vault(tmp_path, project_id)
    monkeypatch.setattr(evidence_router, "SourceVault", lambda: vault)
    monkeypatch.setattr(agent_bridge_router, "SourceVault", lambda: vault)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue Source Vault molten pool evidence",
            "top_k": 7,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    refs = payload["evidence_refs"]
    source_vault_refs = [ref for ref in refs if ref["source_type"] == "source_vault"]
    assert source_vault_refs
    first = source_vault_refs[0]
    assert first["project_id"] == project_id
    assert first["ref_id"] == f"source_vault:chunk:{chunk_id}"
    assert first["read_endpoint"] == f"/api/agent-bridge/resource/{first['ref_id']}"
    assert first["chunk_id"] == f"source_vault:{chunk_id}"
    assert first["material_id"] == "source_vault"
    assert first["locator"] is None
    assert first["source_title"] == "Source Vault Evidence Paper"
    assert first["source_path"].endswith("source-vault-paper.pdf")
    assert len(first["summary"]) <= 300
    assert "content" not in first

    diagnostics = payload["retrieval_diagnostics"]
    knowledge_refs = diagnostics["joint_recall"]["knowledge_refs"]
    assert knowledge_refs["enabled"] is True
    assert knowledge_refs["status"] == "active"
    assert knowledge_refs["source_counts"]["source_vault"] >= 1
    summary = knowledge_refs["source_vault_summaries"][0]
    assert summary["ref_id"] == first["ref_id"]
    assert summary["read_endpoint"] == first["read_endpoint"]
    assert summary["source_path"] == first["source_path"]
    assert summary["source_id"]
    assert summary["chunk_id"] == chunk_id
    assert summary["chunker_version"] == "chunker-v1"
    assert len(summary["source_hash"]) == 64
    assert len(summary["content_hash"]) == 64
    assert isinstance(summary["span_start"], int)
    assert isinstance(summary["span_end"], int)
    assert diagnostics["locator_coverage"]["non_project_ref_count"] >= 1
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["knowledge_refs"]["status"] == "success"
    assert attempts["knowledge_refs"]["metadata"]["source_counts"]["source_vault"] >= 1

    resource_response = client.get(first["read_endpoint"], params={"project_id": project_id, "max_chars": 500, "cursor": "0"})
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "source_vault"
    assert resource["ref_id"] == first["ref_id"]
    assert resource["metadata"]["source_hash"] == summary["source_hash"]
    assert resource["metadata"]["content_hash"] == summary["content_hash"]
    assert resource["metadata"]["source_path"] == first["source_path"]
    assert "MODEL_CONTEXT_SHOULD_STAY_BEHIND_SOURCE_VAULT_RESOURCE_READ" in resource["content"]

    serialized = str(payload)
    assert "MODEL_CONTEXT_SHOULD_STAY_BEHIND_SOURCE_VAULT_RESOURCE_READ" not in serialized


def test_evidence_pack_build_blocks_stale_wiki_joint_recall(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Stale wiki source manifests must block wiki refs from model context."""

    import routers.evidence_router as evidence_router

    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    page_path = Path("synthesis/alsi10mg-stale.md")
    page_store = WikiPageStore(wiki_root)
    page_store.write_rendered(
        render_page(
            page_path,
            {"id": "synthesis/alsi10mg-stale", "kind": "synthesis", "title": "AlSi10Mg stale wiki"},
            "AlSi10Mg porosity fatigue wiki source before indexing.",
        )
    )
    query_index = WikiQueryIndex(runtime_root / "wiki_query_index.db")
    build_wiki_index(page_store, query_index)
    query_index.close()
    page_store.write_rendered(
        render_page(
            page_path,
            {"id": "synthesis/alsi10mg-stale", "kind": "synthesis", "title": "AlSi10Mg stale wiki"},
            "AlSi10Mg porosity fatigue wiki source changed after indexing.",
        )
    )
    monkeypatch.setattr(evidence_router, "wiki_enabled", lambda: True)
    monkeypatch.setattr(evidence_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    monkeypatch.setattr(evidence_router, "wiki_query_index_path", lambda: runtime_root / "wiki_query_index.db")

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    joint = payload["retrieval_diagnostics"]["joint_recall"]
    assert joint["enabled"] is True
    assert joint["status"] == "blocked"
    assert joint["integrity_gate"]["status"] == "source_hash_mismatch"
    assert joint["wiki_hit_count"] == 0
    assert all(ref["source_type"] == "project" for ref in payload["evidence_refs"])
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["joint_recall"]["status"] == "blocked"
    assert attempts["wiki_integrity_gate"]["status"] == "blocked"
    assert attempts["wiki_integrity_gate"]["error_class"] == "wiki_source_hash_mismatch"
    assert attempts["wiki_integrity_gate"]["metadata"]["source_manifest_hash"] != (
        attempts["wiki_integrity_gate"]["metadata"]["indexed_source_manifest_hash"]
    )


def test_evidence_pack_build_ignores_unfinalized_wiki_joint_recall(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Draft wiki pages remain reviewable but cannot contaminate evidence packs."""

    import routers.evidence_router as evidence_router

    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    page_store = WikiPageStore(wiki_root)
    page_store.write_rendered(
        render_page(
            Path("synthesis/alsi10mg-draft.md"),
            {
                "id": "synthesis/alsi10mg-draft",
                "kind": "synthesis",
                "title": "AlSi10Mg draft wiki",
                "status": "draft",
            },
            "AlSi10Mg porosity fatigue wiki source awaiting governance.",
        )
    )
    query_index = WikiQueryIndex(runtime_root / "wiki_query_index.db")
    build_wiki_index(page_store, query_index)
    query_index.close()
    monkeypatch.setattr(evidence_router, "wiki_enabled", lambda: True)
    monkeypatch.setattr(evidence_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    monkeypatch.setattr(evidence_router, "wiki_query_index_path", lambda: runtime_root / "wiki_query_index.db")

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    joint = payload["retrieval_diagnostics"]["joint_recall"]
    assert joint["enabled"] is True
    assert joint["status"] == "empty"
    assert joint["wiki_hit_count"] == 0
    assert all(ref["source_type"] == "project" for ref in payload["evidence_refs"])


def test_evidence_pack_build_reports_canonical_qrels_quality_gate() -> None:
    """Canonical qrels are required before retrieval quality can be claimed."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    canonical_qrels_path = resources_router.project_data_path(  # type: ignore[attr-defined]
        project_id,
        "qrels",
        "canonical.qrels",
    )
    canonical_qrels_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_qrels_path.write_text("pkg_q_0001 0 pack_chunk_1 2\n", encoding="utf-8")

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    qrels_status = response.json()["retrieval_diagnostics"]["qrels_status"]
    qrels_content_hash = qrels_status.pop("qrels_content_hash")
    assert qrels_content_hash.startswith("sha256:")
    assert len(qrels_content_hash) == 71
    assert qrels_status == {
        "schema_version": "retrieval-qrels-status/v1",
        "status": "canonical",
        "candidate_qrels_count": 0,
        "reviewed_qrels_count": 0,
        "canonical_qrels_count": 1,
        "semantic_quality_claim_allowed": True,
        "quality_claim": "canonical_qrels_available",
        "notes": [
            "Canonical qrels are available for offline retrieval-quality evaluation.",
        ],
    }


def test_evidence_pack_build_reports_candidate_qrels_without_quality_claim() -> None:
    """Candidate qrels stay visible but never authorize semantic quality claims."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    candidate_qrels_path = resources_router.project_data_path(  # type: ignore[attr-defined]
        project_id,
        "qrels",
        "qrels_candidate.trec",
    )
    candidate_qrels_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_qrels_path.write_text(
        "# candidate qrels generated from chunk-package evidence sections\n"
        "pkg_q_0001 0 pack_chunk_1 1\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    qrels_status = response.json()["retrieval_diagnostics"]["qrels_status"]
    assert qrels_status["status"] == "candidate"
    assert qrels_status["candidate_qrels_count"] == 1
    assert qrels_status["canonical_qrels_count"] == 0
    assert qrels_status["qrels_content_hash"].startswith("sha256:")
    assert qrels_status["semantic_quality_claim_allowed"] is False
    assert qrels_status["quality_claim"] == "candidate_qrels_review_required"
    outcome = response.json()["outcome"]
    attempts = {attempt["stage"]: attempt for attempt in outcome["attempts"]}
    assert attempts["qrels_quality_gate"]["status"] == "blocked"
    assert attempts["qrels_quality_gate"]["error_class"] == "qrels_review_needed"
    assert attempts["qrels_quality_gate"]["metadata"]["status"] == "candidate"


def test_evidence_pack_build_reports_reviewed_qrels_without_quality_claim() -> None:
    """Reviewed qrels still require canonical promotion before quality claims."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    reviewed_qrels_path = resources_router.project_data_path(  # type: ignore[attr-defined]
        project_id,
        "qrels",
        "reviewed.jsonl",
    )
    reviewed_qrels_path.parent.mkdir(parents=True, exist_ok=True)
    reviewed_qrels_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in [
                {
                    "schema_version": "chunk-goldset-review-judgment/v1",
                    "query_id": "pkg_q_0001",
                    "query_text": "AlSi10Mg porosity fatigue",
                    "source_section": "AlSi10Mg porosity fatigue",
                    "chunk_id": "pack_chunk_1",
                    "judgment": "relevant",
                    "human_relevance": 3,
                    "no_gold": False,
                },
                {
                    "schema_version": "chunk-goldset-review-judgment/v1",
                    "query_id": "pkg_q_0001",
                    "query_text": "AlSi10Mg porosity fatigue",
                    "source_section": "AlSi10Mg porosity fatigue",
                    "chunk_id": "pack_chunk_2",
                    "judgment": "unknown",
                    "human_relevance": None,
                    "no_gold": False,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    qrels_status = response.json()["retrieval_diagnostics"]["qrels_status"]
    assert qrels_status["status"] == "reviewed"
    assert qrels_status["candidate_qrels_count"] == 0
    assert qrels_status["reviewed_qrels_count"] == 1
    assert qrels_status["canonical_qrels_count"] == 0
    assert qrels_status["qrels_content_hash"].startswith("sha256:")
    assert qrels_status["semantic_quality_claim_allowed"] is False
    assert qrels_status["quality_claim"] == "reviewed_qrels_promotion_required"
    outcome = response.json()["outcome"]
    attempts = {attempt["stage"]: attempt for attempt in outcome["attempts"]}
    assert attempts["qrels_quality_gate"]["status"] == "blocked"
    assert attempts["qrels_quality_gate"]["error_class"] == "qrels_review_needed"
    assert attempts["qrels_quality_gate"]["metadata"]["status"] == "reviewed"
    assert attempts["qrels_quality_gate"]["metadata"]["reviewed_qrels_count"] == 1


def test_evidence_pack_build_empty_store_is_stable() -> None:
    """Empty project chunk stores return an empty lexical pack envelope."""

    client = _client()
    project = _create_project(client)

    response = client.post(
        "/api/evidence-pack/build",
        json={"project_id": project["project_id"], "query": "missing evidence", "top_k": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project["project_id"]
    assert payload["retrieval_method"] == "lexical"
    assert payload["rerank_status"] == "unavailable"
    assert payload["retrieval_diagnostics"]["embedding_status"] == "unavailable"
    assert payload["retrieval_diagnostics"]["rerank_status"] == "unavailable"
    assert payload["retrieval_diagnostics"]["locator_coverage"]["coverage_state"] == "no_refs"
    assert payload["retrieval_diagnostics"]["locator_coverage"]["risk_level"] == "none"
    assert payload["total"] == 0
    assert payload["truncated"] is False
    outcome = payload["outcome"]
    assert outcome["status"] == "empty"
    assert outcome["quality"] == "none"
    assert outcome["next_action"]["kind"] == "scan_folder"
    assert outcome["next_action"]["tool_name"] == "literature.project_scan_folder"
    attempts = {attempt["stage"]: attempt for attempt in outcome["attempts"]}
    assert attempts["chunk_load"]["status"] == "skipped"
    assert attempts["chunk_load"]["error_class"] == "ingest_needed"
    assert attempts["locator_coverage"]["status"] == "success"
    assert attempts["locator_coverage"]["metadata"]["coverage_state"] == "no_refs"
    assert payload["evidence_refs"] == []


def test_evidence_pack_build_rejects_blank_query() -> None:
    """Blank request fields should fail before touching retrieval."""

    client = _client()
    project = _create_project(client)

    response = client.post(
        "/api/evidence-pack/build",
        json={"project_id": project["project_id"], "query": "   "},
    )

    assert response.status_code == 422
