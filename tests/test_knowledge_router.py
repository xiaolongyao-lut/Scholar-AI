from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from literature_assistant.core import academic_english_resources
from literature_assistant.core import config_knowledge
from literature_assistant.core import product_docs_knowledge
from literature_assistant.core import skill_package_knowledge
from literature_assistant.core.wiki.page_store import WikiPageStore, render_page
from literature_assistant.core.wiki.query import WikiQueryIndex, build_wiki_index
from routers import knowledge_router
import routers.agent_bridge_router as agent_bridge_router
import routers.wiki_router as wiki_router
from source_vault import SourceChunkInput, SourceVault


def load_academic_english_builder() -> ModuleType:
    """Load the academic-English builder without importing package-local scripts globally."""

    script_path = (
        Path(__file__).resolve().parents[1]
        / "extension_packages"
        / "skills"
        / "academic-english-discourse"
        / "scripts"
        / "build_discourse_db.py"
    )
    spec = importlib.util.spec_from_file_location("academic_english_discourse_builder_for_router_tests", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_vault(tmp_path: Path) -> SourceVault:
    """Create an isolated Source Vault for router tests."""

    return SourceVault(
        db_path=tmp_path / "source_vault" / "source_vault.sqlite3",
        storage_root=tmp_path / "source_vault",
    )


def make_client(vault: SourceVault) -> TestClient:
    """Create a FastAPI client with the Source Vault dependency overridden."""

    app = FastAPI()
    app.include_router(wiki_router.router)
    app.include_router(knowledge_router.router)
    app.include_router(agent_bridge_router.router)
    app.dependency_overrides[knowledge_router.get_source_vault] = lambda: vault
    agent_bridge_router.SourceVault = lambda: vault  # type: ignore[assignment]
    return TestClient(app)


def seed_vault(vault: SourceVault) -> str:
    """Insert one source with chunks and return its source id."""

    source = vault.upsert_source_bytes(
        b"paper bytes for knowledge router",
        filename="paper-a.pdf",
        source_type="pdf",
        title="Molten Pool Study",
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        project_id="project-alpha",
        now_iso="2026-06-06T01:00:00Z",
    ).source
    vault.register_chunks(
        source.source_id,
        [
            SourceChunkInput(
                text="Laser melting creates a molten pool with measurable flow.",
                chunk_index=0,
                page=1,
            ),
            SourceChunkInput(
                text="Cooling rate controls grain refinement in the alloy.",
                chunk_index=1,
                page=2,
            ),
        ],
        now_iso="2026-06-06T01:01:00Z",
    )
    return source.source_id


def seed_wiki_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Create an isolated wiki page plus query index for knowledge pipeline tests."""

    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    page_store = WikiPageStore(wiki_root)
    body = (
        "KnowledgeRuntimeWikiAnchor proves registry discovered wiki refs can be searched, "
        "read by an agent resource, and loaded into bounded context receipts."
    )
    page_store.write_rendered(
        render_page(
            Path("concepts/knowledge-runtime-wiki.md"),
            {
                "id": "concepts/knowledge-runtime-wiki",
                "kind": "concept",
                "title": "Knowledge Runtime Wiki",
                "status": "final",
            },
            body,
        )
    )
    query_index = WikiQueryIndex(runtime_root / "wiki_query_index.db")
    build_wiki_index(page_store, query_index)
    query_index.close()
    wiki_modules = {wiki_router, knowledge_router._wiki_router}
    for module in wiki_modules:
        monkeypatch.setattr(module, "wiki_enabled", lambda: True)
        monkeypatch.setattr(module, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
        monkeypatch.setattr(module, "wiki_graph_path", lambda: runtime_root / "graph.json")
        monkeypatch.setattr(module, "wiki_graph_db_path", lambda: runtime_root / "graph.db")
        monkeypatch.setattr(module, "wiki_query_index_path", lambda: runtime_root / "wiki_query_index.db")
        monkeypatch.setattr(module, "wiki_review_queue_path", lambda: runtime_root / "review_queue.jsonl")
        monkeypatch.setattr(module, "wiki_runtime_db_path", lambda: runtime_root / "wiki.db")
    monkeypatch.setattr(agent_bridge_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    monkeypatch.setattr(knowledge_router._agent_bridge_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))


def seed_academic_english_output(root: Path) -> None:
    """Create a minimal generated academic-English package."""

    root.mkdir(parents=True, exist_ok=True)
    chunks_path = root / "chunks.jsonl"
    phrases_path = root / "phrases.jsonl"
    habits_path = root / "academic_english_habits.json"
    frames_path = root / "discourse_frames.json"
    report_path = root / "build_report.md"
    chunk_text = "Hedging calibrates claims and OldAcademicAnchor preserves evidential strength in academic prose."
    phrase_text = "These findings should be interpreted in light of the sample boundary."
    source_hash = hashlib.sha256(b"source text for hedging records").hexdigest()
    chunk_record = {
        "chunk_id": "chunk-hedging",
        "source_id": "source-1",
        "source_type": "text",
        "source_path": "C:/private/source/path/should/not/leak.txt",
        "source_hash": source_hash,
        "title": "Hedging Review",
        "locator": "private/source/path/should/not/leak.txt",
        "section": "discussion",
        "text": chunk_text,
        "summary": "Hedging calibrates claims with OldAcademicAnchor.",
        "content_hash": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        "span_start": 7,
        "span_end": 7 + len(chunk_text),
        "rhetorical_moves": ["limitation"],
        "features": ["hedging"],
        "keywords": ["hedging", "claims", "OldAcademicAnchor"],
        "char_count": 78,
        "word_count": 10,
    }
    phrase_record = {
        "phrase_id": "phrase-hedging",
        "source_id": "source-1",
        "source_type": "text",
        "source_path": "C:/private/source/path/should/not/leak.txt",
        "source_hash": source_hash,
        "text": phrase_text,
        "normalized": "these findings should be interpreted in light of",
        "content_hash": hashlib.sha256(phrase_text.encode("utf-8")).hexdigest(),
        "span_start": 90,
        "span_end": 90 + len(phrase_text),
        "move": "limitation",
        "features": ["hedging"],
        "section": "discussion",
        "locator": "private/source/path/should/not/leak.txt",
        "adaptation_note": "Use when limiting a claim.",
    }
    habits = {
        "schema_version": "0.2",
        "knowledge_type": "academic_english_habits",
        "policy_markdown": "# Academic English Discourse Habits\n\nHedging protects evidential scope.",
        "policy_source": "references/english_discourse_habits.md",
        "policy_source_path": "C:/private/english_discourse_habits.md",
        "policy_loaded": True,
        "policy_load_status": "loaded",
        "policy_content_hash": hashlib.sha256(
            "# Academic English Discourse Habits\n\nHedging protects evidential scope.".encode("utf-8")
        ).hexdigest(),
        "policy_char_count": 71,
        "purpose": "Help Scholar AI plan academic prose.",
    }
    chunks_path.write_text(json.dumps(chunk_record, ensure_ascii=False) + "\n", encoding="utf-8")
    phrases_path.write_text(json.dumps(phrase_record, ensure_ascii=False) + "\n", encoding="utf-8")
    habits_path.write_text(json.dumps(habits, ensure_ascii=False), encoding="utf-8")
    frames_path.write_text("[]", encoding="utf-8")
    report_path.write_text("# report\n", encoding="utf-8")
    manifest = {
        "schema_version": "0.2",
        "builder_version": "0.2.0",
        "built_at": "2026-06-24T00:00:00+00:00",
        "counts": {"chunks": 1, "phrases": 1},
        "warnings": [],
        "errors": [],
        "knowledge_sources": {
            "academic_english_habits": {
                "source_path": "C:/private/english_discourse_habits.md",
                "source_label": "references/english_discourse_habits.md",
                "loaded": True,
                "load_status": "loaded",
                "content_hash": habits["policy_content_hash"],
                "char_count": habits["policy_char_count"],
            }
        },
        "output_artifacts": {
            "chunks_jsonl": {
                "path": "C:/private/chunks.jsonl",
                "exists": True,
                "bytes": chunks_path.stat().st_size,
                "sha256": hashlib.sha256(chunks_path.read_bytes()).hexdigest(),
                "status": "written",
                "rows": 1,
            },
            "phrases_jsonl": {
                "path": "C:/private/phrases.jsonl",
                "exists": True,
                "bytes": phrases_path.stat().st_size,
                "sha256": hashlib.sha256(phrases_path.read_bytes()).hexdigest(),
                "status": "written",
                "rows": 1,
            },
            "academic_english_habits_json": {
                "path": "C:/private/academic_english_habits.json",
                "exists": True,
                "bytes": habits_path.stat().st_size,
                "sha256": hashlib.sha256(habits_path.read_bytes()).hexdigest(),
                "status": "written",
            },
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def write_scoring_rules_fixture(root: Path, *, anchor: str, direct_evidence: float) -> Path:
    """Write a minimal scoring-rules source under an isolated repo root."""

    source = root / "literature_assistant" / "core" / "config" / "scoring_rules.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        json.dumps(
            {
                "version": "1.0",
                "last_updated": "2026-06-24",
                "description": "isolated drift-proof scoring rules",
                "weights": {anchor: direct_evidence},
                "thresholds": {"high_quality": 0.85},
                "multipliers": {"full_paper_advantage": 1.2},
                "goal_mapping": {"process_parameters": ["parameter"]},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return source


def write_skill_package_fixture(root: Path, *, anchor: str) -> Path:
    """Write a minimal supported Skill package under an isolated repo root."""

    package_root = root / "extension_packages" / "skills" / "academic-english-discourse"
    references = package_root / "references"
    references.mkdir(parents=True, exist_ok=True)
    skill_md = package_root / "SKILL.md"
    skill_md.write_text(
        f"""---
id: "academic-english-discourse"
name: "Academic English Discourse"
version: "0.2.0"
kind: "style"
description: "Validates source-hash drift for Scholar AI."
entry_mode: "assistant"
ui_visibility: "skill_assisted"
supported_scopes:
  - "selection"
permissions:
  retrieval.read: true
  files.read: true
script_policy:
  has_scripts: false
  safe_to_execute: false
model_policy:
  allow_llm: true
  allow_embedding: false
root_policy:
  allowed_roots:
    - "skill_root"
---

# Academic English Discourse

The Skill manifest stays stable while reference files prove package content drift.
""",
        encoding="utf-8",
    )
    reference = references / "drift-proof.md"
    reference.write_text(
        f"# Drift Proof\n\n{anchor} {anchor} should enter search, resource read, and context receipt.",
        encoding="utf-8",
    )
    return reference


def rewrite_academic_english_chunk(root: Path, *, anchor: str) -> dict[str, object]:
    """Rewrite the generated academic-English chunk artifact and manifest hash."""

    chunks_path = root / "chunks.jsonl"
    manifest_path = root / "manifest.json"
    record = json.loads(chunks_path.read_text(encoding="utf-8").splitlines()[0])
    text = f"{anchor} calibrates claims and proves generated artifact drift reaches bounded context."
    source_hash = hashlib.sha256(f"source text for {anchor}".encode("utf-8")).hexdigest()
    record.update(
        {
            "source_hash": source_hash,
            "text": text,
            "summary": f"{anchor} generated artifact drift proof.",
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "span_start": 0,
            "span_end": len(text),
            "keywords": [anchor, "generated", "artifact", "drift"],
            "char_count": len(text),
            "word_count": len(text.split()),
        }
    )
    chunks_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks_artifact = manifest["output_artifacts"]["chunks_jsonl"]
    chunks_artifact["bytes"] = chunks_path.stat().st_size
    chunks_artifact["sha256"] = hashlib.sha256(chunks_path.read_bytes()).hexdigest()
    chunks_artifact["rows"] = 1
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return record


def build_academic_english_fixture(
    builder: ModuleType,
    *,
    output_dir: Path,
    text_source: Path,
) -> dict[str, object]:
    """Build academic-English artifacts with deterministic local inputs."""

    manifest = builder.build_database(
        builder.parse_args(
            [
                "--text",
                str(text_source),
                "--output-dir",
                str(output_dir),
                "--chunk-size",
                "220",
                "--chunk-overlap",
                "40",
            ]
        )
    )
    assert isinstance(manifest, dict)
    return manifest


def test_source_vault_overview_returns_sources_and_counts(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    source_id = seed_vault(vault)
    client = make_client(vault)

    response = client.get("/api/knowledge/source-vault")

    assert response.status_code == 200
    body = response.json()
    assert body["total_sources"] == 1
    assert body["total_project_links"] == 1
    assert isinstance(body["fts_enabled"], bool)
    assert body["storage_root"].endswith("source_vault")
    assert body["sources"][0]["source_id"] == source_id
    assert body["sources"][0]["project_ids"] == ["project-alpha"]


def test_source_vault_search_returns_chunk_hits(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    source_id = seed_vault(vault)
    client = make_client(vault)

    response = client.get(
        "/api/knowledge/source-vault/search",
        params={"q": "molten pool", "project_id": "project-alpha"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "molten pool"
    assert body["project_id"] == "project-alpha"
    assert body["results"]
    hit = body["results"][0]
    assert hit["ref_id"] == f"source_vault:chunk:{hit['chunk_id']}"
    assert hit["read_endpoint"] == f"/api/agent-bridge/resource/{hit['ref_id']}"
    assert body["results"][0]["source_id"] == source_id
    assert "molten pool" in body["results"][0]["summary"]
    assert "molten pool" in body["results"][0]["text"]
    assert body["results"][0]["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-source-vault-knowledge-ref/v1"
    assert body["results"][0]["metadata"]["source"] == "source_vault"
    assert body["results"][0]["metadata"]["source_id"] == source_id
    assert body["results"][0]["metadata"]["resource_kind"] == "chunk"


def test_source_vault_search_result_is_readable_as_agent_resource(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    seed_vault(vault)
    client = make_client(vault)
    import routers.agent_bridge_router as agent_bridge_router

    agent_bridge_router.SourceVault = lambda: vault  # type: ignore[assignment]

    search_response = client.get(
        "/api/knowledge/source-vault/search",
        params={"q": "molten pool", "project_id": "project-alpha"},
    )
    ref_id = search_response.json()["results"][0]["ref_id"]

    resource_response = client.get(f"/api/agent-bridge/resource/{ref_id}")

    assert resource_response.status_code == 200
    body = resource_response.json()
    assert body["kind"] == "source_vault"
    assert "molten pool" in body["content"]
    assert body["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-source-vault-knowledge-ref/v1"
    assert body["metadata"]["resource_kind"] == "chunk"


def test_source_vault_source_edit_rebuilds_hash_ref_resource_and_context_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A changed source file should create a new immutable Source Vault ref chain."""

    vault = make_vault(tmp_path)
    source_path = tmp_path / "editable-source.txt"
    source_path.write_text(
        "ObsoleteVaultAnchor is the original source version.",
        encoding="utf-8",
    )
    first_source = vault.upsert_source_from_file(
        source_path,
        source_type="text",
        title="Editable Source",
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        project_id="project-alpha",
        now_iso="2026-06-25T00:00:00Z",
    ).source
    first_chunk_text = "ObsoleteVaultAnchor should remain tied to the first immutable source."
    vault.register_chunks(
        first_source.source_id,
        [
            SourceChunkInput(
                text=first_chunk_text,
                chunk_index=0,
                span_start=0,
                span_end=len(first_chunk_text),
            )
        ],
        now_iso="2026-06-25T00:01:00Z",
    )
    monkeypatch.setattr(agent_bridge_router, "SourceVault", lambda: vault)
    monkeypatch.setattr(knowledge_router._agent_bridge_router, "SourceVault", lambda: vault)
    client = make_client(vault)

    first_packages = client.get("/api/knowledge/packages")
    assert first_packages.status_code == 200
    first_projection = {
        package["package_id"]: package
        for package in first_packages.json()["packages"]
    }["source_vault"]

    source_path.write_text(
        "FreshVaultAnchor is the edited source version.",
        encoding="utf-8",
    )
    second_source = vault.upsert_source_from_file(
        source_path,
        source_type="text",
        title="Editable Source",
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        project_id="project-alpha",
        now_iso="2026-06-25T00:02:00Z",
    ).source
    fresh_chunk_text = "FreshVaultAnchor proves edited source bytes reached bounded context."
    vault.register_chunks(
        second_source.source_id,
        [
            SourceChunkInput(
                text=fresh_chunk_text,
                chunk_index=0,
                span_start=0,
                span_end=len(fresh_chunk_text),
                metadata={"proof": "source_edit_hash"},
            )
        ],
        now_iso="2026-06-25T00:03:00Z",
    )

    second_packages = client.get("/api/knowledge/packages")
    assert second_packages.status_code == 200
    second_projection = {
        package["package_id"]: package
        for package in second_packages.json()["packages"]
    }["source_vault"]
    assert second_source.source_id != first_source.source_id
    assert second_source.source_hash != first_source.source_hash
    assert second_projection["source_hash"] != first_projection["source_hash"]
    assert second_projection["content_hash"] != first_projection["content_hash"]
    assert second_projection["manifest"]["total_sources"] == 2
    assert second_projection["manifest"]["chunk_count"] == 2
    assert second_projection["manifest"]["artifact_count"] == 2
    assert (
        second_projection["manifest"]["chunk_artifact_hash"]
        != first_projection["manifest"]["chunk_artifact_hash"]
    )

    search_response = client.get(
        "/api/knowledge/source-vault/search",
        params={"q": "FreshVaultAnchor", "project_id": "project-alpha", "limit": 1},
    )
    assert search_response.status_code == 200
    fresh_hit = search_response.json()["results"][0]
    assert fresh_hit["source_id"] == second_source.source_id
    assert fresh_hit["source_hash"] == second_source.source_hash
    assert fresh_hit["ref_id"].startswith("source_vault:chunk:")
    assert fresh_hit["metadata"]["content_hash"] == fresh_hit["text_hash"]
    assert fresh_hit["metadata"]["source_hash"] == second_source.source_hash

    resource_response = client.get(
        fresh_hit["read_endpoint"],
        params={"project_id": "project-alpha", "max_chars": 260, "cursor": "0"},
    )
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "source_vault"
    assert "FreshVaultAnchor" in resource["content"]
    assert resource["metadata"]["source_id"] == second_source.source_id
    assert resource["metadata"]["source_hash"] == second_source.source_hash
    assert resource["metadata"]["content_hash"] == fresh_hit["text_hash"]

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [fresh_hit["ref_id"]],
            "project_id": "project-alpha",
            "prompt_name": "source_vault_source_edit_probe",
            "max_chars_per_ref": 260,
        },
    )
    assert receipt_response.status_code == 200
    receipt_body = receipt_response.json()
    assert "FreshVaultAnchor" in receipt_body["assembled_context_preview"]
    receipt = receipt_body["resource_read_receipts"][0]
    assert receipt["ref_id"] == fresh_hit["ref_id"]
    assert receipt["kind"] == "source_vault"
    assert receipt["source_hash"] == second_source.source_hash
    assert receipt["package_content_hash"] == fresh_hit["text_hash"]
    assert receipt["source_path"] == fresh_hit["metadata"]["source_path"]
    assert receipt["metadata"]["source_id"] == second_source.source_id
    assert receipt["metadata"]["content_hash"] == fresh_hit["text_hash"]


