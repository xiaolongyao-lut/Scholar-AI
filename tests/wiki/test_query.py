from __future__ import annotations

from pathlib import Path

import pytest

from literature_assistant.core.wiki.page_store import WikiPageStore
from literature_assistant.core.wiki.query import (
    WikiQueryIndex,
    WikiSearchResult,
    build_wiki_index,
    wiki_first_search,
)


class TestWikiQueryIndex:
    @pytest.fixture
    def index(self, tmp_path: Path) -> WikiQueryIndex:
        db_path = tmp_path / "wiki_index.db"
        idx = WikiQueryIndex(db_path)
        idx.initialize()
        return idx

    def test_initialize_creates_tables(self, index: WikiQueryIndex) -> None:
        status = index.get_status()
        assert status.page_count == 0
        assert status.index_hash == "none"

    def test_index_page(self, index: WikiQueryIndex) -> None:
        index.index_page(Path("test.md"), "Test Page", "This is test content.")
        status = index.get_status()
        assert status.page_count == 1

    def test_search_returns_results(self, index: WikiQueryIndex) -> None:
        index.index_page(Path("page1.md"), "First Page", "Content about Python programming.")
        index.index_page(Path("page2.md"), "Second Page", "Content about Java development.")
        results = index.search("Python", limit=10)
        assert len(results) == 1
        assert results[0].title == "First Page"
        assert "Python" in results[0].snippet

    def test_search_ranks_by_relevance(self, index: WikiQueryIndex) -> None:
        index.index_page(Path("page1.md"), "Python Guide", "Python Python Python")
        index.index_page(Path("page2.md"), "Programming", "Python is a language")
        results = index.search("Python", limit=10)
        assert len(results) == 2
        assert results[0].title == "Python Guide"

    def test_search_empty_query(self, index: WikiQueryIndex) -> None:
        index.index_page(Path("page1.md"), "Test", "Content")
        results = index.search("", limit=10)
        assert len(results) == 0


class TestBuildWikiIndex:
    @pytest.fixture
    def page_store(self, tmp_path: Path) -> WikiPageStore:
        wiki_root = tmp_path / "wiki"
        return WikiPageStore(wiki_root)

    @pytest.fixture
    def index(self, tmp_path: Path) -> WikiQueryIndex:
        db_path = tmp_path / "wiki_index.db"
        return WikiQueryIndex(db_path)

    def test_build_index_from_pages(
        self, page_store: WikiPageStore, index: WikiQueryIndex
    ) -> None:
        from literature_assistant.core.wiki.page_store import render_page

        frontmatter = {"id": "test1", "kind": "concept", "title": "Test Page"}
        rendered = render_page(Path("test.md"), frontmatter, "Test content.")
        page_store.write_rendered(rendered)
        build_wiki_index(page_store, index)
        status = index.get_status()
        assert status.page_count == 1
        results = index.search("Test", limit=10)
        assert len(results) == 1
        assert results[0].title == "Test Page"

    def test_build_index_multiple_pages(
        self, page_store: WikiPageStore, index: WikiQueryIndex
    ) -> None:
        from literature_assistant.core.wiki.page_store import render_page

        frontmatter1 = {"id": "page1", "kind": "concept", "title": "First"}
        frontmatter2 = {"id": "page2", "kind": "concept", "title": "Second"}
        rendered1 = render_page(Path("page1.md"), frontmatter1, "First content.")
        rendered2 = render_page(Path("page2.md"), frontmatter2, "Second content.")
        page_store.write_rendered(rendered1)
        page_store.write_rendered(rendered2)
        build_wiki_index(page_store, index)
        status = index.get_status()
        assert status.page_count == 2


