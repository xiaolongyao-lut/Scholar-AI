# -*- coding: utf-8 -*-
"""Quality audit for portable literature chunk packages."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field


ChunkSeverity = Literal["error", "warning", "info"]
ReviewJudgment = Literal["relevant", "partial", "offtopic", "unknown"]
_ALLOWED_REVIEW_JUDGMENTS: tuple[ReviewJudgment, ...] = (
    "relevant",
    "partial",
    "offtopic",
    "unknown",
)


class ChunkQualityIssue(BaseModel):
    """One machine-readable chunk-package quality finding.

    Args:
        code: Stable issue code used by goldset/update tooling.
        severity: Severity for pass/fail and prioritization.
        message: Short human-readable remediation target.
        count: Number of affected records when the issue is aggregate.
        examples: Bounded examples such as chunk ids or section names.
    """

    code: str = Field(min_length=1)
    severity: ChunkSeverity
    message: str = Field(min_length=1)
    count: int = Field(default=0, ge=0)
    examples: list[str] = Field(default_factory=list)


class ChunkQualityMetrics(BaseModel):
    """Aggregate metrics for one chunk package."""

    source_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    evidence_section_count: int = Field(ge=0)
    evidence_item_count: int = Field(ge=0)
    review_section_count: int = Field(ge=0)
    reference_count: int = Field(ge=0)
    chunk_id_coverage: float = Field(ge=0.0, le=1.0)
    evidence_chunk_id_coverage: float = Field(ge=0.0, le=1.0)
    referenced_chunk_recall: float = Field(ge=0.0, le=1.0)
    duplicate_chunk_ratio: float = Field(ge=0.0, le=1.0)
    median_chunk_chars: float = Field(ge=0.0)
    p95_chunk_chars: float = Field(ge=0.0)
    citation_count: int = Field(ge=0)
    figure_reference_count: int = Field(ge=0)
    table_reference_count: int = Field(ge=0)
    equation_reference_count: int = Field(ge=0)


class ChunkPackageQualityReport(BaseModel):
    """Quality report for a chunk package and its writing artifacts."""

    schema_version: str = "chunk-package-quality/v1"
    package_path: str
    passed: bool
    score: float = Field(ge=0.0, le=100.0)
    metrics: ChunkQualityMetrics
    issues: list[ChunkQualityIssue] = Field(default_factory=list)
    standard_feedback: list[str] = Field(default_factory=list)
    goldset_feedback: list[str] = Field(default_factory=list)
    joint_recall_policy: dict[str, Any] = Field(default_factory=dict)


class GoldsetProposalQuery(BaseModel):
    """One read-only proposed goldset query derived from evidence sections."""

    query_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    source_section: str = Field(min_length=1)
    expected_chunk_ids: list[str] = Field(default_factory=list)
    qrels: dict[str, int] = Field(default_factory=dict)
    no_gold: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)


class GoldsetProposalReport(BaseModel):
    """Read-only goldset proposal generated from a chunk package."""

    schema_version: str = "chunk-package-goldset-proposal/v1"
    package_path: str
    query_count: int = Field(ge=0)
    queries: list[GoldsetProposalQuery] = Field(default_factory=list)
    guardrails: dict[str, bool] = Field(default_factory=dict)


class ChunkGoldsetReviewBundle(BaseModel):
    """Generated review artifacts for chunk-package and goldset promotion.

    Args:
        package_path: Audited chunk package path.
        output_dir: Directory containing all generated review artifacts.
        quality_report_path: JSON quality report path.
        goldset_proposal_path: JSON query/qrels proposal path.
        qrels_candidate_path: TREC-style candidate qrels path.
        judgment_template_path: JSON Lines human-review template path.
        standards_markdown_path: Markdown standard-feedback packet path.
        query_count: Number of proposed queries.
        candidate_qrels_count: Number of candidate qrel rows.
        guardrails: Machine-readable mutation and review constraints.
    """

    schema_version: str = "chunk-goldset-review-bundle/v1"
    package_path: str
    output_dir: str
    quality_report_path: str
    goldset_proposal_path: str
    qrels_candidate_path: str
    judgment_template_path: str
    standards_markdown_path: str
    query_count: int = Field(ge=0)
    candidate_qrels_count: int = Field(ge=0)
    guardrails: dict[str, bool] = Field(default_factory=dict)


class ChunkGoldsetPromotionManifest(BaseModel):
    """Manifest for qrels promoted from human-reviewed JSONL judgments.

    Args:
        source_judgment_path: Reviewed JSONL input path.
        output_qrels_path: Canonical qrels output path.
        promoted_qrels_count: Number of TREC qrels rows written.
        judged_row_count: Number of reviewed rows consumed.
        skipped_row_count: Rows intentionally skipped as off-topic/no-gold.
        relevance_mapping: Judgment-to-qrels relevance mapping.
        guardrails: Machine-readable constraints proving unknown rows were not promoted.
    """

    schema_version: str = "chunk-goldset-promotion/v1"
    source_judgment_path: str
    output_qrels_path: str
    promoted_qrels_count: int = Field(ge=0)
    judged_row_count: int = Field(ge=0)
    skipped_row_count: int = Field(ge=0)
    relevance_mapping: dict[str, int] = Field(default_factory=dict)
    guardrails: dict[str, bool] = Field(default_factory=dict)


_CITATION_RE = re.compile(r"\[(\d{1,3})(?:\s*[-,]\s*\d{1,3})*\]")
_FIGURE_RE = re.compile(r"(?:图\s*\d+|Figure\s*\d+|Fig\.\s*\d+)", re.IGNORECASE)
_TABLE_RE = re.compile(r"(?:表\s*\d+|Table\s*\d+)", re.IGNORECASE)
_EQUATION_RE = re.compile(r"(?:式\s*[（(]?\s*\d+\s*[）)]?|公式\s*\d+|Equation\s*[（(]?\s*\d+\s*[）)]?|Eq\.\s*[（(]?\s*\d+\s*[）)]?)", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def audit_chunk_package(package_path: Path | str) -> ChunkPackageQualityReport:
    """Audit a chunk package without mutating source files.

    Args:
        package_path: Directory containing ``chunks.json``, ``evidence.json``,
            ``manifest.json``, and optionally ``review_content.json``.

    Returns:
        Deterministic quality report suitable for workspace artifacts and
        future goldset proposal tooling.

    Raises:
        FileNotFoundError: Required package files are missing.
        ValueError: Required JSON roots have unsupported shapes.
    """

    root = Path(package_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"chunk package directory not found: {root}")
    manifest = _read_json(root / "manifest.json", expected=list)
    chunks = _read_json(root / "chunks.json", expected=list)
    evidence = _read_json(root / "evidence.json", expected=dict)
    review = _read_json(root / "review_content.json", expected=dict, required=False) or {}

    chunk_ids = [str(item.get("chunk_id") or "").strip() for item in chunks if isinstance(item, dict)]
    chunk_id_set = {chunk_id for chunk_id in chunk_ids if chunk_id}
    evidence_refs = _evidence_chunk_ids(evidence)
    review_text = _review_text(review)
    char_counts = [_chunk_char_count(item) for item in chunks if isinstance(item, dict)]
    duplicate_ratio = _duplicate_ratio(_normalized_chunk_texts(chunks))

    metrics = ChunkQualityMetrics(
        source_count=len(manifest),
        chunk_count=len(chunks),
        evidence_section_count=len(evidence),
        evidence_item_count=sum(len(items) for items in evidence.values() if isinstance(items, list)),
        review_section_count=len(review.get("sections") or []) if isinstance(review.get("sections"), list) else 0,
        reference_count=len(review.get("references") or []) if isinstance(review.get("references"), list) else 0,
        chunk_id_coverage=_safe_ratio(len(chunk_id_set), len(chunks)),
        evidence_chunk_id_coverage=_safe_ratio(len([ref for ref in evidence_refs if ref]), len(evidence_refs)),
        referenced_chunk_recall=_safe_ratio(len(set(evidence_refs) & chunk_id_set), len(set(evidence_refs))),
        duplicate_chunk_ratio=duplicate_ratio,
        median_chunk_chars=_percentile(char_counts, 50),
        p95_chunk_chars=_percentile(char_counts, 95),
        citation_count=len(_CITATION_RE.findall(review_text)),
        figure_reference_count=len(_FIGURE_RE.findall(review_text)),
        table_reference_count=len(_TABLE_RE.findall(review_text)),
        equation_reference_count=len(_EQUATION_RE.findall(review_text)),
    )
    issues = _build_issues(metrics=metrics, chunks=chunks, evidence_refs=evidence_refs, chunk_id_set=chunk_id_set)
    score = _score_issues(issues)
    return ChunkPackageQualityReport(
        package_path=str(root),
        passed=score >= 70.0 and not any(issue.severity == "error" for issue in issues),
        score=score,
        metrics=metrics,
        issues=issues,
        standard_feedback=_standard_feedback(metrics, issues),
        goldset_feedback=_goldset_feedback(metrics, issues),
        joint_recall_policy=default_joint_recall_policy(),
    )


def default_joint_recall_policy() -> dict[str, Any]:
    """Return the default wiki+project recall policy for future implementation.

    The policy deliberately gives wiki a higher prior while bounding it so a
    large wiki cannot bury project-specific evidence.
    """

    return {
        "schema_version": "joint-recall-policy/v1",
        "project_weight": 0.4,
        "wiki_weight": 0.6,
        "fusion": "weighted_rrf",
        "rrf_k": 60,
        "per_source_minimums": {"project": 2, "wiki": 2},
        "per_source_caps": {"project": 12, "wiki": 18},
        "anti_drowning": {
            "max_wiki_share_after_fusion": 0.7,
            "always_keep_project_hits_when_score_positive": True,
        },
        "diagnostics_required": [
            "project_hit_count",
            "wiki_hit_count",
            "wiki_weight",
            "project_weight",
            "fusion_method",
        ],
    }


def write_chunk_package_quality_report(package_path: Path | str, output_path: Path | str) -> ChunkPackageQualityReport:
    """Audit a chunk package and write the JSON report atomically."""

    report = audit_chunk_package(package_path)
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(target)
    return report


def propose_goldset_from_chunk_package(
    package_path: Path | str,
    *,
    max_chunks_per_section: int = 5,
) -> GoldsetProposalReport:
    """Build a read-only query/qrels proposal from evidence sections.

    Args:
        package_path: Directory containing ``evidence.json`` and ``chunks.json``.
        max_chunks_per_section: Maximum expected chunks per proposed query.

    Returns:
        Proposal report. It intentionally does not modify gold/qrels files.
    """

    if max_chunks_per_section < 1 or max_chunks_per_section > 50:
        raise ValueError("max_chunks_per_section must be between 1 and 50")
    root = Path(package_path).expanduser().resolve()
    evidence = _read_json(root / "evidence.json", expected=dict)
    chunks = _read_json(root / "chunks.json", expected=list)
    valid_chunk_ids = {
        str(item.get("chunk_id") or "").strip()
        for item in chunks
        if isinstance(item, dict) and str(item.get("chunk_id") or "").strip()
    }
    queries: list[GoldsetProposalQuery] = []
    for index, (section, items) in enumerate(evidence.items(), start=1):
        if not isinstance(items, list):
            continue
        expected: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            chunk_id = str(item.get("chunk_id") or "").strip()
            if chunk_id and chunk_id in valid_chunk_ids and chunk_id not in expected:
                expected.append(chunk_id)
            if len(expected) >= max_chunks_per_section:
                break
        query_id = f"pkg_q_{index:04d}"
        queries.append(
            GoldsetProposalQuery(
                query_id=query_id,
                query_text=str(section),
                source_section=str(section),
                expected_chunk_ids=expected,
                qrels={chunk_id: 1 for chunk_id in expected},
                no_gold=not bool(expected),
                provenance={
                    "source": "evidence.json",
                    "evidence_items": len(items),
                    "max_chunks_per_section": max_chunks_per_section,
                },
            )
        )
    return GoldsetProposalReport(
        package_path=str(root),
        query_count=len(queries),
        queries=queries,
        guardrails={
            "read_only_no_file_mutation": True,
            "requires_human_review_before_gold_promotion": True,
        },
    )


def write_goldset_proposal_report(
    package_path: Path | str,
    output_path: Path | str,
    *,
    max_chunks_per_section: int = 5,
) -> GoldsetProposalReport:
    """Write a read-only goldset proposal report atomically."""

    report = propose_goldset_from_chunk_package(
        package_path,
        max_chunks_per_section=max_chunks_per_section,
    )
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(target)
    return report


def write_chunk_goldset_review_bundle(
    package_path: Path | str,
    output_dir: Path | str,
    *,
    max_chunks_per_section: int = 5,
) -> ChunkGoldsetReviewBundle:
    """Write review-ready chunk quality and goldset proposal artifacts.

    Args:
        package_path: Directory containing the chunk package.
        output_dir: Directory that receives only generated review artifacts.
        max_chunks_per_section: Maximum candidate qrels per evidence section.

    Returns:
        Manifest describing the generated review bundle.

    Raises:
        FileNotFoundError: The package path or required package files are
            missing.
        ValueError: Bounds are invalid or JSON package shapes are unsupported.
    """

    if max_chunks_per_section < 1 or max_chunks_per_section > 50:
        raise ValueError("max_chunks_per_section must be between 1 and 50")
    root = Path(package_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"chunk package directory not found: {root}")
    target_dir = Path(output_dir).expanduser().resolve()
    if target_dir.exists() and not target_dir.is_dir():
        raise ValueError(f"output_dir must be a directory: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)

    quality = audit_chunk_package(root)
    proposal = propose_goldset_from_chunk_package(
        root,
        max_chunks_per_section=max_chunks_per_section,
    )
    chunks = _read_json(root / "chunks.json", expected=list)
    chunk_lookup = _chunk_lookup(chunks)

    quality_path = target_dir / "chunk_quality_report.json"
    proposal_path = target_dir / "goldset_proposal.json"
    qrels_path = target_dir / "qrels_candidate.trec"
    judgment_path = target_dir / "goldset_review_template.jsonl"
    standards_path = target_dir / "chunk_goldset_standards.md"
    manifest_path = target_dir / "bundle_manifest.json"

    _atomic_write_text(quality_path, quality.model_dump_json(indent=2))
    _atomic_write_text(proposal_path, proposal.model_dump_json(indent=2))
    qrels_text, qrels_count = _render_trec_qrels(proposal)
    _atomic_write_text(qrels_path, qrels_text)
    judgment_rows = _review_judgment_rows(proposal, chunk_lookup)
    _atomic_write_text(
        judgment_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in judgment_rows),
    )
    _atomic_write_text(
        standards_path,
        _render_standards_markdown(
            quality=quality,
            proposal=proposal,
            qrels_count=qrels_count,
            max_chunks_per_section=max_chunks_per_section,
        ),
    )

    bundle = ChunkGoldsetReviewBundle(
        package_path=str(root),
        output_dir=str(target_dir),
        quality_report_path=str(quality_path),
        goldset_proposal_path=str(proposal_path),
        qrels_candidate_path=str(qrels_path),
        judgment_template_path=str(judgment_path),
        standards_markdown_path=str(standards_path),
        query_count=proposal.query_count,
        candidate_qrels_count=qrels_count,
        guardrails={
            "read_only_no_source_package_mutation": True,
            "candidate_qrels_not_canonical": True,
            "requires_human_review_before_gold_promotion": True,
            "trec_qrels_export_is_candidate_only": True,
            "jsonl_review_template_is_manual_judgment_input": True,
        },
    )
    _atomic_write_text(manifest_path, bundle.model_dump_json(indent=2))
    return bundle


def promote_reviewed_goldset_qrels(
    judgment_jsonl_path: Path | str,
    output_qrels_path: Path | str,
    *,
    manifest_path: Path | str | None = None,
) -> ChunkGoldsetPromotionManifest:
    """Promote human-reviewed judgments to canonical TREC qrels.

    Args:
        judgment_jsonl_path: JSONL produced from ``goldset_review_template.jsonl``
            after a reviewer replaces every ``unknown`` judgment.
        output_qrels_path: Destination for canonical qrels rows.
        manifest_path: Optional destination for the promotion manifest.

    Returns:
        Promotion manifest with counts and guardrails.

    Raises:
        FileNotFoundError: Judgment file is missing.
        ValueError: Rows are malformed, contain unknown judgments, or produce
            no promotable qrels.
    """

    source = Path(judgment_jsonl_path).expanduser().resolve()
    target = Path(output_qrels_path).expanduser().resolve()
    rows = _load_review_judgment_rows(source)
    qrels_lines: list[str] = [
        "# canonical qrels promoted from human-reviewed chunk-goldset judgments",
        "# format: query_id iteration doc_id relevance",
        "# unknown_judgments_promoted: false",
    ]
    judged = 0
    skipped = 0
    mapping = {"relevant": 2, "partial": 1, "offtopic": 0}
    for row_index, row in enumerate(rows, start=1):
        judgment = str(row.get("judgment") or "").strip().lower()
        if judgment == "unknown":
            raise ValueError(f"row {row_index} has unknown judgment; review is incomplete")
        if judgment not in mapping:
            raise ValueError(f"row {row_index} has unsupported judgment: {judgment!r}")
        no_gold = bool(row.get("no_gold"))
        chunk_id = str(row.get("chunk_id") or "").strip()
        query_id = str(row.get("query_id") or "").strip()
        relevance = _coerce_human_relevance(row.get("human_relevance"), mapping[judgment])
        judged += 1
        if no_gold or judgment == "offtopic" or relevance <= 0:
            skipped += 1
            continue
        qrels_lines.append(f"{_qrels_token(query_id)} 0 {_qrels_token(chunk_id)} {relevance}")

    promoted = len(qrels_lines) - 3
    if promoted <= 0:
        raise ValueError("reviewed judgments produced no promotable qrels")
    _atomic_write_text(target, "\n".join(qrels_lines) + "\n")
    manifest = ChunkGoldsetPromotionManifest(
        source_judgment_path=str(source),
        output_qrels_path=str(target),
        promoted_qrels_count=promoted,
        judged_row_count=judged,
        skipped_row_count=skipped,
        relevance_mapping=mapping,
        guardrails={
            "requires_all_rows_reviewed": True,
            "unknown_judgments_rejected": True,
            "offtopic_rows_not_promoted": True,
            "canonical_qrels_written_atomically": True,
        },
    )
    if manifest_path is not None:
        _atomic_write_text(Path(manifest_path).expanduser().resolve(), manifest.model_dump_json(indent=2))
    return manifest


def weighted_rrf_fuse(
    *,
    project_hits: list[dict[str, Any]],
    wiki_hits: list[dict[str, Any]],
    top_k: int = 10,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fuse project and wiki results with source weights and anti-drowning caps.

    Args:
        project_hits: Ranked project-local retrieval hits with a stable id field.
        wiki_hits: Ranked wiki retrieval hits with a stable id field.
        top_k: Maximum fused hits to return. Must be between 1 and 200.
        policy: Optional joint-recall policy matching
            ``default_joint_recall_policy``.

    Returns:
        Diagnostics and fused hits. The response keeps project/wiki hit counts
        separate so future retrieval audits can prove which corpus contributed.

    Raises:
        ValueError: Bounds are invalid or fusion parameters are unsafe.
    """

    if top_k < 1 or top_k > 200:
        raise ValueError("top_k must be between 1 and 200")
    config = policy or default_joint_recall_policy()
    raw_rrf_k = config.get("rrf_k", 60)
    rrf_k = int(raw_rrf_k)
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    weights = {
        "project": float(config.get("project_weight", 0.4)),
        "wiki": float(config.get("wiki_weight", 0.6)),
    }
    if weights["project"] < 0.0 or weights["wiki"] < 0.0:
        raise ValueError("project_weight and wiki_weight must be non-negative")
    caps = config.get("per_source_caps") if isinstance(config.get("per_source_caps"), dict) else {}
    max_wiki_share = float(
        (config.get("anti_drowning") or {}).get("max_wiki_share_after_fusion", 0.7)
        if isinstance(config.get("anti_drowning"), dict)
        else 0.7
    )
    scored: dict[str, dict[str, Any]] = {}
    _accumulate_rrf(scored, hits=project_hits, source="project", weight=weights["project"], rrf_k=rrf_k)
    _accumulate_rrf(scored, hits=wiki_hits, source="wiki", weight=weights["wiki"], rrf_k=rrf_k)
    ranked = sorted(
        scored.values(),
        key=lambda item: (-float(item["joint_score"]), str(item["doc_id"])),
    )
    fused = _apply_source_caps(
        ranked,
        top_k=top_k,
        project_cap=int(caps.get("project", top_k) or top_k),
        wiki_cap=int(caps.get("wiki", top_k) or top_k),
        max_wiki_share=max_wiki_share,
    )
    return {
        "schema_version": "joint-recall-fusion/v1",
        "fusion_method": "weighted_rrf",
        "top_k": top_k,
        "project_weight": weights["project"],
        "wiki_weight": weights["wiki"],
        "project_hit_count": len(project_hits),
        "wiki_hit_count": len(wiki_hits),
        "wiki_share_after_fusion": _safe_ratio(
            sum(1 for item in fused if item["dominant_source"] == "wiki"),
            len(fused),
        ),
        "hits": fused,
    }


