"""LMWR-477: query fallback and linked expansion tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from literature_assistant.core.wiki.page_store import WikiPageStore, render_page
from literature_assistant.core.wiki.query import WikiQueryIndex


@pytest.fixture
def query_index(tmp_path: Path) -> WikiQueryIndex:
    db_path = tmp_path / "query.db"
    idx = WikiQueryIndex(db_path)
    idx.initialize()
    return idx


@pytest.fixture
def page_store(tmp_path: Path) -> WikiPageStore:
    return WikiPageStore(tmp_path / "wiki")


def write_page(
    page_store: WikiPageStore,
    relative_path: str,
    *,
    title: str,
    kind: str = "concept",
    body: str = "Body.",
) -> None:
    frontmatter = {
        "id": relative_path.replace(".md", ""),
        "kind": kind,
        "title": title,
        "status": "draft",
    }
    page_store.write_rendered(render_page(Path(relative_path), frontmatter, body))


# --- Fallback bridge ---


def test_wiki_no_hits_returns_empty(query_index: WikiQueryIndex) -> None:
    results = query_index.search("nonexistent topic xyz")
    assert len(results) == 0


def test_wiki_partial_hits(query_index: WikiQueryIndex) -> None:
    query_index.index_page(Path("concepts/a.md"), "Alpha", "Alpha is about machine learning.")
    query_index.index_page(Path("concepts/b.md"), "Beta", "Beta covers deep learning.")
    results = query_index.search("machine learning")
    assert len(results) >= 1


def test_empty_query_returns_empty(query_index: WikiQueryIndex) -> None:
    results = query_index.search("")
    assert len(results) == 0


def test_zero_limit_returns_empty(query_index: WikiQueryIndex) -> None:
    query_index.index_page(Path("concepts/a.md"), "Alpha", "Alpha text.")
    results = query_index.search("Alpha", limit=0)
    assert len(results) == 0


# --- Index operations ---


def test_index_page_and_search(query_index: WikiQueryIndex) -> None:
    query_index.index_page(Path("concepts/test.md"), "Test Concept", "This is a test concept about retrieval.")
    results = query_index.search("retrieval")
    assert len(results) == 1
    assert results[0].title == "Test Concept"


def test_index_page_upsert(query_index: WikiQueryIndex) -> None:
    query_index.index_page(Path("concepts/test.md"), "V1", "Version one text.")
    query_index.index_page(Path("concepts/test.md"), "V2", "Version two text updated.")
    results = query_index.search("updated")
    assert len(results) == 1
    assert results[0].title == "V2"


def test_search_returns_snippet(query_index: WikiQueryIndex) -> None:
    query_index.index_page(Path("concepts/test.md"), "Test", "This is a long document about information retrieval systems.")
    results = query_index.search("information retrieval")
    assert len(results) >= 1
    assert results[0].snippet != ""


def test_search_limit(query_index: WikiQueryIndex) -> None:
    for i in range(20):
        query_index.index_page(Path(f"concepts/c{i:02d}.md"), f"Concept {i}", f"Concept number {i} about research.")
    results = query_index.search("research", limit=5)
    assert len(results) == 5


def test_index_status(query_index: WikiQueryIndex) -> None:
    query_index.index_page(Path("concepts/a.md"), "A", "Text A.")
    status = query_index.get_status()
    assert status.page_count >= 1
    assert status.index_hash != "none"


# --- Build wiki index from page store ---


def test_build_wiki_index(page_store: WikiPageStore, tmp_path: Path) -> None:
    write_page(page_store, "concepts/a.md", title="Alpha", body="Alpha is about machine learning.")
    write_page(page_store, "concepts/b.md", title="Beta", body="Beta covers deep learning networks.")
    db_path = tmp_path / "query.db"
    idx = WikiQueryIndex(db_path)
    idx.initialize()
    idx.build_wiki_index(page_store)
    results = idx.search("machine learning")
    assert len(results) >= 1


def test_build_wiki_index_empty(page_store: WikiPageStore, tmp_path: Path) -> None:
    db_path = tmp_path / "query.db"
    idx = WikiQueryIndex(db_path)
    idx.initialize()
    idx.build_wiki_index(page_store)
    results = idx.search("anything")
    assert len(results) == 0


# --- Warmup ---


def test_warmup_no_error(query_index: WikiQueryIndex) -> None:
    query_index.index_page(Path("concepts/a.md"), "A", "Test text.")
    query_index.warmup_common_queries()
    assert query_index._warmup_done is True


def test_warmup_idempotent(query_index: WikiQueryIndex) -> None:
    query_index.index_page(Path("concepts/a.md"), "A", "Test text.")
    query_index.warmup_common_queries()
    query_index.warmup_common_queries()
    assert query_index._warmup_done is True
