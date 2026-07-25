from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from literature_assistant.core.routers import knowledge_router, wiki_router
from literature_assistant.core.wiki import models as wiki_models
from literature_assistant.core.wiki import page_store as wiki_page_store_module
from literature_assistant.core.wiki import review_queue as wiki_review_queue_module
from literature_assistant.core.wiki import service as wiki_service_module
from literature_assistant.core.wiki.models import WikiPage
from literature_assistant.core.wiki.page_store import WikiPageStore, render_page
from literature_assistant.core.wiki.query import WikiQueryIndex, build_source_manifest, build_wiki_index
from literature_assistant.core.wiki.review_queue import (
    ReviewItem,
    ReviewItemKind,
    ReviewQueue,
    make_annotation_note_review_target,
    make_review_item,
    make_wiki_page_revision_review_target,
)
from literature_assistant.core.wiki.service import WikiService
from literature_assistant.core.wiki.source_registry import (
    ChunkInput,
    SourceRecord,
    WikiRegistry,
    derive_source_id,
    sha256_text,
    utc_now_iso,
)


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


def make_annotation_review_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> TestClient:
    """Bind Wiki review and annotation persistence to temporary local stores."""

    from routers import annotation_router, resources_router

    class _ResourceStore:
        def get_project(self, project_id: str) -> object | None:
            return object() if project_id in {"project-a", "project-b"} else None

        def get_material(self, material_id: str) -> object | None:
            if material_id == "material-a":
                return SimpleNamespace(project_id="project-a")
            return None

    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(wiki_router, "wiki_enabled", lambda: True)
    monkeypatch.setattr(wiki_router, "wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts))
    monkeypatch.setattr(wiki_router, "wiki_review_queue_path", lambda: runtime_root / "review_queue.jsonl")
    monkeypatch.setattr(annotation_router, "runtime_state_path", lambda: runtime_root)
    monkeypatch.setattr(resources_router, "get_writing_resource_store", lambda: _ResourceStore())
    app = FastAPI()
    app.include_router(annotation_router.router)
    app.include_router(wiki_router.router)
    return TestClient(app)


def create_wiki_review_note(client: TestClient) -> dict[str, object]:
    """Create and explicitly authorize one note for Wiki review."""

    note = client.post(
        "/api/annotations/material-a/notes",
        json={
            "page": 4,
            "anchor_text": "quoted evidence",
            "body": "review this interpretation",
            "tags": ["review"],
        },
    ).json()["note"]
    enabled = client.put(
        f"/api/annotations/material-a/notes/{note['note_id']}/usage",
        json={
            "enabled_scopes": ["wiki_review"],
            "expected_updated_at": note["updated_at"],
        },
    )
    assert enabled.status_code == 200, enabled.text
    return enabled.json()["note"]


def annotation_enqueue_payload(note: dict[str, object], *, request_id: str) -> dict[str, object]:
    return {
        "project_id": "project-a",
        "material_id": "material-a",
        "note_id": note["note_id"],
        "expected_updated_at": note["updated_at"],
        "expected_content_hash": note["content_hash"],
        "request_id": request_id,
    }


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


def append_page_review_item(
    queue: ReviewQueue,
    *,
    item_id: str,
    page: WikiPage,
    service: WikiService,
    summary: str,
) -> ReviewItem:
    stable_slug = page.stable_slug
    kind_value = page.kind.value
    page_path = f"{kind_value}/{stable_slug}.md"
    content = service.page_store.read_page(Path(page_path))
    assert content is not None
    return queue.append(
        make_review_item(
            item_id=item_id,
            kind=ReviewItemKind.draft,
            title=page.title,
            page_path=page_path,
            summary=summary,
            target=make_wiki_page_revision_review_target(
                page_id=stable_slug,
                page_path=page_path,
                expected_content_hash=hashlib.sha256(str(content).encode("utf-8")).hexdigest(),
                expected_status="draft",
            ),
        )
    )


def page_review_decision_payload(item: ReviewItem, *, reason: str) -> dict[str, str]:
    assert item.target is not None
    return {
        "reason": reason,
        "decided_by": "tester",
        "request_id": f"approve-{item.item_id}",
        "expected_item_revision": item.item_revision,
        "expected_target_content_hash": item.target.expected_content_hash,
    }


def promotion_withdrawal_payload(item: ReviewItem, *, reason: str) -> dict[str, str]:
    assert item.promotion_intent is not None
    return {
        "reason": reason,
        "expected_item_revision": item.item_revision,
        "expected_promotion_operation_id": item.promotion_intent.operation_id,
    }


class SimulatedPromotionCrash(BaseException):
    """Stand in for process loss at a durable promotion boundary."""


def test_wiki_backend_uses_canonical_module_identity() -> None:
    assert wiki_service_module.WikiPage is wiki_models.WikiPage
    assert wiki_service_module.WikiPageStore is wiki_page_store_module.WikiPageStore
    assert wiki_router.WikiPageStore is wiki_page_store_module.WikiPageStore
    assert wiki_router.ReviewQueue is wiki_review_queue_module.ReviewQueue


def bind_wiki_service(monkeypatch: pytest.MonkeyPatch, service: WikiService) -> None:
    """Route Wiki approval helpers to a temporary service instance."""

    monkeypatch.setattr(wiki_service_module, "get_wiki_service", lambda: service)


def make_review_promotion_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    item_id: str,
    title: str,
) -> tuple[TestClient, WikiService, ReviewItem, Path]:
    """Create one version-bound draft review item on temporary storage."""

    wiki_root = tmp_path / "wiki"
    service = WikiService(WikiPageStore(wiki_root, create=True))
    page = service.create_page(
        title=title,
        kind="concept",
        body="Recoverable promotion body.",
        status="draft",
    )
    bind_wiki_service(monkeypatch, service)
    item = append_page_review_item(
        ReviewQueue(tmp_path / "runtime" / "review_queue.jsonl"),
        item_id=item_id,
        page=page,
        service=service,
        summary="Requires durable approval.",
    )
    page_path = Path(page.kind.value) / f"{page.stable_slug}.md"
    return make_client(monkeypatch, tmp_path, enabled=True), service, item, page_path