def _accumulate_rrf(
    scored: dict[str, dict[str, Any]],
    *,
    hits: list[dict[str, Any]],
    source: Literal["project", "wiki"],
    weight: float,
    rrf_k: int,
) -> None:
    seen_in_source: set[str] = set()
    for rank, hit in enumerate(hits, start=1):
        if not isinstance(hit, dict):
            continue
        doc_id = _hit_doc_id(hit)
        if not doc_id or doc_id in seen_in_source:
            continue
        seen_in_source.add(doc_id)
        score = weight / float(rrf_k + rank)
        existing = scored.setdefault(
            doc_id,
            {
                "doc_id": doc_id,
                "joint_score": 0.0,
                "sources": [],
                "source_ranks": {},
                "dominant_source": source,
                "payload": dict(hit),
            },
        )
        existing["joint_score"] = round(float(existing["joint_score"]) + score, 8)
        if source not in existing["sources"]:
            existing["sources"].append(source)
        existing["source_ranks"][source] = rank
        if source == "wiki" and weight >= float(existing.get("dominant_weight", 0.0)):
            existing["dominant_source"] = "wiki"
            existing["dominant_weight"] = weight
        elif source == "project":
            existing.setdefault("dominant_weight", weight)


def _apply_source_caps(
    ranked: list[dict[str, Any]],
    *,
    top_k: int,
    project_cap: int,
    wiki_cap: int,
    max_wiki_share: float,
) -> list[dict[str, Any]]:
    fused: list[dict[str, Any]] = []
    counts = {"project": 0, "wiki": 0}
    wiki_limit = max(1, int(math.floor(top_k * max(0.0, min(1.0, max_wiki_share)))))
    for item in ranked:
        source = "wiki" if item["dominant_source"] == "wiki" else "project"
        if source == "wiki" and (counts["wiki"] >= wiki_cap or counts["wiki"] >= wiki_limit):
            continue
        if source == "project" and counts["project"] >= project_cap:
            continue
        cleaned = dict(item)
        cleaned["joint_score"] = round(float(cleaned["joint_score"]), 8)
        fused.append(cleaned)
        counts[source] += 1
        if len(fused) >= top_k:
            break
    return fused


