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

    def test_rebuild_index_removes_deleted_pages(
        self, page_store: WikiPageStore, index: WikiQueryIndex
    ) -> None:
        from literature_assistant.core.wiki.page_store import render_page

        rendered1 = render_page(Path("page1.md"), {"id": "page1", "kind": "concept", "title": "First"}, "First content.")
        rendered2 = render_page(Path("page2.md"), {"id": "page2", "kind": "concept", "title": "Second"}, "Second content.")
        page_store.write_rendered(rendered1)
        page_store.write_rendered(rendered2)
        build_wiki_index(page_store, index)

        page_store.resolve(Path("page2.md")).unlink()
        build_wiki_index(page_store, index)

        status = index.get_status()
        assert status.page_count == 1
        assert index.search("Second", limit=10) == []


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

    def test_expand_linked_pages_deduplicates_primary(self, page_store: WikiPageStore) -> None:
        from literature_assistant.core.wiki.page_store import render_page
        from literature_assistant.core.wiki.query import expand_linked_pages

        fm1 = {"id": "page1", "kind": "concept", "title": "Page 1"}
        fm2 = {"id": "page2", "kind": "concept", "title": "Page 2"}
        fm3 = {"id": "page3", "kind": "concept", "title": "Page 3"}
        rendered1 = render_page(Path("page1.md"), fm1, "Links to [[page2.md]] and [[page3.md]].")
        rendered2 = render_page(Path("page2.md"), fm2, "Links back to [[page1.md]].")
        rendered3 = render_page(Path("page3.md"), fm3, "Independent content.")
        page_store.write_rendered(rendered1)
        page_store.write_rendered(rendered2)
        page_store.write_rendered(rendered3)

        primary_results = [
            WikiSearchResult(page_path=Path("page1.md"), title="Page 1", score=1.0, snippet=""),
            WikiSearchResult(page_path=Path("page2.md"), title="Page 2", score=0.8, snippet=""),
        ]
        expanded = expand_linked_pages(primary_results, page_store, max_linked=5)
        expanded_paths = {r.page_path for r in expanded}
        assert Path("page1.md") not in expanded_paths
        assert Path("page2.md") not in expanded_paths
        assert Path("page3.md") in expanded_paths

    def test_expand_linked_pages_ranks_shared_link_first(self, page_store: WikiPageStore) -> None:
        from literature_assistant.core.wiki.page_store import render_page
        from literature_assistant.core.wiki.query import expand_linked_pages

        page_store.write_rendered(
            render_page(
                Path("concept/primary-a.md"),
                {"id": "primary-a", "kind": "concept", "title": "Primary A"},
                "Links to [[shared-target]] and [[single-target]].",
            )
        )
        page_store.write_rendered(
            render_page(
                Path("concept/primary-b.md"),
                {"id": "primary-b", "kind": "concept", "title": "Primary B"},
                "Links to [[shared-target]].",
            )
        )
        page_store.write_rendered(
            render_page(
                Path("concept/shared-target.md"),
                {"id": "shared", "kind": "concept", "title": "Shared Target"},
                "Shared linked page.",
            )
        )
        page_store.write_rendered(
            render_page(
                Path("concept/single-target.md"),
                {"id": "single", "kind": "concept", "title": "Single Target"},
                "Single linked page.",
            )
        )

        expanded = expand_linked_pages(
            [
                WikiSearchResult(
                    page_path=Path("concept/primary-a.md"),
                    title="Primary A",
                    score=1.0,
                    snippet="",
                ),
                WikiSearchResult(
                    page_path=Path("concept/primary-b.md"),
                    title="Primary B",
                    score=0.9,
                    snippet="",
                ),
            ],
            page_store,
            max_linked=2,
        )

        assert [item.page_path for item in expanded] == [
            Path("concept/shared-target.md"),
            Path("concept/single-target.md"),
        ]


