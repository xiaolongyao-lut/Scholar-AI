from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

import python_adapter_server as server
from literature_assistant.core import academic_english_resources
from literature_assistant.core import tolf_bridge_lexicon_store
from literature_assistant.core.config_knowledge import search_scoring_rules
from literature_assistant.core import product_docs_knowledge
from literature_assistant.core.skill_package_knowledge import search_skill_package
from literature_assistant.core.source_vault import SourceChunkInput, SourceVault, derive_chunk_id
import routers.agent_bridge_router as agent_bridge_router
import routers.runtime_router as runtime_router
from writing_runtime import SessionMode, WritingRuntime
from literature_assistant.core.wiki.source_registry import derive_chunk_id as derive_wiki_chunk_id


def _isolated_runtime(monkeypatch: Any) -> WritingRuntime:
    """Return a non-persistent runtime for agent-bridge API tests."""

    runtime = WritingRuntime(autosave=False)
    monkeypatch.setattr(agent_bridge_router, "get_runtime", lambda: (runtime, SessionMode))
    monkeypatch.setattr(runtime_router, "get_runtime", lambda: runtime)
    monkeypatch.setattr(runtime, "_sync_job_to_memory_if_enabled", lambda _job_id: None)
    monkeypatch.setattr(runtime, "_schedule_runtime_job_capture", lambda *_args, **_kwargs: None)
    return runtime


def _client(monkeypatch: Any) -> TestClient:
    monkeypatch.setenv("LITASSIST_API_CAPABILITY_AUTH", "1")
    return TestClient(server.app)


def _capability_headers() -> dict[str, str]:
    return {server.LOCAL_API_CAPABILITY_HEADER: server.get_local_api_capability_token()}


