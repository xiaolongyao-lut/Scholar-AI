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
from models import (
    EvidencePackBuildResponse,
    EvidencePackIntegrityGateResponse,
    EvidencePackReferencePayload,
    EvidenceRetrievalDiagnosticsPayload,
    RetrievalQrelsStatusPayload,
)
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


def test_running_desktop_runtime_skips_self_health_probe(monkeypatch: Any, tmp_path: Path) -> None:
    """Desktop-hosted API must not synchronously probe its own health endpoint."""

    descriptor = tmp_path / "desktop-runtime.json"
    descriptor.write_text(
        json.dumps(
            {
                "process_kind": "desktop",
                "ready": True,
                "pid": 4321,
                "base_url": "http://127.0.0.1:8000",
                "window_title": "文献助手",
            }
        ),
        encoding="utf-8",
    )

    def _unexpected_health_probe(_base_url: str, timeout_sec: float = 1.5) -> bool:
        raise AssertionError("same-process desktop runtime should not call /health")

    monkeypatch.setattr(agent_bridge_router, "desktop_runtime_file_path", lambda: descriptor)
    monkeypatch.setattr(agent_bridge_router.os, "getpid", lambda: 4321)
    monkeypatch.setattr(agent_bridge_router, "_pid_exists", lambda _pid: True)
    monkeypatch.setattr(agent_bridge_router, "_health_ok", _unexpected_health_probe)

    runtime = agent_bridge_router._read_running_desktop_runtime()

    assert runtime == {
        "pid": 4321,
        "base_url": "http://127.0.0.1:8000",
        "window_title": "文献助手",
    }


def test_desktop_open_focuses_existing_runtime_without_relaunch(monkeypatch: Any) -> None:
    """Existing desktop runtime should be raised instead of launching another copy."""

    existing = {
        "pid": 1234,
        "base_url": "http://127.0.0.1:8000",
        "window_title": "文献助手",
    }
    raised: list[dict[str, Any]] = []

    def _raise_existing(runtime: dict[str, Any]) -> bool:
        raised.append(dict(runtime))
        return True

    def _unexpected_launch() -> tuple[list[str], dict[str, str]]:
        raise AssertionError("existing desktop runtime should not trigger launch")

    monkeypatch.setattr(agent_bridge_router, "_read_running_desktop_runtime", lambda: existing)
    monkeypatch.setattr(agent_bridge_router, "_raise_running_desktop", _raise_existing)
    monkeypatch.setattr(agent_bridge_router, "_desktop_launch_command", _unexpected_launch)

    status = agent_bridge_router._launch_desktop_if_needed()

    assert status["started"] is False
    assert status["focused"] is True
    assert status["status"] == "running"
    assert raised == [existing]


def test_agent_sidebar_desktop_open_reports_focused_running_desktop(monkeypatch: Any) -> None:
    """Desktop-open route should tell the sidebar when an existing window was raised."""

    client = _client(monkeypatch)
    monkeypatch.setattr(
        agent_bridge_router,
        "_launch_desktop_if_needed",
        lambda: {
            "status": "running",
            "started": False,
            "focused": True,
            "pid": 1234,
            "base_url": "http://127.0.0.1:8000",
            "window_title": "文献助手",
        },
    )

    response = client.post("/api/agent-bridge/desktop/open", headers=_capability_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["focused"] is True
    assert payload["started"] is False
    assert payload["message"] == "已切换到文献助手桌面端。"


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


def test_codex_handoff_latest_projects_unresolved_sidebar_request(monkeypatch: Any) -> None:
    """Codex handoff latest should be derived from existing agent request jobs."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={
            "source": "agent_sidebar",
            "agent_host": "codex",
            "intent": "sidebar_answer",
            "user_text": "What does the evidence say?",
            "project_id": "proj_demo",
            "route": "/agent-sidebar",
            "resource_refs": [
                {
                    "ref_id": "chunk:1",
                    "kind": "chunk",
                    "project_id": "proj_demo",
                    "title": "Demo Evidence",
                    "summary": "bounded summary",
                }
            ],
            "metadata": {
                "source_conversation_id": "sidebar_agentreq_demo",
                "evidence_pack_ref": "evidence_pack:demo",
            },
        },
    )

    assert created.status_code == 200
    request_id = created.json()["request_id"]

    latest = client.get(
        "/api/agent-bridge/codex-handoff/latest",
        headers=_capability_headers(),
        params={"project_id": "proj_demo"},
    )

    assert latest.status_code == 200
    payload = latest.json()
    assert payload["schema_version"] == "scholar-ai-codex-handoff-latest/v1"
    assert payload["found"] is True
    assert payload["request_id"] == request_id
    assert payload["project_id"] == "proj_demo"
    assert payload["receipt_id"] == "sidebar_agentreq_demo"
    assert payload["ref_count"] == 1
    assert payload["job_status"] == "started"

    other_project = client.get(
        "/api/agent-bridge/codex-handoff/latest",
        headers=_capability_headers(),
        params={"project_id": "proj_other"},
    )
    assert other_project.status_code == 200
    assert other_project.json()["found"] is False


def test_agent_bridge_sidebar_answer_disables_capture_side_effects(monkeypatch: Any) -> None:
    """Pure sidebar QA requests should not schedule Wiki/graph/evolution capture."""

    runtime = _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={
            "source": "mcp",
            "agent_host": "codex",
            "intent": "sidebar_answer",
            "project_id": "proj_sidebar",
        },
    )

    assert created.status_code == 200
    job = runtime.get_job(created.json()["job"]["job_id"])
    assert job is not None
    targets = job.metadata["output_targets"]
    assert targets["runtime_job"] is True
    assert targets["smart_read_conversation"] is True
    assert targets["wiki_candidate"] is False
    assert targets["graph_candidate"] is False
    assert targets["evolution_capture"] is False


def test_agent_bridge_result_rejects_provider_private_payload(monkeypatch: Any) -> None:
    """Agent result write-back accepts only whitelisted answer fields."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)
    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={"intent": "sidebar_answer", "project_id": "proj_sidebar"},
    )
    request_id = created.json()["request_id"]

    result = client.post(
        f"/api/agent-bridge/request/{request_id}/result",
        headers=_capability_headers(),
        json={
            "content": {
                "text": "final answer",
                "provider_payload": {"raw": "must not land"},
            }
        },
    )

    assert result.status_code == 422
    assert "provider_payload" in result.text