class TestWikiFirstSearch:
    @pytest.fixture
    def index(self, tmp_path: Path) -> WikiQueryIndex:
        db_path = tmp_path / "wiki_index.db"
        idx = WikiQueryIndex(db_path)
        idx.initialize()
        idx.index_page(Path("test.md"), "Test Page", "Test content.")
        return idx

    def test_wiki_first_disabled(self, index: WikiQueryIndex) -> None:
        results, found = wiki_first_search("Test", index, enabled=False)
        assert not found
        assert len(results) == 0

    def test_wiki_first_enabled_with_results(self, index: WikiQueryIndex) -> None:
        results, found = wiki_first_search("Test", index, enabled=True, limit=5)
        assert found
        assert len(results) == 1
        assert results[0].title == "Test Page"

    def test_wiki_first_enabled_no_results(self, index: WikiQueryIndex) -> None:
        results, found = wiki_first_search("Nonexistent", index, enabled=True, limit=5)
        assert not found
        assert len(results) == 0


class TestExpandLinkedPages:
    @pytest.fixture
    def page_store(self, tmp_path: Path) -> WikiPageStore:
        wiki_root = tmp_path / "wiki"
        return WikiPageStore(wiki_root)

    def test_expand_linked_pages(self, page_store: WikiPageStore) -> None:
        from literature_assistant.core.wiki.page_store import render_page
        from literature_assistant.core.wiki.query import expand_linked_pages

        fm1 = {"id": "page1", "kind": "concept", "title": "Page 1"}
        fm2 = {"id": "page2", "kind": "concept", "title": "Page 2"}
        rendered1 = render_page(Path("page1.md"), fm1, "Content with [[page2.md]] link.")
        rendered2 = render_page(Path("page2.md"), fm2, "Linked content.")
        page_store.write_rendered(rendered1)
        page_store.write_rendered(rendered2)

        primary_results = [
            WikiSearchResult(
                page_path=Path("page1.md"),
                title="Page 1",
                score=1.0,
                snippet="Content with link",
            )
        ]
        expanded = expand_linked_pages(primary_results, page_store, max_linked=3)
        assert len(expanded) == 1
        assert expanded[0].page_path == Path("page2.md")
        assert expanded[0].title == "Page 2"

    def test_expand_linked_pages_no_links(self, page_store: WikiPageStore) -> None:
        from literature_assistant.core.wiki.page_store import render_page
        from literature_assistant.core.wiki.query import expand_linked_pages

        fm1 = {"id": "page1", "kind": "concept", "title": "Page 1"}
        rendered1 = render_page(Path("page1.md"), fm1, "Content without links.")
        page_store.write_rendered(rendered1)

        primary_results = [
            WikiSearchResult(
                page_path=Path("page1.md"),
                title="Page 1",
                score=1.0,
                snippet="Content",
            )
        ]
        expanded = expand_linked_pages(primary_results, page_store, max_linked=3)
        assert len(expanded) == 0


class TestWikiQueryWithFallback:
    @pytest.fixture
    def index(self, tmp_path: Path) -> WikiQueryIndex:
        db_path = tmp_path / "wiki_index.db"
        idx = WikiQueryIndex(db_path)
        idx.initialize()
        idx.index_page(Path("test.md"), "Test Page", "Test content.")
        return idx

    @pytest.fixture
    def page_store(self, tmp_path: Path) -> WikiPageStore:
        wiki_root = tmp_path / "wiki"
        return WikiPageStore(wiki_root)

    def test_wiki_query_with_fallback_no_hits(
        self, index: WikiQueryIndex, page_store: WikiPageStore
    ) -> None:
        from literature_assistant.core.wiki.query import wiki_query_with_fallback

        result = wiki_query_with_fallback(
            "Nonexistent", index, page_store, enabled=True, limit=5
        )
        assert result.fallback_used
        assert result.fallback_reason == "no wiki hits"
        assert len(result.wiki_hits) == 0

    def test_wiki_query_with_fallback_with_hits(
        self, index: WikiQueryIndex, page_store: WikiPageStore
    ) -> None:
        from literature_assistant.core.wiki.page_store import render_page
        from literature_assistant.core.wiki.query import wiki_query_with_fallback

        fm = {"id": "test1", "kind": "concept", "title": "Test Page"}
        rendered = render_page(Path("test.md"), fm, "Test content.")
        page_store.write_rendered(rendered)

        result = wiki_query_with_fallback(
            "Test", index, page_store, enabled=True, limit=5
        )
        assert not result.fallback_used
        assert len(result.wiki_hits) == 1
        assert result.wiki_hits[0].title == "Test Page"
