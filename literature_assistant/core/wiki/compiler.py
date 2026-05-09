from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from literature_assistant.core.wiki.llm_gateway import LLMGateway, LLMRequest, validate_json_response
from literature_assistant.core.wiki.models import WikiPageKind, WikiPageStatus
from literature_assistant.core.wiki.page_store import (
    WikiPageStore,
    render_page,
    stable_slug,
)
from literature_assistant.core.wiki.observability import WikiObservabilitySink
from literature_assistant.core.wiki.source_registry import WikiRegistry


def _load_prompt_template(name: str) -> str:
    """Load a prompt template from the prompt_templates directory.

    Templates live in ``literature_assistant/core/prompt_templates/`` and
    are named ``wiki_<name>.txt``.
    """
    template_dir = Path(__file__).resolve().parent.parent / "prompt_templates"
    path = template_dir / f"wiki_{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class CompileBudget:
    """Hard limits for deterministic and future LLM-backed wiki compile paths."""

    max_source_chunks: int = 100
    max_total_chunk_chars: int = 50000
    max_estimated_tokens: int = 12500
    chars_per_token: float = 4.0


@dataclass(frozen=True)
class CompileBudgetCheck:
    """Budget decision for one source compile input."""

    source_id: str
    source_chunks: int
    total_chunk_chars: int
    estimated_tokens: int
    over_budget: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_chunks": self.source_chunks,
            "total_chunk_chars": self.total_chunk_chars,
            "estimated_tokens": self.estimated_tokens,
            "over_budget": self.over_budget,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CompilePricing:
    """Pricing inputs for compile dry-run estimates.

    Rates are explicit configuration values because provider prices change over
    time and must be verified against the selected model before production use.
    """

    input_usd_per_1m_tokens: float = 0.0
    output_usd_per_1m_tokens: float = 0.0
    estimated_output_tokens_per_source: int = 0
    pricing_source: str = "not_configured"
    currency: str = "USD"