def test_source_vault_search_rejects_blank_query(tmp_path: Path) -> None:
    client = make_client(make_vault(tmp_path))

    response = client.get("/api/knowledge/source-vault/search", params={"q": "   "})

    assert response.status_code == 422


def test_source_vault_overview_rejects_invalid_limit(tmp_path: Path) -> None:
    client = make_client(make_vault(tmp_path))

    response = client.get("/api/knowledge/source-vault", params={"limit": 0})

    assert response.status_code == 422


def test_empty_source_vault_does_not_create_context_receipts(tmp_path: Path) -> None:
    """An empty Source Vault should stay searchable but must not prove loaded context."""

    client = make_client(make_vault(tmp_path))

    search_response = client.get("/api/knowledge/source-vault/search", params={"q": "molten pool"})

    assert search_response.status_code == 200
    search_body = search_response.json()
    assert search_body["query"] == "molten pool"
    assert search_body["results"] == []

    read_response = client.get(
        "/api/agent-bridge/resource/source_vault:chunk:missing_chunk",
        params={"max_chars": 240},
    )
    assert read_response.status_code == 404
    assert "Source Vault chunk not found" in str(read_response.json())

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": ["source_vault:chunk:missing_chunk"],
            "prompt_name": "empty_source_vault_probe",
            "max_chars_per_ref": 240,
        },
    )

    assert receipt_response.status_code == 404
    assert "Source Vault chunk not found" in str(receipt_response.json())