class TestWikiQueryWithFallback:
    @pytest.fixture
    def setup(self, tmp_path: Path) -> tuple[WikiQueryIndex, WikiPageStore]:
        from literature_assistant.core.wiki.page_store import render_page

        wiki_root = tmp_path / "wiki"
        page_store = WikiPageStore(wiki_root)
        fm1 = {"id": "page1", "kind": "concept", "title": "Test Page"}
        rendered1 = render_page(Path("page1.md"), fm1, "Test content.")
        page_store.write_rendered(rendered1)

        db_path = tmp_path / "wiki_index.db"
        idx = WikiQueryIndex(db_path)
        idx.initialize()
        idx.index_page(Path("page1.md"), "Test Page", "Test content.")
        return idx, page_store

    def test_wiki_query_with_fallback_no_hits(self, setup: tuple[WikiQueryIndex, WikiPageStore]) -> None:
        from literature_assistant.core.wiki.query import wiki_query_with_fallback

        index, page_store = setup
        result = wiki_query_with_fallback("Nonexistent", index, page_store, enabled=True)
        assert result.fallback_used
        assert result.fallback_reason == "no wiki hits"
        assert len(result.wiki_hits) == 0

    def test_wiki_query_with_fallback_with_hits(self, setup: tuple[WikiQueryIndex, WikiPageStore]) -> None:
        from literature_assistant.core.wiki.query import wiki_query_with_fallback

        index, page_store = setup
        result = wiki_query_with_fallback("Test", index, page_store, enabled=True)
        assert not result.fallback_used
        assert len(result.wiki_hits) == 1


class TestRenderContextPack:
    @pytest.fixture
    def context_page_store(self, tmp_path: Path) -> WikiPageStore:
        from literature_assistant.core.wiki.page_store import render_page

        wiki_root = tmp_path / "wiki"
        print(f"[FIXTURE] Creating WikiPageStore at {wiki_root}")
        store = WikiPageStore(wiki_root)
        fm1 = {"id": "page1", "kind": "concept", "title": "Page 1"}
        fm2 = {"id": "page2", "kind": "concept", "title": "Page 2"}
        rendered1 = render_page(Path("page1.md"), fm1, "Content of page 1.")
        rendered2 = render_page(Path("page2.md"), fm2, "Content of page 2.")
        print(f"[FIXTURE] Writing page1.md")
        store.write_rendered(rendered1)
        print(f"[FIXTURE] Writing page2.md")
        store.write_rendered(rendered2)

        # Verify files were written
        page1_path = store.wiki_root / "page1.md"
        page2_path = store.wiki_root / "page2.md"
        print(f"[FIXTURE] page1.md exists: {page1_path.exists()}")
        print(f"[FIXTURE] page2.md exists: {page2_path.exists()}")
        assert page1_path.exists(), f"page1.md not found at {page1_path}"
        assert page2_path.exists(), f"page2.md not found at {page2_path}"

        return store

    def test_render_context_pack_basic(self, context_page_store: WikiPageStore) -> None:
        from literature_assistant.core.wiki.query import WikiQueryResult, render_context_pack

        # Debug: verify page exists
        print(f"Wiki root: {context_page_store.wiki_root}")
        print(f"Wiki root exists: {context_page_store.wiki_root.exists()}")
        print(f"page1.md path: {context_page_store.wiki_root / 'page1.md'}")
        print(f"page1.md exists: {(context_page_store.wiki_root / 'page1.md').exists()}")

        content = context_page_store.read_page(Path("page1.md"))
        print(f"Read content: {content[:100] if content else 'None'}")
        assert content is not None, "page1.md should exist"

        query_result = WikiQueryResult(
            wiki_hits=[
                WikiSearchResult(page_path=Path("page1.md"), title="Page 1", score=1.0, snippet="")
            ],
            linked_hits=[],
            fallback_used=False,
            fallback_reason="",
        )
        pack = render_context_pack("test query", query_result, context_page_store, max_tokens=1000)
        assert pack.query == "test query"
        assert len(pack.primary_pages) == 1, f"Expected 1 primary page, got {len(pack.primary_pages)}"
        assert "Page 1" in pack.primary_pages[0]
        assert "Content of page 1" in pack.primary_pages[0]
        assert not pack.truncated

    def test_render_context_pack_with_linked(self, context_page_store: WikiPageStore) -> None:
        from literature_assistant.core.wiki.query import WikiQueryResult, render_context_pack

        query_result = WikiQueryResult(
            wiki_hits=[
                WikiSearchResult(page_path=Path("page1.md"), title="Page 1", score=1.0, snippet="")
            ],
            linked_hits=[
                WikiSearchResult(page_path=Path("page2.md"), title="Page 2", score=0.5, snippet="")
            ],
            fallback_used=False,
            fallback_reason="",
        )
        pack = render_context_pack("test query", query_result, context_page_store, max_tokens=2000)
        assert len(pack.primary_pages) == 1
        assert len(pack.linked_pages) == 1
        assert "Page 2" in pack.linked_pages[0]
        assert "(linked)" in pack.linked_pages[0]

    def test_render_context_pack_truncates(self, context_page_store: WikiPageStore) -> None:
        from literature_assistant.core.wiki.query import WikiQueryResult, render_context_pack

        query_result = WikiQueryResult(
            wiki_hits=[
                WikiSearchResult(page_path=Path("page1.md"), title="Page 1", score=1.0, snippet=""),
                WikiSearchResult(page_path=Path("page2.md"), title="Page 2", score=0.9, snippet=""),
            ],
            linked_hits=[],
            fallback_used=False,
            fallback_reason="",
        )
        pack = render_context_pack("test query", query_result, context_page_store, max_tokens=10)
        assert pack.truncated
        assert len(pack.primary_pages) < 2
        assert pack.omitted_pages

    def test_render_context_pack_records_missing_pages_as_omitted(self, context_page_store: WikiPageStore) -> None:
        from literature_assistant.core.wiki.query import WikiQueryResult, render_context_pack

        query_result = WikiQueryResult(
            wiki_hits=[
                WikiSearchResult(page_path=Path("missing.md"), title="Missing", score=1.0, snippet=""),
            ],
            linked_hits=[],
            fallback_used=False,
            fallback_reason="",
        )

        pack = render_context_pack("test query", query_result, context_page_store, max_tokens=100)

        assert pack.primary_pages == []
        assert pack.omitted_pages == ["missing.md"]


