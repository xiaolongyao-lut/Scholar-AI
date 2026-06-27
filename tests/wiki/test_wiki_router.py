from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from literature_assistant.core.routers import knowledge_router, wiki_router
from literature_assistant.core.wiki.page_store import WikiPageStore, render_page
from literature_assistant.core.wiki.query import WikiQueryIndex, build_source_manifest, build_wiki_index
from literature_assistant.core.wiki.review_queue import ReviewItemKind, ReviewQueue, make_review_item
from literature_assistant.core.wiki.service import WikiService
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


def make_wiki_agent_client(monkeypatch, tmp_path: Path, *, enabled: bool) -> TestClient:
    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(wiki_router, "wiki_enabled", lambda: enabled)
    monkeypatch.setattr(wiki_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    monkeypatch.setattr(wiki_router, "wiki_graph_path", lambda: runtime_root / "graph.json")
    monkeypatch.setattr(wiki_router, "wiki_graph_db_path", lambda: runtime_root / "graph.db")
    monkeypatch.setattr(wiki_router, "wiki_query_index_path", lambda: runtime_root / "wiki_query_index.db")
    monkeypatch.setattr(wiki_router, "wiki_review_queue_path", lambda: runtime_root / "review_queue.jsonl")
    monkeypatch.setattr(wiki_router, "wiki_runtime_db_path", lambda: runtime_root / "wiki.db")

    from literature_assistant.core.routers import agent_bridge_router

    monkeypatch.setattr(agent_bridge_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    app = FastAPI()
    app.include_router(wiki_router.router)
    app.include_router(agent_bridge_router.router)
    return TestClient(app)


def make_wiki_knowledge_client(monkeypatch, tmp_path: Path, *, enabled: bool) -> TestClient:
    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(wiki_router, "wiki_enabled", lambda: enabled)
    monkeypatch.setattr(wiki_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    monkeypatch.setattr(wiki_router, "wiki_graph_path", lambda: runtime_root / "graph.json")
    monkeypatch.setattr(wiki_router, "wiki_graph_db_path", lambda: runtime_root / "graph.db")
    monkeypatch.setattr(wiki_router, "wiki_query_index_path", lambda: runtime_root / "wiki_query_index.db")
    monkeypatch.setattr(wiki_router, "wiki_review_queue_path", lambda: runtime_root / "review_queue.jsonl")
    monkeypatch.setattr(wiki_router, "wiki_runtime_db_path", lambda: runtime_root / "wiki.db")

    from literature_assistant.core.routers import agent_bridge_router

    monkeypatch.setattr(agent_bridge_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    monkeypatch.setattr(knowledge_router._agent_bridge_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    app = FastAPI()
    app.include_router(wiki_router.router)
    app.include_router(agent_bridge_router.router)
    app.include_router(knowledge_router.router)
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
    assert payload["integrity_status"] == "missing_index"
    assert len(payload["source_manifest_hash"]) == 64
    assert payload["indexed_source_manifest_hash"] == "unknown"
    assert payload["source_page_count"] == 1
    assert payload["indexed_page_count"] == 0
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
    assert payload["integrity_status"] == "aligned"
    assert len(payload["source_manifest_hash"]) == 64
    assert payload["source_manifest_hash"] == payload["indexed_source_manifest_hash"]
    assert payload["indexed_page_count"] == 1
    assert payload["source_page_count"] == 1


def test_status_marks_stale_when_source_hash_changes_without_rebuild(monkeypatch, tmp_path: Path) -> None:
    page_path = Path("concepts/alpha.md")
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            page_path,
            {"id": "concepts/alpha", "kind": "concept", "title": "Alpha", "status": "draft"},
            "Alpha body.",
        )
    )
    query_index = WikiQueryIndex(tmp_path / "runtime" / "wiki_query_index.db")
    build_wiki_index(page_store, query_index)
    query_index.close()
    page_store.write_rendered(
        render_page(
            page_path,
            {"id": "concepts/alpha", "kind": "concept", "title": "Alpha", "status": "draft"},
            "Alpha body changed after indexing.",
        )
    )

    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["page_count"] == 1
    assert payload["indexed_page_count"] == 1
    assert payload["stale"] is True
    assert payload["integrity_status"] == "source_hash_mismatch"
    assert payload["source_manifest_hash"] != payload["indexed_source_manifest_hash"]
    assert payload["manifest_drilldown"]["mismatched_count"] == 1
    assert payload["manifest_drilldown"]["mismatched_pages"][0]["page_path"] == "concepts/alpha.md"
    assert any("source manifest hash differs" in warning for warning in payload["warnings"])


def test_status_manifest_drilldown_is_bounded_and_redacts_extra_pages(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    for relative_path, body in {
        "concepts/a.md": "Alpha body.",
        "concepts/b.md": "Beta body.",
        "concepts/c.md": "Gamma body.",
    }.items():
        page_path = Path(relative_path)
        page_store.write_rendered(
            render_page(
                page_path,
                {
                    "id": page_path.with_suffix("").as_posix(),
                    "kind": "concept",
                    "title": page_path.stem.title(),
                    "status": "draft",
                },
                body,
            )
        )
    query_index = WikiQueryIndex(tmp_path / "runtime" / "wiki_query_index.db")
    build_wiki_index(page_store, query_index)
    query_index.close()
    page_store.write_rendered(
        render_page(
            Path("concepts/a.md"),
            {"id": "concepts/a", "kind": "concept", "title": "A", "status": "draft"},
            "Alpha body changed after indexing.",
        )
    )
    page_store.resolve(Path("concepts/b.md")).unlink()
    page_store.write_rendered(
        render_page(
            Path("concepts/d.md"),
            {"id": "concepts/d", "kind": "concept", "title": "D", "status": "draft"},
            "Delta body added after indexing.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/status")

    assert response.status_code == 200
    payload = response.json()
    drilldown = payload["manifest_drilldown"]
    assert drilldown["schema_version"] == "scholar-ai-wiki-manifest-drilldown/v1"
    assert drilldown["missing_count"] == 1
    assert drilldown["extra_count"] == 1
    assert drilldown["mismatched_count"] == 1
    assert drilldown["missing_pages"][0]["page_path"] == "concepts/d.md"
    assert drilldown["mismatched_pages"][0]["page_path"] == "concepts/a.md"
    assert drilldown["extra_pages"][0] == {
        "kind": "extra",
        "page_path": "<redacted>",
        "source_hash": None,
        "indexed_hash": None,
        "redacted": True,
    }
    assert str(tmp_path) not in json.dumps(payload, ensure_ascii=False)


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


def test_categories_tree_uses_frontmatter_and_page_kind(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    page_store = WikiPageStore(wiki_root)
    page_store.write_rendered(
        render_page(
            Path("concepts/alpha.md"),
            {
                "id": "concepts/alpha",
                "kind": "concept",
                "title": "Alpha",
                "status": "draft",
                "categories": ["Methods", "Embedding"],
            },
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

    response = client.get("/api/wiki/categories")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    roots = {category["key"]: category for category in payload["categories"]}
    assert roots["methods"]["label"] == "Methods"
    assert roots["methods"]["page_count"] == 1
    assert roots["methods"]["children"][0]["key"] == "methods/embedding"
    assert roots["methods"]["children"][0]["pages"][0]["path"] == "concepts/alpha.md"
    assert roots["claim"]["pages"][0]["path"] == "claims/beta.md"


def test_categories_tree_respects_page_permissions(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    page_store = WikiPageStore(wiki_root)
    page_store.write_rendered(
        render_page(
            Path("concepts/private.md"),
            {
                "id": "concepts/private",
                "kind": "concept",
                "title": "Private",
                "status": "draft",
                "category": "Hidden",
                "extra": {"permissions": {"owner": "owner-a", "visibility": "private", "shared_with": []}},
            },
            "Private body.",
        )
    )
    page_store.write_rendered(
        render_page(
            Path("concepts/public.md"),
            {
                "id": "concepts/public",
                "kind": "concept",
                "title": "Public",
                "status": "draft",
                "category": "Visible",
                "extra": {"permissions": {"owner": "owner-a", "visibility": "public", "shared_with": []}},
            },
            "Public body.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/categories", params={"user_id": "reader-b"})

    assert response.status_code == 200
    category_keys = [category["key"] for category in response.json()["categories"]]
    assert category_keys == ["visible"]


def test_tags_index_uses_frontmatter_tags_and_labels(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            Path("concepts/alpha.md"),
            {
                "id": "concepts/alpha",
                "kind": "concept",
                "title": "Alpha",
                "status": "draft",
                "tags": ["Embedding", "RAG"],
                "labels": ["method"],
            },
            "Alpha body.",
        )
    )
    page_store.write_rendered(
        render_page(
            Path("claims/beta.md"),
            {
                "id": "claims/beta",
                "kind": "claim",
                "title": "Beta",
                "status": "draft",
                "category": "RAG",
            },
            "Beta body.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/tags")

    assert response.status_code == 200
    tags = {tag["key"]: tag for tag in response.json()["tags"]}
    assert sorted(tags) == ["embedding", "method", "rag"]
    assert tags["rag"]["page_count"] == 2
    assert sorted(page["path"] for page in tags["rag"]["pages"]) == ["claims/beta.md", "concepts/alpha.md"]


def test_tags_index_respects_permissions(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            Path("concepts/private.md"),
            {
                "id": "concepts/private",
                "kind": "concept",
                "title": "Private",
                "status": "draft",
                "tags": ["hidden"],
                "extra": {"permissions": {"owner": "owner-a", "visibility": "private", "shared_with": []}},
            },
            "Private body.",
        )
    )
    page_store.write_rendered(
        render_page(
            Path("concepts/public.md"),
            {
                "id": "concepts/public",
                "kind": "concept",
                "title": "Public",
                "status": "draft",
                "tags": ["visible"],
                "extra": {"permissions": {"owner": "owner-a", "visibility": "public", "shared_with": []}},
            },
            "Public body.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/tags", params={"user_id": "reader-b"})

    assert response.status_code == 200
    assert [tag["key"] for tag in response.json()["tags"]] == ["visible"]


def test_page_versions_endpoint_returns_history(monkeypatch, tmp_path: Path) -> None:
    from literature_assistant.core.wiki.service import WikiService

    store = WikiPageStore(tmp_path / "wiki")
    service = WikiService(store)
    page = service.create_page(title="History", kind="synthesis", body="Original")
    service.update_page(page.stable_slug, body="Updated")
    monkeypatch.setattr("wiki.service.get_wiki_service", lambda: service)
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get(f"/api/wiki/pages/{page.stable_slug}/versions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["slug"] == page.stable_slug
    assert [version["action"] for version in payload["versions"]] == ["create", "update"]


def test_page_versions_endpoint_respects_permissions(monkeypatch, tmp_path: Path) -> None:
    from literature_assistant.core.wiki.permissions import WikiPagePermissions, WikiPageVisibility, set_permissions
    from literature_assistant.core.wiki.service import WikiService

    store = WikiPageStore(tmp_path / "wiki")
    service = WikiService(store)
    page = service.create_page(
        title="Private History",
        kind="synthesis",
        body="Private",
        extra=set_permissions({}, WikiPagePermissions(owner="owner-a", visibility=WikiPageVisibility.PRIVATE)),
    )
    monkeypatch.setattr("wiki.service.get_wiki_service", lambda: service)
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get(f"/api/wiki/pages/{page.stable_slug}/versions", params={"user_id": "reader-b"})

    assert response.status_code == 403


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
    wiki_root = tmp_path / "wiki"
    page = WikiService(WikiPageStore(wiki_root, create=True)).create_page(
        title="Draft",
        kind="concept",
        body="Needs review.",
        status="draft",
    )
    import sys

    core_path = Path(__file__).resolve().parents[2] / "literature_assistant" / "core"
    if str(core_path) not in sys.path:
        sys.path.insert(0, str(core_path))
    import wiki.service as flat_wiki_service  # type: ignore[import-not-found]

    monkeypatch.setattr(flat_wiki_service, "get_wiki_service", lambda: WikiService(WikiPageStore(wiki_root, create=True)))
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    queue = ReviewQueue(queue_path)
    queue.append(
        make_review_item(
            item_id="draft-1",
            kind=ReviewItemKind.draft,
            title="Draft",
            page_path=f"concept/{page.stable_slug}.md",
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


def test_search_returns_wiki_knowledge_ref_readable_as_agent_resource(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    page_store = WikiPageStore(wiki_root)
    body = (
        "Laser welding evidence enters the Scholar AI wiki knowledge pipeline. "
        "This generated page is long enough to prove bounded agent loading, "
        "cursor continuation, and search-to-resource traceability without relying "
        "on project material chunks or stale evidence-ref payloads."
    )
    page_store.write_rendered(
        render_page(
            Path("concepts/laser-welding.md"),
            {
                "id": "concepts/laser-welding",
                "kind": "concept",
                "title": "Laser Welding",
                "status": "final",
            },
            body,
        )
    )
    query_index = WikiQueryIndex(runtime_root / "wiki_query_index.db")
    build_wiki_index(page_store, query_index)
    query_index.close()
    client = make_wiki_agent_client(monkeypatch, tmp_path, enabled=True)

    search_response = client.post("/api/wiki/search", json={"query": "laser welding"})

    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload["enabled"] is True
    assert search_payload["fallback_required"] is False
    assert search_payload["evidence_refs"]
    hit = search_payload["evidence_refs"][0]
    assert hit["schema_version"] == "scholar-ai-wiki-knowledge-ref/v1"
    assert hit["ref_id"] == "wiki:concepts/laser-welding.md"
    assert hit["chunk_id"].startswith("wiki:concepts/laser-welding.md#")
    assert hit["source_path"] == "concepts/laser-welding.md"
    assert len(hit["source_hash"]) == 64
    assert len(hit["content_hash"]) == 64
    assert hit["span_start"] == 0
    assert hit["span_end"] > hit["span_start"]
    assert hit["read_endpoint"] == "/api/agent-bridge/resource/wiki:concepts/laser-welding.md"
    assert hit["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-wiki-knowledge-ref/v1"
    assert hit["metadata"]["ref_id"] == hit["ref_id"]
    assert hit["metadata"]["chunk_id"] == hit["chunk_id"]
    assert hit["metadata"]["resource_kind"] == "chunk"
    assert hit["metadata"]["page_path"] == "concepts/laser-welding.md"
    assert hit["metadata"]["source_path"] == "concepts/laser-welding.md"
    assert hit["metadata"]["source"] == "wiki"
    assert hit["metadata"]["source_type"] == "wiki"
    assert hit["metadata"]["retrieval_source"] == "wiki_fts"
    assert hit["metadata"]["source_hash"] == hit["source_hash"]
    assert hit["metadata"]["content_hash"] == hit["content_hash"]
    assert hit["metadata"]["span_start"] == hit["span_start"]
    assert hit["metadata"]["span_end"] == hit["span_end"]
    assert hit["metadata"]["read_endpoint"] == hit["read_endpoint"]
    assert hit["metadata"]["bounded"] is True
    assert "content" not in hit

    resource_response = client.get(hit["read_endpoint"], params={"max_chars": 120})

    assert resource_response.status_code == 200
    resource_payload = resource_response.json()
    assert resource_payload["ref_id"] == hit["ref_id"]
    assert resource_payload["kind"] == "wiki"
    assert resource_payload["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-wiki-knowledge-ref/v1"
    assert resource_payload["metadata"]["ref_id"] == hit["ref_id"]
    assert resource_payload["metadata"]["chunk_id"] == hit["chunk_id"]
    assert resource_payload["metadata"]["resource_kind"] == "chunk"
    assert resource_payload["metadata"]["page_path"] == "concepts/laser-welding.md"
    assert resource_payload["metadata"]["source_path"] == "concepts/laser-welding.md"
    assert resource_payload["metadata"]["source"] == "wiki"
    assert resource_payload["metadata"]["source_type"] == "wiki"
    assert resource_payload["metadata"]["source_hash"] == hit["source_hash"]
    assert resource_payload["metadata"]["content_hash"] == hit["content_hash"]
    assert resource_payload["metadata"]["span_start"] == 0
    assert resource_payload["metadata"]["span_end"] == hit["span_end"]
    assert resource_payload["metadata"]["span_end"] == resource_payload["total_chars"]
    assert resource_payload["metadata"]["read_endpoint"] == hit["read_endpoint"]
    assert resource_payload["metadata"]["returned_chars"] <= 120
    assert "Laser welding evidence" in resource_payload["content"]
    assert resource_payload["truncated"] is True
    assert resource_payload["next_cursor"] is not None


def test_wiki_source_rebuild_search_resource_and_context_receipt_chain(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    page_store = WikiPageStore(wiki_root)
    page_path = Path("concepts/context-receipt.md")
    first_body = (
        "First wiki context receipt version explains baseline provenance. "
        "This text is intentionally long enough to exercise bounded reads "
        "without proving the later source-edit rebuild path by accident."
    )
    second_body = (
        "Second wiki context receipt version proves source edits rebuild into "
        "search results, agent resources, and bounded model context receipts."
    )

    page_store.write_rendered(
        render_page(
            page_path,
            {
                "id": "concepts/context-receipt",
                "kind": "concept",
                "title": "Context Receipt",
                "status": "final",
            },
            first_body,
        )
    )
    query_index = WikiQueryIndex(runtime_root / "wiki_query_index.db")
    build_wiki_index(page_store, query_index)
    first_status = query_index.get_status(page_store)
    first_manifest = build_source_manifest(page_store)
    query_index.close()
    client = make_wiki_knowledge_client(monkeypatch, tmp_path, enabled=True)

    first_search = client.post("/api/wiki/search", json={"query": "baseline provenance"})

    assert first_search.status_code == 200
    first_hit = first_search.json()["evidence_refs"][0]
    assert first_hit["ref_id"] == "wiki:concepts/context-receipt.md"
    assert first_hit["source_hash"] == first_manifest.entries[0].split(":", maxsplit=1)[1]
    assert first_status.source_manifest_hash == first_status.indexed_source_manifest_hash

    page_store.write_rendered(
        render_page(
            page_path,
            {
                "id": "concepts/context-receipt",
                "kind": "concept",
                "title": "Context Receipt",
                "status": "final",
            },
            second_body,
        )
    )
    query_index = WikiQueryIndex(runtime_root / "wiki_query_index.db")
    build_wiki_index(page_store, query_index)
    second_status = query_index.get_status(page_store)
    second_manifest = build_source_manifest(page_store)
    query_index.close()

    assert first_status.indexed_source_manifest_hash != second_status.indexed_source_manifest_hash
    assert second_status.source_manifest_hash == second_status.indexed_source_manifest_hash
    assert second_status.integrity_status == "aligned"
    assert second_manifest.entries[0].split(":", maxsplit=1)[1] != first_hit["source_hash"]

    second_search = client.post("/api/wiki/search", json={"query": "bounded model context receipts"})

    assert second_search.status_code == 200
    second_payload = second_search.json()
    assert second_payload["enabled"] is True
    assert second_payload["fallback_required"] is False
    second_hit = second_payload["evidence_refs"][0]
    assert second_hit["ref_id"] == first_hit["ref_id"]
    assert second_hit["read_endpoint"] == "/api/agent-bridge/resource/wiki:concepts/context-receipt.md"
    assert second_hit["source_hash"] == second_manifest.entries[0].split(":", maxsplit=1)[1]
    assert second_hit["source_hash"] != first_hit["source_hash"]
    assert second_hit["content_hash"] != first_hit["content_hash"]
    assert second_hit["chunk_id"] != first_hit["chunk_id"]

    resource_response = client.get(second_hit["read_endpoint"], params={"max_chars": 400})

    assert resource_response.status_code == 200
    resource_payload = resource_response.json()
    assert second_body in resource_payload["content"]
    assert first_body not in resource_payload["content"]
    assert resource_payload["metadata"]["source_hash"] == second_hit["source_hash"]
    assert resource_payload["metadata"]["content_hash"] == second_hit["content_hash"]
    assert resource_payload["metadata"]["chunk_id"] == second_hit["chunk_id"]

    receipt_response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [second_hit["ref_id"]],
            "prompt_name": "wiki_rebuild_context_receipt",
            "max_chars_per_ref": 400,
        },
    )

    assert receipt_response.status_code == 200
    receipt_payload = receipt_response.json()
    assert receipt_payload["schema_version"] == "scholar-ai-knowledge-context-receipt/v1"
    assert receipt_payload["prompt_name"] == "wiki_rebuild_context_receipt"
    assert len(receipt_payload["prompt_hash"]) == 64
    assert len(receipt_payload["assembled_context_hash"]) == 64
    assert second_body in receipt_payload["assembled_context_preview"]
    assert first_body not in receipt_payload["assembled_context_preview"]
    assert receipt_payload["provenance"]["resource_reader"] == "literature_assistant.core.routers.agent_bridge_router"
    assert receipt_payload["provenance"]["mcp_tool"] == "literature.knowledge_context_receipt"
    receipts = receipt_payload["resource_read_receipts"]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["ref_id"] == second_hit["ref_id"]
    assert receipt["kind"] == "wiki"
    assert receipt["read_endpoint"] == second_hit["read_endpoint"]
    assert receipt["source_hash"] == second_hit["source_hash"]
    assert receipt["package_content_hash"] == second_hit["content_hash"]
    assert receipt["source_path"] == second_hit["source_path"]
    assert receipt["span_start"] == second_hit["span_start"]
    assert receipt["span_end"] == second_hit["span_end"]
    assert receipt["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-wiki-knowledge-ref/v1"
    assert receipt["metadata"]["chunk_id"] == second_hit["chunk_id"]


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


def test_compile_write_requires_explicit_allow_write(monkeypatch, tmp_path: Path) -> None:
    registry = WikiRegistry(tmp_path / "runtime" / "wiki.db")
    source = SourceRecord("paper-source-002", "paper", "Write Guard Paper", "hash-write", Path("/paper.pdf"))
    registry.upsert_source(source, now_iso=utc_now_iso())
    registry.register_chunks(
        source.source_id,
        source.source_hash,
        [ChunkInput(text="guarded write chunk", chunk_index=0, page="1")],
        now_iso=utc_now_iso(),
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/compile",
        json={"dry_run": False, "source_id": "paper-source-002"},
    )

    assert response.status_code == 400
    assert "allow_write=true" in response.text


def test_compile_write_persists_planned_source_pages(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    registry = WikiRegistry(tmp_path / "runtime" / "wiki.db")
    source = SourceRecord("paper-source-003", "paper", "Write Paper", "hash-write-3", Path("/paper.pdf"))
    registry.upsert_source(source, now_iso=utc_now_iso())
    registry.register_chunks(
        source.source_id,
        source.source_hash,
        [ChunkInput(text="writeable wiki chunk", chunk_index=0, page="1")],
        now_iso=utc_now_iso(),
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/compile",
        json={"dry_run": False, "allow_write": True, "source_id": "paper-source-003"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["dry_run"] is False
    assert payload["created"] == 1
    assert payload["written_paths"] == ["sources/write-paper.md"]
    assert payload["planned_paths"] == ["sources/write-paper.md", "papers/write-paper.md"]
    assert (wiki_root / "sources" / "write-paper.md").exists()


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
    assert "/api/wiki/categories" in schema["paths"]
    assert "/api/wiki/tags" in schema["paths"]
    assert "/api/wiki/pages/{slug}/versions" in schema["paths"]
    assert "/api/wiki/pages" in schema["paths"]
    assert "/api/wiki/doctor" in schema["paths"]

    status_operation = schema["paths"]["/api/wiki/status"]["get"]
    assert status_operation["tags"] == ["Wiki"]
    assert status_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/WikiStatusResponse"
    }

    status_schema = schema["components"]["schemas"]["WikiStatusResponse"]
    assert set(status_schema["properties"]) >= {
        "enabled",
        "page_count",
        "stale",
        "integrity_status",
        "index_hash",
        "source_manifest_hash",
        "indexed_source_manifest_hash",
        "indexed_page_count",
        "source_page_count",
        "manifest_drilldown",
        "paths",
    }
    drilldown_schema = schema["components"]["schemas"]["WikiManifestDrilldownPayload"]
    assert set(drilldown_schema["properties"]) >= {
        "schema_version",
        "status",
        "hash_algorithm",
        "missing_count",
        "extra_count",
        "mismatched_count",
        "missing_pages",
        "extra_pages",
        "mismatched_pages",
    }

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
    assert set(compile_request_schema["properties"]) >= {"dry_run", "allow_write", "source_id", "project_id"}
    compile_response_schema = schema["components"]["schemas"]["WikiCompileResponse"]
    assert set(compile_response_schema["properties"]) >= {"budget_summary", "budget_checks", "created", "skipped"}

    query_request_schema = schema["components"]["schemas"]["WikiQueryRequest"]
    assert set(query_request_schema["properties"]) >= {"query", "wiki_first", "save", "debug"}

    doctor_operation = schema["paths"]["/api/wiki/doctor"]["get"]
    assert doctor_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/WikiDoctorResponse"
    }