def _seed_academic_english_output(root: Path) -> None:
    """Create a minimal generated academic-English package for reader tests."""

    root.mkdir(parents=True, exist_ok=True)
    chunk = {
        "chunk_id": "chunk-claim-scope",
        "source_id": "source-1",
        "source_type": "text",
        "title": "Claim Scope",
        "locator": "C:/private/should/not/leak.txt",
        "section": "discussion",
        "text": "Claim scope and hedging keep academic prose aligned with evidence. " * 20,
        "summary": "Claim scope and hedging.",
        "rhetorical_moves": ["limitation"],
        "features": ["hedging"],
        "keywords": ["claim", "scope", "hedging"],
        "char_count": 1280,
        "word_count": 160,
    }
    (root / "chunks.jsonl").write_text(json.dumps(chunk, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "phrases.jsonl").write_text("", encoding="utf-8")
    (root / "academic_english_habits.json").write_text(
        json.dumps(
            {
                "knowledge_type": "academic_english_habits",
                "policy_loaded": True,
                "policy_content_hash": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "builder_version": "0.2.0",
                "built_at": "2026-06-24T00:00:00+00:00",
                "knowledge_sources": {
                    "academic_english_habits": {
                        "source_path": "C:/private/english_discourse_habits.md",
                        "source_label": "references/english_discourse_habits.md",
                        "loaded": True,
                        "load_status": "loaded",
                        "content_hash": "a" * 64,
                        "char_count": 128,
                    }
                },
                "output_artifacts": {
                    "chunks_jsonl": {
                        "path": "C:/private/chunks.jsonl",
                        "exists": True,
                        "bytes": (root / "chunks.jsonl").stat().st_size,
                        "sha256": "b" * 64,
                        "status": "written",
                        "rows": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _seed_source_vault(tmp_path: Path) -> SourceVault:
    vault = SourceVault(
        db_path=tmp_path / "source_vault" / "source_vault.sqlite3",
        storage_root=tmp_path / "source_vault",
    )
    source = vault.upsert_source_bytes(
        b"source vault bytes",
        filename="paper.pdf",
        source_type="pdf",
        title="Source Vault Paper",
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        project_id="proj_demo",
        now_iso="2026-06-24T00:00:00Z",
    ).source
    vault.register_chunks(
        source.source_id,
        [
            SourceChunkInput(
                text="Molten pool keeps the discussion grounded in source evidence.",
                chunk_index=0,
                page=1,
            )
        ],
        now_iso="2026-06-24T00:01:00Z",
    )
    return vault


def test_agent_bridge_request_progress_and_result_are_runtime_visible(monkeypatch: Any) -> None:
    """Agent bridge should create a runtime job, progress event, and artifact."""

    runtime = _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={
            "source": "mcp",
            "agent_host": "codex",
            "intent": "smart_read_answer",
            "user_text": "比较这三篇文献的方法差异",
            "project_id": "proj_demo",
            "route": "/dialog",
            "resource_refs": [
                {
                    "ref_id": "material:abc",
                    "kind": "material",
                    "project_id": "proj_demo",
                    "title": "Demo Paper",
                    "summary": "bounded summary",
                }
            ],
        },
    )

    assert created.status_code == 200
    payload = created.json()
    request_id = payload["request_id"]
    job_id = payload["job"]["job_id"]
    assert payload["job"]["kind"] == "agent_request"
    assert payload["job"]["status"] == "started"
    assert payload["job"]["metadata"]["agent_request_id"] == request_id
    assert payload["poll"]["snapshot"] == f"/runtime/job/{job_id}/snapshot"

    progress = client.post(
        f"/api/agent-bridge/request/{request_id}/progress",
        headers=_capability_headers(),
        json={"stage": "reading", "message": "正在读取引用片段", "progress": 40},
    )

    assert progress.status_code == 200
    assert progress.json()["metadata"]["progress"] == 40

    result = client.post(
        f"/api/agent-bridge/request/{request_id}/result",
        headers=_capability_headers(),
        json={
            "text": "三篇文献的核心差异是数据来源、建模假设和验证粒度。",
            "evidence_refs": [{"ref_id": "chunk:1"}],
            "wiki_refs": [{"slug": "method-comparison"}],
        },
    )

    assert result.status_code == 200
    result_payload = result.json()
    assert result_payload["job"]["status"] == "completed"
    assert result_payload["job"]["metadata"]["source"] == "agent_bridge"
    assert result_payload["job"]["metadata"]["agent_source"] == "mcp"
    assert result_payload["artifacts"]
    assert result_payload["artifacts"][0]["metadata"]["agent_request_id"] == request_id
    artifact = runtime.get_job_artifacts(job_id)[0]
    assert artifact.content["request_id"] == request_id
    assert artifact.content["evidence_refs"] == [{"ref_id": "chunk:1"}]
    assert artifact.metadata["agent_request_id"] == request_id
    assert artifact.metadata["knowledge_capture"]["eligible"] is True
    assert artifact.metadata["wiki_refs"] == [{"slug": "method-comparison"}]
    current_job = runtime.get_job(job_id)
    assert current_job is not None
    assert current_job.metadata["agent_result_ready"] is True
    assert current_job.metadata["evidence_refs"] == [{"ref_id": "chunk:1"}]

    snapshot = client.get(
        f"/runtime/job/{job_id}/snapshot",
        headers=_capability_headers(),
    )

    assert snapshot.status_code == 200
    event_types = [item["event_type"] for item in snapshot.json()["events"]]
    assert "job_started" in event_types
    assert "job_progress" in event_types
    assert "job_completed" in event_types


def test_agent_bridge_result_consumes_wiki_and_graph_candidates(monkeypatch: Any, tmp_path: Path) -> None:
    """Agent result flags should create reviewable local knowledge artifacts."""

    runtime = _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    import routers.wiki_router as wiki_router
    from wiki.page_store import WikiPageStore
    from wiki.review_queue import ReviewQueue
    from wiki.service import WikiService

    wiki_root = tmp_path / "wiki"
    review_path = tmp_path / "runtime" / "review_queue.jsonl"
    monkeypatch.setattr(wiki_router, "wiki_enabled", lambda: True)
    monkeypatch.setattr(wiki_router, "wiki_generated_root", lambda: wiki_root)
    monkeypatch.setattr(wiki_router, "wiki_review_queue_path", lambda: review_path)

    def _service() -> WikiService:
        return WikiService(WikiPageStore(wiki_root, create=True))

    import wiki.service as flat_wiki_service

    monkeypatch.setattr(flat_wiki_service, "get_wiki_service", _service)

    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={
            "source": "mcp",
            "agent_host": "codex",
            "intent": "write_review_intro",
            "project_id": "proj_demo",
            "output_targets": {
                "runtime_job": True,
                "agent_workspace": True,
                "wiki_candidate": True,
                "graph_candidate": True,
                "evolution_capture": True,
            },
        },
    )
    assert created.status_code == 200
    request_id = created.json()["request_id"]
    job_id = created.json()["job"]["job_id"]

    result = client.post(
        f"/api/agent-bridge/request/{request_id}/result",
        headers=_capability_headers(),
        json={
            "text": "综述显示孔隙与疲劳裂纹萌生存在可回读证据链。",
            "evidence_refs": [{"ref_id": "chunk:abc", "summary": "孔隙影响疲劳裂纹萌生"}],
            "graph_patch_refs": [{"node": "AlSi10Mg", "relation": "affects", "target": "fatigue"}],
        },
    )

    assert result.status_code == 200
    job = runtime.get_job(job_id)
    assert job is not None
    consumers = job.metadata["knowledge_consumers"]
    assert consumers["wiki"]["status"] == "created"
    assert consumers["wiki"]["slug"].startswith("synthesis-agent-result")
    assert consumers["graph"]["status"] == "attached_to_wiki_candidate"
    assert consumers["graph"]["graph_patch_ref_count"] == 1
    assert consumers["evolution"]["status"] == "scheduled"

    page = _service().get_page(consumers["wiki"]["slug"])
    assert page is not None
    assert page.status.value == "draft"
    assert page.extra["entry_source"] == "agent_bridge"
    assert page.extra["graph_candidate"] is True
    assert page.evidence_refs[0]["ref_id"] == "chunk:abc"
    assert "综述显示孔隙" in page.body
    assert "Evidence refs" in page.body

    review_items = ReviewQueue(review_path).list_items()
    assert len(review_items) == 1
    assert review_items[0].source == "agent_bridge"
    assert review_items[0].metadata["agent_request_id"] == request_id
    assert review_items[0].metadata["graph_candidate"] is True


def test_agent_bridge_lists_and_fails_request(monkeypatch: Any) -> None:
    """Agent bridge list/fail endpoints should operate through runtime jobs."""

    runtime = _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={"intent": "diagnose", "user_text": "检查 MCP 启动"},
    )
    request_id = created.json()["request_id"]

    listed = client.get("/api/agent-bridge/requests", headers=_capability_headers())

    assert listed.status_code == 200
    assert [item["metadata"]["agent_request_id"] for item in listed.json()] == [request_id]

    failed = client.post(
        f"/api/agent-bridge/request/{request_id}/fail",
        headers=_capability_headers(),
        json={"error": "agent stopped by test"},
    )

    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["error"] == "agent stopped by test"
    assert failed.json()["metadata"]["agent_handoff_card"]["status"] == "failed"
    job_id = failed.json()["job_id"]
    failed_job = runtime.get_job(job_id)
    assert failed_job is not None
    assert failed_job.metadata["agent_handoff_card"]["status"] == "failed"
    assert any(
        "agent stopped by test" in blocker
        for blocker in failed_job.metadata["agent_handoff_card"]["blockers"]
    )


def test_agent_bridge_result_persists_agent_handoff_card(monkeypatch: Any) -> None:
    """Terminal agent results should create a resumable local handoff card."""

    runtime = _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={
            "source": "mcp",
            "agent_host": "codex",
            "intent": "single_paper_deep_read",
            "project_id": "proj_demo",
            "resource_refs": [
                {
                    "ref_id": "material:mat_1",
                    "kind": "material",
                    "project_id": "proj_demo",
                    "title": "Demo Paper",
                    "read_endpoint": "/api/agent-bridge/resource/material:mat_1",
                }
            ],
        },
    )
    assert created.status_code == 200
    request_id = created.json()["request_id"]
    job_id = created.json()["job"]["job_id"]

    result = client.post(
        f"/api/agent-bridge/request/{request_id}/result",
        headers=_capability_headers(),
        json={
            "text": "完成精读，但还需要核查引用。",
            "evidence_refs": [{"ref_id": "chunk:1", "page": 2}],
        },
    )

    assert result.status_code == 200
    job = runtime.get_job(job_id)
    assert job is not None
    card = job.metadata["agent_handoff_card"]
    assert card["schema_version"] == "scholar_ai_agent_handoff_card_v1"
    assert card["request_id"] == request_id
    assert card["job_id"] == job_id
    assert card["status"] == "completed"
    assert card["resource_refs"][0]["ref_id"] == "material:mat_1"
    assert any(probe["endpoint"] == "/runtime/evidence-integrity-gate" for probe in card["resume_probes"])
    assert any("PDFMathTranslate" in action for action in card["forbidden_actions"])
    assert "read-only resume probes" in card["resume_prompt"]
    assert card["action_preflight"]["schema_version"] == "scholar_ai_action_preflight_v1"
    assert card["action_preflight"]["action_id"] == "agent.handoff_card"
    assert card["action_preflight"]["required_claim_id"] == "handoff_readiness"
    assert card["action_preflight"]["summary"]["unresolved_is_ready"] is False
    handoff_artifacts = [
        artifact
        for artifact in runtime.get_job_artifacts(job_id)
        if artifact.metadata.get("kind") == "agent_handoff_card"
    ]
    assert handoff_artifacts
    assert handoff_artifacts[-1].content["request_id"] == request_id

    route_response = client.get(
        f"/runtime/job/{job_id}/agent-handoff-card",
        headers=_capability_headers(),
    )
    assert route_response.status_code == 200
    route_payload = route_response.json()
    assert route_payload["request_id"] == request_id
    derived_from = route_payload["provenance"]["derived_from"]
    for source in [
        "runtime.job_metadata",
        "runtime.artifacts",
        "runtime.workflow_passport",
        "runtime.evidence_integrity_gate",
        "runtime.action_preflight",
        "runtime.research_action_lifecycle_refs",
        "runtime.workflow_replay_lineage",
        "runtime.workflow_replay_index",
    ]:
        assert source in derived_from


def test_agent_bridge_requires_bounded_result_payload(monkeypatch: Any) -> None:
    """Result endpoint should reject empty terminal output."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={"intent": "empty_result_guard"},
    )
    request_id = created.json()["request_id"]

    response = client.post(
        f"/api/agent-bridge/request/{request_id}/result",
        headers=_capability_headers(),
        json={},
    )

    assert response.status_code == 400
    assert "result text or content is required" in str(response.json())


def test_agent_bridge_resource_reader_bounds_material_payload(monkeypatch: Any) -> None:
    """Resource reader should return cursor-paginated text, not full context."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    class _Material:
        material_id = "mat_1"
        project_id = "proj_demo"
        title = "Demo"
        summary = "abcdef" * 200
        summary_en = ""
        focus_points: list[str] = []
        focus_points_en: list[str] = []
        type = "reference"

    class _Store:
        def get_material(self, material_id: str) -> Any:
            return _Material() if material_id == "mat_1" else None

    monkeypatch.setattr(agent_bridge_router, "get_resource_store", lambda: _Store())

    response = client.get(
        "/api/agent-bridge/resource/material:mat_1",
        headers=_capability_headers(),
        params={"max_chars": 120, "cursor": "20"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == "material:mat_1"
    assert len(payload["content"]) == 120
    assert payload["truncated"] is True
    assert payload["cursor"] == "20"
    assert payload["next_cursor"] == "140"


def test_agent_bridge_resource_reader_rejects_unbounded_chunk(monkeypatch: Any) -> None:
    """Chunk refs require project_id and server-enforced max_chars."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    missing_project = client.get(
        "/api/agent-bridge/resource/chunk:mat_1_chunk_0",
        headers=_capability_headers(),
        params={"max_chars": 500},
    )
    assert missing_project.status_code == 400

    oversize = client.get(
        "/api/agent-bridge/resource/material:mat_1",
        headers=_capability_headers(),
        params={"max_chars": 50000},
    )
    assert oversize.status_code == 422


def test_agent_bridge_resource_reader_reads_persisted_search_ref_chunk(monkeypatch: Any) -> None:
    """Chunk refs returned by search-refs must round-trip through the bounded reader."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    import routers.resources_router as resources_router

    project_id = "proj_search_ref_reader"
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_1": [
                {
                    "chunk_id": "mat_1_custom_chunk",
                    "material_id": "mat_1",
                    "title": "Search Ref Source",
                    "content": "AlSi10Mg porosity and fatigue evidence.",
                    "summary": "AlSi10Mg porosity summary.",
                    "abstract": "SHOULD_NOT_LEAK_ABSTRACT",
                    "ocr_text": "SHOULD_NOT_LEAK_OCR",
                    "private_note": "SHOULD_NOT_LEAK_PRIVATE",
                    "page": 3,
                    "chunk_type": "body",
                    "source_relative_path": "papers/search-ref.pdf",
                    "locator": {
                        "material_id": "mat_1",
                        "chunk_id": "mat_1_custom_chunk",
                        "page": 3,
                        "chunk_index": 0,
                        "text": "SHOULD_NOT_LEAK_LOCATOR_TEXT",
                    },
                }
            ]
        },
    )

    response = client.get(
        "/api/agent-bridge/resource/chunk:mat_1_custom_chunk",
        headers=_capability_headers(),
        params={"project_id": project_id, "max_chars": 120},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == "chunk:mat_1_custom_chunk"
    assert "AlSi10Mg porosity" in payload["content"]
    assert payload["metadata"]["chunk_id"] == "mat_1_custom_chunk"
    assert payload["metadata"]["material_id"] == "mat_1"
    assert payload["metadata"]["page"] == 3
    assert payload["metadata"]["chunk_type"] == "body"
    assert payload["metadata"]["source_relative_path"] == "papers/search-ref.pdf"
    assert payload["metadata"]["locator"] == {
        "material_id": "mat_1",
        "chunk_id": "mat_1_custom_chunk",
        "page": 3,
        "chunk_index": 0,
    }
    serialized = str(payload)
    assert "abstract" not in serialized
    assert "ocr" not in serialized.lower()
    assert "private_note" not in serialized
    assert "SHOULD_NOT_LEAK" not in serialized


def test_agent_bridge_resource_reader_reads_wiki_page_ref(monkeypatch: Any, tmp_path: Path) -> None:
    """Wiki refs should be first-class bounded resources without project chunk copying."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    wiki_root = tmp_path / "wiki"
    page_path = wiki_root / "synthesis" / "al-si-10-mg.md"
    page_path.parent.mkdir(parents=True)
    page_path.write_text(
        "# AlSi10Mg Wiki\n\n" + ("Wiki porosity and fatigue context. " * 20),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_bridge_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))

    response = client.get(
        "/api/agent-bridge/resource/wiki:synthesis/al-si-10-mg.md",
        headers=_capability_headers(),
        params={"max_chars": 120, "cursor": "2"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == "wiki:synthesis/al-si-10-mg.md"
    assert payload["kind"] == "wiki"
    assert payload["title"] == "AlSi10Mg Wiki"
    assert "AlSi10Mg Wiki" in payload["content"]
    assert len(payload["content"]) == 120
    assert payload["truncated"] is True
    assert payload["metadata"]["page_path"] == "synthesis/al-si-10-mg.md"
    source_hash = payload["metadata"]["source_hash"]
    assert payload["metadata"]["chunk_id"] == f"wiki:synthesis/al-si-10-mg.md#{derive_wiki_chunk_id(source_hash, 0)}"
    assert payload["metadata"]["resource_kind"] == "chunk"
    assert payload["metadata"]["span_start"] == 0
    assert payload["metadata"]["span_end"] > len(payload["content"])
    assert payload["metadata"]["returned_chars"] == 120


def test_agent_bridge_resource_reader_rejects_wiki_escape(monkeypatch: Any, tmp_path: Path) -> None:
    """Wiki resource refs must stay inside the generated wiki root."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    monkeypatch.setattr(agent_bridge_router, "wiki_generated_root", lambda *parts: tmp_path.joinpath(*parts))

    response = client.get(
        "/api/agent-bridge/resource/wiki:../secrets.md",
        headers=_capability_headers(),
        params={"max_chars": 120},
    )

    assert response.status_code == 400
    assert "wiki page path must stay inside the wiki root" in str(response.json())


def test_agent_bridge_resource_reader_reads_academic_english_ref(monkeypatch: Any, tmp_path: Path) -> None:
    """Academic-English refs should be cursor-bounded runtime resources."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    root = tmp_path / "english_discourse"
    _seed_academic_english_output(root)
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))

    response = client.get(
        "/api/agent-bridge/resource/academic_english:chunk:chunk-claim-scope",
        headers=_capability_headers(),
        params={"max_chars": 140, "cursor": "10"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == "academic_english:chunk:chunk-claim-scope"
    assert payload["kind"] == "academic_english"
    assert payload["title"] == "Claim Scope"
    assert len(payload["content"]) == 140
    assert payload["truncated"] is True
    assert payload["metadata"]["resource_kind"] == "chunk"
    assert payload["metadata"]["chunk_id"] == "chunk-claim-scope"
    assert payload["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-academic-english-knowledge-ref/v1"


def test_agent_bridge_resource_reader_reads_bridge_lexicon_ref(monkeypatch: Any, tmp_path: Path) -> None:
    """Bridge-lexicon entry refs should be cursor-bounded runtime resources."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    lexicon_path = tmp_path / "cjk_bridge_lexicon.json"
    lexicon_path.write_text(
        json.dumps(
            {
                "激光": [
                    "laser",
                    "beam",
                    "coherent light source",
                    "high energy density welding bridge term",
                    "optical processing anchor",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = tolf_bridge_lexicon_store.BridgeLexiconStore(lexicon_path)
    monkeypatch.setattr(tolf_bridge_lexicon_store, "_DEFAULT_STORE", store)
    monkeypatch.setattr(agent_bridge_router, "read_bridge_lexicon_resource", store.read_resource)
    ref_id = tolf_bridge_lexicon_store.search_bridge_lexicon("laser", top_k=1)[0]["ref_id"]

    response = client.get(
        f"/api/agent-bridge/resource/{ref_id}",
        headers=_capability_headers(),
        params={"max_chars": 100, "cursor": "7"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == ref_id
    assert payload["kind"] == "bridge_lexicon"
    assert payload["title"] == "Bridge lexicon: 激光"
    assert payload["content"].startswith("Lexicon Entry")
    assert payload["truncated"] is True
    assert payload["metadata"]["resource_kind"] == "entry"
    assert payload["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-bridge-lexicon-knowledge-ref/v1"
    assert payload["metadata"]["source_path"].endswith("cjk_bridge_lexicon.json")
    assert payload["metadata"]["returned_chars"] == 100


def test_agent_bridge_resource_reader_reads_skill_package_ref(monkeypatch: Any) -> None:
    """Skill package refs should be cursor-bounded runtime resources."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    ref_id = search_skill_package("academic-english-discourse", "Academic English Discourse", top_k=1)[0]["ref_id"]

    response = client.get(
        f"/api/agent-bridge/resource/{ref_id}",
        headers=_capability_headers(),
        params={"max_chars": 160, "cursor": "0"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == ref_id
    assert payload["kind"] == "skill_package"
    assert "Academic English Discourse" in payload["content"]
    assert payload["truncated"] is True
    assert payload["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-skill-package-knowledge-ref/v1"
    assert payload["metadata"]["package_id"] == "academic-english-discourse"
    assert payload["metadata"]["source_path"] == "SKILL.md"


def test_agent_bridge_resource_reader_reads_scoring_rules_ref(monkeypatch: Any) -> None:
    """Scoring-rules refs should be cursor-bounded runtime resources."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    ref_id = search_scoring_rules("direct_evidence", top_k=1)[0]["ref_id"]

    response = client.get(
        f"/api/agent-bridge/resource/{ref_id}",
        headers=_capability_headers(),
        params={"max_chars": 320, "cursor": "0"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == ref_id
    assert payload["kind"] == "scoring_rules"
    assert "direct_evidence" in payload["content"]
    assert payload["truncated"] is True
    assert payload["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-scoring-rules-knowledge-ref/v1"
    assert payload["metadata"]["resource_kind"] == "section"
    assert payload["metadata"]["section_id"] == "weights"


def test_agent_bridge_resource_reader_reads_product_docs_ref(monkeypatch: Any, tmp_path: Path) -> None:
    """Product-doc refs should be cursor-bounded runtime resources."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "README.md").write_text(
        "# Scholar AI\n\n" + ("Product docs enter the Knowledge Runtime Pipeline. " * 20),
        encoding="utf-8",
    )
    monkeypatch.setattr(product_docs_knowledge, "REPO_ROOT", root)
    ref_id = product_docs_knowledge.search_product_docs("Knowledge Runtime Pipeline", top_k=1)[0]["ref_id"]

    response = client.get(
        f"/api/agent-bridge/resource/{ref_id}",
        headers=_capability_headers(),
        params={"max_chars": 140, "cursor": "0"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == ref_id
    assert payload["kind"] == "product_docs"
    assert "Scholar AI" in payload["content"]
    assert payload["truncated"] is True
    assert payload["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-product-docs-knowledge-ref/v1"
    assert payload["metadata"]["source_path"] == "README.md"


def test_agent_bridge_resource_reader_reads_source_vault_ref(monkeypatch: Any, tmp_path: Path) -> None:
    """Source Vault chunk refs should be cursor-bounded runtime resources."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    vault = _seed_source_vault(tmp_path)
    source = vault.list_sources()[0]
    chunk_id = derive_chunk_id(source.source_hash, "chunker-v1", 0)
    monkeypatch.setattr(agent_bridge_router, "SourceVault", lambda: vault)

    response = client.get(
        f"/api/agent-bridge/resource/source_vault:chunk:{chunk_id}",
        headers=_capability_headers(),
        params={"max_chars": 140, "cursor": "5"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == f"source_vault:chunk:{chunk_id}"
    assert payload["kind"] == "source_vault"
    assert payload["title"] == "Source Vault Paper"
    assert payload["content"].startswith("n pool keeps the discussion grounded in source evidence.")
    assert payload["metadata"]["resource_kind"] == "chunk"
    assert payload["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-source-vault-knowledge-ref/v1"