def interrupt_promotion_before_page_write(
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: TestClient,
    queue_path: Path,
    item: ReviewItem,
    payload: dict[str, str],
) -> ReviewItem:
    """Crash the request after its intent is durable but before page mutation."""

    original_replace_text = WikiPageStore.replace_text

    def crash_before_write(
        _store: WikiPageStore,
        _relative_path: Path,
        _content: str,
        *,
        expected_current_hash: str | None = None,
    ) -> None:
        del expected_current_hash
        persisted = ReviewQueue(queue_path).get(item.item_id)
        assert persisted is not None
        assert persisted.status.value == "pending"
        assert persisted.promotion_intent is not None
        assert persisted.promotion_intent.request_id == payload["request_id"]
        raise SimulatedPromotionCrash("interrupted before page write")

    monkeypatch.setattr(WikiPageStore, "replace_text", crash_before_write)
    with pytest.raises(SimulatedPromotionCrash, match="before page write"):
        client.post(f"/api/wiki/review/{item.item_id}/approve", json=payload)
    monkeypatch.setattr(WikiPageStore, "replace_text", original_replace_text)

    persisted = ReviewQueue(queue_path).get(item.item_id)
    assert persisted is not None
    assert persisted.promotion_intent is not None
    return persisted


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


def test_status_integrity_uses_full_source_set_when_review_hides_drafts(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            Path("concepts/public-alpha.md"),
            {
                "id": "concepts/public-alpha",
                "kind": "concept",
                "title": "Public Alpha",
                "status": "final",
            },
            "Public alpha body.",
        )
    )
    page_store.write_rendered(
        render_page(
            Path("concepts/review-draft.md"),
            {
                "id": "concepts/review-draft",
                "kind": "concept",
                "title": "Review Draft",
                "status": "draft",
                "extra": {
                    "entry_source": "manual_frontend",
                    "permissions": {"owner": "local-user", "visibility": "private", "shared_with": []},
                },
            },
            "Draft body hidden from published knowledge surfaces.",
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
    assert payload["stale"] is False
    assert payload["integrity_status"] == "aligned"
    assert payload["indexed_page_count"] == 2
    assert payload["source_page_count"] == 2
    assert payload["manifest_drilldown"]["extra_count"] == 0
    assert payload["warnings"] == []


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


def test_wiki_revalidation_preflight_is_read_only_and_apply_uses_manifest_cas(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wiki_root = tmp_path / "wiki"
    WikiService(WikiPageStore(wiki_root, create=True)).create_page(
        title="Revalidation source",
        kind="concept",
        body="Current source body.",
        status="final",
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)
    index_path = tmp_path / "runtime" / "wiki_query_index.db"

    preflight = client.post("/api/wiki/revalidation/preflight")

    assert preflight.status_code == 200
    assert preflight.json()["stale"] is True
    assert preflight.json()["can_apply"] is True
    assert preflight.json()["applied"] is False
    assert not index_path.exists()

    missing_confirmation = client.post(
        "/api/wiki/revalidation/apply",
        json={
            "expected_source_manifest_hash": preflight.json()["source_manifest_hash"],
            "confirm": False,
        },
    )
    wrong_hash = client.post(
        "/api/wiki/revalidation/apply",
        json={"expected_source_manifest_hash": "0" * 64, "confirm": True},
    )

    assert missing_confirmation.status_code == 400
    assert wrong_hash.status_code == 409
    assert not index_path.exists()

    applied = client.post(
        "/api/wiki/revalidation/apply",
        json={
            "expected_source_manifest_hash": preflight.json()["source_manifest_hash"],
            "confirm": True,
        },
    )

    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    assert applied.json()["stale"] is False
    assert applied.json()["source_manifest_hash"] == applied.json()["indexed_source_manifest_hash"]
    assert index_path.exists()


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
    monkeypatch.setattr(wiki_service_module, "get_wiki_service", lambda: service)
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
    monkeypatch.setattr(wiki_service_module, "get_wiki_service", lambda: service)
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


def test_graph_review_disambiguation_apply_and_undo(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_path = Path("claims/dup-b.md")
    page_store.write_rendered(
        render_page(
            page_path,
            {"id": "claims/dup-b", "kind": "claim", "title": "重复证据", "status": "draft"},
            "Body B.",
        )
    )
    original = page_store.read_page(page_path)
    assert original is not None
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/graph/review/apply",
        json={
            "operation_kind": "disambiguate_nodes",
            "nodes": [
                {
                    "node_id": "dup-b",
                    "page_path": "claims/dup-b.md",
                    "label": "重复证据（材料 B）",
                    "disambiguation": "来自材料 B，不能和材料 A 合并。",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated_page_paths"] == ["claims/dup-b.md"]
    assert payload["snapshots"][0]["content"] == original
    updated = page_store.read_page(page_path)
    assert updated is not None
    assert payload["snapshots"][0]["content_hash"] == wiki_router._wiki_content_hash(str(original))
    assert payload["snapshots"][0]["expected_current_hash"] == wiki_router._wiki_content_hash(str(updated))
    frontmatter, _body = wiki_router._split_frontmatter(str(updated))
    assert frontmatter["title"] == "重复证据（材料 B）"
    assert frontmatter["extra"]["disambiguation"] == "来自材料 B，不能和材料 A 合并。"

    undo_response = client.post(
        "/api/wiki/graph/review/undo",
        json={
            "operation_id": payload["operation_id"],
            "snapshots": payload["snapshots"],
        },
    )

    assert undo_response.status_code == 200
    assert page_store.read_page(page_path) == original


def test_graph_review_undo_rejects_any_drift_without_partial_restore(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    first_path = Path("claims/undo-a.md")
    second_path = Path("claims/undo-b.md")
    for path, title in ((first_path, "Undo A"), (second_path, "Undo B")):
        page_store.write_rendered(
            render_page(
                path,
                {"id": path.with_suffix("").as_posix(), "kind": "claim", "title": title, "status": "draft"},
                f"Original {title}.",
            )
        )
    originals = {path: page_store.read_page(path) for path in (first_path, second_path)}
    assert all(value is not None for value in originals.values())
    client = make_client(monkeypatch, tmp_path, enabled=True)

    apply_response = client.post(
        "/api/wiki/graph/review/apply",
        json={
            "operation_kind": "add_node_evidence",
            "nodes": [
                {"node_id": "undo-a", "page_path": first_path.as_posix()},
                {"node_id": "undo-b", "page_path": second_path.as_posix()},
            ],
            "evidence_refs": [{"material_id": "mat-undo", "chunk_id": "chunk-1", "page": 2}],
        },
    )

    assert apply_response.status_code == 200
    receipt = apply_response.json()
    changed_first = page_store.read_page(first_path)
    changed_second = page_store.read_page(second_path)
    assert changed_first is not None and changed_first != originals[first_path]
    assert changed_second is not None and changed_second != originals[second_path]

    # Simulate an unrelated concurrent write after the apply receipt was issued.
    page_store.write_rendered(
        render_page(
            second_path,
            {"id": "claims/undo-b", "kind": "claim", "title": "Undo B (concurrent)", "status": "draft"},
            "Concurrent edit.",
        )
    )
    concurrent = page_store.read_page(second_path)
    assert concurrent is not None

    undo_response = client.post(
        "/api/wiki/graph/review/undo",
        json={"operation_id": receipt["operation_id"], "snapshots": receipt["snapshots"]},
    )

    assert undo_response.status_code == 409
    assert page_store.read_page(first_path) == changed_first
    assert page_store.read_page(second_path) == concurrent


def test_graph_review_merge_marks_alias_and_rebuilds_graph(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            Path("claims/dup-a.md"),
            {
                "id": "claims/dup-a",
                "kind": "claim",
                "title": "重复证据",
                "status": "draft",
                "evidence_refs": [{"material_id": "m1", "chunk_id": "c1", "text": "A"}],
                "source_hashes": ["hash-a"],
            },
            "Body A.",
        )
    )
    page_store.write_rendered(
        render_page(
            Path("claims/dup-b.md"),
            {
                "id": "claims/dup-b",
                "kind": "claim",
                "title": "重复证据",
                "status": "draft",
                "evidence_refs": [{"material_id": "m2", "chunk_id": "c2", "text": "B"}],
                "source_hashes": ["hash-b"],
            },
            "Body B.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/graph/review/apply",
        json={
            "operation_kind": "merge_duplicate_nodes",
            "keep_node_id": "dup-a",
            "merge_node_ids": ["dup-b"],
            "nodes": [
                {"node_id": "dup-a", "page_path": "claims/dup-a.md"},
                {"node_id": "dup-b", "page_path": "claims/dup-b.md"},
            ],
        },
    )

    assert response.status_code == 200
    keep_content = page_store.read_page(Path("claims/dup-a.md"))
    merged_content = page_store.read_page(Path("claims/dup-b.md"))
    assert keep_content is not None
    assert merged_content is not None
    keep_frontmatter, _keep_body = wiki_router._split_frontmatter(str(keep_content))
    merged_frontmatter, _merged_body = wiki_router._split_frontmatter(str(merged_content))
    assert keep_frontmatter["source_hashes"] == ["hash-a", "hash-b"]
    assert {ref["material_id"] for ref in keep_frontmatter["evidence_refs"]} == {"m1", "m2"}
    assert "dup-b" in keep_frontmatter["extra"]["graph_review"]["merged_node_ids"]
    assert merged_frontmatter["extra"]["graph_review"]["merged_into"] == "claims/dup-a.md"

    graph_response = client.get("/api/wiki/graph")

    assert graph_response.status_code == 200
    graph = graph_response.json()["graph"]
    assert graph["node_count"] == 1
    assert [node["page_path"] for node in graph["nodes"]] == ["claims/dup-a.md"]


def test_graph_review_undo_rejects_drift_without_partial_restore(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    first_path = Path("claims/dup-a.md")
    second_path = Path("claims/dup-b.md")
    for path, title, material_id in (
        (first_path, "重复证据 A", "m1"),
        (second_path, "重复证据 B", "m2"),
    ):
        page_store.write_rendered(
            render_page(
                path,
                {
                    "id": path.with_suffix("").as_posix(),
                    "kind": "claim",
                    "title": title,
                    "status": "draft",
                    "evidence_refs": [{"material_id": material_id, "chunk_id": f"{material_id}-c1"}],
                },
                f"{title} body.",
            )
        )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    apply_response = client.post(
        "/api/wiki/graph/review/apply",
        json={
            "operation_kind": "merge_duplicate_nodes",
            "keep_node_id": "dup-a",
            "merge_node_ids": ["dup-b"],
            "nodes": [
                {"node_id": "dup-a", "page_path": first_path.as_posix()},
                {"node_id": "dup-b", "page_path": second_path.as_posix()},
            ],
        },
    )
    assert apply_response.status_code == 200
    receipt = apply_response.json()
    post_apply_first = page_store.read_page(first_path)
    post_apply_second = page_store.read_page(second_path)
    assert post_apply_first is not None
    assert post_apply_second is not None

    drifted_second = render_page(
        second_path,
        {
            "id": "claims/dup-b",
            "kind": "claim",
            "title": "用户后来修改的证据 B",
            "status": "draft",
        },
        "This content changed after the graph review apply.",
    )
    page_store.write_rendered(drifted_second)

    undo_response = client.post(
        "/api/wiki/graph/review/undo",
        json={"operation_id": receipt["operation_id"], "snapshots": receipt["snapshots"]},
    )

    assert undo_response.status_code == 409
    assert "changed after apply" in undo_response.json()["detail"]
    assert page_store.read_page(first_path) == post_apply_first
    assert page_store.read_page(second_path) == drifted_second.text


def test_graph_review_add_node_evidence_apply_and_undo(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_path = Path("evidence/missing.md")
    page_store.write_rendered(
        render_page(
            page_path,
            {"id": "evidence/missing", "kind": "claim", "title": "缺证据节点", "status": "draft"},
            "Body.",
        )
    )
    original = page_store.read_page(page_path)
    assert original is not None
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/graph/review/apply",
        json={
            "operation_kind": "add_node_evidence",
            "nodes": [{"node_id": "missing", "page_path": "evidence/missing.md"}],
            "evidence_refs": [{"material_id": "mat-1", "chunk_id": "chunk-9", "page": 7, "text": "原文证据片段"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["operation_kind"] == "add_node_evidence"
    updated = page_store.read_page(page_path)
    assert updated is not None
    frontmatter, _body = wiki_router._split_frontmatter(str(updated))
    assert frontmatter["evidence_refs"] == [{"material_id": "mat-1", "chunk_id": "chunk-9", "page": 7, "text": "原文证据片段"}]
    assert frontmatter["source_ref"] == {"material_id": "mat-1", "page": 7, "chunk_id": "chunk-9"}
    assert frontmatter["extra"]["graph_review"]["last_operation_kind"] == "add_node_evidence"

    undo_response = client.post(
        "/api/wiki/graph/review/undo",
        json={"operation_id": payload["operation_id"], "snapshots": payload["snapshots"]},
    )

    assert undo_response.status_code == 200
    assert page_store.read_page(page_path) == original


def test_graph_review_add_relation_evidence_updates_relation_item(monkeypatch, tmp_path: Path) -> None:
    page_store = WikiPageStore(tmp_path / "wiki")
    page_store.write_rendered(
        render_page(
            Path("claims/a.md"),
            {
                "id": "claims/a",
                "kind": "claim",
                "title": "A",
                "status": "draft",
                "supports": ["claims/b"],
            },
            "A body.",
        )
    )
    page_store.write_rendered(
        render_page(
            Path("claims/b.md"),
            {"id": "claims/b", "kind": "claim", "title": "B", "status": "draft"},
            "B body.",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/graph/review/apply",
        json={
            "operation_kind": "add_relation_evidence",
            "edges": [
                {
                    "edge_id": "a-supports-b",
                    "source": "claims/a",
                    "target": "claims/b",
                    "relation": "supports",
                    "source_path": "claims/a.md",
                    "target_path": "claims/b.md",
                    "frontmatter_field": "supports",
                }
            ],
            "evidence_refs": [{"material_id": "mat-1", "chunk_id": "chunk-2", "page": 4, "text": "关系证据"}],
        },
    )

    assert response.status_code == 200
    updated = page_store.read_page(Path("claims/a.md"))
    assert updated is not None
    frontmatter, _body = wiki_router._split_frontmatter(str(updated))
    assert frontmatter["supports"] == [
        {
            "target": "claims/b",
            "type": "supports",
            "evidence_refs": [{"material_id": "mat-1", "chunk_id": "chunk-2", "page": 4, "text": "关系证据"}],
            "source_ref": {"material_id": "mat-1", "page": 4, "chunk_id": "chunk-2"},
            "material_id": "mat-1",
            "page": 4,
            "chunk_id": "chunk-2",
            "evidence": "关系证据",
        }
    ]
    assert frontmatter["extra"]["graph_review"]["last_operation_kind"] == "add_relation_evidence"

    graph_response = client.get("/api/wiki/graph")

    assert graph_response.status_code == 200
    edge = graph_response.json()["graph"]["edges"][0]
    assert edge["metadata"]["evidence_refs"][0]["chunk_id"] == "chunk-2"
    assert edge["metadata"]["source_ref"]["material_id"] == "mat-1"


def test_doctor_contract_exposes_source_vault_mirror_backlog(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    runtime_root = tmp_path / "runtime"
    source_text = "Router visible Source Vault mirror backlog."
    source_hash = sha256_text(source_text)
    source_id = derive_source_id("local_markdown_import", "Router Backlog", source_hash)
    source_path = tmp_path / "router-backlog.md"
    source_path.write_text(source_text, encoding="utf-8")
    WikiPageStore(wiki_root).write_rendered(
        render_page(
            Path("synthesis/router-backlog.md"),
            {
                "id": "synthesis/router-backlog",
                "source_id": source_id,
                "kind": "synthesis",
                "title": "Router Backlog",
                "status": "draft",
            },
            source_text,
        )
    )
    registry = WikiRegistry(runtime_root / "wiki.db", mirror_to_source_vault=False)
    registry.upsert_source(
        SourceRecord(
            source_id=source_id,
            source_type="local_markdown_import",
            title="Router Backlog",
            source_hash=source_hash,
            source_path=source_path,
        ),
        now_iso="2026-06-27T23:55:00+00:00",
    )
    registry.register_chunks(
        source_id,
        source_hash,
        [ChunkInput(text=source_text, chunk_index=0, section="synthesis/router-backlog.md")],
        now_iso="2026-06-27T23:55:00+00:00",
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.get("/api/wiki/doctor")

    assert response.status_code == 200
    registry_check = {
        check["id"]: check
        for check in response.json()["report"]["checks"]
    }["registry"]
    mirror = registry_check["metrics"]["source_vault_mirror"]
    assert registry_check["status"] == "warning"
    assert mirror["needs_replay"] is True
    assert mirror["pending_source_count"] == 1
    assert mirror["pending_chunk_count"] == 1
    assert mirror["samples"][0]["source_id"] == source_id


def test_annotation_review_target_round_trips_strictly_through_jsonl(tmp_path: Path) -> None:
    target = make_annotation_note_review_target(
        project_id="project-a",
        material_id="material-a",
        note_id="note-a",
        expected_updated_at="2026-07-17T04:00:00+00:00",
        expected_content_hash="a" * 64,
    )
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")
    item = queue.append(
        make_review_item(
            item_id="annotation-roundtrip",
            kind=ReviewItemKind.annotation_note,
            title="Annotation roundtrip",
            page_path="annotations/material-a/note-a",
            summary="Strict target.",
            source="annotation",
            target=target,
        )
    )

    loaded = ReviewQueue(queue.queue_path).get(item.item_id)
    assert loaded is not None
    assert loaded.target == target
    assert loaded.to_dict()["target"]["type"] == "annotation_note"
    invalid = target.to_dict()
    invalid["unexpected"] = True
    with pytest.raises(ValueError, match="unsupported fields"):
        wiki_review_queue_module.AnnotationNoteReviewTarget.from_dict(invalid)


def test_annotation_review_enqueue_requires_project_ownership_scope_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = make_annotation_review_client(monkeypatch, tmp_path)
    note = client.post(
        "/api/annotations/material-a/notes",
        json={"page": 1, "anchor_text": "anchor", "body": "note", "tags": []},
    ).json()["note"]
    request = annotation_enqueue_payload(note, request_id="enqueue-annotation-a")

    not_enabled = client.post("/api/wiki/review/annotations/enqueue", json=request)
    assert not_enabled.status_code == 409
    enabled = client.put(
        f"/api/annotations/material-a/notes/{note['note_id']}/usage",
        json={"enabled_scopes": ["wiki_review"], "expected_updated_at": note["updated_at"]},
    ).json()["note"]
    request = annotation_enqueue_payload(enabled, request_id="enqueue-annotation-a")
    wrong_project = client.post(
        "/api/wiki/review/annotations/enqueue",
        json={**request, "project_id": "project-b", "request_id": "wrong-project"},
    )
    assert wrong_project.status_code == 400

    created = client.post("/api/wiki/review/annotations/enqueue", json=request)
    replay = client.post("/api/wiki/review/annotations/enqueue", json=request)
    conflict = client.post(
        "/api/wiki/review/annotations/enqueue",
        json={**request, "expected_content_hash": "b" * 64},
    )

    assert created.status_code == 200, created.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["item_id"] == created.json()["item_id"]
    assert created.json()["target"] == {
        "schema_version": "scholar-ai-annotation-note-review-target/v1",
        "type": "annotation_note",
        "project_id": "project-a",
        "material_id": "material-a",
        "note_id": enabled["note_id"],
        "expected_updated_at": enabled["updated_at"],
        "expected_content_hash": enabled["content_hash"],
        "required_scope": "wiki_review",
    }
    assert conflict.status_code == 409


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_annotation_review_decision_is_only_cas_idempotent_queue_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action: str,
) -> None:
    client = make_annotation_review_client(monkeypatch, tmp_path)
    note = create_wiki_review_note(client)
    created = client.post(
        "/api/wiki/review/annotations/enqueue",
        json=annotation_enqueue_payload(note, request_id=f"enqueue-{action}"),
    ).json()
    monkeypatch.setattr(
        wiki_router,
        "_promote_review_target_to_final",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not promote")),
    )
    decision = {
        "reason": f"{action} after review",
        "request_id": f"decide-{action}",
        "expected_item_revision": created["item_revision"],
        "expected_target_content_hash": note["content_hash"],
    }

    decided = client.post(
        f"/api/wiki/review/{created['item_id']}/{action}",
        json=decision,
    )
    replay = client.post(
        f"/api/wiki/review/{created['item_id']}/{action}",
        json=decision,
    )
    conflict = client.post(
        f"/api/wiki/review/{created['item_id']}/{action}",
        json={**decision, "reason": "different decision"},
    )

    assert decided.status_code == 200, decided.text
    expected_status = "approved" if action == "approve" else "rejected"
    assert decided.json()["status"] == expected_status
    assert decided.json()["decision"]["promotion_receipt"] is None
    assert replay.status_code == 200, replay.text
    assert replay.json()["item_revision"] == decided.json()["item_revision"]
    assert conflict.status_code == 409
    assert not (tmp_path / "wiki").exists()


@pytest.mark.parametrize("source_change", ["revoke", "delete", "edit", "queue_revision"])
def test_annotation_review_source_or_queue_change_blocks_decision_and_keeps_audit_item(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_change: str,
) -> None:
    client = make_annotation_review_client(monkeypatch, tmp_path)
    note = create_wiki_review_note(client)
    created = client.post(
        "/api/wiki/review/annotations/enqueue",
        json=annotation_enqueue_payload(note, request_id=f"enqueue-{source_change}"),
    ).json()
    note_path = f"/api/annotations/material-a/notes/{note['note_id']}"
    if source_change == "revoke":
        changed = client.put(
            f"{note_path}/usage",
            json={"enabled_scopes": [], "expected_updated_at": note["updated_at"]},
        )
    elif source_change == "delete":
        changed = client.delete(note_path)
    elif source_change == "edit":
        annotation_path = tmp_path / "runtime" / "annotations" / "material-a.json"
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        annotation["notes"][0]["body"] = "changed without advancing updated_at"
        annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
        changed = None
    else:
        ReviewQueue(tmp_path / "runtime" / "review_queue.jsonl").update_metadata(
            created["item_id"],
            {"audit_revision": "changed"},
        )
        changed = None
    if changed is not None:
        assert changed.status_code == 200, changed.text

    blocked = client.post(
        f"/api/wiki/review/{created['item_id']}/approve",
        json={
            "reason": "approve stale source",
            "request_id": f"approve-{source_change}",
            "expected_item_revision": created["item_revision"],
            "expected_target_content_hash": note["content_hash"],
        },
    )

    assert blocked.status_code == 409, blocked.text
    persisted = ReviewQueue(tmp_path / "runtime" / "review_queue.jsonl").get(created["item_id"])
    assert persisted is not None
    assert persisted.status.value == "pending"
    assert persisted.decision is None


def test_review_approve_and_reject_contract(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    page = WikiService(WikiPageStore(wiki_root, create=True)).create_page(
        title="Draft",
        kind="concept",
        body="Needs review.",
        status="draft",
    )
    monkeypatch.setattr(
        wiki_service_module,
        "get_wiki_service",
        lambda: WikiService(WikiPageStore(wiki_root, create=True)),
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    queue = ReviewQueue(queue_path)
    draft_item = append_page_review_item(
        queue,
        item_id="draft-1",
        page=page,
        service=WikiService(WikiPageStore(wiki_root, create=True)),
        summary="Needs review.",
    )
    warning_item = queue.append(
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
    approve_response = client.post(
        "/api/wiki/review/draft-1/approve",
        json=page_review_decision_payload(draft_item, reason="ok"),
    )
    reject_response = client.post(
        "/api/wiki/review/warn-1/reject",
        json={
            "reason": "missing quote",
            "decided_by": "tester",
            "expected_item_revision": warning_item.item_revision,
        },
    )

    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == 2
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"
    assert approve_response.json()["decision"]["decided_by"] == "local-user"
    assert reject_response.status_code == 200
    assert reject_response.json()["decision"]["reason"] == "missing quote"
    assert reject_response.json()["decision"]["decided_by"] == "local-user"


def test_review_approve_non_page_item_does_not_promote_wiki_page(monkeypatch, tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "runtime" / "review_queue.jsonl")
    item = queue.append(
        make_review_item(
            item_id="manual-edit-1",
            kind=ReviewItemKind.manual_edit,
            title="Qrels edit",
            page_path="artifacts/qrels-judgment.json",
            summary="Manual judgment change.",
            source="qrels",
        )
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)
    monkeypatch.setattr(
        "routers.wiki_router._promote_review_target_to_final",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not promote")),
    )

    response = client.post(
        "/api/wiki/review/manual-edit-1/approve",
        json={
            "reason": "judgment verified",
            "decided_by": "spoofed-user",
            "expected_item_revision": item.item_revision,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["decision"]["decided_by"] == "local-user"


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_review_non_page_decision_rejects_stale_item_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action: str,
) -> None:
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    queue = ReviewQueue(queue_path)
    item = queue.append(
        make_review_item(
            item_id=f"stale-{action}",
            kind=ReviewItemKind.warning,
            title="Stale generic review",
            page_path="artifacts/review.json",
            summary="The visible review revision is stale.",
        )
    )
    queue.update_metadata(item.item_id, {"review_note": "changed after load"})
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        f"/api/wiki/review/{item.item_id}/{action}",
        json={
            "reason": "decision from stale UI",
            "expected_item_revision": item.item_revision,
        },
    )

    assert response.status_code == 409, response.text
    assert "item revision changed" in response.text
    persisted = ReviewQueue(queue_path).get(item.item_id)
    assert persisted is not None
    assert persisted.status.value == "pending"
    assert persisted.decision is None


def test_review_page_decision_requires_page_owner(monkeypatch, tmp_path: Path) -> None:
    wiki_root = tmp_path / "wiki"
    service = WikiService(WikiPageStore(wiki_root, create=True))
    page = service.create_page(
        title="Owned draft",
        kind="concept",
        body="Owner review required.",
        status="draft",
        extra={
            "permissions": {
                "owner": "alice",
                "visibility": "private",
                "shared_with": [],
            }
        },
    )
    monkeypatch.setattr(wiki_service_module, "get_wiki_service", lambda: service)
    owned_item = append_page_review_item(
        ReviewQueue(tmp_path / "runtime" / "review_queue.jsonl"),
        item_id="owned-draft",
        page=page,
        service=service,
        summary="Owner review required.",
    )
    client = make_client(monkeypatch, tmp_path, enabled=True)

    response = client.post(
        "/api/wiki/review/owned-draft/approve",
        params={"user_id": "bob"},
        json=page_review_decision_payload(owned_item, reason="attempted approval"),
    )

    assert response.status_code == 403
    assert ReviewQueue(tmp_path / "runtime" / "review_queue.jsonl").get("owned-draft").status.value == "pending"


def test_review_promotion_persists_intent_before_page_write_and_same_request_resumes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="prepared-promotion",
        title="Prepared promotion",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    payload = page_review_decision_payload(item, reason="verified")
    before_content = service.page_store.read_page(page_path)
    assert before_content is not None

    prepared = interrupt_promotion_before_page_write(
        monkeypatch,
        client=client,
        queue_path=queue_path,
        item=item,
        payload=payload,
    )

    assert prepared.status.value == "pending"
    assert prepared.promotion_intent is not None
    assert prepared.promotion_intent.before_content_hash == item.target.expected_content_hash
    assert service.page_store.read_page(page_path) == before_content

    queue_before_read = queue_path.read_bytes()
    review_response = client.get("/api/wiki/review")
    assert review_response.status_code == 200
    visible_intent = review_response.json()["items"][0]["promotion_intent"]
    assert visible_intent["request_id"] == payload["request_id"]
    assert visible_intent["reason"] == payload["reason"]
    assert review_response.json()["items"][0]["allowed_actions"] == ["approve", "withdraw"]
    assert service.page_store.read_page(page_path) == before_content
    assert queue_path.read_bytes() == queue_before_read

    resumed = client.post(f"/api/wiki/review/{item.item_id}/approve", json=payload)

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "approved"
    assert resumed.json()["decision"]["promotion_receipt"]["receipt_id"] == prepared.promotion_intent.operation_id
    promoted = service.get_page(item.target.page_id)
    assert promoted is not None
    assert promoted.status.value == "final"
    decided = ReviewQueue(queue_path).get(item.item_id)
    assert decided is not None
    assert decided.status.value == "approved"
    assert decided.promotion_intent is None


def test_review_withdraws_unapplied_promotion_and_keeps_candidate_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="withdraw-promotion",
        title="Withdraw promotion",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    prepared = interrupt_promotion_before_page_write(
        monkeypatch,
        client=client,
        queue_path=queue_path,
        item=item,
        payload=page_review_decision_payload(item, reason="approval interrupted"),
    )
    original_page = service.page_store.read_page(page_path)
    assert original_page is not None
    original_revision = prepared.item_revision
    request = promotion_withdrawal_payload(prepared, reason="cancel this approval")

    response = client.post(f"/api/wiki/review/{item.item_id}/withdraw", json=request)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"item", "withdrawal_receipt"}
    withdrawn = payload["item"]
    receipt = payload["withdrawal_receipt"]
    assert withdrawn["status"] == "pending"
    assert withdrawn["promotion_intent"] is None
    assert withdrawn["item_revision"] != original_revision
    assert withdrawn["allowed_actions"] == ["approve", "reject"]
    assert receipt["schema_version"] == "scholar-ai-wiki-promotion-withdrawal-receipt/v1"
    assert receipt["promotion_operation_id"] == request["expected_promotion_operation_id"]
    assert receipt["expected_item_revision"] == original_revision
    assert receipt["resulting_item_revision"] == withdrawn["item_revision"]
    assert receipt["before_content_hash"] == prepared.promotion_intent.before_content_hash
    assert receipt["planned_after_content_hash"] == prepared.promotion_intent.after_content_hash
    assert receipt["outcome"] == "withdrawn"
    assert withdrawn["promotion_withdrawal_receipts"] == [receipt]
    assert service.page_store.read_page(page_path) == original_page
    persisted = ReviewQueue(queue_path).get(item.item_id)
    assert persisted is not None
    assert persisted.status.value == "pending"
    assert persisted.promotion_intent is None
    assert persisted.item_revision == receipt["resulting_item_revision"]
    assert persisted.promotion_withdrawal_receipts[0].to_dict() == receipt


def test_review_withdrawal_requires_pending_promotion_intent_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="withdraw-without-intent",
        title="Withdraw without intent",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    page_before = service.page_store.read_page(page_path)
    queue_before = queue_path.read_bytes()

    response = client.post(
        f"/api/wiki/review/{item.item_id}/withdraw",
        json={
            "reason": "nothing is in flight",
            "expected_item_revision": item.item_revision,
            "expected_promotion_operation_id": "missing-operation",
        },
    )

    assert response.status_code == 409, response.text
    assert "no promotion request to withdraw" in response.text
    assert service.page_store.read_page(page_path) == page_before
    assert queue_path.read_bytes() == queue_before


def test_review_withdrawal_replays_same_request_and_rejects_conflicting_replays(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="replay-withdrawal",
        title="Replay withdrawal",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    prepared = interrupt_promotion_before_page_write(
        monkeypatch,
        client=client,
        queue_path=queue_path,
        item=item,
        payload=page_review_decision_payload(item, reason="approval interrupted"),
    )
    request = promotion_withdrawal_payload(prepared, reason="withdraw once")
    first = client.post(f"/api/wiki/review/{item.item_id}/withdraw", json=request)
    assert first.status_code == 200, first.text
    queue_after = queue_path.read_bytes()
    page_after = service.page_store.read_page(page_path)

    replay = client.post(f"/api/wiki/review/{item.item_id}/withdraw", json=request)

    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert queue_path.read_bytes() == queue_after
    assert service.page_store.read_page(page_path) == page_after

    conflicts = [
        ({**request, "reason": "different reason"}, None),
        ({**request, "expected_item_revision": "different-revision"}, None),
        ({**request, "expected_promotion_operation_id": "different-operation"}, None),
        (request, {"user_id": "different-user"}),
    ]
    for conflict_request, params in conflicts:
        conflict = client.post(
            f"/api/wiki/review/{item.item_id}/withdraw",
            json=conflict_request,
            params=params,
        )
        assert conflict.status_code == 409, conflict.text
        assert queue_path.read_bytes() == queue_after
        assert service.page_store.read_page(page_path) == page_after


@pytest.mark.parametrize("page_state", ["after_hash", "third_party_drift"])
def test_review_withdrawal_rejects_applied_or_drifted_page_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    page_state: str,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id=f"withdraw-{page_state}",
        title=f"Withdraw {page_state}",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    prepared = interrupt_promotion_before_page_write(
        monkeypatch,
        client=client,
        queue_path=queue_path,
        item=item,
        payload=page_review_decision_payload(item, reason="approval interrupted"),
    )
    assert prepared.promotion_intent is not None
    if page_state == "after_hash":
        wiki_router._promote_review_target_to_final(
            prepared,
            "local-user",
            intent=prepared.promotion_intent,
        )
    else:
        page_file = service.page_store.wiki_root / page_path
        page_file.write_text(
            page_file.read_text(encoding="utf-8").replace(
                "Recoverable promotion body.",
                "Third-party drift blocks withdrawal.",
            ),
            encoding="utf-8",
        )
    page_before = service.page_store.read_page(page_path)
    queue_before = queue_path.read_bytes()

    response = client.post(
        f"/api/wiki/review/{item.item_id}/withdraw",
        json=promotion_withdrawal_payload(prepared, reason="withdraw safely"),
    )

    assert response.status_code == 409, response.text
    assert service.page_store.read_page(page_path) == page_before
    assert queue_path.read_bytes() == queue_before
    persisted = ReviewQueue(queue_path).get(item.item_id)
    assert persisted is not None
    assert persisted.status.value == "pending"
    assert persisted.promotion_intent == prepared.promotion_intent


def test_review_reject_holds_queue_lock_for_permission_and_decision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _service, item, _page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="locked-reject",
        title="Locked reject",
    )
    original_locked = ReviewQueue.locked
    original_reject = ReviewQueue.reject
    lock_depth = 0

    @contextmanager
    def observed_locked(queue: ReviewQueue) -> Iterator[None]:
        nonlocal lock_depth
        with original_locked(queue):
            lock_depth += 1
            try:
                yield
            finally:
                lock_depth -= 1

    def observed_reject(
        queue: ReviewQueue,
        item_id: str,
        *,
        reason: str,
        decided_by: str = "user",
    ) -> ReviewItem:
        assert lock_depth == 1
        return original_reject(
            queue,
            item_id,
            reason=reason,
            decided_by=decided_by,
        )

    monkeypatch.setattr(ReviewQueue, "locked", observed_locked)
    monkeypatch.setattr(ReviewQueue, "reject", observed_reject)

    response = client.post(
        f"/api/wiki/review/{item.item_id}/reject",
        json={
            "reason": "not suitable for the Wiki",
            "expected_item_revision": item.item_revision,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"
    assert lock_depth == 0


@pytest.mark.parametrize(
    "page_state",
    ["before_hash", "after_hash", "third_party_drift"],
)
def test_review_reject_blocks_pending_promotion_intent_for_every_page_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    page_state: str,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id=f"reject-{page_state}",
        title=f"Reject {page_state}",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    payload = page_review_decision_payload(item, reason="resume this approval")
    prepared = interrupt_promotion_before_page_write(
        monkeypatch,
        client=client,
        queue_path=queue_path,
        item=item,
        payload=payload,
    )
    intent = prepared.promotion_intent
    assert intent is not None

    if page_state == "after_hash":
        wiki_router._promote_review_target_to_final(
            prepared,
            "local-user",
            intent=intent,
        )
    elif page_state == "third_party_drift":
        page_file = service.page_store.wiki_root / page_path
        drifted_content = page_file.read_text(encoding="utf-8").replace(
            "Recoverable promotion body.",
            "Third-party edit while the promotion remains pending.",
        )
        page_file.write_text(drifted_content, encoding="utf-8")

    content_before_reject = service.page_store.read_page(page_path)
    queue_before_reject = queue_path.read_bytes()

    with pytest.raises(ValueError, match="promotion request is in progress"):
        ReviewQueue(queue_path).reject(
            item.item_id,
            reason="reject the in-flight promotion",
            decided_by="local-user",
        )

    response = client.post(
        f"/api/wiki/review/{item.item_id}/reject",
        json={
            "reason": "reject the in-flight promotion",
            "expected_item_revision": prepared.item_revision,
        },
    )

    assert response.status_code == 409, response.text
    assert "promotion request is in progress" in response.text
    assert service.page_store.read_page(page_path) == content_before_reject
    assert queue_path.read_bytes() == queue_before_reject
    persisted = ReviewQueue(queue_path).get(item.item_id)
    assert persisted is not None
    assert persisted.status.value == "pending"
    assert persisted.promotion_intent == intent


def test_review_promotion_replays_legacy_v1_intent_without_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _service, item, _page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="legacy-intent-reason",
        title="Legacy intent reason",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    payload = page_review_decision_payload(item, reason="legacy verified reason")
    interrupt_promotion_before_page_write(
        monkeypatch,
        client=client,
        queue_path=queue_path,
        item=item,
        payload=payload,
    )

    rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
    intent_payload = rows[0]["promotion_intent"]
    assert intent_payload["schema_version"] == "scholar-ai-wiki-promotion-intent/v2"
    intent_payload["schema_version"] = "scholar-ai-wiki-promotion-intent/v1"
    del intent_payload["reason"]
    queue_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    legacy_item = ReviewQueue(queue_path).get(item.item_id)
    assert legacy_item is not None
    assert legacy_item.promotion_intent is not None
    assert legacy_item.promotion_intent.reason == ""

    conflicting_reason = client.post(
        f"/api/wiki/review/{item.item_id}/approve",
        json={**payload, "reason": "different reason"},
    )
    assert conflicting_reason.status_code == 409

    resumed = client.post(f"/api/wiki/review/{item.item_id}/approve", json=payload)

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "approved"
    assert resumed.json()["decision"]["reason"] == payload["reason"]


def test_review_promotion_restart_finalizes_page_already_at_after_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="after-hash-promotion",
        title="After hash promotion",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    payload = page_review_decision_payload(item, reason="verified after restart")
    original_finalize = ReviewQueue.finalize_promotion

    def crash_before_queue_commit(
        _queue: ReviewQueue,
        _item_id: str,
        *,
        reason: str,
        decided_by: str,
        receipt: object,
    ) -> ReviewItem:
        del reason, decided_by, receipt
        raise SimulatedPromotionCrash("interrupted before queue commit")

    monkeypatch.setattr(ReviewQueue, "finalize_promotion", crash_before_queue_commit)
    with pytest.raises(SimulatedPromotionCrash, match="before queue commit"):
        client.post(f"/api/wiki/review/{item.item_id}/approve", json=payload)
    monkeypatch.setattr(ReviewQueue, "finalize_promotion", original_finalize)

    prepared = ReviewQueue(queue_path).get(item.item_id)
    assert prepared is not None
    assert prepared.status.value == "pending"
    assert prepared.promotion_intent is not None
    after_content = service.page_store.read_page(page_path)
    assert after_content is not None
    assert wiki_router._wiki_content_hash(str(after_content)) == prepared.promotion_intent.after_content_hash
    promoted_page = service.get_page(item.target.page_id)
    assert promoted_page is not None
    assert promoted_page.status.value == "final"

    client.close()
    restarted_service = WikiService(WikiPageStore(tmp_path / "wiki", create=True))
    bind_wiki_service(monkeypatch, restarted_service)
    restarted_client = make_client(monkeypatch, tmp_path, enabled=True)

    resumed = restarted_client.post(f"/api/wiki/review/{item.item_id}/approve", json=payload)

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "approved"
    receipt = resumed.json()["decision"]["promotion_receipt"]
    assert receipt["receipt_id"] == prepared.promotion_intent.operation_id
    versions = restarted_service.list_page_versions(item.target.page_id)
    promotion_versions = [entry for entry in versions if entry["action"] == "review_promote"]
    assert len(promotion_versions) == 1
    assert promotion_versions[0]["operation_id"] == receipt["receipt_id"]


def test_review_promotion_same_request_repairs_failed_version_history_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="version-repair-promotion",
        title="Version repair promotion",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    payload = page_review_decision_payload(item, reason="repair the audit entry")
    original_record_version = service._record_version
    failure_pending = True

    def fail_first_promotion_version(
        page: WikiPage,
        *,
        action: str,
        operation_id: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        nonlocal failure_pending
        if action == "review_promote" and failure_pending:
            failure_pending = False
            raise OSError("simulated version history write failure")
        original_record_version(
            page,
            action=action,
            operation_id=operation_id,
            content_hash=content_hash,
        )

    monkeypatch.setattr(service, "_record_version", fail_first_promotion_version)
    with pytest.raises(OSError, match="version history write failure"):
        client.post(f"/api/wiki/review/{item.item_id}/approve", json=payload)

    prepared = ReviewQueue(queue_path).get(item.item_id)
    assert prepared is not None
    assert prepared.status.value == "pending"
    assert prepared.promotion_intent is not None
    promoted_content = service.page_store.read_page(page_path)
    assert promoted_content is not None
    assert wiki_router._wiki_content_hash(str(promoted_content)) == prepared.promotion_intent.after_content_hash
    assert [entry["action"] for entry in service.list_page_versions(item.target.page_id)].count("review_promote") == 0

    resumed = client.post(f"/api/wiki/review/{item.item_id}/approve", json=payload)

    assert resumed.status_code == 200, resumed.text
    receipt = resumed.json()["decision"]["promotion_receipt"]
    promotion_versions = [
        entry
        for entry in service.list_page_versions(item.target.page_id)
        if entry["action"] == "review_promote"
    ]
    assert len(promotion_versions) == 1
    assert promotion_versions[0]["operation_id"] == receipt["receipt_id"]
    assert promotion_versions[0]["content_hash"] == receipt["after_content_hash"]


@pytest.mark.parametrize(
    ("request_id", "reason"),
    [
        ("different-request-id", "verified"),
        ("approve-conflicting-promotion", "changed decision details"),
    ],
    ids=["different-request", "different-fingerprint"],
)
def test_review_promotion_rejects_request_or_fingerprint_change_while_intent_is_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    request_id: str,
    reason: str,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="conflicting-promotion",
        title="Conflicting promotion",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    payload = page_review_decision_payload(item, reason="verified")
    before_content = service.page_store.read_page(page_path)
    assert before_content is not None
    prepared = interrupt_promotion_before_page_write(
        monkeypatch,
        client=client,
        queue_path=queue_path,
        item=item,
        payload=payload,
    )
    assert prepared.promotion_intent is not None

    conflict = client.post(
        f"/api/wiki/review/{item.item_id}/approve",
        json={**payload, "request_id": request_id, "reason": reason},
    )

    assert conflict.status_code == 409
    assert service.page_store.read_page(page_path) == before_content
    still_prepared = ReviewQueue(queue_path).get(item.item_id)
    assert still_prepared is not None
    assert still_prepared.status.value == "pending"
    assert still_prepared.promotion_intent == prepared.promotion_intent


def test_review_promotion_rejects_third_party_page_drift_from_pending_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, service, item, page_path = make_review_promotion_setup(
        monkeypatch,
        tmp_path,
        item_id="drifted-promotion",
        title="Drifted promotion",
    )
    queue_path = tmp_path / "runtime" / "review_queue.jsonl"
    payload = page_review_decision_payload(item, reason="verified before drift")
    prepared = interrupt_promotion_before_page_write(
        monkeypatch,
        client=client,
        queue_path=queue_path,
        item=item,
        payload=payload,
    )
    assert prepared.promotion_intent is not None
    page_file = service.page_store.wiki_root / page_path
    drifted_content = page_file.read_text(encoding="utf-8").replace(
        "Recoverable promotion body.",
        "Third-party edit after the promotion intent was persisted.",
    )
    page_file.write_text(drifted_content, encoding="utf-8")

    conflict = client.post(f"/api/wiki/review/{item.item_id}/approve", json=payload)

    assert conflict.status_code == 409
    assert "changed outside the pending promotion" in conflict.text
    assert page_file.read_text(encoding="utf-8") == drifted_content
    still_prepared = ReviewQueue(queue_path).get(item.item_id)
    assert still_prepared is not None
    assert still_prepared.status.value == "pending"
    assert still_prepared.promotion_intent == prepared.promotion_intent


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
