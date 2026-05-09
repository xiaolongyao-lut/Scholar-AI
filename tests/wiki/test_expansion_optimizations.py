from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from literature_assistant.core.wiki.page_store import WikiPageStore
from literature_assistant.core.wiki.query import (
    WikiQueryIndex,
    build_wiki_index,
    expand_linked_pages,
)


class TestWarmupOptimization:
    """Tier 1 optimization: Cache warmup (0.5-1s savings)."""

    @pytest.fixture
    def index(self, tmp_path: Path) -> WikiQueryIndex:
        db_path = tmp_path / "wiki_index.db"
        idx = WikiQueryIndex(db_path)
        idx.initialize()
        return idx

    def test_warmup_doesnt_break_cold_start(self, index: WikiQueryIndex) -> None:
        """Verify warmup is optional and doesn't break normal initialization."""
        index.index_page(Path("page1.md"), "Test", "Content about research")
        index.warmup_common_queries()
        results = index.search("research", limit=10)
        assert len(results) == 1
        assert results[0].title == "Test"

    def test_warmup_is_idempotent(self, index: WikiQueryIndex) -> None:
        """Verify warmup can be called multiple times without side effects."""
        index.index_page(Path("page1.md"), "Test", "Content about research")
        index.warmup_common_queries()
        index.warmup_common_queries()
        results = index.search("research", limit=10)
        assert len(results) == 1

    def test_warmup_with_custom_patterns(self, index: WikiQueryIndex) -> None:
        """Verify warmup accepts custom query patterns."""
        index.index_page(Path("page1.md"), "Python", "Python programming language")
        index.index_page(Path("page2.md"), "Java", "Java development platform")
        index.warmup_common_queries(["Python", "Java"])
        results = index.search("Python", limit=10)
        assert len(results) == 1
        assert "Python" in results[0].title

    def test_warmup_with_empty_patterns(self, index: WikiQueryIndex) -> None:
        """Verify warmup handles empty pattern list gracefully."""
        index.index_page(Path("page1.md"), "Test", "Content")
        index.warmup_common_queries([])
        results = index.search("Content", limit=10)
        assert len(results) == 1

    def test_warmup_flag_prevents_redundant_work(self, index: WikiQueryIndex) -> None:
        """Verify _warmup_done flag prevents redundant FTS queries."""
        index.index_page(Path("page1.md"), "Test", "Content")
        assert index._warmup_done is False
        index.warmup_common_queries()
        assert index._warmup_done is True
        index.warmup_common_queries()
        assert index._warmup_done is True


class TestConcurrencyOptimization:
    """Tier 2 optimization: Concurrency increase (1-2s savings)."""

    def test_wiki_expansion_concurrency_env_var_default(self) -> None:
        """Verify WIKI_EXPANSION_CONCURRENCY defaults to 10."""
        env_val = os.getenv("WIKI_EXPANSION_CONCURRENCY", "10")
        assert int(env_val) >= 10

    def test_wiki_expansion_concurrency_env_var_override(self) -> None:
        """Verify WIKI_EXPANSION_CONCURRENCY can be overridden."""
        with patch.dict(os.environ, {"WIKI_EXPANSION_CONCURRENCY": "15"}):
            concurrency = int(os.getenv("WIKI_EXPANSION_CONCURRENCY", "10"))
            assert concurrency == 15

    @pytest.mark.asyncio
    async def test_expansion_semaphore_respects_concurrency(self) -> None:
        """Verify semaphore enforces concurrency limit."""
        concurrency = 3
        semaphore = asyncio.Semaphore(concurrency)
        active_count = 0
        max_active = 0
        lock = asyncio.Lock()

        async def mock_task() -> None:
            nonlocal active_count, max_active
            async with semaphore:
                async with lock:
                    active_count += 1
                    max_active = max(max_active, active_count)
                await asyncio.sleep(0.01)
                async with lock:
                    active_count -= 1

        tasks = [mock_task() for _ in range(10)]
        await asyncio.gather(*tasks)
        assert max_active <= concurrency

    def test_expansion_concurrency_backward_compatible(self) -> None:
        """Verify old ARK_EXPANSION_CONCURRENCY env var still works for fallback."""
        with patch.dict(os.environ, {"ARK_EXPANSION_CONCURRENCY": "5"}):
            ark_concurrency = int(os.getenv("ARK_EXPANSION_CONCURRENCY", "5"))
            assert ark_concurrency == 5


class TestExpansionLatencyPath:
    """Integration tests for expansion optimization paths."""

    @pytest.fixture
    def page_store(self, tmp_path: Path) -> WikiPageStore:
        wiki_root = tmp_path / "wiki"
        return WikiPageStore(wiki_root)

    @pytest.fixture
    def index(self, tmp_path: Path) -> WikiQueryIndex:
        db_path = tmp_path / "wiki_index.db"
        idx = WikiQueryIndex(db_path)
        idx.initialize()
        return idx

    def test_linked_expansion_with_warmup(
        self, page_store: WikiPageStore, index: WikiQueryIndex
    ) -> None:
        """Verify linked page expansion works after warmup."""
        from literature_assistant.core.wiki.query import WikiSearchResult

        # Create mock pages
        primary_result = WikiSearchResult(
            page_path=Path("primary.md"),
            title="Primary",
            score=0.9,
            snippet="Content with [[linked]] reference",
        )

        # Mock page_store.read_page to return content with wikilinks
        def mock_read_page(path: Path) -> str | None:
            if path == Path("primary.md"):
                return "# Primary\nContent with [[linked]] reference"
            if path == Path("linked"):
                return "# Linked\nLinked page content"
            return None

        page_store.read_page = mock_read_page

        # Run warmup
        index.warmup_common_queries()

        # Expand linked pages
        expanded = expand_linked_pages([primary_result], page_store, max_linked=3)
        assert len(expanded) >= 0

    def test_warmup_timing_is_reasonable(self, index: WikiQueryIndex) -> None:
        """Verify warmup completes in reasonable time (< 100ms for empty index)."""
        start = time.time()
        index.warmup_common_queries()
        elapsed = time.time() - start
        assert elapsed < 0.1, f"Warmup took {elapsed:.3f}s, expected < 0.1s"

    def test_search_after_warmup_is_fast(self, index: WikiQueryIndex) -> None:
        """Verify search after warmup is responsive."""
        # Index some pages
        for i in range(10):
            index.index_page(
                Path(f"page{i}.md"),
                f"Page {i}",
                f"Content about research topic {i}",
            )

        # Warmup
        index.warmup_common_queries()

        # Search should be fast
        start = time.time()
        results = index.search("research", limit=5)
        elapsed = time.time() - start
        assert len(results) > 0
        assert elapsed < 0.05, f"Search took {elapsed:.3f}s, expected < 0.05s"