class TestBuildQueryTrace:
    def test_build_query_trace_with_hits(self) -> None:
        from literature_assistant.core.wiki.query import (
            WikiQueryResult,
            WikiContextPack,
            build_query_trace,
        )

        query_result = WikiQueryResult(
            wiki_hits=[
                WikiSearchResult(page_path=Path("p1.md"), title="P1", score=1.0, snippet="")
            ],
            linked_hits=[
                WikiSearchResult(page_path=Path("p2.md"), title="P2", score=0.5, snippet="")
            ],
            fallback_used=False,
            fallback_reason="",
        )
        context_pack = WikiContextPack(
            query="test", primary_pages=["page1"], linked_pages=["page2"], total_tokens=100, truncated=False
        )
        trace = build_query_trace("test", query_result, context_pack, enabled=True)
        assert trace.query == "test"
        assert trace.enabled
        assert trace.fts_hits == 1
        assert trace.linked_hits == 1
        assert not trace.fallback_used
        assert trace.total_pages == 2
        assert trace.context_tokens == 100
        assert trace.context_max_tokens == 0
        assert not trace.context_truncated

    def test_build_query_trace_fallback(self) -> None:
        from literature_assistant.core.wiki.query import WikiQueryResult, build_query_trace

        query_result = WikiQueryResult(
            wiki_hits=[],
            linked_hits=[],
            fallback_used=True,
            fallback_reason="no wiki hits",
        )
        trace = build_query_trace("test", query_result, None, enabled=True)
        assert trace.fallback_used
        assert trace.fallback_reason == "no wiki hits"
        assert trace.fts_hits == 0
        assert trace.total_pages == 0
        assert trace.context_tokens == 0

    def test_write_query_trace_omits_plain_query(self, tmp_path: Path) -> None:
        from literature_assistant.core.wiki.query import WikiQueryResult, build_query_trace, write_query_trace

        query_result = WikiQueryResult(
            wiki_hits=[],
            linked_hits=[],
            fallback_used=True,
            fallback_reason="no wiki hits",
        )
        trace = build_query_trace("secret research question", query_result, None, enabled=True)

        trace_path = write_query_trace(trace, trace_dir=tmp_path)
        payload = trace_path.read_text(encoding="utf-8")

        assert trace_path.exists()
        assert "secret research question" not in payload
        assert "query_hash" in payload




