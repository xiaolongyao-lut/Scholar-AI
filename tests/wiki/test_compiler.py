from __future__ import annotations

from pathlib import Path

import pytest

from literature_assistant.core.wiki.compiler import (
    CompileBudget,
    CompilePricing,
    CompileResult,
    WikiCompiler,
    check_compile_budget,
    compile_pricing_from_env,
    estimate_compile_cost,
)
from literature_assistant.core.wiki.page_store import WikiPageStore
from literature_assistant.core.wiki.source_registry import (
    ChunkInput,
    SourceRecord,
    WikiRegistry,
    utc_now_iso,
)


class TestWikiCompiler:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> WikiRegistry:
        db_path = tmp_path / "test.db"
        reg = WikiRegistry(db_path)
        record = SourceRecord("src1", "paper", "Test Paper", "hash1", Path("/test.pdf"))
        reg.upsert_source(record, now_iso=utc_now_iso())
        chunks = [
            ChunkInput(text="First chunk text", chunk_index=0, page="1"),
            ChunkInput(text="Second chunk text", chunk_index=1, page="2"),
        ]
        reg.register_chunks("src1", "hash1", chunks, now_iso=utc_now_iso())
        return reg

    @pytest.fixture
    def page_store(self, tmp_path: Path) -> WikiPageStore:
        wiki_root = tmp_path / "wiki"
        return WikiPageStore(wiki_root)

    @pytest.fixture
    def compiler(self, registry: WikiRegistry, page_store: WikiPageStore) -> WikiCompiler:
        return WikiCompiler(registry, page_store)

    def test_compile_source_creates_page(
        self, compiler: WikiCompiler, page_store: WikiPageStore
    ) -> None:
        result = compiler.compile_source("src1")
        assert result.created == 1
        assert result.errors == []
        page_path = Path("sources/test-paper.md")
        content = page_store.read_page(page_path)
        assert content is not None
        assert "Test Paper" in content
        assert "hash1" in content

    def test_compile_source_dry_run(self, compiler: WikiCompiler, page_store: WikiPageStore) -> None:
        result = compiler.compile_source("src1", dry_run=True)
        assert result.created == 1
        assert result.cost_estimate.input_tokens > 0
        assert result.cost_estimate.estimated_cost_usd == 0.0
        assert result.budget_checks[0].source_id == "src1"
        page_path = Path("sources/test-paper.md")
        content = page_store.read_page(page_path)
        assert content is None

    def test_compile_source_not_found(self, compiler: WikiCompiler) -> None:
        result = compiler.compile_source("missing")
        assert result.created == 0
        assert len(result.errors) == 1
        assert "not found" in result.errors[0].lower()

    def test_compile_paper_creates_draft(
        self, compiler: WikiCompiler, page_store: WikiPageStore
    ) -> None:
        result = compiler.compile_paper("src1")
        assert result.created == 1
        page_path = Path("papers/test-paper.md")
        content = page_store.read_page(page_path)
        assert content is not None
        assert "Test Paper" in content
        assert "draft" in content.lower()

    def test_compile_paper_dry_run(self, compiler: WikiCompiler, page_store: WikiPageStore) -> None:
        result = compiler.compile_paper("src1", dry_run=True)
        assert result.created == 1
        page_path = Path("papers/test-paper.md")
        content = page_store.read_page(page_path)
        assert content is None

    def test_compile_paper_skips_non_paper(self, registry: WikiRegistry, compiler: WikiCompiler) -> None:
        record = SourceRecord("src2", "web", "Web Page", "hash2", Path("/web.html"))
        registry.upsert_source(record, now_iso=utc_now_iso())
        result = compiler.compile_paper("src2")
        assert result.created == 0
        assert result.skipped == 1

    def test_compile_project(self, compiler: WikiCompiler, page_store: WikiPageStore) -> None:
        result = compiler.compile_project()
        assert result.created == 2
        assert result.errors == []
        source_page = page_store.read_page(Path("sources/test-paper.md"))
        paper_page = page_store.read_page(Path("papers/test-paper.md"))
        assert source_page is not None
        assert paper_page is not None

    def test_compile_project_dry_run(self, compiler: WikiCompiler, page_store: WikiPageStore) -> None:
        result = compiler.compile_project(dry_run=True)
        assert result.created == 2
        source_page = page_store.read_page(Path("sources/test-paper.md"))
        paper_page = page_store.read_page(Path("papers/test-paper.md"))
        assert source_page is None
        assert paper_page is None

    def test_compile_source_refuses_over_budget_input_without_writing(
        self,
        registry: WikiRegistry,
        page_store: WikiPageStore,
    ) -> None:
        compiler = WikiCompiler(registry, page_store, budget=CompileBudget(max_source_chunks=1))

        result = compiler.compile_source("src1")

        assert result.created == 0
        assert result.skipped == 1
        assert "Compile budget exceeded" in result.errors[0]
        assert result.cost_estimate.input_tokens > 0
        assert result.budget_checks[0].over_budget is True
        assert page_store.read_page(Path("sources/test-paper.md")) is None

    def test_compile_source_dry_run_still_reports_budget_refusal(
        self,
        registry: WikiRegistry,
        page_store: WikiPageStore,
    ) -> None:
        compiler = WikiCompiler(registry, page_store, budget=CompileBudget(max_total_chunk_chars=10))

        result = compiler.compile_source("src1", dry_run=True)

        assert result.created == 0
        assert result.skipped == 1
        assert "max_total_chunk_chars" in result.errors[0]
        assert result.cost_estimate.input_tokens > 0
        assert result.cost_estimate.pricing_source == "not_configured"
        assert page_store.read_page(Path("sources/test-paper.md")) is None

    def test_compile_source_dry_run_reports_configured_cost_estimate(
        self,
        registry: WikiRegistry,
        page_store: WikiPageStore,
    ) -> None:
        compiler = WikiCompiler(
            registry,
            page_store,
            pricing=CompilePricing(
                input_usd_per_1m_tokens=1.0,
                output_usd_per_1m_tokens=2.0,
                estimated_output_tokens_per_source=1000,
                pricing_source="test-rate",
            ),
        )

        result = compiler.compile_source("src1", dry_run=True)

        assert result.cost_estimate.pricing_configured is True
        assert result.cost_estimate.pricing_source == "test-rate"
        assert result.cost_estimate.output_tokens == 1000
        assert result.cost_estimate.estimated_cost_usd > 0
        assert result.to_dict()["cost_estimate"] == result.cost_estimate.to_dict()

    def test_plan_compile(self, compiler: WikiCompiler) -> None:
        plan = compiler.plan_compile()
        assert len(plan.pages_to_create) == 2
        assert Path("sources/test-paper.md") in plan.pages_to_create
        assert Path("papers/test-paper.md") in plan.pages_to_create
        assert len(plan.pages_to_update) == 0
        assert len(plan.pages_to_skip) == 0

    def test_plan_compile_after_compile(self, compiler: WikiCompiler) -> None:
        compiler.compile_project()
        plan = compiler.plan_compile()
        assert len(plan.pages_to_create) == 0
        assert len(plan.pages_to_update) == 1
        assert len(plan.pages_to_skip) == 1


