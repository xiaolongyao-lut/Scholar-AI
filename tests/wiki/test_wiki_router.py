from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from literature_assistant.core.routers import wiki_router
from literature_assistant.core.wiki.page_store import WikiPageStore, render_page
from literature_assistant.core.wiki.query import WikiQueryIndex, build_wiki_index
from literature_assistant.core.wiki.review_queue import ReviewItemKind, ReviewQueue, make_review_item
from literature_assistant.core.wiki.source_registry import ChunkInput, SourceRecord, WikiRegistry, utc_now_iso


def make_client(monkeypatch, tmp_path: Path, *, enabled: bool) -> TestClient:
    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(wiki_router, "wiki_enabled", lambda: enabled)
    monkeypatch.setattr(wiki_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    monkeypatch.setattr(wiki_router, "wiki_graph_path", lambda: runtime_root / "graph.json")
    monkeypatch.setattr(wiki_router, "wiki_graph_db_path", lambda: runtime_root / "graph.db")
    monkeypatch.setattr(wiki_router, "wiki_query_index_path", lambda: runtime_root / "wiki_query_index.db")
    monkeypatch.setattr(wiki_router, "wiki_review_queue_path", lambda: runtime_root / "review_queue.jsonl")
    monkeypatch.setattr(wiki_router, "wiki_runtime_db_path", lambda: runtime_root / "wiki.db")
    app = FastAPI()
    app.include_router(wiki_router.router)
    return TestClient(app)


def test_status_default_off_returns_disabled_contract(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path, enabled=False)

    response = client.get("/api/wiki/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["page_count"] == 0
    assert payload["stale"] is False
    assert payload["warnings"]
    assert payload["paths"]["wiki_root"].startswith("<external>/") or payload["paths"]["wiki_root"].startswith("workspace_artifacts/")


def test_status_marks_stale_when_pages_exist_without_query_index(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            Path("concepts/alpha.md"),
            {"id": "concepts/alpha", "kind": "concept", "title": "Alpha", "status": "draft"},
            "Alpha body.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["page_count"] == 1
    assert payload["query_index_exists"] is False
    assert payload["stale"] is True
    assert payload["paths"]["wiki_root"].startswith("<external>/")
    assert payload["paths"]["graph_json"].startswith("<external>/")


def test_status_clears_stale_when_query_index_is_aligned(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            Path("concepts/alpha.md"),
            {"id": "concepts/alpha", "kind": "concept", "title": "Alpha", "status": "draft"},
            "Alpha body.",
        )
    )
    query_index = WikiQueryIndex(tmp_path / "runtime" / "wiki_query_index.db")
    build_wiki_index(page_store, query_index)
    query_index.close()

    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["page_count"] == 1
    assert payload["query_index_exists"] is True
    assert payload["stale"] is False


def test_pages_list_and_read_when_enabled(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    page_store = WikiPageStore(wiki_root)
    page_store.write_rendered(
        render_page(
            Path("concepts/alpha.md"),
            {"id": "concepts/alpha", "kind": "concept", "title": "Alpha", "status": "draft"},
            "Alpha body.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    list_response = client.get("/api/wiki/pages")
    read_response = client.get("/api/wiki/pages/concepts/alpha")

    assert list_response.status_code == 200
    assert list_response.json()["pages"][0]["title"] == "Alpha"
    assert read_response.status_code == 200
    assert read_response.json()["frontmatter"]["id"] == "concepts/alpha"


def test_pages_filter_by_kind_and_status(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    page_store = WikiPageStore(wiki_root)
    page_store.write_rendered(
        render_page(
            Path("concepts/alpha.md"),
            {"id": "concepts/alpha", "kind": "concept", "title": "Alpha", "status": "draft"},
            "Alpha body.",
        )
    )
    page_store.write_rendered(
        render_page(
            Path("claims/beta.md"),
            {"id": "claims/beta", "kind": "claim", "title": "Beta", "status": "final"},
            "Beta body.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/pages", params={"kind": "claims", "status": "final"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert [page["path"] for page in payload["pages"]] == ["claims/beta.md"]


def test_pages_reject_invalid_kind_filter(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/pages", params={"kind": "../claims"})

    assert response.status_code == 400
    assert "kind must be a simple lowercase token" in response.text


def test_page_read_rejects_escape_path(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/pages/%2E%2E/secrets.txt")

    assert response.status_code == 400
    assert "page_path must stay inside the wiki root" in response.text


def test_doctor_and_graph_contract_when_enabled(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            Path("concepts/alpha.md"),
            {"id": "concepts/alpha", "kind": "concept", "title": "Alpha", "status": "draft"},
            "Alpha links [[concepts/beta]].",
        )
    )
    page_store.write_rendered(
        render_page(
            Path("concepts/beta.md"),
            {"id": "concepts/beta", "kind": "concept", "title": "Beta", "status": "draft"},
            "Beta body.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    doctor_response = client.get("/api/wiki/doctor")
    graph_response = client.get("/api/wiki/graph")

    assert doctor_response.status_code == 200
    assert doctor_response.json()["report"]["checks"]
    assert graph_response.status_code == 200
    assert graph_response.json()["graph"]["node_count"] == 2


def test_review_approve_and_reject_contract(monkeypatch, tmp_path: Path) -> None:
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    queue = ReviewQueue(queue_path)
    queue.append(
        make_review_item(
            item_id="draft-1",
            kind=ReviewItemKind.draft,
            title="Draft",
            page_path="concepts/draft.md",
            summary="Needs review.",
        )
    )
    queue.append(
        make_review_item(
            item_id="warn-1",
            kind=ReviewItemKind.warning,
            title="Warning",
            page_path="claims/warn.md",
            summary="Needs citation.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    list_response = client.get("/api/wiki/review")
    approve_response = client.post("/api/wiki/review/draft-1/approve", json={"reason": "ok", "decided_by": "tester"})
    reject_response = client.post(
        "/api/wiki/review/warn-1/reject",
        json={"reason": "missing quote", "decided_by": "tester"},
    )

    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == 2
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"
    assert reject_response.status_code == 200
    assert reject_response.json()["decision"]["reason"] == "missing quote"


def test_review_list_rejects_invalid_status_filter(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/review", params={"status": "APPROVED!"})

    assert response.status_code == 400
    assert "status must be a simple lowercase token" in response.text


def test_compile_and_query_contracts_remain_default_off(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path, enabled=False)

    compile_response = client.post("/api/wiki/compile", json={"dry_run": True})
    query_response = client.post("/api/wiki/query", json={"query": "laser welding"})

    assert compile_response.status_code == 200
    assert compile_response.json()["enabled"] is False
    assert query_response.status_code == 200
    assert query_response.json()["fallback_required"] is True


def test_compile_contract_accepts_source_and_project_ids_without_writing(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    registry = WikiRegistry(tmp_path / "runtime" / "wiki.db")
    source = SourceRecord("paper-source-001", "paper", "Compile Cost Paper", "hash-cost", Path("/paper.pdf"))
    registry.upsert_source(source, now_iso=utc_now_iso())
    registry.register_chunks(
        source.source_id,
        source.source_hash,
        [ChunkInput(text="abcd efgh", chunk_index=0, page="1")],
        now_iso=utc_now_iso(),
    )
    monkeypatch.setenv("LITERATURE_ASSISTANT_WIKI_COMPILE_INPUT_USD_PER_1M_TOKENS", "1")
    monkeypatch.setenv("LITERATURE_ASSISTANT_WIKI_COMPILE_OUTPUT_USD_PER_1M_TOKENS", "2")
    monkeypatch.setenv("LITERATURE_ASSISTANT_WIKI_COMPILE_ESTIMATED_OUTPUT_TOKENS", "1000")
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/compile",
        json={
            "dry_run": True,
            "source_id": "paper-source-001",
            "project_id": "project-alpha",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["dry_run"] is True
    assert payload["created"] == 1
    assert payload["written_paths"] == []
    assert payload["planned_paths"] == ["sources/compile-cost-paper.md", "papers/compile-cost-paper.md"]
    assert payload["budget_summary"]["input_tokens"] == 2
    assert payload["budget_summary"]["output_tokens"] == 1000
    assert payload["budget_summary"]["estimated_cost_usd"] == 0.002002
    assert payload["budget_checks"][0]["source_id"] == "paper-source-001"
    assert not wiki_root.exists()


def test_compile_contract_rejects_invalid_source_id(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/compile",
        json={
            "dry_run": True,
            "source_id": "paper source 001",
        },
    )

    assert response.status_code == 400
    assert "source_id contains unsupported characters" in response.text


def test_query_contract_accepts_wiki_first_and_debug_flags(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/query",
        json={
            "query": "laser welding",
            "wiki_first": True,
            "debug": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["fallback_required"] is True
    assert payload["warnings"]


def test_query_save_requires_explicit_service_integration(monkeypatch, tmp_path: Path) -> None:
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/query",
        json={
            "query": "laser welding",
            "save": True,
        },
    )

    assert response.status_code == 400
    assert "Saved exploration API requires explicit service integration" in response.text


def test_wiki_routes_are_registered_in_full_app_openapi() -> None:
    from python_adapter_server import app as full_app

    full_app.openapi_schema = None
    schema = full_app.openapi()

    assert any(tag["name"] == "Wiki" for tag in schema["tags"])
    assert "/api/wiki/status" in schema["paths"]
    assert "/api/wiki/compile" in schema["paths"]
    assert "/api/wiki/query" in schema["paths"]
    assert "/api/wiki/pages" in schema["paths"]
    assert "/api/wiki/doctor" in schema["paths"]

    status_operation = schema["paths"]["/api/wiki/status"]["get"]
    assert status_operation["tags"] == ["Wiki"]
    assert status_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/WikiStatusResponse"
    }

    status_schema = schema["components"]["schemas"]["WikiStatusResponse"]
    assert set(status_schema["properties"]) >= {"enabled", "page_count", "stale", "paths"}

    compile_operation = schema["paths"]["/api/wiki/compile"]["post"]
    assert compile_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/WikiCompileRequest"
    }
    assert compile_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/WikiCompileResponse"
    }

    query_operation = schema["paths"]["/api/wiki/query"]["post"]
    assert query_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/WikiQueryRequest"
    }
    assert query_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/WikiQueryResponse"
    }

    compile_request_schema = schema["components"]["schemas"]["WikiCompileRequest"]
    assert set(compile_request_schema["properties"]) >= {"dry_run", "source_id", "project_id"}
    compile_response_schema = schema["components"]["schemas"]["WikiCompileResponse"]
    assert set(compile_response_schema["properties"]) >= {"budget_summary", "budget_checks", "created", "skipped"}

    query_request_schema = schema["components"]["schemas"]["WikiQueryRequest"]
    assert set(query_request_schema["properties"]) >= {"query", "wiki_first", "save", "debug"}

    doctor_operation = schema["paths"]["/api/wiki/doctor"]["get"]
    assert doctor_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/WikiDoctorResponse"
    }