def _hit_doc_id(hit: dict[str, Any]) -> str:
    for key in ("doc_id", "chunk_id", "ref_id", "id", "material_id"):
        value = str(hit.get(key) or "").strip()
        if value:
            return value
    return ""


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _chunk_lookup(chunks: list[Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if chunk_id and chunk_id not in lookup:
            lookup[chunk_id] = chunk
    return lookup


def _render_trec_qrels(proposal: GoldsetProposalReport) -> tuple[str, int]:
    lines = [
        "# candidate qrels generated from chunk-package evidence sections",
        "# format: query_id iteration doc_id relevance",
        "# review_required: true",
    ]
    count = 0
    for query in proposal.queries:
        for chunk_id in query.expected_chunk_ids:
            safe_query_id = _qrels_token(query.query_id)
            safe_chunk_id = _qrels_token(chunk_id)
            lines.append(f"{safe_query_id} 0 {safe_chunk_id} 1")
            count += 1
    return "\n".join(lines) + "\n", count


def _qrels_token(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("qrels tokens must be non-empty")
    if any(char.isspace() for char in text):
        raise ValueError(f"qrels token contains whitespace: {text!r}")
    return text


def _review_judgment_rows(
    proposal: GoldsetProposalReport,
    chunk_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for query in proposal.queries:
        if not query.expected_chunk_ids:
            rows.append(
                {
                    "schema_version": "chunk-goldset-review-judgment/v1",
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "source_section": query.source_section,
                    "chunk_id": "",
                    "proposed_relevance": 0,
                    "judgment": "unknown",
                    "allowed_judgments": list(_ALLOWED_REVIEW_JUDGMENTS),
                    "human_relevance": None,
                    "no_gold": True,
                    "source_hint": "evidence_set",
                    "review_note": "No valid candidate chunk id was available; reviewer must either keep no_gold=true or add a vetted chunk id.",
                }
            )
            continue
        for chunk_id in query.expected_chunk_ids:
            chunk = chunk_lookup.get(chunk_id, {})
            rows.append(
                {
                    "schema_version": "chunk-goldset-review-judgment/v1",
                    "query_id": query.query_id,
                    "query_text": query.query_text,
                    "source_section": query.source_section,
                    "chunk_id": chunk_id,
                    "proposed_relevance": int(query.qrels.get(chunk_id, 1)),
                    "judgment": "unknown",
                    "allowed_judgments": list(_ALLOWED_REVIEW_JUDGMENTS),
                    "human_relevance": None,
                    "no_gold": False,
                    "source_hint": "evidence_set",
                    "source_id": _bounded_text(chunk.get("source_id"), 120),
                    "source_name": _bounded_text(chunk.get("source_name") or chunk.get("title"), 240),
                    "page_start": chunk.get("page_start") or chunk.get("page"),
                    "page_end": chunk.get("page_end") or chunk.get("page"),
                    "chunk_type": _bounded_text(chunk.get("chunk_type"), 80),
                    "snippet": _bounded_text(chunk.get("text") or chunk.get("content"), 360),
                    "review_note": "Set judgment and human_relevance after review; do not promote candidate qrels before this row is checked.",
                }
            )
    return rows


def _bounded_text(value: Any, max_chars: int) -> str:
    text = _WHITESPACE_RE.sub(" ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def _render_standards_markdown(
    *,
    quality: ChunkPackageQualityReport,
    proposal: GoldsetProposalReport,
    qrels_count: int,
    max_chunks_per_section: int,
) -> str:
    metrics = quality.metrics
    issue_lines = [
        f"- `{issue.severity}` `{issue.code}`: {issue.message} count={issue.count}"
        for issue in quality.issues
    ] or ["- No issues."]
    standard_feedback = "\n".join(f"- {item}" for item in quality.standard_feedback)
    goldset_feedback = "\n".join(f"- {item}" for item in quality.goldset_feedback)
    policy = quality.joint_recall_policy
    return "\n".join(
        [
            "# Chunk And Goldset Review Standard",
            "",
            "## Package Verdict",
            "",
            f"- Package: `{quality.package_path}`",
            f"- Passed: `{str(quality.passed).lower()}`",
            f"- Score: `{quality.score}`",
            f"- Chunk count: `{metrics.chunk_count}`",
            f"- Evidence sections: `{metrics.evidence_section_count}`",
            f"- Candidate queries: `{proposal.query_count}`",
            f"- Candidate qrels: `{qrels_count}`",
            f"- Max chunks per section: `{max_chunks_per_section}`",
            "",
            "## Required Chunk Standard",
            "",
            "- Every chunk must have a stable `chunk_id` and recoverable source/page locator.",
            "- Evidence refs must resolve back to `chunks.json`; unresolved refs block gold promotion.",
            "- Chunk text should normally stay within 120-3000 characters unless a structured table, formula, or figure caption requires an exception.",
            "- Duplicate chunk text should be deduplicated or represented as multiple source mappings instead of repeated content.",
            "- Writing artifacts must preserve figure, table, equation, citation, evidence, and style-profile audit signals.",
            "",
            "## Candidate Goldset Standard",
            "",
            "- `goldset_proposal.json` and `qrels_candidate.trec` are candidate artifacts only.",
            "- TREC qrels rows use `query_id iteration doc_id relevance`; iteration is `0` for this review bundle.",
            "- `goldset_review_template.jsonl` is the manual review entry point; each JSON Lines row must be judged before canonical promotion.",
            "- `unknown` judgments must not be treated as relevant qrels.",
            "- Canonical promotion requires a rollback checkpoint, old/new metrics, and a recorded recovery path.",
            "",
            "## Joint Recall Standard",
            "",
            f"- Fusion: `{policy.get('fusion')}`",
            f"- Project weight: `{policy.get('project_weight')}`",
            f"- Wiki weight: `{policy.get('wiki_weight')}`",
            f"- Max wiki share after fusion: `{(policy.get('anti_drowning') or {}).get('max_wiki_share_after_fusion')}`",
            "- Report project and wiki hit counts separately before using combined recall as a quality gate.",
            "",
            "## Issues",
            "",
            *issue_lines,
            "",
            "## Standard Feedback",
            "",
            standard_feedback,
            "",
            "## Goldset Feedback",
            "",
            goldset_feedback,
            "",
        ]
    )


def _read_json(path: Path, *, expected: type, required: bool = True) -> Any:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, expected):
        raise ValueError(f"{path.name} must contain {expected.__name__}")
    return data


def _load_review_judgment_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL row {line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"judgment row {line_number} must be an object")
        if str(row.get("schema_version") or "") != "chunk-goldset-review-judgment/v1":
            raise ValueError(f"judgment row {line_number} has unsupported schema_version")
        if not str(row.get("query_id") or "").strip():
            raise ValueError(f"judgment row {line_number} missing query_id")
        if not bool(row.get("no_gold")) and not str(row.get("chunk_id") or "").strip():
            raise ValueError(f"judgment row {line_number} missing chunk_id")
        rows.append(row)
    if not rows:
        raise ValueError("judgment JSONL contains no rows")
    return rows


def _coerce_human_relevance(value: Any, fallback: int) -> int:
    if value is None or value == "":
        return fallback
    try:
        relevance = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"human_relevance must be an integer, got {value!r}") from exc
    if relevance < 0 or relevance > 4:
        raise ValueError("human_relevance must be between 0 and 4")
    return relevance


def _evidence_chunk_ids(evidence: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for items in evidence.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                refs.append(str(item.get("chunk_id") or "").strip())
    return refs


def _review_text(review: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "abstract"):
        value = review.get(key)
        if isinstance(value, str):
            parts.append(value)
    sections = review.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, dict) and isinstance(section.get("text"), str):
                parts.append(section["text"])
    references = review.get("references")
    if isinstance(references, list):
        parts.extend(str(item) for item in references)
    return "\n".join(parts)


def _chunk_char_count(chunk: dict[str, Any]) -> int:
    value = chunk.get("char_count")
    if isinstance(value, int) and value >= 0:
        return value
    return len(str(chunk.get("text") or chunk.get("content") or ""))


def _normalized_chunk_texts(chunks: list[Any]) -> list[str]:
    texts: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text") or chunk.get("content") or "")
        normalized = _WHITESPACE_RE.sub(" ", text).strip().lower()
        if normalized:
            texts.append(normalized)
    return texts


def _duplicate_ratio(texts: list[str]) -> float:
    if not texts:
        return 0.0
    counts = Counter(texts)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    return round(duplicate_count / len(texts), 4)


def _percentile(values: list[int], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[int(index)])
    return round(ordered[lower] * (upper - index) + ordered[upper] * (index - lower), 2)


def _build_issues(
    *,
    metrics: ChunkQualityMetrics,
    chunks: list[Any],
    evidence_refs: list[str],
    chunk_id_set: set[str],
) -> list[ChunkQualityIssue]:
    issues: list[ChunkQualityIssue] = []
    missing_ids = [str(index) for index, chunk in enumerate(chunks) if not isinstance(chunk, dict) or not str(chunk.get("chunk_id") or "").strip()]
    if missing_ids:
        issues.append(ChunkQualityIssue(code="missing_chunk_id", severity="error", message="部分 chunk 缺少稳定 chunk_id。", count=len(missing_ids), examples=missing_ids[:5]))
    missing_evidence = sorted({ref for ref in evidence_refs if ref and ref not in chunk_id_set})
    if missing_evidence:
        issues.append(ChunkQualityIssue(code="evidence_ref_missing_chunk", severity="error", message="evidence.json 引用了 chunks.json 中不存在的 chunk_id。", count=len(missing_evidence), examples=missing_evidence[:5]))
    short_chunks = _chunk_examples(chunks, lambda chunk: _chunk_char_count(chunk) < 120)
    if short_chunks:
        issues.append(ChunkQualityIssue(code="chunk_too_short", severity="warning", message="部分 chunk 过短，可能缺少独立语义。", count=len(short_chunks), examples=short_chunks[:5]))
    long_chunks = _chunk_examples(chunks, lambda chunk: _chunk_char_count(chunk) > 3000)
    if long_chunks:
        issues.append(ChunkQualityIssue(code="chunk_too_long", severity="warning", message="部分 chunk 过长，可能降低召回精度和重排稳定性。", count=len(long_chunks), examples=long_chunks[:5]))
    if metrics.duplicate_chunk_ratio > 0.02:
        issues.append(ChunkQualityIssue(code="duplicate_chunk_text", severity="warning", message="重复 chunk 比例偏高，建议去重或按来源合并。", count=int(metrics.duplicate_chunk_ratio * metrics.chunk_count)))
    if metrics.figure_reference_count == 0:
        issues.append(ChunkQualityIssue(code="missing_figure_refs", severity="warning", message="review_content 未检测到图引用。"))
    if metrics.table_reference_count == 0:
        issues.append(ChunkQualityIssue(code="missing_table_refs", severity="warning", message="review_content 未检测到表引用。"))
    if metrics.equation_reference_count == 0:
        issues.append(ChunkQualityIssue(code="missing_equation_refs", severity="warning", message="review_content 未检测到公式/式号引用。"))
    if metrics.evidence_section_count < 3:
        issues.append(ChunkQualityIssue(code="low_evidence_section_coverage", severity="warning", message="证据索引覆盖的主题 section 偏少。"))
    return issues


def _chunk_examples(chunks: list[Any], predicate: Any) -> list[str]:
    examples: list[str] = []
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            continue
        if predicate(chunk):
            examples.append(str(chunk.get("chunk_id") or index))
    return examples


def _score_issues(issues: list[ChunkQualityIssue]) -> float:
    penalties = {"error": 25.0, "warning": 6.0, "info": 2.0}
    score = 100.0 - sum(penalties[issue.severity] for issue in issues)
    return round(max(0.0, min(100.0, score)), 1)


def _standard_feedback(metrics: ChunkQualityMetrics, issues: list[ChunkQualityIssue]) -> list[str]:
    feedback = [
        "标准建议: chunk 必须有稳定 chunk_id/source_id/page 范围, evidence 引用必须能回查到 chunks.json。",
        "标准建议: 写作包需显式保留图、表、公式引用检查项, 作为 journal style/profile gate 的输入。",
        "标准建议: retrieval diagnostics 必须记录 project/wiki 权重、fusion 方法和 rerank/embedding 状态。",
    ]
    if any(issue.code in {"chunk_too_short", "chunk_too_long"} for issue in issues):
        feedback.append("标准建议: 将 chunk 长度目标收敛到约 120-3000 字符, 对表格/公式/图题单独保留结构化邻居。")
    if metrics.duplicate_chunk_ratio > 0.0:
        feedback.append("标准建议: 对完全重复 chunk 做 hash 去重, 保留多来源映射而不是重复正文。")
    return feedback


def _goldset_feedback(metrics: ChunkQualityMetrics, issues: list[ChunkQualityIssue]) -> list[str]:
    feedback = [
        "金标准建议: 从 evidence.json 的每个主题 section 抽样生成 query->expected_chunk_ids qrels。",
        "金标准建议: 对 review_content 中每个关键引用编号建立 citation->chunk_id/material_id 对照。",
        "金标准建议: wiki+project 联合召回评测需分别报告 project_recall、wiki_recall、combined_recall 和 wiki_share_after_fusion。",
    ]
    if any(issue.severity == "error" for issue in issues):
        feedback.append("金标准阻塞: 先修复 error 级 chunk/evidence 引用一致性, 再把该包提升为 gold 数据。")
    if metrics.figure_reference_count == 0 or metrics.table_reference_count == 0 or metrics.equation_reference_count == 0:
        feedback.append("金标准建议: 为图/表/公式补人工标注 query 和 expected locator, 防止写作只引用正文。")
    return feedback


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(max(0.0, min(1.0, numerator / denominator)), 4)


__all__ = [
    "ChunkGoldsetPromotionManifest",
    "ChunkGoldsetReviewBundle",
    "GoldsetProposalQuery",
    "GoldsetProposalReport",
    "ChunkPackageQualityReport",
    "ChunkQualityIssue",
    "ChunkQualityMetrics",
    "audit_chunk_package",
    "default_joint_recall_policy",
    "promote_reviewed_goldset_qrels",
    "propose_goldset_from_chunk_package",
    "weighted_rrf_fuse",
    "write_chunk_package_quality_report",
    "write_chunk_goldset_review_bundle",
    "write_goldset_proposal_report",
]