def test_knowledge_packages_returns_normalized_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    seed_vault(vault)
    root = tmp_path / "english_discourse"
    seed_academic_english_output(root)

    from literature_assistant.core import tolf_bridge_lexicon_store

    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(json.dumps({"激光": ["laser"]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        tolf_bridge_lexicon_store,
        "_DEFAULT_STORE",
        tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path),
    )
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(knowledge_router, "output_path", lambda *parts: tmp_path.joinpath(*parts))

    class _FakeManifestDrilldown:
        status = "aligned"

        @staticmethod
        def model_dump() -> dict[str, object]:
            return {
                "schema_version": "scholar-ai-wiki-manifest-drilldown/v1",
                "status": "aligned",
                "hash_algorithm": "sha256",
                "limit": 10,
                "missing_count": 0,
                "extra_count": 0,
                "mismatched_count": 0,
                "truncated": False,
                "missing_pages": [],
                "extra_pages": [],
                "mismatched_pages": [],
            }

    class _FakeWikiStatus:
        enabled = True
        page_count = 2
        stale = False
        integrity_status = "aligned"
        index_hash = "i" * 64
        source_manifest_hash = "s" * 64
        indexed_source_manifest_hash = "s" * 64
        indexed_page_count = 2
        source_page_count = 2
        warnings: list[str] = []
        manifest_drilldown = _FakeManifestDrilldown()
        paths = {
            "wiki_root": str(tmp_path / "wiki"),
            "graph_json": str(tmp_path / "wiki_graph.json"),
            "graph_db": str(tmp_path / "wiki_graph.db"),
            "query_index": str(tmp_path / "wiki_query_index"),
            "review_queue": str(tmp_path / "wiki_review_queue"),
        }

        @staticmethod
        def model_dump() -> dict[str, object]:
            return {
                "enabled": True,
                "page_count": 2,
                "stale": False,
                "integrity_status": "aligned",
                "index_hash": "i" * 64,
                "source_manifest_hash": "s" * 64,
                "indexed_source_manifest_hash": "s" * 64,
                "indexed_page_count": 2,
                "source_page_count": 2,
                "graph_json_exists": False,
                "graph_db_exists": False,
                "query_index_exists": False,
                "review_queue_exists": False,
                "paths": _FakeWikiStatus.paths,
                "warnings": [],
                "manifest_drilldown": _FakeManifestDrilldown.model_dump(),
            }

    monkeypatch.setattr(knowledge_router._wiki_router, "wiki_status", lambda user_id=None: _FakeWikiStatus())

    client = make_client(vault)
    response = client.get("/api/knowledge/packages")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "scholar-ai-knowledge-packages/v1"
    assert [package["package_id"] for package in body["packages"]] == [
        "wiki",
        "source_vault",
        "academic_english",
        "bridge_lexicon",
        "skill_package:academic-english-discourse",
        "config:scoring_rules",
        "product_docs",
    ]
    packages = {package["package_id"]: package for package in body["packages"]}

    wiki = packages["wiki"]
    assert wiki["kind"] == "wiki"
    assert wiki["read_endpoint"] == "/api/wiki/status"
    assert wiki["search_endpoint"] == "/api/wiki/search"
    assert wiki["manifest"]["manifest_drilldown"]["schema_version"] == "scholar-ai-wiki-manifest-drilldown/v1"
    assert wiki["manifest"]["runtime_consumers"] == [
        {
            "consumer": "api.wiki.search",
            "use": "Knowledge Runtime Pipeline searchable wiki refs",
        },
        {
            "consumer": "literature.evidence_pack_build",
            "use": "wiki joint-recall refs when the integrity gate is aligned",
        },
        {
            "consumer": "literature.agent_resource_read",
            "use": "bounded wiki resource loading",
        },
    ]
    assert wiki["manifest"]["paths"]["query_index"].endswith("query_index")
    assert wiki["available"] is True
    assert wiki["loaded"] is True
    assert wiki["manifest_loaded"] is True
    assert wiki["source_hash"] == "s" * 64

    source_vault = packages["source_vault"]
    assert source_vault["kind"] == "source_vault"
    assert source_vault["read_endpoint"] == "/api/knowledge/source-vault"
    assert source_vault["search_endpoint"] == "/api/knowledge/source-vault/search"
    assert source_vault["manifest"]["total_sources"] == 1
    assert source_vault["manifest"]["chunk_count"] == 2
    assert source_vault["manifest"]["artifact_count"] == 1
    assert len(source_vault["manifest"]["chunk_artifact_hash"]) == 64
    assert source_vault["manifest"]["manifest_hash"] == source_vault["content_hash"]
    assert source_vault["manifest"]["empty_runtime"] is False
    assert source_vault["manifest"]["loaded_ref_count"] == 2
    assert source_vault["manifest"]["required_for_loaded_context"] == [
        "at least one source_assets row",
        "at least one source_chunks row",
    ]
    assert source_vault["manifest"]["runtime_consumers"] == [
        {
            "consumer": "literature.evidence_pack_build",
            "use": "project evidence pack retrieval",
        },
        {
            "consumer": "literature.agent_resource_read",
            "use": "bounded source-vault chunk resource loading",
        },
        {
            "consumer": "api.knowledge.source_vault.search",
            "use": "Knowledge Runtime Pipeline searchable chunk refs",
        },
    ]
    assert source_vault["loaded"] is True
    assert source_vault["source_path"].endswith("source_vault")
    assert len(source_vault["source_hash"]) == 64
    assert len(source_vault["content_hash"]) == 64

    academic = packages["academic_english"]
    assert academic["kind"] == "academic_english"
    assert academic["read_endpoint"] == "/api/knowledge/academic-english/status"
    assert academic["search_endpoint"] == "/api/knowledge/academic-english/search"
    assert academic["manifest"]["knowledge_sources"]["academic_english_habits"]["load_status"] == "loaded"
    assert academic["loaded"] is True
    assert academic["manifest_loaded"] is True
    assert academic["source_path"].endswith("english_discourse_habits.md")

    bridge = packages["bridge_lexicon"]
    assert bridge["kind"] == "bridge_lexicon"
    assert bridge["read_endpoint"] == "/api/knowledge/bridge-lexicon/read"
    assert bridge["search_endpoint"] == "/api/knowledge/bridge-lexicon/search"
    assert bridge["manifest"]["entry_count"] == 1
    assert bridge["loaded"] is True
    assert bridge["source_path"].endswith("cjk_bridge_lexicon.json")

    skill_package = packages["skill_package:academic-english-discourse"]
    assert skill_package["kind"] == "skill_package"
    assert skill_package["read_endpoint"] == "/api/knowledge/skill-packages/academic-english-discourse/status"
    assert skill_package["search_endpoint"] == "/api/knowledge/skill-packages/academic-english-discourse/search"
    assert skill_package["source_path"] == "extension_packages/skills/academic-english-discourse/SKILL.md"
    assert len(skill_package["source_hash"]) == 64
    assert len(skill_package["content_hash"]) == 64
    assert skill_package["loaded"] is True
    assert skill_package["manifest_loaded"] is True
    assert skill_package["manifest"]["version"] == "0.2.0"
    assert skill_package["manifest"]["skill_kind"] == "style"
    assert set(skill_package["manifest"]["high_risk_flags"]) >= {"files.write", "network", "script.execute"}
    assert skill_package["manifest"]["chunk_count"] >= 3

    scoring_rules = packages["config:scoring_rules"]
    assert scoring_rules["kind"] == "config"
    assert scoring_rules["read_endpoint"] == "/api/knowledge/scoring-rules/status"
    assert scoring_rules["search_endpoint"] == "/api/knowledge/scoring-rules/search"
    assert scoring_rules["source_path"] == "literature_assistant/core/config/scoring_rules.json"
    assert len(scoring_rules["source_hash"]) == 64
    assert len(scoring_rules["content_hash"]) == 64
    assert scoring_rules["loaded"] is True
    assert scoring_rules["manifest_loaded"] is True
    assert scoring_rules["manifest"]["config_id"] == "scoring_rules"
    assert scoring_rules["manifest"]["section_count"] == 4
    assert scoring_rules["manifest"]["load_status"] == "loaded"

    product_docs = packages["product_docs"]
    assert product_docs["kind"] == "product_docs"
    assert product_docs["read_endpoint"] == "/api/knowledge/product-docs/status"
    assert product_docs["search_endpoint"] == "/api/knowledge/product-docs/search"
    assert product_docs["source_path"] == "README.md + docs/*.md"
    assert len(product_docs["source_hash"]) == 64
    assert len(product_docs["content_hash"]) == 64
    assert product_docs["loaded"] is True
    assert product_docs["manifest_loaded"] is True
    assert product_docs["manifest"]["chunk_count"] >= 1
    assert "README.md" in product_docs["manifest"]["source_paths"]


def test_knowledge_runtime_conformance_marks_prompt_context_receipt_proved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Conformance should expose the context-receipt contract for ref packages."""

    vault = make_vault(tmp_path)
    seed_vault(vault)
    root = tmp_path / "english_discourse"
    seed_academic_english_output(root)

    from literature_assistant.core import tolf_bridge_lexicon_store

    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(json.dumps({"激光": ["laser"]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        tolf_bridge_lexicon_store,
        "_DEFAULT_STORE",
        tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path),
    )
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(knowledge_router, "output_path", lambda *parts: tmp_path.joinpath(*parts))

    class _FakeManifestDrilldown:
        status = "aligned"

        @staticmethod
        def model_dump() -> dict[str, object]:
            return {
                "schema_version": "scholar-ai-wiki-manifest-drilldown/v1",
                "status": "aligned",
                "hash_algorithm": "sha256",
                "limit": 10,
                "missing_count": 0,
                "extra_count": 0,
                "mismatched_count": 0,
                "truncated": False,
                "missing_pages": [],
                "extra_pages": [],
                "mismatched_pages": [],
            }

    class _FakeWikiStatus:
        enabled = True
        page_count = 2
        stale = False
        integrity_status = "aligned"
        index_hash = "i" * 64
        source_manifest_hash = "s" * 64
        indexed_source_manifest_hash = "s" * 64
        indexed_page_count = 2
        source_page_count = 2
        warnings: list[str] = []
        manifest_drilldown = _FakeManifestDrilldown()
        paths = {
            "wiki_root": str(tmp_path / "wiki"),
            "graph_json": str(tmp_path / "wiki_graph.json"),
            "graph_db": str(tmp_path / "wiki_graph.db"),
            "query_index": str(tmp_path / "wiki_query_index"),
            "review_queue": str(tmp_path / "wiki_review_queue"),
        }

        @staticmethod
        def model_dump() -> dict[str, object]:
            return {
                "enabled": True,
                "page_count": 2,
                "stale": False,
                "integrity_status": "aligned",
                "index_hash": "i" * 64,
                "source_manifest_hash": "s" * 64,
                "indexed_source_manifest_hash": "s" * 64,
                "indexed_page_count": 2,
                "source_page_count": 2,
                "paths": _FakeWikiStatus.paths,
                "warnings": [],
                "manifest_drilldown": _FakeManifestDrilldown.model_dump(),
            }

    monkeypatch.setattr(knowledge_router._wiki_router, "wiki_status", lambda user_id=None: _FakeWikiStatus())

    client = make_client(vault)
    response = client.get("/api/knowledge/runtime-conformance")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "scholar-ai-knowledge-runtime-conformance/v1"
    assert body["pipeline"] == [
        "authoritative_source",
        "builder_or_loader",
        "structured_runtime_artifact",
        "searchable_index",
        "evidence_or_resource_ref",
        "bounded_context_loading",
        "prompt_assembly_context_receipt",
        "qa_agent_actual_loading_gate",
        "manifest_audit_test_proof",
    ]
    assert body["actual_loading_gate"]["status"] == "blocked"
    assert body["actual_loading_gate"]["verdict"] == "missing_artifact"
    assert body["actual_loading_gate"]["artifact_exists"] is False
    assert body["actual_loading_gate"]["artifact_schema_valid"] is False
    assert body["actual_loading_gate"]["artifact_contract_valid"] is False
    assert body["actual_loading_gate"]["artifact_checked_at"].endswith("Z")
    assert body["actual_loading_gate"]["artifact_path"].endswith(
        "live_api_chat_knowledge_context_receipt_smoke.summary.json"
    )
    assert (
        body["actual_loading_gate"]["artifact_ref"]
        == "workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json"
    )
    assert "authorized live provider smoke artifact with verdict=ok" in body["actual_loading_gate"]["missing"]
    assert "Require provider_preflight.status=proved before running live context-receipt smoke." in (
        body["actual_loading_gate"]["next_safe_local_actions"]
    )
    assert "Run tests/live_api_chat_knowledge_context_receipt_smoke.py only with explicit live-provider authorization." in (
        body["actual_loading_gate"]["next_safe_local_actions"]
    )
    packages = {package["package_id"]: package for package in body["packages"]}
    assert set(packages) == {
        "wiki",
        "source_vault",
        "academic_english",
        "bridge_lexicon",
        "skill_package:academic-english-discourse",
        "config:scoring_rules",
        "product_docs",
    }

    product_docs = packages["product_docs"]
    assert product_docs["overall_status"] == "proved"
    assert product_docs["test_evidence"]["focused_test_exists"] is True
    assert product_docs["test_evidence"]["source_edit_hash_test"] is True
    assert product_docs["test_evidence"]["context_receipt_test"] is True
    assert product_docs["test_evidence"]["evidence_pack_test"] is True
    assert product_docs["test_evidence"]["agent_resource_read_test"] is True
    assert product_docs["test_evidence"]["mcp_tool_test"] is True
    assert (
        "tests/test_knowledge_router.py::test_product_docs_source_edit_rebuilds_search_resource_and_context_receipt"
        in product_docs["test_evidence"]["test_nodes"]
    )
    product_items = {item["requirement"]: item for item in product_docs["conformance"]}
    assert product_items["authoritative_source"]["status"] == "proved"
    assert product_items["authoritative_source"]["evidence_level"] == "runtime_projection"
    assert "source_hash" in product_items["authoritative_source"]["evidence_scope"]
    assert product_items["searchable_index"]["status"] == "proved"
    assert product_items["bounded_context_loading"]["status"] == "proved"
    assert product_items["bounded_context_loading"]["evidence_level"] == "runtime_projection"
    assert product_items["agent_resource_read"]["status"] == "proved"
    assert product_items["evidence_pack_ref_protocol"]["status"] == "proved"
    assert product_items["mcp_entry"]["status"] == "proved"
    assert product_items["mcp_entry"]["evidence_level"] == "contract_evidence"
    assert product_items["prompt_assembly_context_receipt"]["status"] == "proved"
    assert product_items["prompt_assembly_context_receipt"]["evidence_level"] == "focused_test_evidence"
    assert "prompt_context_hash" in product_items["prompt_assembly_context_receipt"]["evidence_scope"]
    assert "/api/knowledge/context-receipt" in product_items["prompt_assembly_context_receipt"]["evidence"]
    assert "literature.knowledge_context_receipt" in product_items["prompt_assembly_context_receipt"]["evidence"]
    assert product_items["manifest_audit_test_proof"]["status"] == "proved"
    assert product_items["manifest_audit_test_proof"]["evidence_level"] == "focused_test_evidence"
    assert "source_edit_hash_test" in product_items["manifest_audit_test_proof"]["evidence_scope"]
    assert "context_receipt_test" in product_items["manifest_audit_test_proof"]["evidence_scope"]
    assert "literature.product_docs_search" in product_docs["mcp_tools"]
    assert "literature.knowledge_context_receipt" in product_docs["mcp_tools"]
    assert any(
        consumer["consumer"] == "literature_assistant.core.routers.agent_bridge_router"
        for consumer in product_docs["runtime_consumers"]
    )

    bridge = packages["bridge_lexicon"]
    bridge_items = {item["requirement"]: item for item in bridge["conformance"]}
    assert bridge["overall_status"] == "proved"
    assert bridge["test_evidence"]["focused_test_exists"] is True
    assert bridge["test_evidence"]["source_edit_hash_test"] is True
    assert bridge["test_evidence"]["context_receipt_test"] is True
    assert bridge["test_evidence"]["agent_resource_read_test"] is True
    assert bridge["test_evidence"]["mcp_tool_test"] is True
    assert bridge_items["searchable_index"]["status"] == "proved"
    assert bridge_items["chunk_or_ref_protocol"]["status"] == "proved"
    assert bridge_items["bounded_context_loading"]["status"] == "proved"
    assert bridge_items["agent_resource_read"]["status"] == "proved"
    assert bridge_items["evidence_pack_ref_protocol"]["status"] == "not_applicable"
    assert bridge_items["prompt_assembly_context_receipt"]["status"] == "proved"
    assert bridge_items["prompt_assembly_context_receipt"]["evidence_level"] == "focused_test_evidence"
    assert bridge_items["mcp_entry"]["status"] == "proved"
    assert "literature.bridge_lexicon_search" in bridge["mcp_tools"]
    assert any(
        consumer["consumer"] == "literature_assistant.core.routers.agent_bridge_router"
        for consumer in bridge["runtime_consumers"]
    )

    wiki = packages["wiki"]
    wiki_items = {item["requirement"]: item for item in wiki["conformance"]}
    assert wiki_items["chunk_or_ref_protocol"]["status"] == "proved"
    assert any(
        evidence.startswith("chunk_count=")
        for evidence in wiki_items["chunk_or_ref_protocol"]["evidence"]
    )
    assert wiki_items["evidence_pack_ref_protocol"]["status"] == "proved"
    assert wiki_items["prompt_assembly_context_receipt"]["status"] == "proved"
    assert wiki_items["manifest_audit_test_proof"]["evidence_level"] == "focused_test_evidence"
    assert wiki_items["mcp_entry"]["status"] == "proved"
    assert wiki["test_evidence"]["mcp_tool_test"] is True
    assert "literature.wiki_status" in wiki["mcp_tools"]
    assert "literature.wiki_search" in wiki["mcp_tools"]
    assert "literature.agent_resource_read" in wiki["mcp_tools"]
    assert "literature.knowledge_context_receipt" in wiki["mcp_tools"]
    assert "agent_mcp_server/tests/test_runtime_tools.py::test_wiki_search_returns_refs_only" in wiki["test_evidence"]["test_nodes"]

    source_vault = packages["source_vault"]
    source_vault_items = {item["requirement"]: item for item in source_vault["conformance"]}
    assert source_vault["overall_status"] == "proved"
    assert source_vault["test_evidence"]["focused_test_exists"] is True
    assert source_vault["test_evidence"]["source_edit_hash_test"] is True
    assert source_vault["test_evidence"]["context_receipt_test"] is True
    assert source_vault["test_evidence"]["evidence_pack_test"] is True
    assert source_vault["test_evidence"]["agent_resource_read_test"] is True
    assert source_vault["test_evidence"]["mcp_tool_test"] is True
    assert (
        "tests/test_knowledge_router.py::test_source_vault_source_edit_rebuilds_hash_ref_resource_and_context_receipt"
        in source_vault["test_evidence"]["test_nodes"]
    )
    assert (
        "tests/test_evidence_pack_build_contract.py::test_evidence_pack_build_adds_source_vault_shared_resource_refs"
        in source_vault["test_evidence"]["test_nodes"]
    )
    assert (
        "agent_mcp_server/tests/test_runtime_tools.py::test_source_vault_search_returns_refs_only"
        in source_vault["test_evidence"]["test_nodes"]
    )
    assert source_vault_items["authoritative_source"]["status"] == "proved"
    assert source_vault_items["structured_runtime_artifact"]["status"] == "proved"
    assert source_vault_items["searchable_index"]["status"] == "proved"
    assert source_vault_items["chunk_or_ref_protocol"]["status"] == "proved"
    assert source_vault_items["bounded_context_loading"]["status"] == "proved"
    assert source_vault_items["agent_resource_read"]["status"] == "proved"
    assert source_vault_items["evidence_pack_ref_protocol"]["status"] == "proved"
    assert source_vault_items["mcp_entry"]["status"] == "proved"
    assert source_vault_items["prompt_assembly_context_receipt"]["status"] == "proved"
    assert "source_edit_hash_test" in source_vault_items["manifest_audit_test_proof"]["evidence_scope"]
    assert "context_receipt_test" in source_vault_items["manifest_audit_test_proof"]["evidence_scope"]
    assert "evidence_pack_test" in source_vault_items["manifest_audit_test_proof"]["evidence_scope"]
    assert "agent_resource_read_test" in source_vault_items["manifest_audit_test_proof"]["evidence_scope"]
    assert "mcp_tool_test" in source_vault_items["manifest_audit_test_proof"]["evidence_scope"]
    assert source_vault_items["manifest_audit_test_proof"]["status"] == "proved"
    assert source_vault_items["manifest_audit_test_proof"]["evidence_level"] == "focused_test_evidence"
    assert "literature.source_vault_search" in source_vault["mcp_tools"]
    assert "literature.source_vault_read" in source_vault["mcp_tools"]
    assert "literature.knowledge_context_receipt" in source_vault["mcp_tools"]
    assert body["actual_loading_gate"]["status"] == "blocked"
    assert body["actual_loading_gate"]["verdict"] == "missing_artifact"
    assert body["summary"]["proved"] >= len(packages)


def write_ok_live_smoke_artifact(
    path: Path,
    *,
    digest: str = "e" * 64,
    provider: str = "hhl",
    base_host: str = "free.hanhanapi.top",
    model: str = "gpt-5.5",
) -> None:
    """Write a minimal live context-receipt artifact that satisfies the contract."""

    path.write_text(
        json.dumps(
            {
                "generatedAt": "2026-06-25T22:12:00",
                "surface": "/api/chat",
                "statusCode": 200,
                "verdict": "ok",
                "claimBoundary": (
                    "Proves one real provider turn saw a Knowledge Runtime context receipt "
                    "through the SmartRead local-tool loop and returned the assembled_context_hash."
                ),
                "provider": provider,
                "baseHost": base_host,
                "model": model,
                "directReceipt": {
                    "assembledContextHash": digest,
                },
                "chatEvidence": {
                    "toolNames": [
                        "literature.agent_resource_read",
                        "literature.knowledge_context_receipt",
                    ],
                    "usedRequiredTools": True,
                    "requiredToolSequence": [
                        "literature.agent_resource_read",
                        "literature.knowledge_context_receipt",
                    ],
                    "receiptSchemaVisibleInToolPreview": True,
                    "receiptHashVisibleInToolPreview": True,
                    "finalAnswerIncludesReceiptHash": True,
                    "queryHashMatchesDirectReceipt": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def write_provider_capability_fixture(
    path: Path,
    *,
    status: str,
    forced_tool_choice_ok: bool,
    provider: str = "hhl",
    base_url_host: str = "free.hanhanapi.top",
    model: str = "gpt-5.5",
    ordinary_chat_ok: bool = True,
    failure_class: str = "",
    masked_error: str = "",
) -> None:
    """Write a redacted provider capability record for actual-loading gate tests."""

    path.write_text(
        json.dumps(
            {
                "records": {
                    "a" * 64: {
                        "fingerprint": "a" * 64,
                        "provider": provider,
                        "base_url_host": base_url_host,
                        "model": model,
                        "status": status,
                        "ordinary_chat_ok": ordinary_chat_ok,
                        "forced_tool_choice_ok": forced_tool_choice_ok,
                        "last_probe_at": "2026-06-25T20:13:21Z",
                        "failure_class": failure_class,
                        "masked_error": masked_error,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_knowledge_runtime_conformance_proves_actual_loading_only_from_ok_live_smoke_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Live QA/model loading must be gated by the authorized smoke artifact."""

    artifact = tmp_path / "live_api_chat_knowledge_context_receipt_smoke.summary.json"
    provider_capabilities = tmp_path / "provider-capabilities.json"
    write_ok_live_smoke_artifact(artifact)
    write_provider_capability_fixture(
        provider_capabilities,
        status="tool_call_ok",
        forced_tool_choice_ok=True,
    )
    monkeypatch.setattr(knowledge_router, "output_path", lambda *parts: artifact)
    monkeypatch.setattr(knowledge_router, "_provider_capabilities_path", lambda: provider_capabilities)

    client = make_client(make_vault(tmp_path))
    response = client.get("/api/knowledge/runtime-conformance")

    assert response.status_code == 200
    gate = response.json()["actual_loading_gate"]
    assert gate["status"] == "proved"
    assert gate["evidence_level"] == "focused_test_evidence"
    assert gate["verdict"] == "ok"
    assert gate["artifact_path"] == str(artifact)
    assert gate["artifact_ref"] == (
        "workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json"
    )
    assert gate["artifact_exists"] is True
    assert gate["artifact_schema_valid"] is True
    assert gate["artifact_contract_valid"] is True
    assert gate["artifact_checked_at"].endswith("Z")
    assert gate["artifact_contract"] == "scholar-ai-live-context-receipt-smoke/v1"
    assert "live_smoke_artifact" in gate["evidence_scope"]
    assert gate["validation_errors"] == []
    assert gate["evidence"][0] == gate["artifact_ref"]
    assert any(item == f"assembledContextHash={'e' * 64}" for item in gate["evidence"])
    assert gate["provider_preflight"]["status"] == "proved"
    assert any(item == "baseHost=free.hanhanapi.top" for item in gate["evidence"])
    assert any(item == "provider_preflight_match=hhl/free.hanhanapi.top/gpt-5.5" for item in gate["evidence"])


def test_knowledge_runtime_conformance_surfaces_provider_preflight_auth_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Actual-loading gate should expose provider auth blockers without a live call."""

    artifact = tmp_path / "missing-live-smoke.json"
    provider_capabilities = tmp_path / "provider-capabilities.json"
    provider_capabilities.write_text(
        json.dumps(
            {
                "records": {
                    "a" * 64: {
                        "fingerprint": "a" * 64,
                        "provider": "hhl",
                        "base_url_host": "free.hanhanapi.top",
                        "model": "gpt-5.5",
                        "status": "auth_required",
                        "ordinary_chat_ok": False,
                        "forced_tool_choice_ok": False,
                        "last_probe_at": "2026-06-25T20:13:21Z",
                        "failure_class": "models",
                        "masked_error": "HTTP 401: Invalid token (request id: [REDACTED])",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(knowledge_router, "output_path", lambda *parts: artifact)
    monkeypatch.setattr(knowledge_router, "_provider_capabilities_path", lambda: provider_capabilities)

    client = make_client(make_vault(tmp_path))
    response = client.get("/api/knowledge/runtime-conformance")

    assert response.status_code == 200
    gate = response.json()["actual_loading_gate"]
    assert gate["status"] == "blocked"
    assert gate["verdict"] == "missing_artifact"
    preflight = gate["provider_preflight"]
    assert preflight["status"] == "blocked"
    assert preflight["artifact_exists"] is True
    assert preflight["artifact_schema_valid"] is True
    assert preflight["record_count"] == 1
    assert preflight["latest_status"] == "auth_required"
    assert preflight["artifact_ref"] == "workspace_artifacts/runtime_state/provider-capabilities.json"
    assert "provider_tool_call_status=tool_call_ok" in preflight["missing"]
    assert "valid provider credentials before live actual-loading smoke" in preflight["missing"]
    assert "Stop live actual-loading smoke while latest provider status is auth_required." in (
        preflight["next_safe_local_actions"]
    )
    assert "After the user corrects provider credentials/config, rerun provider tool-capability preflight." in (
        preflight["next_safe_local_actions"]
    )
    assert preflight["records"][0]["base_url_host"] == "free.hanhanapi.top"
    assert preflight["records"][0]["status"] == "auth_required"
    assert preflight["records"][0]["masked_error"] == "HTTP 401: Invalid token (request id: [REDACTED])"


def test_knowledge_runtime_conformance_blocks_ok_artifact_when_provider_preflight_requires_auth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An OK smoke artifact cannot override an auth_required provider preflight."""

    artifact = tmp_path / "live_api_chat_knowledge_context_receipt_smoke.summary.json"
    provider_capabilities = tmp_path / "provider-capabilities.json"
    write_ok_live_smoke_artifact(artifact)
    write_provider_capability_fixture(
        provider_capabilities,
        status="auth_required",
        forced_tool_choice_ok=False,
        ordinary_chat_ok=False,
        failure_class="models",
        masked_error="HTTP 401: Invalid token (request id: [REDACTED])",
    )
    monkeypatch.setattr(knowledge_router, "output_path", lambda *parts: artifact)
    monkeypatch.setattr(knowledge_router, "_provider_capabilities_path", lambda: provider_capabilities)

    client = make_client(make_vault(tmp_path))
    response = client.get("/api/knowledge/runtime-conformance")

    assert response.status_code == 200
    gate = response.json()["actual_loading_gate"]
    assert gate["status"] == "blocked"
    assert gate["verdict"] == "ok"
    assert gate["artifact_schema_valid"] is True
    assert gate["artifact_contract_valid"] is True
    assert "provider_preflight.status=proved" in gate["missing"]
    assert "valid provider credentials before live actual-loading smoke" in gate["missing"]
    assert "Resolve provider_preflight.status before treating an OK smoke artifact as actual-loading proof." in (
        gate["next_safe_local_actions"]
    )
    assert "provider_preflight" in gate["evidence_scope"]
    assert gate["provider_preflight"]["status"] == "blocked"
    assert gate["provider_preflight"]["latest_status"] == "auth_required"


def test_knowledge_runtime_conformance_blocks_ok_artifact_when_provider_preflight_endpoint_differs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Provider preflight must prove the same endpoint used by the live artifact."""

    artifact = tmp_path / "live_api_chat_knowledge_context_receipt_smoke.summary.json"
    provider_capabilities = tmp_path / "provider-capabilities.json"
    write_ok_live_smoke_artifact(artifact)
    write_provider_capability_fixture(
        provider_capabilities,
        status="tool_call_ok",
        forced_tool_choice_ok=True,
        provider="OpenAI",
        base_url_host="api.openai.com",
        model="gpt-test",
    )
    monkeypatch.setattr(knowledge_router, "output_path", lambda *parts: artifact)
    monkeypatch.setattr(knowledge_router, "_provider_capabilities_path", lambda: provider_capabilities)

    client = make_client(make_vault(tmp_path))
    response = client.get("/api/knowledge/runtime-conformance")

    assert response.status_code == 200
    gate = response.json()["actual_loading_gate"]
    assert gate["status"] == "blocked"
    assert gate["verdict"] == "ok"
    assert gate["artifact_schema_valid"] is True
    assert gate["artifact_contract_valid"] is True
    assert gate["provider_preflight"]["status"] == "proved"
    assert "provider_preflight_endpoint_match" in gate["evidence_scope"]
    assert gate["missing"] == [
        "provider_preflight matching provider=hhl baseHost=free.hanhanapi.top model=gpt-5.5 with tool_call_ok"
    ]
    assert "provider forced-tool preflight is not proved for the same provider/baseHost/model endpoint" in (
        gate["claim_boundary"]
    )


def test_knowledge_runtime_conformance_blocks_schema_invalid_live_smoke_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Malformed smoke summaries must produce machine-readable validation errors."""

    artifact = tmp_path / "live_api_chat_knowledge_context_receipt_smoke.summary.json"
    artifact.write_text(
        json.dumps(
            {
                "generatedAt": "2026-06-25T22:12:00",
                "surface": "/api/chat",
                "statusCode": 200,
                "verdict": "ok",
                "directReceipt": {"assembledContextHash": "not-a-sha256"},
                "chatEvidence": {"usedRequiredTools": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(knowledge_router, "output_path", lambda *parts: artifact)

    client = make_client(make_vault(tmp_path))
    response = client.get("/api/knowledge/runtime-conformance")

    assert response.status_code == 200
    gate = response.json()["actual_loading_gate"]
    assert gate["status"] == "blocked"
    assert gate["verdict"] == "invalid_artifact"
    assert gate["artifact_exists"] is True
    assert gate["artifact_schema_valid"] is False
    assert gate["artifact_contract_valid"] is False
    assert gate["artifact_checked_at"].endswith("Z")
    assert gate["artifact_contract"] == "scholar-ai-live-context-receipt-smoke/v1"
    assert "valid live smoke artifact schema" in gate["missing"]
    assert any("artifact.schema.directReceipt.assembledContextHash" in item for item in gate["validation_errors"])


def test_knowledge_runtime_conformance_blocks_contract_incomplete_live_smoke_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A schema-valid summary cannot prove loading when required checks fail."""

    artifact = tmp_path / "live_api_chat_knowledge_context_receipt_smoke.summary.json"
    artifact.write_text(
        json.dumps(
            {
                "generatedAt": "2026-06-25T22:12:00",
                "surface": "/api/chat",
                "statusCode": 200,
                "verdict": "ok",
                "claimBoundary": "Contract-incomplete artifact must stay blocked.",
                "provider": "OpenAI",
                "model": "gpt-test",
                "directReceipt": {
                    "assembledContextHash": "f" * 64,
                    "assembledContextCharCount": 321,
                    "resourceReceiptCount": 1,
                },
                "chatEvidence": {
                    "toolNames": [
                        "literature.agent_resource_read",
                        "literature.knowledge_context_receipt",
                    ],
                    "usedRequiredTools": True,
                    "requiredToolSequence": [
                        "literature.agent_resource_read",
                        "literature.knowledge_context_receipt",
                    ],
                    "receiptSchemaVisibleInToolPreview": True,
                    "receiptHashVisibleInToolPreview": True,
                    "finalAnswerIncludesReceiptHash": False,
                    "queryHashMatchesDirectReceipt": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(knowledge_router, "output_path", lambda *parts: artifact)

    client = make_client(make_vault(tmp_path))
    response = client.get("/api/knowledge/runtime-conformance")

    assert response.status_code == 200
    gate = response.json()["actual_loading_gate"]
    assert gate["status"] == "blocked"
    assert gate["verdict"] == "ok"
    assert gate["artifact_exists"] is True
    assert gate["artifact_schema_valid"] is True
    assert gate["artifact_contract_valid"] is False
    assert gate["artifact_checked_at"].endswith("Z")
    assert gate["validation_errors"] == ["artifact.receipt_hash.final_answer"]
    assert gate["missing"] == ["artifact.receipt_hash.final_answer"]
    assert "artifact.receipt_hash.final_answer" in gate["required_checks"]


def test_knowledge_runtime_conformance_blocks_endpoint_only_claims(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Endpoint strings must not prove loaded refs or prompt-context entry."""

    class _MissingWikiManifestDrilldown:
        status = "missing_index"

        @staticmethod
        def model_dump() -> dict[str, object]:
            return {
                "schema_version": "scholar-ai-wiki-manifest-drilldown/v1",
                "status": "missing_index",
                "hash_algorithm": "sha256",
                "limit": 10,
                "missing_count": 1,
                "extra_count": 0,
                "mismatched_count": 0,
                "truncated": False,
                "missing_pages": ["concepts/missing-index.md"],
                "extra_pages": [],
                "mismatched_pages": [],
            }

    class _MissingWikiStatus:
        enabled = True
        page_count = 1
        stale = True
        integrity_status = "missing_index"
        index_hash = "unknown"
        source_manifest_hash = "s" * 64
        indexed_source_manifest_hash = "unknown"
        indexed_page_count = 0
        source_page_count = 1
        warnings = ["wiki query index is missing or stale"]
        manifest_drilldown = _MissingWikiManifestDrilldown()
        paths = {
            "wiki_root": str(tmp_path / "wiki"),
            "graph_json": str(tmp_path / "wiki_graph.json"),
            "graph_db": str(tmp_path / "wiki_graph.db"),
            "query_index": str(tmp_path / "wiki_query_index.db"),
            "review_queue": str(tmp_path / "wiki_review_queue.jsonl"),
        }

        @staticmethod
        def model_dump() -> dict[str, object]:
            return {
                "enabled": True,
                "page_count": 1,
                "stale": True,
                "integrity_status": "missing_index",
                "index_hash": "unknown",
                "source_manifest_hash": "s" * 64,
                "indexed_source_manifest_hash": "unknown",
                "indexed_page_count": 0,
                "source_page_count": 1,
                "warnings": ["wiki query index is missing or stale"],
                "paths": _MissingWikiStatus.paths,
                "manifest_drilldown": _MissingWikiManifestDrilldown.model_dump(),
            }

    monkeypatch.setattr(knowledge_router._wiki_router, "wiki_status", lambda user_id=None: _MissingWikiStatus())
    client = make_client(make_vault(tmp_path))

    response = client.get("/api/knowledge/runtime-conformance")

    assert response.status_code == 200
    body = response.json()
    packages = {package["package_id"]: package for package in body["packages"]}

    wiki = packages["wiki"]
    wiki_items = {item["requirement"]: item for item in wiki["conformance"]}
    assert wiki["overall_status"] == "blocked"
    assert wiki["loaded"] is False
    assert wiki["search_endpoint"] == "/api/wiki/search"
    assert wiki["source_hash"] == "s" * 64
    assert wiki["content_hash"] == "unknown"
    assert wiki["manifest"]["source_page_count"] == 1
    assert wiki["manifest"]["indexed_page_count"] == 0
    assert wiki_items["authoritative_source"]["status"] == "proved"
    assert wiki_items["structured_runtime_artifact"]["status"] == "blocked"
    assert wiki_items["searchable_index"]["status"] == "blocked"
    assert "/api/wiki/search" in wiki_items["searchable_index"]["evidence"]
    assert "loaded runtime knowledge package" in wiki_items["searchable_index"]["missing"]
    assert wiki_items["bounded_context_loading"]["status"] == "blocked"
    assert wiki_items["agent_resource_read"]["status"] == "blocked"
    assert wiki_items["prompt_assembly_context_receipt"]["status"] == "blocked"
    assert wiki_items["mcp_entry"]["status"] == "proved"

    source_vault = packages["source_vault"]
    source_items = {item["requirement"]: item for item in source_vault["conformance"]}
    assert source_vault["overall_status"] == "blocked"
    assert source_vault["loaded"] is False
    assert source_vault["search_endpoint"] == "/api/knowledge/source-vault/search"
    assert source_vault["source_hash"] == "unknown"
    assert len(source_vault["content_hash"]) == 64
    assert source_vault["manifest"]["manifest_hash"] == source_vault["content_hash"]
    assert source_vault["manifest"]["empty_runtime"] is True
    assert source_vault["manifest"]["loaded_ref_count"] == 0
    assert source_vault["manifest"]["total_sources"] == 0
    assert source_vault["manifest"]["chunk_count"] == 0
    assert source_vault["manifest"]["artifact_count"] == 0
    assert len(source_vault["manifest"]["chunk_artifact_hash"]) == 64
    assert source_items["authoritative_source"]["status"] == "blocked"
    assert source_items["structured_runtime_artifact"]["status"] == "blocked"
    assert source_items["searchable_index"]["status"] == "blocked"
    assert source_items["chunk_or_ref_protocol"]["status"] == "blocked"
    assert source_items["bounded_context_loading"]["status"] == "blocked"
    assert source_items["agent_resource_read"]["status"] == "blocked"
    assert source_items["evidence_pack_ref_protocol"]["status"] == "blocked"
    assert source_items["prompt_assembly_context_receipt"]["status"] == "blocked"
    assert source_items["mcp_entry"]["status"] == "proved"
    assert "loaded runtime knowledge package" in source_items["searchable_index"]["missing"]
    assert "source-vault chunks" in source_items["searchable_index"]["missing"]
    assert body["summary"]["blocked"] >= 10


def test_knowledge_registry_searchable_packages_round_trip_refs_to_context_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Every registry-declared searchable package should share the ref/context protocol."""

    vault = make_vault(tmp_path)
    seed_vault(vault)
    seed_wiki_runtime(monkeypatch, tmp_path)
    english_root = tmp_path / "english_discourse"
    seed_academic_english_output(english_root)
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))

    repo_root = tmp_path / "repo"
    write_skill_package_fixture(repo_root, anchor="RegistrySkillAnchor")
    write_scoring_rules_fixture(repo_root, anchor="RegistryScoreAnchor", direct_evidence=0.97)
    docs_root = repo_root / "docs"
    docs_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "README.md").write_text(
        "# Scholar AI\n\nRegistryProductAnchor enters the shared knowledge runtime context pipeline.",
        encoding="utf-8",
    )
    (docs_root / "USAGE.md").write_text(
        "# Usage\n\nRegistryProductAnchor is read through the product_docs resource protocol.",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_package_knowledge, "REPO_ROOT", repo_root)
    monkeypatch.setattr(config_knowledge, "REPO_ROOT", repo_root)
    monkeypatch.setattr(product_docs_knowledge, "REPO_ROOT", repo_root)

    from literature_assistant.core import tolf_bridge_lexicon_store

    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(
        json.dumps({"RegistryBridgeAnchor": ["registry bridge anchor"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tolf_bridge_lexicon_store,
        "_DEFAULT_STORE",
        tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path),
    )
    monkeypatch.setattr(agent_bridge_router, "SourceVault", lambda: vault)
    monkeypatch.setattr(knowledge_router._agent_bridge_router, "SourceVault", lambda: vault)

    client = make_client(vault)
    registry_response = client.get("/api/knowledge/packages")
    conformance_response = client.get("/api/knowledge/runtime-conformance")

    assert registry_response.status_code == 200
    assert conformance_response.status_code == 200
    registry = registry_response.json()
    conformance = conformance_response.json()
    packages = {package["package_id"]: package for package in registry["packages"]}
    conformance_packages = {package["package_id"]: package for package in conformance["packages"]}
    assert set(conformance_packages) == set(packages)

    probes: dict[str, dict[str, object]] = {
        "wiki": {
            "method": "POST",
            "query": {"query": "KnowledgeRuntimeWikiAnchor"},
            "results_key": "evidence_refs",
            "expected_kind": "wiki",
            "expected_text": "KnowledgeRuntimeWikiAnchor",
        },
        "source_vault": {
            "method": "GET",
            "query": {"q": "molten pool", "project_id": "project-alpha", "limit": 1},
            "results_key": "results",
            "expected_kind": "source_vault",
            "expected_text": "molten pool",
            "project_id": "project-alpha",
        },
        "academic_english": {
            "method": "GET",
            "query": {"q": "hedging", "top_k": 1},
            "results_key": "results",
            "expected_kind": "academic_english",
            "expected_text": "Hedging calibrates claims",
        },
        "bridge_lexicon": {
            "method": "GET",
            "query": {"q": "RegistryBridgeAnchor", "top_k": 1},
            "results_key": "results",
            "expected_kind": "bridge_lexicon",
            "expected_text": "registry bridge anchor",
        },
        "skill_package:academic-english-discourse": {
            "method": "GET",
            "query": {"q": "RegistrySkillAnchor", "top_k": 1},
            "results_key": "results",
            "expected_kind": "skill_package",
            "expected_text": "RegistrySkillAnchor",
        },
        "config:scoring_rules": {
            "method": "GET",
            "query": {"q": "RegistryScoreAnchor", "top_k": 1},
            "results_key": "results",
            "expected_kind": "scoring_rules",
            "expected_text": "RegistryScoreAnchor",
        },
        "product_docs": {
            "method": "GET",
            "query": {"q": "RegistryProductAnchor", "top_k": 1},
            "results_key": "results",
            "expected_kind": "product_docs",
            "expected_text": "RegistryProductAnchor",
        },
    }
    searchable_package_ids = {
        package_id
        for package_id, package in packages.items()
        if package.get("search_endpoint")
    }
    assert searchable_package_ids == set(probes)

    for package_id, package in packages.items():
        probe = probes[package_id]
        endpoint = str(package["search_endpoint"])
        if probe["method"] == "POST":
            search_response = client.post(endpoint, json=probe["query"])
        else:
            search_response = client.get(endpoint, params=probe["query"])
        assert search_response.status_code == 200, package_id
        search_body = search_response.json()
        hits = search_body[str(probe["results_key"])]
        assert hits, package_id
        hit = hits[0]
        ref_id = hit["ref_id"]
        read_endpoint = hit["read_endpoint"]
        assert ref_id
        assert read_endpoint == f"/api/agent-bridge/resource/{ref_id}"
        assert hit["metadata"]["resource_kind"] in {"chunk", "section", "entry"}
        assert str(hit["metadata"]["knowledge_ref_schema_version"]).startswith("scholar-ai-")

        resource_response = client.get(
            read_endpoint,
            params={
                "project_id": probe.get("project_id"),
                "max_chars": 320,
                "cursor": "0",
            },
        )
        assert resource_response.status_code == 200, package_id
        resource = resource_response.json()
        assert resource["ref_id"] == ref_id
        assert resource["kind"] == probe["expected_kind"]
        assert str(probe["expected_text"]) in resource["content"]
        assert resource["metadata"]["resource_kind"] in {"chunk", "section", "entry"}
        assert str(resource["metadata"]["knowledge_ref_schema_version"]).startswith("scholar-ai-")
        assert resource["metadata"]["returned_chars"] <= 320

        receipt_response = client.post(
            "/api/knowledge/context-receipt",
            json={
                "ref_ids": [ref_id],
                "project_id": probe.get("project_id"),
                "prompt_name": f"{package_id.replace(':', '_')}_registry_round_trip",
                "max_chars_per_ref": 320,
            },
        )
        assert receipt_response.status_code == 200, package_id
        receipt_body = receipt_response.json()
        assert receipt_body["schema_version"] == "scholar-ai-knowledge-context-receipt/v1"
        assert str(probe["expected_text"]) in receipt_body["assembled_context_preview"]
        assert len(receipt_body["assembled_context_hash"]) == 64
        assert receipt_body["provenance"]["resource_reader"] == "literature_assistant.core.routers.agent_bridge_router"
        receipt = receipt_body["resource_read_receipts"][0]
        assert receipt["ref_id"] == ref_id
        assert receipt["kind"] == probe["expected_kind"]
        assert receipt["read_endpoint"] == read_endpoint
        assert len(receipt["content_hash"]) == 64
        assert len(receipt["source_hash"]) == 64
        assert len(receipt["package_content_hash"]) == 64
        assert receipt["source_path"]

        conformance_items = {
            item["requirement"]: item
            for item in conformance_packages[package_id]["conformance"]
        }
        for requirement in [
            "searchable_index",
            "chunk_or_ref_protocol",
            "bounded_context_loading",
            "agent_resource_read",
            "prompt_assembly_context_receipt",
        ]:
            assert conformance_items[requirement]["status"] == "proved", (package_id, requirement)


def test_academic_english_status_redacts_generated_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "english_discourse"
    seed_academic_english_output(root)
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))
    client = make_client(make_vault(tmp_path))

    response = client.get("/api/knowledge/academic-english/status")

    assert response.status_code == 200
    body = response.json()
    assert body["manifest_loaded"] is True
    assert body["knowledge_sources"]["academic_english_habits"]["load_status"] == "loaded"
    assert "source_path" not in body["knowledge_sources"]["academic_english_habits"]
    assert body["artifacts"]["chunks_jsonl"]["relative_path"] == "english_discourse/chunks.jsonl"
    serialized = json.dumps(body)
    assert "C:/private" not in serialized


def test_academic_english_status_recovers_legacy_manifest_artifact_hashes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Legacy generated manifests should not hide existing runtime artifacts."""

    root = tmp_path / "english_discourse"
    root.mkdir(parents=True)
    policy_markdown = "# Academic English Discourse Habits\n\nLegacyPolicyAnchor calibrates claims."
    habits_path = root / "academic_english_habits.json"
    habits_path.write_text(
        json.dumps(
            {
                "schema_version": "0.2",
                "knowledge_type": "academic_english_habits",
                "policy_loaded": True,
                "policy_markdown": policy_markdown,
                "policy_source": "references/english_discourse_habits.md",
                "purpose": "Legacy manifest compatibility.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunks_path = root / "chunks.jsonl"
    chunks_path.write_text(
        json.dumps(
            {
                "chunk_id": "legacy-chunk",
                "title": "Legacy Chunk",
                "section": "policy",
                "text": "LegacyPolicyAnchor enters runtime search.",
                "summary": "LegacyPolicyAnchor enters runtime search.",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "0.2",
                "builder_version": "0.2.0",
                "built_at": "2026-06-23T18:01:28+00:00",
                "counts": {"chunks": 1, "phrases": 0},
                "outputs": {
                    "chunks_jsonl": str(chunks_path),
                    "academic_english_habits_json": str(habits_path),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    expected_policy_hash = hashlib.sha256(policy_markdown.encode("utf-8")).hexdigest()
    expected_chunks_hash = hashlib.sha256(chunks_path.read_bytes()).hexdigest()
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))
    client = make_client(make_vault(tmp_path))

    status_response = client.get("/api/knowledge/academic-english/status")
    packages_response = client.get("/api/knowledge/packages")

    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["manifest_loaded"] is True
    assert status_body["artifacts"]["chunks_jsonl"]["exists"] is True
    assert status_body["artifacts"]["chunks_jsonl"]["sha256"] == expected_chunks_hash
    source = status_body["knowledge_sources"]["academic_english_habits"]
    assert source["load_status"] == "loaded"
    assert source["content_hash"] == expected_policy_hash
    assert "source_path" not in source

    assert packages_response.status_code == 200
    packages = {item["package_id"]: item for item in packages_response.json()["packages"]}
    academic = packages["academic_english"]
    assert academic["loaded"] is True
    assert academic["source_hash"] == expected_policy_hash
    assert len(academic["content_hash"]) == 64


def test_knowledge_packages_openapi_contract() -> None:
    from python_adapter_server import app as full_app

    full_app.openapi_schema = None
    schema = full_app.openapi()

    assert "/api/knowledge/packages" in schema["paths"]
    assert "/api/knowledge/runtime-conformance" in schema["paths"]
    packages_operation = schema["paths"]["/api/knowledge/packages"]["get"]
    assert packages_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/KnowledgePackagesResponse"
    }
    conformance_operation = schema["paths"]["/api/knowledge/runtime-conformance"]["get"]
    assert conformance_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/KnowledgeRuntimeConformanceResponse"
    }
    package_schema = schema["components"]["schemas"]["KnowledgePackagesResponse"]
    assert set(package_schema["properties"]) >= {"schema_version", "packages"}
    conformance_schema = schema["components"]["schemas"]["KnowledgeRuntimeConformanceResponse"]
    assert set(conformance_schema["properties"]) >= {
        "schema_version",
        "pipeline",
        "summary",
        "actual_loading_gate",
        "packages",
    }
    assert (
        conformance_schema["properties"]["actual_loading_gate"]["$ref"]
        == "#/components/schemas/KnowledgeRuntimeActualLoadingGateResponse"
    )
    actual_gate_schema = schema["components"]["schemas"]["KnowledgeRuntimeActualLoadingGateResponse"]
    assert set(actual_gate_schema["properties"]) >= {
        "status",
        "evidence_level",
        "artifact_path",
        "artifact_ref",
        "artifact_exists",
        "artifact_schema_valid",
        "artifact_contract_valid",
        "artifact_checked_at",
        "artifact_contract",
        "verdict",
        "evidence_scope",
        "evidence",
        "missing",
        "validation_errors",
        "required_checks",
        "next_safe_local_actions",
        "claim_boundary",
        "provider_preflight",
    }
    assert (
        actual_gate_schema["properties"]["provider_preflight"]["$ref"]
        == "#/components/schemas/KnowledgeRuntimeProviderPreflightResponse"
    )
    provider_preflight_schema = schema["components"]["schemas"]["KnowledgeRuntimeProviderPreflightResponse"]
    assert set(provider_preflight_schema["properties"]) >= {
        "status",
        "evidence_level",
        "artifact_path",
        "artifact_ref",
        "artifact_exists",
        "artifact_schema_valid",
        "checked_at",
        "record_count",
        "latest_status",
        "records",
        "evidence_scope",
        "evidence",
        "missing",
        "validation_errors",
        "next_safe_local_actions",
        "claim_boundary",
    }
    projection_schema = schema["components"]["schemas"]["KnowledgePackageProjectionResponse"]
    assert package_schema["properties"]["packages"]["items"]["$ref"] == "#/components/schemas/KnowledgePackageProjectionResponse"
    assert set(projection_schema["properties"]) >= {
        "package_id",
        "kind",
        "title",
        "status",
        "read_endpoint",
        "manifest",
    }


def test_academic_english_search_returns_bounded_refs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "english_discourse"
    seed_academic_english_output(root)
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))
    client = make_client(make_vault(tmp_path))

    response = client.get("/api/knowledge/academic-english/search", params={"q": "hedging", "top_k": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "hedging"
    assert body["results"]
    first = body["results"][0]
    assert first["ref_id"] == "academic_english:chunk:chunk-hedging"
    assert first["read_endpoint"] == "/api/agent-bridge/resource/academic_english:chunk:chunk-hedging"
    assert "Hedging calibrates claims" in first["summary"]
    assert first["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-academic-english-knowledge-ref/v1"
    assert first["metadata"]["source"] == "academic_english"
    assert first["metadata"]["source_id"] == "source-1"
    assert first["metadata"]["source_type"] == "text"
    assert first["metadata"]["source_path"] == "source:leak.txt"
    assert first["metadata"]["source_hash"] == hashlib.sha256(b"source text for hedging records").hexdigest()
    expected_chunk_text = "Hedging calibrates claims and OldAcademicAnchor preserves evidential strength in academic prose."
    assert first["metadata"]["content_hash"] == hashlib.sha256(expected_chunk_text.encode("utf-8")).hexdigest()
    assert first["metadata"]["span_start"] == 7
    assert first["metadata"]["span_end"] == 7 + len(expected_chunk_text)
    assert "artifact_hashes" in first["metadata"]
    serialized = json.dumps(body)
    assert "C:/private" not in serialized
    assert "should/not/leak" not in serialized


def test_academic_english_artifact_edit_updates_search_resource_and_context_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A generated artifact edit should flow through refs, resources, and receipts."""

    root = tmp_path / "english_discourse"
    seed_academic_english_output(root)
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))
    client = make_client(make_vault(tmp_path))

    first_status_response = client.get("/api/knowledge/academic-english/status")
    assert first_status_response.status_code == 200
    first_status = first_status_response.json()
    first_chunks_hash = first_status["artifacts"]["chunks_jsonl"]["sha256"]

    first_search_response = client.get(
        "/api/knowledge/academic-english/search",
        params={"q": "OldAcademicAnchor", "top_k": 1},
    )
    assert first_search_response.status_code == 200
    first_hit = first_search_response.json()["results"][0]
    assert first_hit["ref_id"] == "academic_english:chunk:chunk-hedging"
    assert first_hit["metadata"]["artifact_hashes"]["chunks_jsonl"] == first_chunks_hash

    fresh_record = rewrite_academic_english_chunk(root, anchor="FreshAcademicAnchor")

    second_status_response = client.get("/api/knowledge/academic-english/status")
    assert second_status_response.status_code == 200
    second_status = second_status_response.json()
    second_chunks_hash = second_status["artifacts"]["chunks_jsonl"]["sha256"]
    assert second_chunks_hash != first_chunks_hash

    stale_search_response = client.get(
        "/api/knowledge/academic-english/search",
        params={"q": "OldAcademicAnchor", "top_k": 1},
    )
    assert stale_search_response.status_code == 200
    assert stale_search_response.json()["results"] == []

    fresh_search_response = client.get(
        "/api/knowledge/academic-english/search",
        params={"q": "FreshAcademicAnchor", "top_k": 1},
    )
    assert fresh_search_response.status_code == 200
    fresh_hit = fresh_search_response.json()["results"][0]
    assert fresh_hit["kind"] == "academic_english"
    assert fresh_hit["resource_kind"] == "chunk"
    assert fresh_hit["ref_id"] == "academic_english:chunk:chunk-hedging"
    assert fresh_hit["read_endpoint"] == "/api/agent-bridge/resource/academic_english:chunk:chunk-hedging"
    assert fresh_hit["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-academic-english-knowledge-ref/v1"
    assert fresh_hit["metadata"]["artifact_hashes"]["chunks_jsonl"] == second_chunks_hash
    assert fresh_hit["metadata"]["source_hash"] == fresh_record["source_hash"]
    assert fresh_hit["metadata"]["content_hash"] == fresh_record["content_hash"]

    resource_response = client.get(fresh_hit["read_endpoint"], params={"max_chars": 220, "cursor": "0"})
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "academic_english"
    assert "FreshAcademicAnchor" in resource["content"]
    assert "OldAcademicAnchor" not in resource["content"]
    assert resource["metadata"]["artifact_hashes"]["chunks_jsonl"] == second_chunks_hash

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [fresh_hit["ref_id"]],
            "prompt_name": "academic_english_artifact_change_probe",
            "max_chars_per_ref": 220,
        },
    )

    assert receipt_response.status_code == 200
    receipt_body = receipt_response.json()
    assert "FreshAcademicAnchor" in receipt_body["assembled_context_preview"]
    assert "OldAcademicAnchor" not in receipt_body["assembled_context_preview"]
    assert len(receipt_body["assembled_context_hash"]) == 64
    receipt = receipt_body["resource_read_receipts"][0]
    assert receipt["ref_id"] == fresh_hit["ref_id"]
    assert receipt["kind"] == "academic_english"
    assert receipt["read_endpoint"] == "/api/agent-bridge/resource/academic_english:chunk:chunk-hedging"
    assert receipt["source_path"] == fresh_hit["metadata"]["source_path"]
    assert receipt["metadata"]["content_hash"] == fresh_hit["metadata"]["content_hash"]
    assert receipt["metadata"]["artifact_hashes"]["chunks_jsonl"] == second_chunks_hash


def test_academic_english_policy_source_edit_rebuilds_search_resource_and_context_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A policy Markdown edit should rebuild hashes and enter bounded prompt context."""

    builder = load_academic_english_builder()
    policy_path = tmp_path / "references" / "english_discourse_habits.md"
    policy_path.parent.mkdir(parents=True)
    text_source = tmp_path / "mini_review.txt"
    text_source.write_text(
        (
            "Research on evidence-grounded drafting has increasingly focused on hedging. "
            "However, little is known about how bilingual writers preserve cautious claims."
        ),
        encoding="utf-8",
    )
    policy_path.write_text(
        "# Academic English Discourse Habits\n\nOldPolicyAnchor keeps the initial policy visible.",
        encoding="utf-8",
    )
    first_output = tmp_path / "first" / "english_discourse"
    monkeypatch.setattr(builder, "_habit_policy_path", lambda: policy_path)
    first_manifest = build_academic_english_fixture(builder, output_dir=first_output, text_source=text_source)
    first_habits = json.loads((first_output / "academic_english_habits.json").read_text(encoding="utf-8"))
    first_policy_hash = first_habits["policy_content_hash"]
    first_artifact_hash = first_manifest["output_artifacts"]["academic_english_habits_json"]["sha256"]

    policy_path.write_text(
        "# Academic English Discourse Habits\n\nFreshPolicyAnchor proves source edits rebuild runtime context.",
        encoding="utf-8",
    )
    second_output = tmp_path / "second" / "english_discourse"
    second_manifest = build_academic_english_fixture(builder, output_dir=second_output, text_source=text_source)
    second_habits = json.loads((second_output / "academic_english_habits.json").read_text(encoding="utf-8"))
    second_policy_hash = second_habits["policy_content_hash"]
    second_artifact_hash = second_manifest["output_artifacts"]["academic_english_habits_json"]["sha256"]

    assert second_policy_hash != first_policy_hash
    assert second_artifact_hash != first_artifact_hash
    assert second_manifest["knowledge_sources"]["academic_english_habits"]["content_hash"] == second_policy_hash
    assert "FreshPolicyAnchor" in second_habits["policy_markdown"]
    assert "OldPolicyAnchor" not in second_habits["policy_markdown"]

    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath("second", *parts))
    client = make_client(make_vault(tmp_path))

    search_response = client.get(
        "/api/knowledge/academic-english/search",
        params={"q": "FreshPolicyAnchor", "top_k": 1},
    )
    assert search_response.status_code == 200
    fresh_hit = search_response.json()["results"][0]
    assert fresh_hit["ref_id"] == "academic_english:habits"
    assert fresh_hit["metadata"]["source_path"] == "references/english_discourse_habits.md"
    assert fresh_hit["metadata"]["source_hash"] == second_policy_hash
    assert fresh_hit["metadata"]["content_hash"] == second_policy_hash
    assert fresh_hit["metadata"]["policy_content_hash"] == second_policy_hash
    assert fresh_hit["metadata"]["artifact_hashes"]["academic_english_habits_json"] == second_artifact_hash

    resource_response = client.get(fresh_hit["read_endpoint"], params={"max_chars": 12000, "cursor": "0"})
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert "FreshPolicyAnchor" in resource["content"]
    assert "OldPolicyAnchor" not in resource["content"]
    assert resource["metadata"]["policy_content_hash"] == second_policy_hash

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [fresh_hit["ref_id"]],
            "prompt_name": "academic_english_policy_source_change_probe",
            "max_chars_per_ref": 4000,
        },
    )
    assert receipt_response.status_code == 200
    receipt_body = receipt_response.json()
    assert "FreshPolicyAnchor" in receipt_body["assembled_context_preview"]
    assert "OldPolicyAnchor" not in receipt_body["assembled_context_preview"]
    assert len(receipt_body["assembled_context_hash"]) == 64
    receipt = receipt_body["resource_read_receipts"][0]
    assert receipt["ref_id"] == fresh_hit["ref_id"]
    assert receipt["kind"] == "academic_english"
    assert receipt["source_hash"] == second_policy_hash
    assert receipt["package_content_hash"] == second_policy_hash
    assert receipt["metadata"]["artifact_hashes"]["academic_english_habits_json"] == second_artifact_hash


def test_skill_package_status_and_search_expose_read_only_refs(tmp_path: Path) -> None:
    client = make_client(make_vault(tmp_path))

    status_response = client.get("/api/knowledge/skill-packages/academic-english-discourse/status")

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["schema_version"] == "scholar-ai-skill-package-knowledge/v1"
    assert status["package_id"] == "academic-english-discourse"
    assert status["source_path"] == "extension_packages/skills/academic-english-discourse/SKILL.md"
    assert status["loaded"] is True
    assert status["manifest_loaded"] is True
    assert status["chunk_count"] >= 3
    assert any(item["relative_path"] == "references/english_discourse_habits.md" for item in status["source_files"])
    assert any(
        consumer["consumer"] == "literature_assistant.core.routers.agent_bridge_router"
        for consumer in status["runtime_consumers"]
    )
    assert any(consumer["consumer"] == "literature.skill_package_status" for consumer in status["runtime_consumers"])
    assert any(consumer["consumer"] == "literature.skill_package_search" for consumer in status["runtime_consumers"])

    search_response = client.get(
        "/api/knowledge/skill-packages/academic-english-discourse/search",
        params={"q": "discourse move", "top_k": 3},
    )

    assert search_response.status_code == 200
    body = search_response.json()
    assert body["package_id"] == "academic-english-discourse"
    assert body["query"] == "discourse move"
    assert body["results"]
    first = body["results"][0]
    assert first["schema_version"] == "scholar-ai-skill-package-knowledge-ref/v1"
    assert first["kind"] == "skill_package"
    assert first["resource_kind"] == "chunk"
    assert first["ref_id"].startswith("skill_package:academic-english-discourse:chunk:")
    assert first["read_endpoint"] == f"/api/agent-bridge/resource/{first['ref_id']}"
    assert first["metadata"]["source"] == "skill_package"
    assert first["metadata"]["package_id"] == "academic-english-discourse"
    assert len(first["metadata"]["package_content_hash"]) == 64


def test_skill_package_search_result_is_readable_as_agent_resource(tmp_path: Path) -> None:
    client = make_client(make_vault(tmp_path))

    search_response = client.get(
        "/api/knowledge/skill-packages/academic-english-discourse/search",
        params={"q": "Academic English Discourse", "top_k": 1},
    )
    ref_id = search_response.json()["results"][0]["ref_id"]

    resource_response = client.get(
        f"/api/agent-bridge/resource/{ref_id}",
        params={"max_chars": 180, "cursor": "0"},
    )

    assert resource_response.status_code == 200
    body = resource_response.json()
    assert body["ref_id"] == ref_id
    assert body["kind"] == "skill_package"
    assert "Academic English Discourse" in body["content"]
    assert body["truncated"] is True
    assert body["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-skill-package-knowledge-ref/v1"
    assert body["metadata"]["resource_kind"] == "chunk"
    assert body["metadata"]["source_path"] == "SKILL.md"


def test_skill_package_source_edit_rebuilds_search_resource_and_context_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A Skill source edit should flow through search, resource reads, and receipts."""

    root = tmp_path / "repo"
    reference = write_skill_package_fixture(root, anchor="OldSkillAnchor")
    monkeypatch.setattr(skill_package_knowledge, "REPO_ROOT", root)
    client = make_client(make_vault(tmp_path))

    first_status_response = client.get("/api/knowledge/skill-packages/academic-english-discourse/status")
    assert first_status_response.status_code == 200
    first_status = first_status_response.json()
    assert first_status["loaded"] is True
    assert first_status["manifest_loaded"] is True

    first_search_response = client.get(
        "/api/knowledge/skill-packages/academic-english-discourse/search",
        params={"q": "OldSkillAnchor", "top_k": 1},
    )
    assert first_search_response.status_code == 200
    first_hit = first_search_response.json()["results"][0]
    assert first_hit["metadata"]["package_content_hash"] == first_status["content_hash"]
    assert first_hit["metadata"]["source_path"] == "references/drift-proof.md"

    reference.write_text(
        "# Drift Proof\n\nFreshSkillAnchor reaches search, resource read, and context receipt.",
        encoding="utf-8",
    )

    second_status_response = client.get("/api/knowledge/skill-packages/academic-english-discourse/status")
    assert second_status_response.status_code == 200
    second_status = second_status_response.json()
    assert second_status["content_hash"] != first_status["content_hash"]
    assert second_status["source_hash"] == first_status["source_hash"]
    fresh_source = next(
        source for source in second_status["source_files"] if source["relative_path"] == "references/drift-proof.md"
    )
    old_source = next(
        source for source in first_status["source_files"] if source["relative_path"] == "references/drift-proof.md"
    )
    assert fresh_source["content_hash"] != old_source["content_hash"]

    stale_search_response = client.get(
        "/api/knowledge/skill-packages/academic-english-discourse/search",
        params={"q": "OldSkillAnchor", "top_k": 1},
    )
    assert stale_search_response.status_code == 200
    assert stale_search_response.json()["results"] == []

    fresh_search_response = client.get(
        "/api/knowledge/skill-packages/academic-english-discourse/search",
        params={"q": "FreshSkillAnchor", "top_k": 1},
    )
    assert fresh_search_response.status_code == 200
    fresh_hit = fresh_search_response.json()["results"][0]
    assert fresh_hit["kind"] == "skill_package"
    assert fresh_hit["resource_kind"] == "chunk"
    assert fresh_hit["read_endpoint"] == f"/api/agent-bridge/resource/{fresh_hit['ref_id']}"
    assert fresh_hit["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-skill-package-knowledge-ref/v1"
    assert fresh_hit["metadata"]["package_content_hash"] == second_status["content_hash"]
    assert fresh_hit["metadata"]["source_path"] == "references/drift-proof.md"
    assert fresh_hit["metadata"]["content_hash"] == fresh_source["content_hash"]

    resource_response = client.get(fresh_hit["read_endpoint"], params={"max_chars": 220, "cursor": "0"})
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "skill_package"
    assert "FreshSkillAnchor" in resource["content"]
    assert "OldSkillAnchor" not in resource["content"]
    assert resource["metadata"]["package_content_hash"] == second_status["content_hash"]

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [fresh_hit["ref_id"]],
            "prompt_name": "skill_package_source_change_probe",
            "max_chars_per_ref": 220,
        },
    )

    assert receipt_response.status_code == 200
    receipt_body = receipt_response.json()
    assert "FreshSkillAnchor" in receipt_body["assembled_context_preview"]
    assert "OldSkillAnchor" not in receipt_body["assembled_context_preview"]
    assert len(receipt_body["assembled_context_hash"]) == 64
    receipt = receipt_body["resource_read_receipts"][0]
    assert receipt["ref_id"] == fresh_hit["ref_id"]
    assert receipt["kind"] == "skill_package"
    assert receipt["read_endpoint"] == f"/api/agent-bridge/resource/{fresh_hit['ref_id']}"
    assert receipt["package_content_hash"] == second_status["content_hash"]
    assert receipt["source_path"] == "references/drift-proof.md"
    assert receipt["metadata"]["content_hash"] == fresh_hit["metadata"]["content_hash"]


def test_skill_package_status_reports_missing_source_without_500(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(skill_package_knowledge, "REPO_ROOT", tmp_path)
    client = make_client(make_vault(tmp_path))

    response = client.get("/api/knowledge/skill-packages/academic-english-discourse/status")

    assert response.status_code == 200
    body = response.json()
    assert body["loaded"] is False
    assert body["manifest_loaded"] is False
    assert body["load_status"] == "missing"
    assert body["source_hash"] == "unknown"
    assert body["warnings"]


def test_scoring_rules_snapshot_hash_changes_with_source(tmp_path: Path) -> None:
    source = tmp_path / "scoring_rules.json"
    source.write_text(
        json.dumps(
            {
                "version": "1.0",
                "last_updated": "2026-06-24",
                "description": "test rules",
                "weights": {"direct_evidence": 0.85},
                "thresholds": {"high_quality": 0.85},
                "multipliers": {"full_paper_advantage": 1.2},
                "goal_mapping": {"工艺参数": ["power"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = config_knowledge.load_scoring_rules_snapshot(source)
    source.write_text(
        json.dumps(
            {
                "version": "1.0",
                "last_updated": "2026-06-24",
                "description": "test rules",
                "weights": {"direct_evidence": 0.75},
                "thresholds": {"high_quality": 0.85},
                "multipliers": {"full_paper_advantage": 1.2},
                "goal_mapping": {"工艺参数": ["power"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second = config_knowledge.load_scoring_rules_snapshot(source)

    assert first.loaded is True
    assert second.loaded is True
    assert first.source_hash != second.source_hash
    assert first.content_hash != second.content_hash


def test_scoring_rules_status_search_and_read_expose_bounded_refs(tmp_path: Path) -> None:
    client = make_client(make_vault(tmp_path))

    status_response = client.get("/api/knowledge/scoring-rules/status")

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["schema_version"] == "scholar-ai-scoring-rules-knowledge/v1"
    assert status["package_id"] == "config:scoring_rules"
    assert status["config_id"] == "scoring_rules"
    assert status["source_path"] == "literature_assistant/core/config/scoring_rules.json"
    assert status["loaded"] is True
    assert status["manifest_loaded"] is True
    assert status["section_count"] == 4
    assert {item["section_id"] for item in status["sections"]} == {
        "weights",
        "thresholds",
        "multipliers",
        "goal_mapping",
    }
    assert any(
        consumer["consumer"] == "literature_assistant.core.modules.configuration_manager"
        for consumer in status["runtime_consumers"]
    )

    search_response = client.get("/api/knowledge/scoring-rules/search", params={"q": "direct_evidence", "top_k": 2})

    assert search_response.status_code == 200
    body = search_response.json()
    assert body["query"] == "direct_evidence"
    assert body["package_id"] == "config:scoring_rules"
    assert body["results"]
    first = body["results"][0]
    assert first["schema_version"] == "scholar-ai-scoring-rules-knowledge-ref/v1"
    assert first["kind"] == "scoring_rules"
    assert first["resource_kind"] == "section"
    assert first["ref_id"] == "scoring_rules:section:weights"
    assert first["read_endpoint"] == "/api/agent-bridge/resource/scoring_rules:section:weights"
    assert first["metadata"]["source_type"] == "json_config"
    assert first["metadata"]["section_id"] == "weights"
    assert len(first["metadata"]["package_content_hash"]) == 64

    read_response = client.get("/api/knowledge/scoring-rules/read")

    assert read_response.status_code == 200
    read_body = read_response.json()
    assert read_body["entries"]["weights"]["direct_evidence"] == 0.85
    assert read_body["entries"]["thresholds"]["high_quality"] == 0.85
    assert read_body["entries"]["goal_mapping"]["工艺参数"][0] == "parameter"


def test_scoring_rules_search_result_is_readable_as_agent_resource(tmp_path: Path) -> None:
    client = make_client(make_vault(tmp_path))

    search_response = client.get("/api/knowledge/scoring-rules/search", params={"q": "high_quality", "top_k": 1})
    ref_id = search_response.json()["results"][0]["ref_id"]

    resource_response = client.get(
        f"/api/agent-bridge/resource/{ref_id}",
        params={"max_chars": 120, "cursor": "0"},
    )

    assert resource_response.status_code == 200
    body = resource_response.json()
    assert body["ref_id"] == ref_id
    assert body["kind"] == "scoring_rules"
    assert "high_quality" in body["content"]
    assert body["truncated"] is True
    assert body["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-scoring-rules-knowledge-ref/v1"
    assert body["metadata"]["resource_kind"] == "section"
    assert body["metadata"]["source_path"] == "literature_assistant/core/config/scoring_rules.json"


def test_scoring_rules_source_edit_rebuilds_search_resource_and_context_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A scoring-rules source edit should flow through refs, resources, and receipts."""

    root = tmp_path / "repo"
    write_scoring_rules_fixture(root, anchor="ObsoleteScoreAnchor", direct_evidence=0.81)
    monkeypatch.setattr(config_knowledge, "REPO_ROOT", root)
    client = make_client(make_vault(tmp_path))

    first_status_response = client.get("/api/knowledge/scoring-rules/status")
    assert first_status_response.status_code == 200
    first_status = first_status_response.json()
    assert first_status["loaded"] is True
    assert first_status["manifest_loaded"] is True

    first_search_response = client.get(
        "/api/knowledge/scoring-rules/search",
        params={"q": "ObsoleteScoreAnchor", "top_k": 1},
    )
    assert first_search_response.status_code == 200
    first_hit = first_search_response.json()["results"][0]
    assert first_hit["ref_id"] == "scoring_rules:section:weights"
    assert first_hit["metadata"]["package_content_hash"] == first_status["content_hash"]

    write_scoring_rules_fixture(root, anchor="FreshScoreAnchor", direct_evidence=0.93)

    second_status_response = client.get("/api/knowledge/scoring-rules/status")
    assert second_status_response.status_code == 200
    second_status = second_status_response.json()
    assert second_status["source_hash"] != first_status["source_hash"]
    assert second_status["content_hash"] != first_status["content_hash"]
    fresh_section = next(section for section in second_status["sections"] if section["section_id"] == "weights")
    old_section = next(section for section in first_status["sections"] if section["section_id"] == "weights")
    assert fresh_section["content_hash"] != old_section["content_hash"]

    stale_search_response = client.get(
        "/api/knowledge/scoring-rules/search",
        params={"q": "ObsoleteScoreAnchor", "top_k": 1},
    )
    assert stale_search_response.status_code == 200
    assert stale_search_response.json()["results"] == []

    fresh_search_response = client.get(
        "/api/knowledge/scoring-rules/search",
        params={"q": "FreshScoreAnchor", "top_k": 1},
    )
    assert fresh_search_response.status_code == 200
    fresh_hit = fresh_search_response.json()["results"][0]
    assert fresh_hit["kind"] == "scoring_rules"
    assert fresh_hit["resource_kind"] == "section"
    assert fresh_hit["ref_id"] == "scoring_rules:section:weights"
    assert fresh_hit["read_endpoint"] == "/api/agent-bridge/resource/scoring_rules:section:weights"
    assert fresh_hit["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-scoring-rules-knowledge-ref/v1"
    assert fresh_hit["metadata"]["package_content_hash"] == second_status["content_hash"]
    assert fresh_hit["metadata"]["source_path"] == "literature_assistant/core/config/scoring_rules.json"
    assert fresh_hit["metadata"]["content_hash"] == fresh_section["content_hash"]

    resource_response = client.get(fresh_hit["read_endpoint"], params={"max_chars": 220, "cursor": "0"})
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "scoring_rules"
    assert "FreshScoreAnchor" in resource["content"]
    assert "ObsoleteScoreAnchor" not in resource["content"]
    assert resource["metadata"]["package_content_hash"] == second_status["content_hash"]

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [fresh_hit["ref_id"]],
            "prompt_name": "scoring_rules_source_change_probe",
            "max_chars_per_ref": 220,
        },
    )

    assert receipt_response.status_code == 200
    receipt_body = receipt_response.json()
    assert "FreshScoreAnchor" in receipt_body["assembled_context_preview"]
    assert "ObsoleteScoreAnchor" not in receipt_body["assembled_context_preview"]
    assert len(receipt_body["assembled_context_hash"]) == 64
    receipt = receipt_body["resource_read_receipts"][0]
    assert receipt["ref_id"] == fresh_hit["ref_id"]
    assert receipt["kind"] == "scoring_rules"
    assert receipt["read_endpoint"] == "/api/agent-bridge/resource/scoring_rules:section:weights"
    assert receipt["package_content_hash"] == second_status["content_hash"]
    assert receipt["source_path"] == "literature_assistant/core/config/scoring_rules.json"
    assert receipt["metadata"]["content_hash"] == fresh_hit["metadata"]["content_hash"]


def test_scoring_rules_status_reports_missing_source_without_500(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config_knowledge, "REPO_ROOT", tmp_path)
    client = make_client(make_vault(tmp_path))

    response = client.get("/api/knowledge/scoring-rules/status")

    assert response.status_code == 200
    body = response.json()
    assert body["loaded"] is False
    assert body["manifest_loaded"] is False
    assert body["load_status"] == "missing"
    assert body["source_hash"] == "unknown"
    assert body["warnings"]


def test_product_docs_snapshot_hash_changes_with_source(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    docs_root = root / "docs"
    plans_root = docs_root / "plans"
    plans_root.mkdir(parents=True)
    (root / "README.md").write_text("# Scholar AI\n\nMCP-first product documentation.", encoding="utf-8")
    (docs_root / "API_CONFIGURATION.md").write_text("# API Configuration\n\nProvider setup notes.", encoding="utf-8")
    (plans_root / "private-plan.md").write_text("# Must Stay Out\n\nplanning-only text", encoding="utf-8")

    first = product_docs_knowledge.load_product_docs_snapshot(root)
    (root / "README.md").write_text("# Scholar AI\n\nMCP-first product documentation updated.", encoding="utf-8")
    second = product_docs_knowledge.load_product_docs_snapshot(root)

    assert first.loaded is True
    assert second.loaded is True
    assert first.source_hash != second.source_hash
    assert first.content_hash != second.content_hash
    assert all("docs/plans" not in item.source_path for item in first.chunks)
    assert first.manifest["source_paths"] == ["README.md", "docs/API_CONFIGURATION.md"]


def test_product_docs_status_search_and_read_expose_bounded_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    docs_root = root / "docs"
    docs_root.mkdir(parents=True)
    (root / "README.md").write_text(
        "# Scholar AI\n\nMCP-first research workflow and product documentation.",
        encoding="utf-8",
    )
    (docs_root / "MCP_SECURITY_ISOLATION.md").write_text(
        "# MCP Security Isolation\n\nLocal toolbox boundaries keep external agents read-only.",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_docs_knowledge, "REPO_ROOT", root)
    client = make_client(make_vault(tmp_path))

    status_response = client.get("/api/knowledge/product-docs/status")

    assert status_response.status_code == 200
    status = status_response.json()
    assert status["schema_version"] == "scholar-ai-product-docs-knowledge/v1"
    assert status["package_id"] == "product_docs"
    assert status["source_path"] == "README.md + docs/*.md"
    assert status["loaded"] is True
    assert status["manifest_loaded"] is True
    assert status["chunk_count"] == 2
    assert status["manifest"]["source_paths"] == ["README.md", "docs/MCP_SECURITY_ISOLATION.md"]
    assert any(
        consumer["consumer"] == "literature_assistant.core.routers.agent_bridge_router"
        for consumer in status["runtime_consumers"]
    )

    search_response = client.get("/api/knowledge/product-docs/search", params={"q": "external agents", "top_k": 2})

    assert search_response.status_code == 200
    body = search_response.json()
    assert body["query"] == "external agents"
    assert body["package_id"] == "product_docs"
    assert body["results"]
    first = body["results"][0]
    assert first["schema_version"] == "scholar-ai-product-docs-knowledge-ref/v1"
    assert first["kind"] == "product_docs"
    assert first["resource_kind"] == "chunk"
    assert first["ref_id"].startswith("product_docs:chunk:")
    assert first["read_endpoint"] == f"/api/agent-bridge/resource/{first['ref_id']}"
    assert first["metadata"]["source"] == "product_docs"
    assert first["metadata"]["source_type"] == "product_markdown"
    assert first["metadata"]["source_path"] == "docs/MCP_SECURITY_ISOLATION.md"
    assert len(first["metadata"]["package_content_hash"]) == 64

    read_response = client.get("/api/knowledge/product-docs/read")

    assert read_response.status_code == 200
    read_body = read_response.json()
    assert read_body["entries"]
    assert any("MCP Security Isolation" in item["title"] for item in read_body["entries"].values())


def test_product_docs_search_result_is_readable_as_agent_resource(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "README.md").write_text(
        "# Scholar AI\n\n" + ("MCP-first product documentation enters bounded context. " * 20),
        encoding="utf-8",
    )
    monkeypatch.setattr(product_docs_knowledge, "REPO_ROOT", root)
    client = make_client(make_vault(tmp_path))

    search_response = client.get("/api/knowledge/product-docs/search", params={"q": "bounded context", "top_k": 1})
    ref_id = search_response.json()["results"][0]["ref_id"]

    resource_response = client.get(
        f"/api/agent-bridge/resource/{ref_id}",
        params={"max_chars": 150, "cursor": "0"},
    )

    assert resource_response.status_code == 200
    body = resource_response.json()
    assert body["ref_id"] == ref_id
    assert body["kind"] == "product_docs"
    assert "Scholar AI" in body["content"]
    assert body["truncated"] is True
    assert body["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-product-docs-knowledge-ref/v1"
    assert body["metadata"]["resource_kind"] == "chunk"
    assert body["metadata"]["source_path"] == "README.md"


def test_product_docs_knowledge_pipeline_registry_search_and_resource_share_ref_protocol(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Registry, search, and agent resource reads should share product-doc refs."""

    root = tmp_path / "repo"
    docs_root = root / "docs"
    docs_root.mkdir(parents=True)
    (root / "README.md").write_text(
        "# Scholar AI\n\nKnowledge Runtime Pipeline loads product documentation into bounded model context.",
        encoding="utf-8",
    )
    (docs_root / "USAGE.md").write_text(
        "# Usage\n\nAgent resource readers consume the same product_docs chunk refs that search returns.",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_docs_knowledge, "REPO_ROOT", root)
    client = make_client(make_vault(tmp_path))

    registry_response = client.get("/api/knowledge/packages")

    assert registry_response.status_code == 200
    packages = {package["package_id"]: package for package in registry_response.json()["packages"]}
    product_docs_package = packages["product_docs"]
    assert product_docs_package["loaded"] is True
    assert product_docs_package["manifest_loaded"] is True
    assert product_docs_package["read_endpoint"] == "/api/knowledge/product-docs/status"
    assert product_docs_package["search_endpoint"] == "/api/knowledge/product-docs/search"
    assert product_docs_package["manifest"]["source_paths"] == ["README.md", "docs/USAGE.md"]
    assert product_docs_package["manifest"]["chunk_count"] == 2
    assert any(
        consumer["consumer"] == "literature_assistant.core.routers.agent_bridge_router"
        for consumer in product_docs_package["manifest"]["runtime_consumers"]
    )

    status_response = client.get(product_docs_package["read_endpoint"])
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["content_hash"] == product_docs_package["content_hash"]
    assert status["source_hash"] == product_docs_package["source_hash"]
    assert status["chunk_count"] == product_docs_package["manifest"]["chunk_count"]

    search_response = client.get(
        product_docs_package["search_endpoint"],
        params={"q": "bounded model context", "top_k": 1},
    )
    assert search_response.status_code == 200
    first = search_response.json()["results"][0]
    assert first["ref_id"].startswith("product_docs:chunk:")
    assert first["read_endpoint"] == f"/api/agent-bridge/resource/{first['ref_id']}"
    assert first["metadata"]["package_content_hash"] == status["content_hash"]
    assert first["metadata"]["source_hash"]
    assert first["metadata"]["content_hash"]
    assert first["metadata"]["span_start"] >= 0
    assert first["metadata"]["span_end"] > first["metadata"]["span_start"]

    resource_response = client.get(
        first["read_endpoint"],
        params={"max_chars": 120, "cursor": "0"},
    )
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["ref_id"] == first["ref_id"]
    assert resource["kind"] == "product_docs"
    assert resource["max_chars"] == 120
    assert resource["total_chars"] >= resource["metadata"]["returned_chars"]
    assert resource["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-product-docs-knowledge-ref/v1"
    assert resource["metadata"]["package_content_hash"] == status["content_hash"]
    assert resource["metadata"]["source_path"] == first["metadata"]["source_path"]


def test_knowledge_context_receipt_proves_product_docs_ref_enters_bounded_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A search ref should be provably read into a bounded prompt context receipt."""

    root = tmp_path / "repo"
    docs_root = root / "docs"
    docs_root.mkdir(parents=True)
    (root / "README.md").write_text(
        "# Scholar AI\n\nKnowledge refs enter prompt context through bounded readers.",
        encoding="utf-8",
    )
    (docs_root / "USAGE.md").write_text(
        "# Usage\n\nContext receipts hash the exact text passed into model input.",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_docs_knowledge, "REPO_ROOT", root)
    client = make_client(make_vault(tmp_path))

    search_response = client.get(
        "/api/knowledge/product-docs/search",
        params={"q": "model input", "top_k": 1},
    )
    assert search_response.status_code == 200
    search_hit = search_response.json()["results"][0]

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [search_hit["ref_id"]],
            "prompt_name": "qa_prompt",
            "max_chars_per_ref": 160,
        },
    )

    assert receipt_response.status_code == 200
    body = receipt_response.json()
    assert body["schema_version"] == "scholar-ai-knowledge-context-receipt/v1"
    assert body["prompt_name"] == "qa_prompt"
    assert len(body["prompt_hash"]) == 64
    assert len(body["assembled_context_hash"]) == 64
    assert "Context receipts hash" in body["assembled_context_preview"]
    assert body["assembled_context_char_count"] == len(body["assembled_context_preview"])
    assert body["provenance"]["resource_reader"] == "literature_assistant.core.routers.agent_bridge_router"
    assert body["provenance"]["mcp_tool"] == "literature.knowledge_context_receipt"
    receipts = body["resource_read_receipts"]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["ref_id"] == search_hit["ref_id"]
    assert receipt["kind"] == "product_docs"
    assert receipt["read_endpoint"] == f"/api/agent-bridge/resource/{search_hit['ref_id']}"
    assert len(receipt["content_hash"]) == 64
    assert receipt["source_hash"] == search_hit["metadata"]["source_hash"]
    assert receipt["package_content_hash"] == search_hit["metadata"]["package_content_hash"]
    assert receipt["source_path"] == search_hit["metadata"]["source_path"]
    assert receipt["returned_chars"] <= 160
    assert receipt["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-product-docs-knowledge-ref/v1"


def test_product_docs_source_edit_rebuilds_search_resource_and_context_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A product-doc source edit should flow through hashes, refs, resources, and receipts."""

    root = tmp_path / "repo"
    docs_root = root / "docs"
    docs_root.mkdir(parents=True)
    (root / "README.md").write_text(
        "# Scholar AI\n\nProduct docs runtime source registry.",
        encoding="utf-8",
    )
    usage_path = docs_root / "USAGE.md"
    usage_path.write_text(
        "# Usage\n\nObsoleteAnchor confirms the first source snapshot.",
        encoding="utf-8",
    )
    monkeypatch.setattr(product_docs_knowledge, "REPO_ROOT", root)
    client = make_client(make_vault(tmp_path))

    first_status_response = client.get("/api/knowledge/product-docs/status")
    assert first_status_response.status_code == 200
    first_status = first_status_response.json()
    assert first_status["loaded"] is True
    assert first_status["manifest_loaded"] is True

    first_search_response = client.get(
        "/api/knowledge/product-docs/search",
        params={"q": "ObsoleteAnchor", "top_k": 1},
    )
    assert first_search_response.status_code == 200
    first_hit = first_search_response.json()["results"][0]
    assert first_hit["metadata"]["package_content_hash"] == first_status["content_hash"]
    assert first_hit["metadata"]["source_path"] == "docs/USAGE.md"

    usage_path.write_text(
        "# Usage\n\nFreshAnchor proves the edited source reached bounded prompt context.",
        encoding="utf-8",
    )

    second_status_response = client.get("/api/knowledge/product-docs/status")
    assert second_status_response.status_code == 200
    second_status = second_status_response.json()
    assert second_status["content_hash"] != first_status["content_hash"]
    assert second_status["source_hash"] != first_status["source_hash"]
    usage_source = next(
        source for source in second_status["source_files"] if source["relative_path"] == "docs/USAGE.md"
    )
    first_usage_source = next(
        source for source in first_status["source_files"] if source["relative_path"] == "docs/USAGE.md"
    )
    assert usage_source["content_hash"] != first_usage_source["content_hash"]

    stale_search_response = client.get(
        "/api/knowledge/product-docs/search",
        params={"q": "ObsoleteAnchor", "top_k": 1},
    )
    assert stale_search_response.status_code == 200
    assert stale_search_response.json()["results"] == []

    fresh_search_response = client.get(
        "/api/knowledge/product-docs/search",
        params={"q": "FreshAnchor", "top_k": 1},
    )
    assert fresh_search_response.status_code == 200
    fresh_hit = fresh_search_response.json()["results"][0]
    assert fresh_hit["ref_id"].startswith("product_docs:chunk:")
    assert fresh_hit["metadata"]["package_content_hash"] == second_status["content_hash"]
    assert fresh_hit["metadata"]["source_path"] == "docs/USAGE.md"
    assert fresh_hit["metadata"]["content_hash"] == usage_source["content_hash"]
    assert fresh_hit["metadata"]["source_hash"] == usage_source["content_hash"]

    resource_response = client.get(
        fresh_hit["read_endpoint"],
        params={"max_chars": 220, "cursor": "0"},
    )
    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["ref_id"] == fresh_hit["ref_id"]
    assert resource["kind"] == "product_docs"
    assert "FreshAnchor" in resource["content"]
    assert "ObsoleteAnchor" not in resource["content"]
    assert resource["metadata"]["package_content_hash"] == second_status["content_hash"]

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [fresh_hit["ref_id"]],
            "prompt_name": "product_docs_source_change_probe",
            "max_chars_per_ref": 220,
        },
    )

    assert receipt_response.status_code == 200
    receipt_body = receipt_response.json()
    assert "FreshAnchor" in receipt_body["assembled_context_preview"]
    assert "ObsoleteAnchor" not in receipt_body["assembled_context_preview"]
    assert len(receipt_body["assembled_context_hash"]) == 64
    receipt = receipt_body["resource_read_receipts"][0]
    assert receipt["ref_id"] == fresh_hit["ref_id"]
    assert receipt["package_content_hash"] == second_status["content_hash"]
    assert receipt["source_path"] == "docs/USAGE.md"
    assert receipt["metadata"]["content_hash"] == fresh_hit["metadata"]["content_hash"]


@pytest.mark.parametrize(
    ("endpoint", "params", "expected_kind", "expected_text"),
    [
        (
            "/api/knowledge/scoring-rules/search",
            {"q": "direct_evidence", "top_k": 1},
            "scoring_rules",
            "direct_evidence",
        ),
        (
            "/api/knowledge/skill-packages/academic-english-discourse/search",
            {"q": "Academic English Discourse", "top_k": 1},
            "skill_package",
            "Academic English Discourse",
        ),
        (
            "/api/knowledge/academic-english/search",
            {"q": "hedging", "top_k": 1},
            "academic_english",
            "Hedging calibrates claims",
        ),
        (
            "/api/knowledge/source-vault/search",
            {"q": "molten pool", "project_id": "project-alpha", "limit": 1},
            "source_vault",
            "molten pool",
        ),
        (
            "/api/knowledge/bridge-lexicon/search",
            {"q": "laser", "top_k": 1},
            "bridge_lexicon",
            "laser",
        ),
    ],
)
def test_knowledge_context_receipt_covers_ref_bearing_knowledge_families(
    endpoint: str,
    params: dict[str, object],
    expected_kind: str,
    expected_text: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ref-bearing knowledge families should enter one bounded receipt protocol."""

    vault = make_vault(tmp_path)
    seed_vault(vault)
    root = tmp_path / "english_discourse"
    seed_academic_english_output(root)
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))
    from literature_assistant.core import tolf_bridge_lexicon_store

    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(
        json.dumps({"激光": ["laser", "beam"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tolf_bridge_lexicon_store,
        "_DEFAULT_STORE",
        tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path),
    )
    monkeypatch.setattr(agent_bridge_router, "SourceVault", lambda: vault)
    monkeypatch.setattr(knowledge_router._agent_bridge_router, "SourceVault", lambda: vault)
    client = make_client(vault)

    search_response = client.get(endpoint, params=params)
    assert search_response.status_code == 200
    search_hit = search_response.json()["results"][0]
    ref_id = search_hit["ref_id"]
    project_id = params.get("project_id") if isinstance(params.get("project_id"), str) else None

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [ref_id],
            "project_id": project_id,
            "prompt_name": f"{expected_kind}_qa_prompt",
            "max_chars_per_ref": 220,
        },
    )

    assert receipt_response.status_code == 200
    body = receipt_response.json()
    assert body["schema_version"] == "scholar-ai-knowledge-context-receipt/v1"
    assert body["prompt_name"] == f"{expected_kind}_qa_prompt"
    assert len(body["prompt_hash"]) == 64
    assert len(body["assembled_context_hash"]) == 64
    assert expected_text in body["assembled_context_preview"]
    assert body["assembled_context_char_count"] >= len(body["assembled_context_preview"])
    assert body["provenance"]["mcp_tool"] == "literature.knowledge_context_receipt"
    assert body["provenance"]["resource_reader"] == "literature_assistant.core.routers.agent_bridge_router"
    receipts = body["resource_read_receipts"]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["ref_id"] == ref_id
    assert receipt["kind"] == expected_kind
    assert receipt["read_endpoint"] == f"/api/agent-bridge/resource/{ref_id}"
    assert len(receipt["content_hash"]) == 64
    assert len(receipt["source_hash"]) == 64
    assert len(receipt["package_content_hash"]) == 64
    assert receipt["returned_chars"] <= 220
    assert receipt["metadata"]["resource_kind"] in {"chunk", "section", "entry"}
    assert str(receipt["metadata"]["knowledge_ref_schema_version"]).startswith("scholar-ai-")


def test_knowledge_context_receipt_rejects_invalid_ref_payloads(tmp_path: Path) -> None:
    """The receipt endpoint should fail visibly for invalid or unsupported refs."""

    client = make_client(make_vault(tmp_path))

    empty_response = client.post("/api/knowledge/context-receipt", json={"ref_ids": []})
    assert empty_response.status_code == 422

    blank_response = client.post("/api/knowledge/context-receipt", json={"ref_ids": ["   "]})
    assert blank_response.status_code == 422

    too_many_response = client.post(
        "/api/knowledge/context-receipt",
        json={"ref_ids": [f"product_docs:chunk:{index}" for index in range(21)]},
    )
    assert too_many_response.status_code == 422

    unsupported_response = client.post(
        "/api/knowledge/context-receipt",
        json={"ref_ids": ["unsupported:ref"]},
    )
    assert unsupported_response.status_code == 400


def test_academic_english_search_uses_sqlite_fts_when_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "english_discourse"
    root.mkdir(parents=True)
    with sqlite3.connect(root / "academic_english_discourse.sqlite3") as conn:
        conn.execute(
            """
            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                chunk_id, title, section, text, summary, keywords
            )
            """
        )
        conn.execute(
            """
            INSERT INTO chunks_fts(chunk_id, title, section, text, summary, keywords)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "chunk-fts",
                "Rhetorical Moves",
                "introduction",
                "Rhetorical move selection controls academic argument flow.",
                "Rhetorical moves guide argument flow.",
                "rhetorical move argument",
            ),
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "builder_version": "0.2.0",
                "built_at": "2026-06-24T00:00:00+00:00",
                "knowledge_sources": {
                    "academic_english_habits": {
                        "loaded": True,
                        "load_status": "loaded",
                        "content_hash": "c" * 64,
                        "char_count": 100,
                    }
                },
                "output_artifacts": {
                    "sqlite": {
                        "path": "C:/private/academic_english_discourse.sqlite3",
                        "exists": True,
                        "bytes": (root / "academic_english_discourse.sqlite3").stat().st_size,
                        "sha256": "d" * 64,
                        "status": "written",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))
    client = make_client(make_vault(tmp_path))

    response = client.get("/api/knowledge/academic-english/search", params={"q": "rhetorical move", "top_k": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["ref_id"] == "academic_english:chunk:chunk-fts"
    assert body["results"][0]["metadata"]["artifact_hashes"]["sqlite"] == "d" * 64
    resource = academic_english_resources.read_academic_english_resource("chunk:chunk-fts")
    assert "Rhetorical move selection" in resource["content"]


def test_bridge_lexicon_status_exposes_runtime_provenance(tmp_path: Path) -> None:
    lexicon_root = tmp_path / "runtime_state"
    lexicon_root.mkdir(parents=True, exist_ok=True)
    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(
        json.dumps(
            {
                "激光": ["laser"],
                "焊接": ["welding", "laser welding"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    from literature_assistant.core import tolf_bridge_lexicon_store

    store = tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path)
    snapshot = store.load()

    assert snapshot.loaded is True
    assert ("literature_assistant.core.tolf_text_selector", "selector_query_expansion") in snapshot.runtime_consumers
    assert (
        "literature_assistant.core.routers.knowledge_router",
        "entry_ref_search_and_context_receipt",
    ) in snapshot.runtime_consumers
    assert ("literature_assistant.core.routers.agent_bridge_router", "bounded_entry_resource_read") in snapshot.runtime_consumers
    assert ("literature.bridge_lexicon_search", "mcp_ref_search") in snapshot.runtime_consumers
    status = store.get_snapshot().to_status_payload()
    assert status["schema_version"] == "scholar-ai-cjk-bridge-lexicon/v1"
    assert status["loaded"] is True
    assert status["entry_count"] == 2
    assert status["runtime_consumers"][0]["consumer"] == "literature_assistant.core.tolf_text_selector"


def test_bridge_lexicon_status_route_returns_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from literature_assistant.core import tolf_bridge_lexicon_store

    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(
        json.dumps({"激光": ["laser"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tolf_bridge_lexicon_store,
        "_DEFAULT_STORE",
        tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path),
    )

    app = FastAPI()
    app.include_router(knowledge_router.router)
    client = TestClient(app)

    response = client.get("/api/knowledge/bridge-lexicon/status")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "scholar-ai-cjk-bridge-lexicon/v1"
    assert body["loaded"] is True
    assert body["entry_count"] == 1
    assert body["runtime_consumers"][0]["consumer"] == "literature_assistant.core.tolf_text_selector"


def test_bridge_lexicon_read_route_returns_entries_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from literature_assistant.core import tolf_bridge_lexicon_store

    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(
        json.dumps(
            {
                "激光": ["laser", "beam"],
                "焊接": ["welding"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tolf_bridge_lexicon_store,
        "_DEFAULT_STORE",
        tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path),
    )

    app = FastAPI()
    app.include_router(knowledge_router.router)
    client = TestClient(app)

    response = client.get("/api/knowledge/bridge-lexicon/read")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "scholar-ai-cjk-bridge-lexicon/v1"
    assert body["loaded"] is True
    assert body["entry_count"] == 2
    assert body["entries"]["激光"] == ["beam", "laser"]
    assert body["entries"]["焊接"] == ["welding"]
    assert body["runtime_consumers"][0]["consumer"] == "literature_assistant.core.tolf_text_selector"
    assert "source_path" in body


def test_bridge_lexicon_search_result_is_readable_as_agent_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bridge lexicon search should return stable refs readable through agent bridge."""

    from literature_assistant.core import tolf_bridge_lexicon_store

    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(
        json.dumps(
            {
                "激光": ["laser", "beam"],
                "焊接": ["laser welding"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tolf_bridge_lexicon_store,
        "_DEFAULT_STORE",
        tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path),
    )

    client = make_client(make_vault(tmp_path))
    response = client.get("/api/knowledge/bridge-lexicon/search", params={"q": "laser", "top_k": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "laser"
    assert body["package_id"] == "bridge_lexicon"
    assert body["results"]
    first_hit = body["results"][0]
    assert first_hit["ref_id"].startswith("bridge_lexicon:entry:")
    assert first_hit["resource_kind"] == "entry"
    assert first_hit["read_endpoint"] == f"/api/agent-bridge/resource/{first_hit['ref_id']}"
    assert first_hit["metadata"]["source_path"].endswith("cjk_bridge_lexicon.json")
    assert len(first_hit["metadata"]["source_hash"]) == 64
    assert len(first_hit["metadata"]["package_content_hash"]) == 64

    resource_response = client.get(first_hit["read_endpoint"])

    assert resource_response.status_code == 200
    resource = resource_response.json()
    assert resource["kind"] == "bridge_lexicon"
    assert "laser" in resource["content"]
    assert resource["metadata"]["ref_id"] == first_hit["ref_id"]
    assert resource["metadata"]["resource_kind"] == "entry"


def test_bridge_lexicon_source_edit_rebuilds_search_resource_and_context_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source edits must change bridge-lexicon hashes and bounded context refs."""

    from literature_assistant.core import tolf_bridge_lexicon_store

    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(json.dumps({"旧词": ["ObsoleteBridge"]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(
        tolf_bridge_lexicon_store,
        "_DEFAULT_STORE",
        tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path),
    )
    client = make_client(make_vault(tmp_path))

    first_status_response = client.get("/api/knowledge/bridge-lexicon/status")
    assert first_status_response.status_code == 200
    first_status = first_status_response.json()
    assert first_status["entry_count"] == 1

    lexicon_path.write_text(json.dumps({"新词": ["FreshBridgeAnchor"]}, ensure_ascii=False), encoding="utf-8")
    search_response = client.get("/api/knowledge/bridge-lexicon/search", params={"q": "FreshBridgeAnchor", "top_k": 1})

    assert search_response.status_code == 200
    second_status = client.get("/api/knowledge/bridge-lexicon/status").json()
    assert second_status["source_hash"] != first_status["source_hash"]
    assert second_status["content_hash"] != first_status["content_hash"]
    fresh_hit = search_response.json()["results"][0]
    assert fresh_hit["metadata"]["package_content_hash"] == second_status["content_hash"]
    assert fresh_hit["metadata"]["source_hash"] == second_status["source_hash"]

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [fresh_hit["ref_id"]],
            "prompt_name": "bridge_lexicon_source_edit_probe",
            "max_chars_per_ref": 220,
        },
    )

    assert receipt_response.status_code == 200
    receipt_body = receipt_response.json()
    assert "FreshBridgeAnchor" in receipt_body["assembled_context_preview"]
    assert "ObsoleteBridge" not in receipt_body["assembled_context_preview"]
    receipt = receipt_body["resource_read_receipts"][0]
    assert receipt["ref_id"] == fresh_hit["ref_id"]
    assert receipt["kind"] == "bridge_lexicon"
    assert receipt["package_content_hash"] == second_status["content_hash"]
    assert receipt["source_path"].endswith("cjk_bridge_lexicon.json")
    assert receipt["metadata"]["resource_kind"] == "entry"