def test_check_compile_budget_returns_estimate_for_valid_input() -> None:
    check = check_compile_budget(
        "src1",
        [{"text": "abcd efgh"}],
        CompileBudget(max_source_chunks=5, max_total_chunk_chars=100, max_estimated_tokens=10, chars_per_token=4.0),
    )

    assert check.over_budget is False
    assert check.source_chunks == 1
    assert check.total_chunk_chars == 9
    assert check.estimated_tokens == 2


def test_estimate_compile_cost_sums_budget_checks_with_configured_rates() -> None:
    checks = [
        check_compile_budget(
            "src1",
            [{"text": "abcd efgh"}],
            CompileBudget(max_source_chunks=5, max_total_chunk_chars=100, max_estimated_tokens=10, chars_per_token=4.0),
        )
    ]

    estimate = estimate_compile_cost(
        checks,
        CompilePricing(
            input_usd_per_1m_tokens=1.0,
            output_usd_per_1m_tokens=2.0,
            estimated_output_tokens_per_source=1000,
            pricing_source="test-rate",
        ),
    )

    assert estimate.input_tokens == 2
    assert estimate.output_tokens == 1000
    assert estimate.total_tokens == 1002
    assert estimate.estimated_cost_usd == 0.002002


def test_compile_pricing_from_env_rejects_invalid_rates() -> None:
    with pytest.raises(ValueError, match="INPUT_USD"):
        compile_pricing_from_env({"LITERATURE_ASSISTANT_WIKI_COMPILE_INPUT_USD_PER_1M_TOKENS": "-1"})