@dataclass(frozen=True)
class CompileCostEstimate:
    """Token and cost estimate for a compile dry-run result.

    The estimate is a planning artifact, not a billing record. It intentionally
    separates input/output rates so a caller can inject current provider prices.
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    estimated_cost_usd: float
    input_usd_per_1m_tokens: float
    output_usd_per_1m_tokens: float
    pricing_configured: bool
    pricing_source: str
    currency: str = "USD"

    def to_dict(self) -> dict[str, object]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cost_usd": self.input_cost_usd,
            "output_cost_usd": self.output_cost_usd,
            "estimated_cost_usd": self.estimated_cost_usd,
            "input_usd_per_1m_tokens": self.input_usd_per_1m_tokens,
            "output_usd_per_1m_tokens": self.output_usd_per_1m_tokens,
            "pricing_configured": self.pricing_configured,
            "pricing_source": self.pricing_source,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class CompilePlan:
    pages_to_create: list[Path]
    pages_to_update: list[Path]
    pages_to_skip: list[Path]


@dataclass(frozen=True)
class CompileResult:
    created: int
    updated: int
    skipped: int
    errors: list[str]
    budget_checks: list[CompileBudgetCheck] = field(default_factory=list)
    cost_estimate: CompileCostEstimate = field(default_factory=lambda: estimate_compile_cost(()))

    def to_dict(self) -> dict[str, object]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": list(self.errors),
            "budget_checks": [check.to_dict() for check in self.budget_checks],
            "cost_estimate": self.cost_estimate.to_dict(),
        }


class WikiCompiler:
    def __init__(
        self,
        registry: WikiRegistry,
        page_store: WikiPageStore,
        *,
        budget: CompileBudget | None = None,
        pricing: CompilePricing | None = None,
        observability_sink: WikiObservabilitySink | None = None,
        llm_gateway: LLMGateway | None = None,
    ) -> None:
        self.registry = registry
        self.page_store = page_store
        self.budget = budget or CompileBudget()
        self.pricing = pricing or compile_pricing_from_env()
        self.observability_sink = observability_sink
        self.llm_gateway = llm_gateway or LLMGateway(stub_mode=True)

    def compile_source(
        self,
        source_id: str,
        *,
        dry_run: bool = False,
    ) -> CompileResult:
        source = self.registry.get_source(source_id)
        if not source:
            return self._observe_compile_result(
                "wiki.compiler.source",
                CompileResult(0, 0, 0, [f"Source not found: {source_id}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        chunks = self.registry.get_chunks_by_source(source_id)
        budget_check = check_compile_budget(source_id, chunks, self.budget)
        cost_estimate = estimate_compile_cost((budget_check,), self.pricing)
        if budget_check.over_budget:
            return self._observe_compile_result(
                "wiki.compiler.source",
                CompileResult(
                    0,
                    0,
                    1,
                    [budget_check.reason],
                    budget_checks=[budget_check],
                    cost_estimate=cost_estimate,
                ),
                {"source_id": source_id, "dry_run": dry_run},
            )
        slug = stable_slug(source.title)
        relative_path = Path(f"sources/{slug}.md")
        frontmatter = {
            "id": source.source_id,
            "kind": "source",
            "title": source.title,
            "status": WikiPageStatus.final.value,
            "source_type": source.source_type,
            "source_hash": source.source_hash,
            "chunk_count": len(chunks),
        }
        body_lines = [
            f"# {source.title}",
            "",
            f"**Type:** {source.source_type}",
            f"**Path:** `{source.source_path}`",
            f"**Hash:** `{source.source_hash}`",
            f"**Chunks:** {len(chunks)}",
            "",
            "## Chunks",
            "",
        ]
        for chunk in chunks[:10]:
            body_lines.append(f"### Chunk {chunk['chunk_index']}")
            if chunk.get("page"):
                body_lines.append(f"**Page:** {chunk['page']}")
            text_preview = chunk["text"][:200]
            body_lines.append(f"\n{text_preview}...\n")
        body = "\n".join(body_lines)
        if dry_run:
            return self._observe_compile_result(
                "wiki.compiler.source",
                CompileResult(1, 0, 0, [], budget_checks=[budget_check], cost_estimate=cost_estimate),
                {"source_id": source_id, "dry_run": dry_run},
            )
        rendered = render_page(relative_path, frontmatter, body)
        self.page_store.write_rendered(rendered)
        return self._observe_compile_result(
            "wiki.compiler.source",
            CompileResult(1, 0, 0, [], budget_checks=[budget_check], cost_estimate=cost_estimate),
            {"source_id": source_id, "dry_run": dry_run},
        )

    def compile_paper(
        self,
        source_id: str,
        *,
        dry_run: bool = False,
    ) -> CompileResult:
        source = self.registry.get_source(source_id)
        if not source:
            return self._observe_compile_result(
                "wiki.compiler.paper",
                CompileResult(0, 0, 0, [f"Source not found: {source_id}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        if source.source_type != "paper":
            return self._observe_compile_result(
                "wiki.compiler.paper",
                CompileResult(0, 0, 1, []),
                {"source_id": source_id, "dry_run": dry_run},
            )
        slug = stable_slug(source.title)
        relative_path = Path(f"papers/{slug}.md")
        frontmatter = {
            "id": f"paper-{source.source_id}",
            "kind": WikiPageKind.paper.value,
            "title": source.title,
            "status": WikiPageStatus.draft.value,
            "source_id": source.source_id,
        }
        body = f"# {source.title}\n\nDraft paper page for [[sources/{slug}]].\n"
        if dry_run:
            return self._observe_compile_result(
                "wiki.compiler.paper",
                CompileResult(1, 0, 0, []),
                {"source_id": source_id, "dry_run": dry_run},
            )
        rendered = render_page(relative_path, frontmatter, body)
        self.page_store.write_rendered(rendered)
        return self._observe_compile_result(
            "wiki.compiler.paper",
            CompileResult(1, 0, 0, []),
            {"source_id": source_id, "dry_run": dry_run},
        )

    def compile_paper_with_llm(
        self,
        source_id: str,
        *,
        dry_run: bool = False,
    ) -> CompileResult:
        """LLM-backed paper summary compilation.

        Uses ``wiki_paper_summary.txt`` prompt template. Falls back to
        deterministic stub when the gateway is in stub mode.
        """
        source = self.registry.get_source(source_id)
        if not source:
            return self._observe_compile_result(
                "wiki.compiler.paper_llm",
                CompileResult(0, 0, 0, [f"Source not found: {source_id}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        chunks = self.registry.get_chunks_by_source(source_id)
        budget_check = check_compile_budget(source_id, chunks, self.budget)
        cost_estimate = estimate_compile_cost((budget_check,), self.pricing)
        if budget_check.over_budget:
            return self._observe_compile_result(
                "wiki.compiler.paper_llm",
                CompileResult(0, 0, 1, [budget_check.reason], budget_checks=[budget_check], cost_estimate=cost_estimate),
                {"source_id": source_id, "dry_run": dry_run},
            )
        source_text = "\n\n".join(chunk["text"] for chunk in chunks if chunk.get("text"))
        if not source_text.strip():
            return self._observe_compile_result(
                "wiki.compiler.paper_llm",
                CompileResult(0, 0, 1, [f"No chunk text for source: {source_id}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        template = _load_prompt_template("paper_summary")
        prompt = template.replace("{source_text}", source_text)
        llm_response = self.llm_gateway.generate(LLMRequest(prompt=prompt))
        parsed, parse_error = validate_json_response(llm_response.text)
        if parse_error:
            return self._observe_compile_result(
                "wiki.compiler.paper_llm",
                CompileResult(0, 0, 1, [f"LLM JSON parse error: {parse_error}"], cost_estimate=cost_estimate),
                {"source_id": source_id, "dry_run": dry_run},
            )
        slug = stable_slug(source.title)
        relative_path = Path(f"papers/{slug}.md")
        title = parsed.get("title", source.title)
        summary = parsed.get("summary", "")
        key_findings = parsed.get("key_findings", [])
        methodology = parsed.get("methodology", "")
        evidence_refs = parsed.get("evidence_refs", [])
        frontmatter = {
            "id": f"paper-{source.source_id}",
            "kind": WikiPageKind.paper.value,
            "title": title,
            "status": WikiPageStatus.draft.value,
            "source_id": source.source_id,
            "evidence_refs": evidence_refs,
        }
        body_parts = [f"# {title}", ""]
        if summary:
            body_parts.append(f"## Summary\n\n{summary}")
        if key_findings:
            body_parts.append("\n## Key Findings\n")
            for finding in key_findings:
                body_parts.append(f"- {finding}")
        if methodology:
            body_parts.append(f"\n## Methodology\n\n{methodology}")
        body = "\n".join(body_parts)
        if dry_run:
            return self._observe_compile_result(
                "wiki.compiler.paper_llm",
                CompileResult(1, 0, 0, [], budget_checks=[budget_check], cost_estimate=cost_estimate),
                {"source_id": source_id, "dry_run": dry_run},
            )
        rendered = render_page(relative_path, frontmatter, body)
        self.page_store.write_rendered(rendered)
        return self._observe_compile_result(
            "wiki.compiler.paper_llm",
            CompileResult(1, 0, 0, [], budget_checks=[budget_check], cost_estimate=cost_estimate),
            {"source_id": source_id, "dry_run": dry_run},
        )

    def compile_concepts_with_llm(
        self,
        source_id: str,
        *,
        existing_concepts: str = "",
        dry_run: bool = False,
    ) -> CompileResult:
        """LLM-backed concept extraction from a source.

        Uses ``wiki_concept_extract.txt`` prompt template.
        """
        source = self.registry.get_source(source_id)
        if not source:
            return self._observe_compile_result(
                "wiki.compiler.concepts_llm",
                CompileResult(0, 0, 0, [f"Source not found: {source_id}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        chunks = self.registry.get_chunks_by_source(source_id)
        source_text = "\n\n".join(chunk["text"] for chunk in chunks if chunk.get("text"))
        if not source_text.strip():
            return self._observe_compile_result(
                "wiki.compiler.concepts_llm",
                CompileResult(0, 0, 1, [f"No chunk text for source: {source_id}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        template = _load_prompt_template("concept_extract")
        prompt = template.replace("{source_text}", source_text).replace("{existing_concepts}", existing_concepts)
        llm_response = self.llm_gateway.generate(LLMRequest(prompt=prompt))
        parsed, parse_error = validate_json_response(llm_response.text)
        if parse_error:
            return self._observe_compile_result(
                "wiki.compiler.concepts_llm",
                CompileResult(0, 0, 1, [f"LLM JSON parse error: {parse_error}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        concepts = parsed.get("concepts", [])
        if not concepts:
            return self._observe_compile_result(
                "wiki.compiler.concepts_llm",
                CompileResult(0, 0, 1, ["No concepts extracted"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        created = 0
        for concept in concepts:
            name = concept.get("name", "")
            if not name:
                continue
            slug = stable_slug(name)
            relative_path = Path(f"concepts/{slug}.md")
            frontmatter = {
                "id": f"concept-{slug}",
                "kind": WikiPageKind.concept.value,
                "title": name,
                "status": WikiPageStatus.draft.value,
                "aliases": concept.get("aliases", []),
                "evidence_refs": concept.get("evidence_refs", []),
                "related_concepts": concept.get("related_concepts", []),
            }
            definition = concept.get("definition", "")
            body = f"# {name}\n\n{definition}\n"
            if dry_run:
                created += 1
                continue
            rendered = render_page(relative_path, frontmatter, body)
            self.page_store.write_rendered(rendered)
            created += 1
        return self._observe_compile_result(
            "wiki.compiler.concepts_llm",
            CompileResult(created, 0, 0, []),
            {"source_id": source_id, "dry_run": dry_run, "concept_count": len(concepts)},
        )

    def compile_claims_with_llm(
        self,
        source_id: str,
        *,
        dry_run: bool = False,
    ) -> CompileResult:
        """LLM-backed claim extraction from a source.

        Uses ``wiki_claim_extract.txt`` prompt template.
        """
        source = self.registry.get_source(source_id)
        if not source:
            return self._observe_compile_result(
                "wiki.compiler.claims_llm",
                CompileResult(0, 0, 0, [f"Source not found: {source_id}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        chunks = self.registry.get_chunks_by_source(source_id)
        source_text = "\n\n".join(chunk["text"] for chunk in chunks if chunk.get("text"))
        if not source_text.strip():
            return self._observe_compile_result(
                "wiki.compiler.claims_llm",
                CompileResult(0, 0, 1, [f"No chunk text for source: {source_id}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        template = _load_prompt_template("claim_extract")
        prompt = template.replace("{source_text}", source_text)
        llm_response = self.llm_gateway.generate(LLMRequest(prompt=prompt))
        parsed, parse_error = validate_json_response(llm_response.text)
        if parse_error:
            return self._observe_compile_result(
                "wiki.compiler.claims_llm",
                CompileResult(0, 0, 1, [f"LLM JSON parse error: {parse_error}"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        claims = parsed.get("claims", [])
        if not claims:
            return self._observe_compile_result(
                "wiki.compiler.claims_llm",
                CompileResult(0, 0, 1, ["No claims extracted"]),
                {"source_id": source_id, "dry_run": dry_run},
            )
        created = 0
        for claim in claims:
            claim_text = claim.get("claim_text", "")
            if not claim_text:
                continue
            slug = stable_slug(claim_text[:80])
            relative_path = Path(f"claims/{slug}.md")
            frontmatter = {
                "id": f"claim-{slug}",
                "kind": WikiPageKind.claim.value,
                "title": claim_text[:120],
                "status": WikiPageStatus.draft.value,
                "confidence": claim.get("confidence", "medium"),
                "evidence_refs": claim.get("evidence_refs", []),
                "supports": claim.get("supports", []),
                "contradicts": claim.get("contradicts", []),
            }
            body_parts = [f"# {claim_text[:120]}", "", f"**Confidence:** {claim.get('confidence', 'medium')}"]
            if claim.get("supports"):
                body_parts.append(f"\n**Supports:** {', '.join(claim['supports'])}")
            if claim.get("contradicts"):
                body_parts.append(f"\n**Contradicts:** {', '.join(claim['contradicts'])}")
            body = "\n".join(body_parts)
            if dry_run:
                created += 1
                continue
            rendered = render_page(relative_path, frontmatter, body)
            self.page_store.write_rendered(rendered)
            created += 1
        return self._observe_compile_result(
            "wiki.compiler.claims_llm",
            CompileResult(created, 0, 0, []),
            {"source_id": source_id, "dry_run": dry_run, "claim_count": len(claims)},
        )

    def compile_synthesis_with_llm(
        self,
        question: str,
        rag_answer: str,
        wiki_evidence: str,
        *,
        dry_run: bool = False,
    ) -> CompileResult:
        """LLM-backed synthesis answer with wiki evidence.

        Uses ``wiki_synthesis.txt`` prompt template.
        """
        if not question.strip():
            return CompileResult(0, 0, 0, ["question cannot be empty"])
        template = _load_prompt_template("synthesis")
        prompt = (
            template.replace("{question}", question)
            .replace("{rag_answer}", rag_answer)
            .replace("{wiki_evidence}", wiki_evidence)
        )
        llm_response = self.llm_gateway.generate(LLMRequest(prompt=prompt))
        parsed, parse_error = validate_json_response(llm_response.text)
        if parse_error:
            return CompileResult(0, 0, 1, [f"LLM JSON parse error: {parse_error}"])
        answer = parsed.get("answer", "")
        if not answer:
            return CompileResult(0, 0, 1, ["No answer in LLM response"])
        slug = stable_slug(question)
        relative_path = Path(f"synthesis/{slug}.md")
        frontmatter = {
            "id": f"synthesis-{slug}",
            "kind": WikiPageKind.synthesis.value,
            "title": question[:120],
            "status": WikiPageStatus.draft.value,
            "evidence_refs": parsed.get("evidence_refs", []),
        }
        body_parts = [f"# {question[:120]}", "", answer]
        if parsed.get("limitations"):
            body_parts.append(f"\n## Limitations\n\n{parsed['limitations']}")
        body = "\n".join(body_parts)
        if dry_run:
            return CompileResult(1, 0, 0, [])
        rendered = render_page(relative_path, frontmatter, body)
        self.page_store.write_rendered(rendered)
        return CompileResult(1, 0, 0, [])

    def compile_project(
        self,
        *,
        dry_run: bool = False,
    ) -> CompileResult:
        sources = self.registry.list_sources()
        created = 0
        updated = 0
        skipped = 0
        errors: list[str] = []
        for source in sources:
            result = self.compile_source(source.source_id, dry_run=dry_run)
            created += result.created
            updated += result.updated
            skipped += result.skipped
            errors.extend(result.errors)
        budget_checks: list[CompileBudgetCheck] = []
        for source in sources:
            chunks = self.registry.get_chunks_by_source(source.source_id)
            budget_checks.append(check_compile_budget(source.source_id, chunks, self.budget))
        for source in sources:
            if source.source_type == "paper":
                result = self.compile_paper(source.source_id, dry_run=dry_run)
                created += result.created
                updated += result.updated
                skipped += result.skipped
                errors.extend(result.errors)
        return self._observe_compile_result(
            "wiki.compiler.project",
            CompileResult(
                created,
                updated,
                skipped,
                errors,
                budget_checks=budget_checks,
                cost_estimate=estimate_compile_cost(budget_checks, self.pricing),
            ),
            {"source_count": len(sources), "dry_run": dry_run},
        )

    def plan_compile(self) -> CompilePlan:
        sources = self.registry.list_sources()
        to_create: list[Path] = []
        to_update: list[Path] = []
        to_skip: list[Path] = []
        for source in sources:
            slug = stable_slug(source.title)
            source_path = Path(f"sources/{slug}.md")
            if self.page_store.read_page(source_path):
                to_update.append(source_path)
            else:
                to_create.append(source_path)
            if source.source_type == "paper":
                paper_path = Path(f"papers/{slug}.md")
                if self.page_store.read_page(paper_path):
                    to_skip.append(paper_path)
                else:
                    to_create.append(paper_path)
        return CompilePlan(to_create, to_update, to_skip)

    def _observe_compile_result(
        self,
        operation: str,
        result: CompileResult,
        attributes: Mapping[str, object],
    ) -> CompileResult:
        if self.observability_sink is None:
            return result
        status = "error" if result.errors else "ok"
        event_attributes = {
            **dict(attributes),
            "created": result.created,
            "updated": result.updated,
            "skipped": result.skipped,
            "error_count": len(result.errors),
            "input_tokens": result.cost_estimate.input_tokens,
            "output_tokens": result.cost_estimate.output_tokens,
        }
        self.observability_sink.emit_event(f"{operation}.completed", event_attributes, status=status)
        self.observability_sink.record_metric(
            f"{operation}.created",
            result.created,
            attributes,
            unit="pages",
            status=status,
        )
        self.observability_sink.record_metric(
            f"{operation}.errors",
            len(result.errors),
            attributes,
            unit="count",
            status=status,
        )
        return result


def check_compile_budget(
    source_id: str,
    chunks: list[dict[str, object]],
    budget: CompileBudget | None = None,
) -> CompileBudgetCheck:
    """Return a hard budget decision before source compile writes.

    The guard rejects oversized inputs before any future LLM-backed prompt can
    be built, keeping current deterministic compiles and later model compiles on
    the same safety boundary.
    """

    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id must be a non-empty string")
    if not isinstance(chunks, list):
        raise TypeError("chunks must be a list of dictionaries")
    compile_budget = budget or CompileBudget()
    _validate_compile_budget(compile_budget)
    total_chars = 0
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, Mapping):
            raise TypeError(f"chunks[{index}] must be a mapping")
        text = chunk.get("text")
        if not isinstance(text, str):
            raise TypeError(f"chunks[{index}].text must be a string")
        total_chars += len(text)
    estimated_tokens = int(total_chars / compile_budget.chars_per_token) if total_chars else 0
    if len(chunks) > compile_budget.max_source_chunks:
        return CompileBudgetCheck(
            source_id=source_id.strip(),
            source_chunks=len(chunks),
            total_chunk_chars=total_chars,
            estimated_tokens=estimated_tokens,
            over_budget=True,
            reason=(
                f"Compile budget exceeded for {source_id.strip()}: "
                f"{len(chunks)} chunks > max_source_chunks={compile_budget.max_source_chunks}"
            ),
        )
    if total_chars > compile_budget.max_total_chunk_chars:
        return CompileBudgetCheck(
            source_id=source_id.strip(),
            source_chunks=len(chunks),
            total_chunk_chars=total_chars,
            estimated_tokens=estimated_tokens,
            over_budget=True,
            reason=(
                f"Compile budget exceeded for {source_id.strip()}: "
                f"{total_chars} chars > max_total_chunk_chars={compile_budget.max_total_chunk_chars}"
            ),
        )
    if estimated_tokens > compile_budget.max_estimated_tokens:
        return CompileBudgetCheck(
            source_id=source_id.strip(),
            source_chunks=len(chunks),
            total_chunk_chars=total_chars,
            estimated_tokens=estimated_tokens,
            over_budget=True,
            reason=(
                f"Compile budget exceeded for {source_id.strip()}: "
                f"{estimated_tokens} estimated tokens > max_estimated_tokens={compile_budget.max_estimated_tokens}"
            ),
        )
    return CompileBudgetCheck(
        source_id=source_id.strip(),
        source_chunks=len(chunks),
        total_chunk_chars=total_chars,
        estimated_tokens=estimated_tokens,
        over_budget=False,
        reason="within compile budget",
    )


def estimate_compile_cost(
    budget_checks: tuple[CompileBudgetCheck, ...] | list[CompileBudgetCheck],
    pricing: CompilePricing | None = None,
) -> CompileCostEstimate:
    """Estimate compile tokens and configured provider cost.

    The estimate uses budget checks generated from source chunks. Pricing is
    optional and must come from explicit configuration or caller injection.
    """

    if not isinstance(budget_checks, (tuple, list)):
        raise TypeError("budget_checks must be a tuple or list of CompileBudgetCheck")
    checked_sources = list(budget_checks)
    for index, check in enumerate(checked_sources):
        if not isinstance(check, CompileBudgetCheck):
            raise TypeError(f"budget_checks[{index}] must be a CompileBudgetCheck")
    compile_pricing = pricing or CompilePricing()
    _validate_compile_pricing(compile_pricing)

    input_tokens = sum(check.estimated_tokens for check in checked_sources)
    output_tokens = compile_pricing.estimated_output_tokens_per_source * len(checked_sources)
    total_tokens = input_tokens + output_tokens
    input_cost = _normalize_cost(input_tokens * compile_pricing.input_usd_per_1m_tokens / 1_000_000)
    output_cost = _normalize_cost(output_tokens * compile_pricing.output_usd_per_1m_tokens / 1_000_000)
    pricing_configured = (
        compile_pricing.input_usd_per_1m_tokens > 0
        or compile_pricing.output_usd_per_1m_tokens > 0
        or compile_pricing.pricing_source != "not_configured"
    )
    return CompileCostEstimate(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        estimated_cost_usd=_normalize_cost(input_cost + output_cost),
        input_usd_per_1m_tokens=compile_pricing.input_usd_per_1m_tokens,
        output_usd_per_1m_tokens=compile_pricing.output_usd_per_1m_tokens,
        pricing_configured=pricing_configured,
        pricing_source=compile_pricing.pricing_source,
        currency=compile_pricing.currency,
    )


def compile_pricing_from_env(env: Mapping[str, str] | None = None) -> CompilePricing:
    values = env if env is not None else os.environ
    input_rate = _non_negative_float(
        values.get("LITERATURE_ASSISTANT_WIKI_COMPILE_INPUT_USD_PER_1M_TOKENS"),
        "LITERATURE_ASSISTANT_WIKI_COMPILE_INPUT_USD_PER_1M_TOKENS",
    )
    output_rate = _non_negative_float(
        values.get("LITERATURE_ASSISTANT_WIKI_COMPILE_OUTPUT_USD_PER_1M_TOKENS"),
        "LITERATURE_ASSISTANT_WIKI_COMPILE_OUTPUT_USD_PER_1M_TOKENS",
    )
    output_tokens = _non_negative_int(
        values.get("LITERATURE_ASSISTANT_WIKI_COMPILE_ESTIMATED_OUTPUT_TOKENS"),
        "LITERATURE_ASSISTANT_WIKI_COMPILE_ESTIMATED_OUTPUT_TOKENS",
    )
    pricing_source = str(values.get("LITERATURE_ASSISTANT_WIKI_COMPILE_PRICING_SOURCE") or "").strip()
    if not pricing_source:
        pricing_source = "configured_env" if input_rate > 0 or output_rate > 0 else "not_configured"
    return CompilePricing(
        input_usd_per_1m_tokens=input_rate,
        output_usd_per_1m_tokens=output_rate,
        estimated_output_tokens_per_source=output_tokens,
        pricing_source=pricing_source,
    )


def _validate_compile_budget(budget: CompileBudget) -> None:
    if not isinstance(budget, CompileBudget):
        raise TypeError("budget must be a CompileBudget")
    if budget.max_source_chunks <= 0:
        raise ValueError("max_source_chunks must be positive")
    if budget.max_total_chunk_chars <= 0:
        raise ValueError("max_total_chunk_chars must be positive")
    if budget.max_estimated_tokens <= 0:
        raise ValueError("max_estimated_tokens must be positive")
    if budget.chars_per_token <= 0:
        raise ValueError("chars_per_token must be positive")


def _validate_compile_pricing(pricing: CompilePricing) -> None:
    if not isinstance(pricing, CompilePricing):
        raise TypeError("pricing must be a CompilePricing")
    if pricing.input_usd_per_1m_tokens < 0:
        raise ValueError("input_usd_per_1m_tokens cannot be negative")
    if pricing.output_usd_per_1m_tokens < 0:
        raise ValueError("output_usd_per_1m_tokens cannot be negative")
    if pricing.estimated_output_tokens_per_source < 0:
        raise ValueError("estimated_output_tokens_per_source cannot be negative")
    if not pricing.currency.strip():
        raise ValueError("currency must be a non-empty string")
    if not pricing.pricing_source.strip():
        raise ValueError("pricing_source must be a non-empty string")


def _non_negative_float(raw_value: str | None, name: str) -> float:
    if raw_value is None or not str(raw_value).strip():
        return 0.0
    try:
        value = float(str(raw_value).strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative number") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _non_negative_int(raw_value: str | None, name: str) -> int:
    if raw_value is None or not str(raw_value).strip():
        return 0
    try:
        value = int(str(raw_value).strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _normalize_cost(value: float) -> float:
    return round(float(value), 10)