def test_agent_bridge_sidebar_result_persists_answer_receipt(monkeypatch: Any, tmp_path: Path) -> None:
    """Host-agent sidebar answers should land in the existing SmartRead history store."""

    runtime = _isolated_runtime(monkeypatch)
    history_db = tmp_path / "chat_history.db"
    session_store = tmp_path / "sessions.json"
    session_store.write_text(json.dumps({"sessions": {}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(agent_bridge_router, "default_chat_history_db_path", lambda: history_db)

    import routers.evidence_router as evidence_router
    import routers.intelligent_chat_router as intelligent_chat_router

    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(intelligent_chat_router, "default_chat_history_db_path", lambda: history_db)

    qrels_hash = "sha256:" + "d" * 64
    gate_hash = "sha256:" + "e" * 64

    class _QrelsStatus:
        qrels_content_hash = qrels_hash

    monkeypatch.setattr(evidence_router, "_project_qrels_status", lambda _project_id: _QrelsStatus())
    monkeypatch.setattr(evidence_router, "_evidence_pack_gate_config_hash", lambda: gate_hash)
    restore_calls: list[dict[str, Any]] = []

    def _restore_evidence_pack_build(**kwargs: Any) -> object | None:
        restore_calls.append(dict(kwargs))
        if kwargs.get("query") == "":
            return object()
        return None

    monkeypatch.setattr(evidence_router, "_restore_evidence_pack_build", _restore_evidence_pack_build)

    client = _client(monkeypatch)
    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={
            "source": "mcp",
            "agent_host": "codex",
            "intent": "sidebar_answer",
            "user_text": "Which evidence supports the weld appearance claim?",
            "project_id": "proj_sidebar_receipt",
            "chat_session_id": "session_sidebar_receipt",
        },
    )
    assert created.status_code == 200
    request_id = created.json()["request_id"]

    result = client.post(
        f"/api/agent-bridge/request/{request_id}/result",
        headers=_capability_headers(),
        json={
            "content": {
                "text": "The bounded evidence supports the appearance claim.",
                "answer_model": "codex-host",
                "evidence_pack_ref": "evidence_pack:sidebar",
                "retrieval_diagnostics": {
                    "retrieval_method": "hybrid",
                    "rerank_status": "active",
                },
                "qrels_status": {"qrels_content_hash": qrels_hash},
                "evidence_gate_status": {"gate_config_hash": gate_hash},
                "output_language": "en",
            },
            "evidence_refs": [{"ref_id": "chunk:1", "chunk_hash": "sha256:" + "f" * 64}],
        },
    )

    assert result.status_code == 200
    job_id = created.json()["job"]["job_id"]
    job = runtime.get_job(job_id)
    assert job is not None
    assert job.metadata["smart_read_conversation"]["status"] == "persisted"
    assert job.metadata["smart_read_conversation"]["conversation_id"] == "session_sidebar_receipt"

    read = client.get(
        "/api/chat/answer-receipts/session_sidebar_receipt",
        headers=_capability_headers(),
    )
    assert read.status_code == 200
    payload = read.json()
    receipt = payload["receipt"]
    assert payload["answer"] == "The bounded evidence supports the appearance claim."
    assert receipt["generated_in"] == "mcp_sidebar"
    assert receipt["answer_origin"] == "host_agent"
    assert receipt["answer_model"] == "codex-host"
    assert receipt["evidence_pack_ref"] == "evidence_pack:sidebar"
    assert receipt["question"] == "Which evidence supports the weld appearance claim?"
    assert receipt["qrels_status"]["qrels_content_hash"] == qrels_hash
    assert receipt["receipt_fingerprint_inputs"]["qrels_content_hash"] == qrels_hash
    workflow_refs = receipt["workflow_refs"]
    assert workflow_refs["read_only"] is True
    assert workflow_refs["agent_request_id"] == request_id
    assert workflow_refs["runtime_job_id"] == job_id
    assert workflow_refs["project_id"] == "proj_sidebar_receipt"
    assert workflow_refs["workflow_passport_ref"]["endpoint"] == "/runtime/workflow-passport"
    assert workflow_refs["research_action_lifecycle_ref"]["endpoint"] == "/runtime/research-action-lifecycle"
    assert workflow_refs["agent_handoff_card_ref"]["endpoint"] == f"/runtime/job/{job_id}/agent-handoff-card"
    assert workflow_refs["workflow_replay_lineage_ref"]["endpoint"] == f"/runtime/job/{job_id}/workflow-replay-lineage"
    assert workflow_refs["workflow_replay_index_ref"]["endpoint"] == "/runtime/workflow-replay-index"
    assert receipt["workflow_passport_ref"] == workflow_refs["workflow_passport_ref"]
    assert receipt["research_action_lifecycle_ref"] == workflow_refs["research_action_lifecycle_ref"]
    assert payload["staleness"]["status"] == "saved"
    assert restore_calls == [
        {
            "project_id": "proj_sidebar_receipt",
            "query": "Which evidence supports the weld appearance claim?",
            "evidence_pack_ref": "evidence_pack:sidebar",
        },
        {
            "project_id": "proj_sidebar_receipt",
            "query": "",
            "evidence_pack_ref": "evidence_pack:sidebar",
        },
    ]

    sessions = client.get("/api/chat/sessions", headers=_capability_headers())
    assert sessions.status_code == 200
    session_rows = sessions.json()["sessions"]
    sidebar_row = next(
        item for item in session_rows if item["session_id"] == "session_sidebar_receipt"
    )
    assert sidebar_row["project_id"] == "proj_sidebar_receipt"
    assert sidebar_row["preview"] == "The bounded evidence supports the appearance claim."
    assert sidebar_row["source"] == "mcp_sidebar"

    resume = client.post(
        "/api/chat/resume",
        headers=_capability_headers(),
        json={"session_id": "session_sidebar_receipt", "limit": 100},
    )
    assert resume.status_code == 200
    resumed = resume.json()
    assert resumed["project_id"] == "proj_sidebar_receipt"
    assert [message["role"] for message in resumed["messages"]] == ["user", "assistant"]
    assert resumed["messages"][0]["content"] == "Which evidence supports the weld appearance claim?"
    assert resumed["messages"][1]["content"] == "The bounded evidence supports the appearance claim."
    assert resumed["messages"][1]["generated_in"] == "mcp_sidebar"
    assert resumed["messages"][1]["answer_origin"] == "external_agent"
    assert resumed["messages"][1]["evidence_pack_ref"] == "evidence_pack:sidebar"


def test_agent_bridge_sidebar_result_falls_back_to_request_metadata(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Sidebar handoff results should not drop receipt metadata carried by the request."""

    runtime = _isolated_runtime(monkeypatch)
    history_db = tmp_path / "chat_history.db"
    session_store = tmp_path / "sessions.json"
    session_store.write_text(json.dumps({"sessions": {}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(agent_bridge_router, "default_chat_history_db_path", lambda: history_db)

    import routers.evidence_router as evidence_router
    import routers.intelligent_chat_router as intelligent_chat_router

    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(intelligent_chat_router, "default_chat_history_db_path", lambda: history_db)

    qrels_hash = "sha256:" + "a" * 64
    gate_hash = "sha256:" + "b" * 64
    pack_ref = "evidence_pack:from-request"

    class _QrelsStatus:
        qrels_content_hash = qrels_hash

    restore_calls: list[dict[str, Any]] = []

    def _restore_evidence_pack_build(**kwargs: Any) -> object | None:
        restore_calls.append(dict(kwargs))
        if kwargs.get("evidence_pack_ref") == pack_ref:
            return object()
        return None

    monkeypatch.setattr(evidence_router, "_project_qrels_status", lambda _project_id: _QrelsStatus())
    monkeypatch.setattr(evidence_router, "_evidence_pack_gate_config_hash", lambda: gate_hash)
    monkeypatch.setattr(evidence_router, "_restore_evidence_pack_build", _restore_evidence_pack_build)

    client = _client(monkeypatch)
    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={
            "source": "codex_side_browser",
            "agent_host": "codex",
            "intent": "sidebar_answer",
            "user_text": "Summarize the bounded evidence.",
            "project_id": "proj_sidebar_request_fallback",
            "chat_session_id": "session_sidebar_request_fallback",
            "metadata": {
                "evidence_pack_ref": pack_ref,
                "answer_model": "codex-request-model",
                "output_language": "en",
            },
            "resource_refs": [
                {
                    "ref_id": "chunk:request-fallback",
                    "kind": "evidence_chunk",
                    "project_id": "proj_sidebar_request_fallback",
                    "metadata": {
                        "evidence_pack_ref": pack_ref,
                        "retrieval_diagnostics": {
                            "retrieval_method": "lexical",
                            "rerank_status": "skipped",
                        },
                        "qrels_status": {"qrels_content_hash": qrels_hash},
                        "evidence_gate_status": {"gate_config_hash": gate_hash},
                    },
                }
            ],
        },
    )
    assert created.status_code == 200
    request_id = created.json()["request_id"]

    result = client.post(
        f"/api/agent-bridge/request/{request_id}/result",
        headers=_capability_headers(),
        json={
            "content": {
                "text": "The answer uses the request-scoped evidence metadata.",
                "retrieval_diagnostics": {
                    "retrieval_method": "hybrid_rerank",
                    "qrels_status": {"status": "candidate"},
                },
                "qrels_status": {
                    "schema_version": "retrieval-qrels-status/v1",
                    "status": "candidate",
                    "semantic_quality_claim_allowed": False,
                },
                "evidence_gate_status": {"status": "passed"},
            },
            "evidence_refs": [{"ref_id": "chunk:request-fallback", "chunk_hash": "sha256:" + "c" * 64}],
        },
    )

    assert result.status_code == 200
    job = runtime.get_job(created.json()["job"]["job_id"])
    assert job is not None
    assert job.metadata["smart_read_conversation"]["status"] == "persisted"

    read = client.get(
        "/api/chat/answer-receipts/session_sidebar_request_fallback",
        headers=_capability_headers(),
    )
    assert read.status_code == 200
    receipt = read.json()["receipt"]
    assert receipt["evidence_pack_ref"] == pack_ref
    assert receipt["answer_model"] == "codex-request-model"
    assert receipt["output_language"] == "en"
    assert receipt["retrieval_diagnostics"]["retrieval_method"] == "hybrid_rerank"
    assert receipt["retrieval_diagnostics"]["rerank_status"] == "skipped"
    assert receipt["retrieval_diagnostics"]["qrels_status"]["qrels_content_hash"] == qrels_hash
    assert receipt["qrels_status"]["status"] == "candidate"
    assert receipt["qrels_status"]["semantic_quality_claim_allowed"] is False
    assert receipt["qrels_status"]["qrels_content_hash"] == qrels_hash
    assert receipt["receipt_fingerprint_inputs"]["qrels_content_hash"] == qrels_hash
    assert receipt["evidence_gate_status"]["status"] == "passed"
    assert receipt["evidence_gate_status"]["gate_config_hash"] == gate_hash
    assert receipt["receipt_fingerprint_inputs"]["gate_config_hash"] == gate_hash
    assert receipt["workflow_refs"]["agent_request_id"] == request_id
    assert receipt["workflow_refs"]["runtime_job_id"] == created.json()["job"]["job_id"]
    assert receipt["workflow_passport_ref"]["endpoint"] == "/runtime/workflow-passport"
    assert receipt["agent_handoff_card_ref"]["endpoint"].endswith("/agent-handoff-card")
    assert read.json()["staleness"]["status"] == "saved"
    assert restore_calls == [
        {
            "project_id": "proj_sidebar_request_fallback",
            "query": "Summarize the bounded evidence.",
            "evidence_pack_ref": pack_ref,
        }
    ]


def test_smart_read_external_agent_chat_imports_sidebar_answer_receipt(monkeypatch: Any, tmp_path: Path) -> None:
    """Persisting SmartRead turns should import sidebar receipt metadata."""

    _isolated_runtime(monkeypatch)
    history_db = tmp_path / "chat_history.db"
    session_store = tmp_path / "sessions.json"
    session_store.write_text(json.dumps({"sessions": {}}, ensure_ascii=False), encoding="utf-8")

    import routers.intelligent_chat_router as intelligent_chat_router
    import routers.evidence_router as evidence_router

    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(intelligent_chat_router, "default_chat_history_db_path", lambda: history_db)
    monkeypatch.setattr(intelligent_chat_router, "runtime_state_path", lambda: tmp_path / "runtime_state")
    monkeypatch.setattr(evidence_router, "_restore_evidence_pack_build", lambda **_kwargs: object())

    class _ProjectStore:
        def get_project(self, project_id: str) -> dict[str, str] | None:
            if project_id == "proj_sidebar_receipt":
                return {"project_id": project_id}
            return None

    async def _build_project_context_chunks(*_args: Any, **_kwargs: Any) -> tuple[list[Any], bool]:
        return (
            [
                intelligent_chat_router.ContextChunkPayload(
                    index=1,
                    source="Sidebar Receipt Source",
                    content="A bounded evidence chunk for the shared receipt import path.",
                    relevance_score=0.91,
                    chunk_id="chunk-sidebar-receipt",
                    material_id="mat-sidebar",
                    source_labels=["local_context"],
                    page=3,
                    rerank_score=0.82,
                )
            ],
            False,
        )

    monkeypatch.setattr(intelligent_chat_router, "get_writing_resource_store", lambda: _ProjectStore())
    monkeypatch.setattr(intelligent_chat_router, "_build_project_context_chunks", _build_project_context_chunks)

    client = _client(monkeypatch)
    asked = client.post(
        "/api/chat",
        headers=_capability_headers(),
        json={
            "project_id": "proj_sidebar_receipt",
            "session_id": "session_smartread_sidebar_receipt",
            "query": "Which bounded evidence should the host agent use?",
            "tier": "balanced",
            "mode": "literature_qa",
            "answer_origin": "external_agent",
            "generated_in": "mcp_sidebar",
            "evidence_pack_ref": "evidence_pack:smartread-sidebar",
        },
    )

    assert asked.status_code == 200
    assert asked.json()["session_id"] == "session_smartread_sidebar_receipt"

    read = client.get(
        "/api/chat/answer-receipts/session_smartread_sidebar_receipt",
        headers=_capability_headers(),
    )
    assert read.status_code == 200
    payload = read.json()
    receipt = payload["receipt"]
    assert receipt["generated_in"] == "mcp_sidebar"
    assert receipt["answer_origin"] == "host_agent"
    assert receipt["evidence_pack_ref"] == "evidence_pack:smartread-sidebar"
    assert receipt["question"] == "Which bounded evidence should the host agent use?"
    assert receipt["retrieval_diagnostics"]["retrieval_method"] == "legacy_project_retrieval"
    assert payload["staleness"]["status"] == "saved"

    resume = client.post(
        "/api/chat/resume",
        headers=_capability_headers(),
        json={"session_id": "session_smartread_sidebar_receipt", "limit": 20},
    )
    assert resume.status_code == 200
    assistant = resume.json()["messages"][1]
    assert assistant["generated_in"] == "mcp_sidebar"
    assert assistant["answer_origin"] == "external_agent"
    assert assistant["evidence_pack_ref"] == "evidence_pack:smartread-sidebar"


def test_answer_receipt_revalidate_dry_run_and_apply(monkeypatch: Any, tmp_path: Path) -> None:
    """Receipt revalidate should dry-run first and update only existing receipt metadata."""

    _isolated_runtime(monkeypatch)
    history_db = tmp_path / "chat_history.db"
    session_store = tmp_path / "sessions.json"
    session_store.write_text(json.dumps({"sessions": {}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(agent_bridge_router, "default_chat_history_db_path", lambda: history_db)

    import routers.evidence_router as evidence_router
    import routers.intelligent_chat_router as intelligent_chat_router

    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(intelligent_chat_router, "default_chat_history_db_path", lambda: history_db)

    old_qrels_hash = "sha256:" + "1" * 64
    new_qrels_hash = "sha256:" + "2" * 64
    old_gate_hash = "sha256:" + "3" * 64
    new_gate_hash = "sha256:" + "4" * 64

    class _QrelsStatus:
        qrels_content_hash = new_qrels_hash

    evidence_ref = EvidencePackReferencePayload(
        project_id="proj_sidebar_revalidate",
        ref_id="chunk:1",
        read_endpoint="/api/agent-bridge/resource/chunk:1",
        chunk_id="chunk-1",
        material_id="mat-1",
        page=1,
        lexical_score=1.0,
        citation_anchor="mat_1_chunk_1",
        summary="Bounded evidence summary.",
        source_title="Source A",
    )
    diagnostics = EvidenceRetrievalDiagnosticsPayload(
        retrieval_method="hybrid",
        embedding_status="active",
        rerank_status="active",
        qrels_status=RetrievalQrelsStatusPayload(
            status="candidate",
            candidate_qrels_count=1,
            qrels_content_hash=new_qrels_hash,
            semantic_quality_claim_allowed=False,
            quality_claim="candidate_qrels_review_required",
        ),
    )
    pack = EvidencePackBuildResponse(
        evidence_pack_ref="evidence_pack:sidebar",
        project_id="proj_sidebar_revalidate",
        query="Which evidence supports the weld appearance claim?",
        retrieval_method="hybrid",
        rerank_status="active",
        total=1,
        retrieval_diagnostics=diagnostics,
        evidence_refs=[evidence_ref],
    )
    gate = EvidencePackIntegrityGateResponse(
        generated_at="2026-07-07T00:00:00+00:00",
        gate_config_hash=new_gate_hash,
        project_id="proj_sidebar_revalidate",
        evidence_pack_ref="evidence_pack:sidebar",
        query="Which evidence supports the weld appearance claim?",
        status="passed",
        summary={"gate_config_hash": new_gate_hash, "evidence_ref_count": 1},
    )

    async def _build_evidence_pack(request: Any) -> EvidencePackBuildResponse:
        assert request.project_id == "proj_sidebar_revalidate"
        assert request.query == "Which evidence supports the weld appearance claim?"
        assert request.top_k == 7
        return pack

    monkeypatch.setattr(evidence_router, "build_evidence_pack", _build_evidence_pack)
    monkeypatch.setattr(evidence_router, "_build_evidence_pack_integrity_gate", lambda _request: gate)
    monkeypatch.setattr(evidence_router, "_restore_evidence_pack_build", lambda **_kwargs: pack)
    monkeypatch.setattr(evidence_router, "_project_qrels_status", lambda _project_id: _QrelsStatus())
    monkeypatch.setattr(evidence_router, "_evidence_pack_gate_config_hash", lambda: new_gate_hash)

    client = _client(monkeypatch)
    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={
            "source": "mcp",
            "agent_host": "codex",
            "intent": "sidebar_answer",
            "user_text": "Which evidence supports the weld appearance claim?",
            "project_id": "proj_sidebar_revalidate",
            "chat_session_id": "session_sidebar_revalidate",
        },
    )
    assert created.status_code == 200
    request_id = created.json()["request_id"]

    result = client.post(
        f"/api/agent-bridge/request/{request_id}/result",
        headers=_capability_headers(),
        json={
            "content": {
                "text": "The bounded evidence supports the appearance claim.",
                "answer_model": "codex-host",
                "evidence_pack_ref": "evidence_pack:sidebar",
                "retrieval_diagnostics": {
                    "retrieval_method": "hybrid",
                    "rerank_status": "active",
                },
                "qrels_status": {"qrels_content_hash": old_qrels_hash},
                "evidence_gate_status": {"gate_config_hash": old_gate_hash},
                "output_language": "en",
            },
            "evidence_refs": [{"ref_id": "chunk:1"}],
        },
    )
    assert result.status_code == 200

    import_calls: list[str] = []

    async def _unexpected_import_chat_history() -> Any:
        import_calls.append("called")
        raise AssertionError("durable answer receipts should not force legacy history import")

    monkeypatch.setattr(intelligent_chat_router, "import_chat_history", _unexpected_import_chat_history)

    dry_run = client.post(
        "/api/chat/answer-receipts/session_sidebar_revalidate/revalidate",
        headers=_capability_headers(),
        json={"top_k": 7},
    )
    assert dry_run.status_code == 200
    dry_payload = dry_run.json()
    assert dry_payload["applied"] is False
    assert dry_payload["apply_allowed"] is True
    assert dry_payload["status"] == "ready"
    assert dry_payload["receipt"]["qrels_status"]["qrels_content_hash"] == new_qrels_hash
    assert dry_payload["receipt"]["evidence_gate_status"]["gate_config_hash"] == new_gate_hash

    after_dry_run = client.get(
        "/api/chat/answer-receipts/session_sidebar_revalidate",
        headers=_capability_headers(),
    )
    assert after_dry_run.json()["receipt"]["qrels_status"]["qrels_content_hash"] == old_qrels_hash

    applied = client.post(
        "/api/chat/answer-receipts/session_sidebar_revalidate/revalidate",
        headers=_capability_headers(),
        json={"apply": True, "top_k": 7},
    )
    assert applied.status_code == 200
    applied_payload = applied.json()
    assert applied_payload["applied"] is True
    assert applied_payload["status"] == "revalidated"
    assert applied_payload["revalidated_staleness"]["status"] == "saved"

    read = client.get(
        "/api/chat/answer-receipts/session_sidebar_revalidate",
        headers=_capability_headers(),
    )
    receipt = read.json()["receipt"]
    assert receipt["lifecycle_state"] == "revalidated"
    assert receipt["qrels_status"]["qrels_content_hash"] == new_qrels_hash
    assert receipt["evidence_gate_status"]["gate_config_hash"] == new_gate_hash
    assert import_calls == []


def test_agent_bridge_result_consumes_wiki_and_graph_candidates(monkeypatch: Any, tmp_path: Path) -> None:
    """Agent result flags should create reviewable local knowledge artifacts."""

    runtime = _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    import routers.wiki_router as wiki_router
    from wiki.page_store import WikiPageStore
    from literature_assistant.core.wiki.review_queue import ReviewQueue
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
    appended_item_modules: list[str] = []
    original_append = ReviewQueue.append

    def record_canonical_queue_append(queue: ReviewQueue, item: Any) -> Any:
        appended_item_modules.append(type(item).__module__)
        return original_append(queue, item)

    monkeypatch.setattr(ReviewQueue, "append", record_canonical_queue_append)

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
    assert appended_item_modules == ["literature_assistant.core.wiki.review_queue"]

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


def test_agent_bridge_receipt_links_wiki_and_graph_consumer_refs(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Saved answer receipts should expose read-only Wiki/graph candidate refs."""

    runtime = _isolated_runtime(monkeypatch)
    history_db = tmp_path / "chat_history.db"
    session_store = tmp_path / "sessions.json"
    session_store.write_text(json.dumps({"sessions": {}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(agent_bridge_router, "default_chat_history_db_path", lambda: history_db)

    import routers.evidence_router as evidence_router
    import routers.intelligent_chat_router as intelligent_chat_router
    import routers.wiki_router as wiki_router
    from wiki.page_store import WikiPageStore
    from literature_assistant.core.wiki.review_queue import ReviewQueue
    from wiki.service import WikiService

    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(intelligent_chat_router, "default_chat_history_db_path", lambda: history_db)

    wiki_root = tmp_path / "wiki"
    review_path = tmp_path / "runtime" / "review_queue.jsonl"
    monkeypatch.setattr(wiki_router, "wiki_enabled", lambda: True)
    monkeypatch.setattr(wiki_router, "wiki_generated_root", lambda: wiki_root)
    monkeypatch.setattr(wiki_router, "wiki_review_queue_path", lambda: review_path)
    monkeypatch.setattr(agent_bridge_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))

    def _service() -> WikiService:
        return WikiService(WikiPageStore(wiki_root, create=True))

    import wiki.service as flat_wiki_service

    monkeypatch.setattr(flat_wiki_service, "get_wiki_service", _service)

    pack_ref = "evidence_pack:wiki-graph-continuity"
    qrels_hash = "sha256:" + "8" * 64
    gate_hash = "sha256:" + "9" * 64

    class _QrelsStatus:
        qrels_content_hash = qrels_hash

    monkeypatch.setattr(evidence_router, "_project_qrels_status", lambda _project_id: _QrelsStatus())
    monkeypatch.setattr(evidence_router, "_evidence_pack_gate_config_hash", lambda: gate_hash)
    monkeypatch.setattr(evidence_router, "_restore_evidence_pack_build", lambda **_kwargs: object())

    client = _client(monkeypatch)
    created = client.post(
        "/api/agent-bridge/request",
        headers=_capability_headers(),
        json={
            "source": "codex_side_browser",
            "agent_host": "codex",
            "intent": "write_review_intro",
            "user_text": "Turn the bounded evidence into a reviewable claim.",
            "project_id": "proj_wiki_graph_continuity",
            "chat_session_id": "session_wiki_graph_continuity",
            "output_targets": {
                "runtime_job": True,
                "smart_read_conversation": True,
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
            "content": {
                "text": "孔隙证据可作为 Wiki 候选条目，并由图谱候选关系回看。",
                "answer_model": "codex-host",
                "evidence_pack_ref": pack_ref,
                "retrieval_diagnostics": {"retrieval_method": "hybrid"},
                "qrels_status": {"qrels_content_hash": qrels_hash},
                "evidence_gate_status": {"gate_config_hash": gate_hash},
                "output_language": "zh",
            },
            "evidence_refs": [{"ref_id": "chunk:abc", "summary": "孔隙影响疲劳裂纹萌生"}],
            "graph_patch_refs": [{"node": "AlSi10Mg", "relation": "affects", "target": "fatigue"}],
        },
    )

    assert result.status_code == 200
    job = runtime.get_job(job_id)
    assert job is not None
    consumers = job.metadata["knowledge_consumers"]
    assert consumers["wiki"]["status"] == "created"
    assert consumers["graph"]["status"] == "attached_to_wiki_candidate"

    read = client.get(
        "/api/chat/answer-receipts/session_wiki_graph_continuity",
        headers=_capability_headers(),
    )
    assert read.status_code == 200
    receipt = read.json()["receipt"]
    assert receipt["evidence_pack_ref"] == pack_ref
    assert receipt["top_evidence_refs"][0]["ref_id"] == "chunk:abc"
    consumer_refs = receipt["knowledge_consumer_refs"]
    assert consumer_refs["read_only"] is True
    assert consumer_refs["agent_request_id"] == request_id
    assert consumer_refs["runtime_job_id"] == job_id
    wiki_ref = consumer_refs["wiki_candidate_ref"]
    assert wiki_ref["ref_type"] == "wiki_candidate_review_page"
    assert wiki_ref["read_endpoint"].startswith("/api/agent-bridge/resource/wiki:synthesis/")
    assert wiki_ref["page_path"] == consumers["wiki"]["page_path"]
    assert consumer_refs["wiki_review_item_ref"]["item_id"] == consumers["wiki"]["review_item_id"]
    graph_ref = consumer_refs["graph_candidate_ref"]
    assert graph_ref["status"] == "attached_to_wiki_candidate"
    assert graph_ref["graph_patch_ref_count"] == 1
    assert graph_ref["wiki_slug"] == consumers["wiki"]["slug"]

    resource_response = client.get(wiki_ref["read_endpoint"], headers=_capability_headers())
    assert resource_response.status_code == 200
    resource_payload = resource_response.json()
    assert resource_payload["kind"] == "wiki"
    assert resource_payload["metadata"]["page_path"] == consumers["wiki"]["page_path"]
    assert "孔隙证据可作为 Wiki 候选条目" in resource_payload["content"]
    assert "chunk:abc" in resource_payload["content"]

    review_items = ReviewQueue(review_path).list_items()
    assert [item.item_id for item in review_items] == [consumers["wiki"]["review_item_id"]]


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
                    "content": "AlSi10Mg porosity and fatigue evidence. Fig. 2 shows the weld surface morphology.",
                    "summary": "AlSi10Mg porosity summary.",
                    "abstract": "SHOULD_NOT_LEAK_ABSTRACT",
                    "ocr_text": "SHOULD_NOT_LEAK_OCR",
                    "private_note": "SHOULD_NOT_LEAK_PRIVATE",
                    "page": 3,
                    "chunk_type": "body",
                    "source_relative_path": "papers/search-ref.pdf",
                    "figure_candidate": "figure:search-ref-surface",
                    "image_paths": ["figure_assets/extracted/search-ref/p0003_img002.png"],
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
    assert payload["image_paths"] == ["figure_assets/extracted/search-ref/p0003_img002.png"]
    assert payload["metadata"]["image_paths"] == ["figure_assets/extracted/search-ref/p0003_img002.png"]
    assert payload["figure_candidate_detail"]["id"] == "figure:search-ref-surface"
    assert payload["figure_candidate_detail"]["label"] == "图 2"
    assert payload["figure_candidate_detail"]["page"] == 3
    assert payload["figure_candidate_detail"]["chunk_id"] == "mat_1_custom_chunk"
    assert payload["figure_candidate_detail"]["asset_path"] == "figure_assets/extracted/search-ref/p0003_img002.png"
    assert payload["metadata"]["figure_candidate_detail"]["asset_path"] == "figure_assets/extracted/search-ref/p0003_img002.png"
    assert payload["source_title"] == "Search Ref Source"
    assert payload["source_path"] == "papers/search-ref.pdf"
    assert payload["material_id"] == "mat_1"
    assert payload["chunk_id"] == "mat_1_custom_chunk"
    assert payload["page"] == 3
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


def test_agent_bridge_resource_reader_preserves_custom_chunk_id_after_ensure(monkeypatch: Any) -> None:
    """Bounded chunk reads must not rewrite evidence-pack ref identities."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    import routers.resources_router as resources_router

    project_id = "proj_custom_chunk_identity"
    resources_router._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_1": {
                "title": "Custom Chunk Identity.pdf",
                "content": "Doc-store content should not force a new chunk id.",
                "source_relative_path": "papers/custom-chunk-identity.pdf",
            }
        },
    )
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_1": [
                {
                    "chunk_id": "alsi10mg_defects_chunk_0",
                    "material_id": "mat_1",
                    "title": "Custom Chunk Identity",
                    "content": "AlSi10Mg lack-of-fusion pores remain readable through the original ref.",
                    "page": 4,
                    "chunk_type": "body",
                    "source_relative_path": "papers/custom-chunk-identity.pdf",
                }
            ]
        },
    )

    response = client.get(
        "/api/agent-bridge/resource/chunk:alsi10mg_defects_chunk_0",
        headers=_capability_headers(),
        params={"project_id": project_id, "max_chars": 200},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ref_id"] == "chunk:alsi10mg_defects_chunk_0"
    assert payload["chunk_id"] == "alsi10mg_defects_chunk_0"
    assert payload["metadata"]["chunk_id"] == "alsi10mg_defects_chunk_0"
    assert "lack-of-fusion pores" in payload["content"]


def test_agent_bridge_resource_reader_uses_doc_store_source_when_chunk_lacks_it(monkeypatch: Any) -> None:
    """Legacy chunks should remain traceable through doc-store source metadata."""

    _isolated_runtime(monkeypatch)
    client = _client(monkeypatch)

    import routers.resources_router as resources_router

    project_id = "proj_resource_doc_store_source"
    resources_router._save_doc_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_legacy": {
                "title": "Doc Store Source Paper.pdf",
                "content": "Legacy doc content",
                "source_relative_path": "1220/Doc Store Source Paper.pdf",
            }
        },
    )
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_legacy": [
                {
                    "chunk_id": "mat_legacy_chunk_7",
                    "material_id": "mat_legacy",
                    "content": "Legacy chunk without embedded source path.",
                    "page": 9,
                    "chunk_type": "body",
                }
            ]
        },
    )

    response = client.get(
        "/api/agent-bridge/resource/chunk:mat_legacy_chunk_7",
        headers=_capability_headers(),
        params={"project_id": project_id, "max_chars": 120},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_title"] == "Doc Store Source Paper.pdf"
    assert payload["source_path"] == "1220/Doc Store Source Paper.pdf"
    assert payload["metadata"]["source_relative_path"] == "1220/Doc Store Source Paper.pdf"
    assert payload["material_id"] == "mat_legacy"
    assert payload["chunk_id"] == "mat_legacy_chunk_7"
    assert payload["page"] == 9


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
