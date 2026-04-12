# -*- coding: utf-8 -*-
"""
Writing Resources - First-class backend models for writing project structure.

Phase 3 of harness upgrade: Real project/section/draft/revision resources.
Replaces fabricated success payloads with persistent resource layer.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from datetime_utils import utc_now_iso_z


class ProjectStatus(str, Enum):
    """Status of a writing project."""
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ContentType(str, Enum):
    """Type of writing content."""
    ACADEMIC = "academic"
    TECHNICAL = "technical"
    CREATIVE = "creative"
    BUSINESS = "business"
    GENERAL = "general"


class DraftStatus(str, Enum):
    """Status of a draft."""
    CREATED = "created"
    EDITING = "editing"
    REVIEW_READY = "review_ready"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class WritingProject:
    """
    Represents a writing project containing sections and drafts.
    
    Immutable root resource for organizing writing work.
    """
    project_id: str
    title: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.DRAFT
    content_type: ContentType = ContentType.GENERAL
    created_at: str = field(default_factory=utc_now_iso_z)
    updated_at: str = field(default_factory=utc_now_iso_z)
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    @staticmethod
    def create(
        title: str,
        description: str = "",
        content_type: ContentType = ContentType.GENERAL,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> WritingProject:
        """Factory method to create a new project."""
        return WritingProject(
            project_id=f"proj_{uuid4().hex[:12]}",
            title=title,
            description=description,
            status=ProjectStatus.DRAFT,
            content_type=content_type,
            user_id=user_id,
            metadata=metadata or {},
            tags=tags or [],
        )

    def with_status(self, status: ProjectStatus) -> WritingProject:
        """Return a new project with updated status."""
        return WritingProject(
            project_id=self.project_id,
            title=self.title,
            description=self.description,
            status=status,
            content_type=self.content_type,
            created_at=self.created_at,
            updated_at=utc_now_iso_z(),
            user_id=self.user_id,
            metadata=self.metadata,
            tags=self.tags,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        data = asdict(self)
        data["status"] = self.status.value
        data["content_type"] = self.content_type.value
        return data


@dataclass(frozen=True)
class WritingSection:
    """
    Represents a section within a project.
    
    Sections organize large documents into manageable parts.
    """
    section_id: str
    project_id: str
    title: str
    order: int
    description: str = ""
    created_at: str = field(default_factory=utc_now_iso_z)
    updated_at: str = field(default_factory=utc_now_iso_z)
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        project_id: str,
        title: str,
        order: int,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WritingSection:
        """Factory method to create a new section."""
        return WritingSection(
            section_id=f"sect_{uuid4().hex[:12]}",
            project_id=project_id,
            title=title,
            order=order,
            description=description,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)


@dataclass(frozen=True)
class WritingDraft:
    """
    Represents a draft of content for a section or entire project.
    
    Drafts are versioned; multiple revisions can exist for one draft.
    """
    draft_id: str
    project_id: str
    section_id: str | None = None  # None for project-level draft
    title: str = ""
    content: str = ""
    status: DraftStatus = DraftStatus.CREATED
    created_at: str = field(default_factory=utc_now_iso_z)
    updated_at: str = field(default_factory=utc_now_iso_z)
    last_edited_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        project_id: str,
        title: str = "",
        content: str = "",
        section_id: str | None = None,
        last_edited_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingDraft:
        """Factory method to create a new draft."""
        return WritingDraft(
            draft_id=f"draft_{uuid4().hex[:12]}",
            project_id=project_id,
            section_id=section_id,
            title=title,
            content=content,
            status=DraftStatus.CREATED,
            last_edited_by=last_edited_by,
            metadata=metadata or {},
        )

    def with_content(self, content: str, edited_by: str | None = None) -> WritingDraft:
        """Return a new draft with updated content."""
        return WritingDraft(
            draft_id=self.draft_id,
            project_id=self.project_id,
            section_id=self.section_id,
            title=self.title,
            content=content,
            status=DraftStatus.EDITING,
            created_at=self.created_at,
            updated_at=utc_now_iso_z(),
            last_edited_by=edited_by or self.last_edited_by,
            metadata=self.metadata,
        )

    def with_status(self, status: DraftStatus) -> WritingDraft:
        """Return a new draft with updated status."""
        return WritingDraft(
            draft_id=self.draft_id,
            project_id=self.project_id,
            section_id=self.section_id,
            title=self.title,
            content=self.content,
            status=status,
            created_at=self.created_at,
            updated_at=utc_now_iso_z(),
            last_edited_by=self.last_edited_by,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class WritingRevision:
    """
    Represents a revision/snapshot of a draft.
    
    Each revision captures a point-in-time version of content.
    Immutable audit trail for draft evolution.
    """
    revision_id: str
    draft_id: str
    project_id: str
    content: str
    revision_number: int
    created_at: str = field(default_factory=utc_now_iso_z)
    created_by: str | None = None
    message: str = "Auto-saved"
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        draft_id: str,
        project_id: str,
        content: str,
        revision_number: int,
        created_by: str | None = None,
        message: str = "Auto-saved",
        metadata: dict[str, Any] | None = None,
    ) -> WritingRevision:
        """Factory method to create a new revision."""
        return WritingRevision(
            revision_id=f"rev_{uuid4().hex[:12]}",
            draft_id=draft_id,
            project_id=project_id,
            content=content,
            revision_number=revision_number,
            created_by=created_by or "system",
            message=message,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)


@dataclass(frozen=True)
class WritingAssociationSignal:
    """
    Normalized evidence that can seed associative writing.

    Why:
        Writing guidance should retain source traceability so downstream tools can
        explain why a section, draft, or memory hit was suggested.
    """

    source_type: str
    source_id: str
    title: str
    excerpt: str
    score: float
    shared_terms: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the signal to a JSON-safe payload."""
        return asdict(self)


@dataclass(frozen=True)
class WritingAssociationAngle:
    """
    Bridgeable angle synthesized from multiple association signals.

    Why:
        Associative writing is more useful when the system returns explicit
        connection paths rather than only ranked retrieval results.
    """

    angle_id: str
    title: str
    prompt: str
    supporting_source_ids: list[str] = field(default_factory=list)
    shared_terms: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the angle to a JSON-safe payload."""
        return asdict(self)


@dataclass(frozen=True)
class WritingEvidenceGap:
    """
    Missing evidence or coverage weakness detected during association building.

    Why:
        Strong writing support needs to expose where the knowledge chain is thin
        so the user can decide whether to retrieve more evidence before drafting.
    """

    gap: str
    severity: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the gap to a JSON-safe payload."""
        return asdict(self)


@dataclass(frozen=True)
class WritingAssociationBundle:
    """
    Full associative-writing response for one project-scoped request.

    Why:
        The bundle groups focus terms, linked evidence, bridge prompts, and gap
        analysis into a single stable payload that can be consumed by APIs or UI.
    """

    project_id: str
    query: str
    generated_at: str = field(default_factory=utc_now_iso_z)
    draft_id: str | None = None
    section_id: str | None = None
    mode: str = "no_ai"
    ai_enhanced: bool = False
    focus_terms: list[str] = field(default_factory=list)
    memory_used: bool = False
    memory_hit_count: int = 0
    related_signals: list[WritingAssociationSignal] = field(default_factory=list)
    association_angles: list[WritingAssociationAngle] = field(default_factory=list)
    continuation_prompts: list[str] = field(default_factory=list)
    evidence_gaps: list[WritingEvidenceGap] = field(default_factory=list)
    recommended_memory_queries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bundle to a JSON-safe payload."""
        return {
            "project_id": self.project_id,
            "query": self.query,
            "generated_at": self.generated_at,
            "draft_id": self.draft_id,
            "section_id": self.section_id,
            "mode": self.mode,
            "ai_enhanced": self.ai_enhanced,
            "focus_terms": list(self.focus_terms),
            "memory_used": self.memory_used,
            "memory_hit_count": self.memory_hit_count,
            "related_signals": [signal.to_dict() for signal in self.related_signals],
            "association_angles": [angle.to_dict() for angle in self.association_angles],
            "continuation_prompts": list(self.continuation_prompts),
            "evidence_gaps": [gap.to_dict() for gap in self.evidence_gaps],
            "recommended_memory_queries": list(self.recommended_memory_queries),
        }


@dataclass(frozen=True)
class _AssociationCandidate:
    """Internal normalized source used during associative scoring."""

    source_type: str
    source_id: str
    title: str
    excerpt: str
    terms: tuple[str, ...]
    raw_score_boost: float = 0.0


_TERM_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]{2,}")
_EN_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "it", "of", "on", "or", "that", "the", "their", "this", "to", "with",
    "using", "used", "via", "than", "then", "when", "where", "which", "while",
}
_ZH_STOPWORDS = {
    "一个", "一种", "一些", "以及", "但是", "因为", "所以", "可以", "进行", "如果", "需要",
    "对于", "通过", "没有", "这个", "那个", "这些", "那些", "我们", "你们", "他们", "研究",
    "问题", "方法", "结果", "分析", "内容", "相关", "说明", "工作", "阶段", "当前",
}


def _trim_preview(text: str, limit: int) -> str:
    """Return a bounded preview string for API-facing association output."""
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _expand_chinese_term(token: str) -> list[str]:
    """Expand a Chinese token into stable phrase windows for overlap matching."""
    cleaned = token.strip()
    if len(cleaned) < 2:
        return []
    if len(cleaned) <= 4:
        return [cleaned]

    terms: list[str] = [cleaned]
    max_ngram = min(4, len(cleaned))
    for size in range(2, max_ngram + 1):
        for start in range(0, len(cleaned) - size + 1):
            candidate = cleaned[start : start + size]
            if candidate not in terms:
                terms.append(candidate)
    return terms


def _extract_terms(text: str) -> list[str]:
    """Extract normalized English and Chinese terms for associative scoring."""
    if not isinstance(text, str):
        return []

    terms: list[str] = []
    seen: set[str] = set()
    for match in _TERM_PATTERN.finditer(text):
        raw_token = match.group(0).strip()
        if not raw_token:
            continue

        if raw_token.isascii():
            token = raw_token.lower()
            if token in _EN_STOPWORDS or len(token) < 2:
                continue
            if token not in seen:
                seen.add(token)
                terms.append(token)
            continue

        for candidate in _expand_chinese_term(raw_token):
            if candidate in _ZH_STOPWORDS or len(candidate) < 2:
                continue
            if candidate not in seen:
                seen.add(candidate)
                terms.append(candidate)
    return terms


def _extract_focus_terms(texts: Iterable[str], limit: int) -> list[str]:
    """Rank salient terms across multiple texts for downstream association use."""
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    counter: Counter[str] = Counter()
    for text in texts:
        for term in _extract_terms(text):
            counter[term] += 1
    ranked = sorted(counter.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [term for term, _ in ranked[:limit]]


def _normalize_score(value: float) -> float:
    """Clamp association scores into the stable 0-1 range."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return round(value, 4)


def _coerce_unit_score(value: Any) -> float:
    """Convert heterogeneous retrieval scores into a stable 0-1 range."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0

    if numeric <= 0.0:
        return 0.0
    if numeric <= 1.0:
        return round(numeric, 4)
    if numeric <= 10.0:
        return round(numeric / 10.0, 4)
    if numeric <= 100.0:
        return round(numeric / 100.0, 4)
    return 1.0


def _normalize_gap_severity(value: Any) -> str:
    """Map heterogeneous severity payloads into the public low/medium/high contract."""
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric >= 3.0:
            return "high"
        if numeric >= 2.0:
            return "medium"
        return "low"

    text = str(value or "").strip().lower()
    if text in {"critical", "high", "severe"}:
        return "high"
    if text in {"medium", "moderate"}:
        return "medium"
    return "low"


def _derive_analysis_terms(*texts: Any, limit: int = 4) -> list[str]:
    """Extract a compact set of matching terms from heterogeneous analysis text."""
    normalized_texts = [
        str(text).strip()
        for text in texts
        if isinstance(text, str) and text.strip()
    ]
    if not normalized_texts:
        return []
    return _extract_focus_terms(normalized_texts, limit=limit)


def _resolve_supporting_source_ids(
    signals: Sequence[WritingAssociationSignal],
    candidate_terms: Sequence[str],
    fallback_limit: int = 2,
) -> list[str]:
    """Resolve analysis-derived angles back to grounded source identifiers."""
    fallback_ids = [signal.source_id for signal in signals[: max(1, fallback_limit)]]
    normalized_terms = [term for term in candidate_terms if isinstance(term, str) and term.strip()]
    if not normalized_terms:
        return fallback_ids

    matched_ids: list[str] = []
    for signal in signals:
        signal_terms = set(
            [
                *signal.shared_terms,
                *_extract_terms(signal.title),
                *_extract_terms(signal.excerpt),
            ]
        )
        if any(term in signal_terms for term in normalized_terms):
            matched_ids.append(signal.source_id)

    if matched_ids:
        return list(dict.fromkeys(matched_ids))
    return fallback_ids


def _merge_unique_angles(
    base_angles: Sequence[WritingAssociationAngle],
    extra_angles: Sequence[WritingAssociationAngle],
    limit: int,
) -> list[WritingAssociationAngle]:
    """Merge association angles while preserving order and avoiding duplicates."""
    merged: list[WritingAssociationAngle] = []
    seen: set[tuple[str, str]] = set()
    for angle in [*base_angles, *extra_angles]:
        key = (angle.title.strip().lower(), angle.prompt.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append(angle)
        if len(merged) >= limit:
            break
    return merged


def _merge_unique_gaps(
    base_gaps: Sequence[WritingEvidenceGap],
    extra_gaps: Sequence[WritingEvidenceGap],
    limit: int,
) -> list[WritingEvidenceGap]:
    """Merge evidence gaps while preserving order and avoiding duplicates."""
    merged: list[WritingEvidenceGap] = []
    seen: set[tuple[str, str, str]] = set()
    for gap in [*base_gaps, *extra_gaps]:
        key = (
            gap.gap.strip().lower(),
            gap.severity.strip().lower(),
            gap.recommendation.strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(gap)
        if len(merged) >= limit:
            break
    return merged


def _merge_unique_strings(
    base_items: Sequence[str],
    extra_items: Sequence[str],
    limit: int,
) -> list[str]:
    """Merge user-facing strings while preserving order and avoiding duplicates."""
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*base_items, *extra_items]:
        normalized = str(item).strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
        if len(merged) >= limit:
            break
    return merged


def _extract_scoring_payload(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the scoring payload from either the raw file envelope or the inner object."""
    if isinstance(payload.get("scoring"), Mapping):
        return payload.get("scoring")
    if "selected_writing_points" in payload or "semantic_themes" in payload:
        return payload
    return None


def _extract_reasoning_payload(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return a normalized reasoning payload when present."""
    if isinstance(payload.get("reasoning_chain"), Mapping):
        return payload.get("reasoning_chain")
    if "conflicts" in payload or "final_conclusion" in payload:
        return payload
    return None


def _extract_association_output_payload(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the analysis payload that follows the AssociationOutput contract."""
    if isinstance(payload.get("association_output"), Mapping):
        return payload.get("association_output")
    if (
        "structural_risks" in payload
        or "logic_tracing_path" in payload
        or "conflict_report" in payload
    ):
        return payload
    return None


def _extract_cross_paper_payload(
    payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """Return normalized cross-paper conflict and trend payloads when present."""
    if isinstance(payload.get("conflict_analysis"), Mapping):
        trend_payload = payload.get("technology_trends")
        return payload.get("conflict_analysis"), trend_payload if isinstance(trend_payload, Mapping) else None
    if (
        "parameter_consensus" in payload
        or "high_conflict_parameters" in payload
        or "consensus_parameters" in payload
    ):
        return payload, None
    return None, None


def _build_analysis_angle(
    bundle: WritingAssociationBundle,
    angle_id: str,
    title: str,
    prompt: str,
    *term_texts: Any,
    confidence: float,
) -> WritingAssociationAngle | None:
    """Create a grounded writing angle from analysis text."""
    normalized_title = str(title).strip()
    normalized_prompt = str(prompt).strip()
    if not normalized_title or not normalized_prompt:
        return None

    shared_terms = _derive_analysis_terms(bundle.query, *term_texts, limit=4)
    if not shared_terms:
        shared_terms = list(bundle.focus_terms[:2])

    return WritingAssociationAngle(
        angle_id=angle_id,
        title=normalized_title,
        prompt=normalized_prompt,
        supporting_source_ids=_resolve_supporting_source_ids(bundle.related_signals, shared_terms),
        shared_terms=shared_terms[:4],
        confidence=_normalize_score(confidence),
    )


def _extract_scoring_enrichment(
    bundle: WritingAssociationBundle,
    payload: Mapping[str, Any],
) -> tuple[list[WritingAssociationAngle], list[str], list[WritingEvidenceGap], list[str]]:
    """Translate scoring-layer themes into writing-facing angles and prompts."""
    scoring = _extract_scoring_payload(payload)
    if scoring is None:
        return [], [], [], []

    extra_angles: list[WritingAssociationAngle] = []
    extra_prompts: list[str] = []
    extra_gaps: list[WritingEvidenceGap] = []
    extra_queries: list[str] = []

    raw_themes = scoring.get("semantic_themes", [])
    if isinstance(raw_themes, Sequence):
        for index, raw_theme in enumerate(raw_themes[:2], start=1):
            if not isinstance(raw_theme, Mapping):
                continue
            theme_title = str(raw_theme.get("theme_title", "")).strip()
            summary = str(raw_theme.get("summary", "")).strip()
            if not theme_title:
                continue
            angle = _build_analysis_angle(
                bundle,
                f"analysis_theme_{index}",
                f"Synthesize theme '{theme_title}'",
                (
                    f"Use the '{theme_title}' theme as the next bridge paragraph: "
                    f"condense its evidence, then connect that synthesis back to '{bundle.query}'."
                ),
                theme_title,
                summary,
                confidence=0.68,
            )
            if angle is not None:
                extra_angles.append(angle)
            extra_prompts.append(
                f"After the current paragraph, synthesize the '{theme_title}' theme and explain how it reframes '{bundle.query}'."
            )
            extra_queries.append(f"{bundle.query} {theme_title}".strip())

    selected_points = scoring.get("selected_writing_points", [])
    if isinstance(selected_points, Sequence) and not selected_points:
        extra_gaps.append(
            WritingEvidenceGap(
                gap="Academic scoring did not surface stable writing points",
                severity="medium",
                recommendation="Refine the goal or add a narrower draft anchor before expanding the section.",
            )
        )

    return extra_angles, extra_prompts, extra_gaps, extra_queries


def _extract_reasoning_enrichment(
    bundle: WritingAssociationBundle,
    payload: Mapping[str, Any],
) -> tuple[list[WritingAssociationAngle], list[str], list[WritingEvidenceGap], list[str]]:
    """Translate reasoning-chain conflicts into writing gaps and contrast angles."""
    reasoning = _extract_reasoning_payload(payload)
    if reasoning is None:
        return [], [], [], []

    extra_angles: list[WritingAssociationAngle] = []
    extra_prompts: list[str] = []
    extra_gaps: list[WritingEvidenceGap] = []
    extra_queries: list[str] = []

    final_conclusion = str(reasoning.get("final_conclusion", "")).strip()
    if final_conclusion:
        angle = _build_analysis_angle(
            bundle,
            "analysis_reasoning_conclusion",
            "Frame the next paragraph with the reasoning conclusion",
            (
                "Use the reasoning conclusion as the framing sentence for the next paragraph, "
                f"then ground it with the strongest retrieved evidence: {final_conclusion}"
            ),
            final_conclusion,
            confidence=0.72,
        )
        if angle is not None:
            extra_angles.append(angle)
        extra_prompts.append(
            f"Open the next paragraph with this bounded synthesis, then justify it with cited evidence: {final_conclusion}"
        )

    raw_conflicts = reasoning.get("conflicts", [])
    if isinstance(raw_conflicts, Sequence):
        for index, raw_conflict in enumerate(raw_conflicts[:2], start=1):
            if not isinstance(raw_conflict, Mapping):
                continue
            severity = _normalize_gap_severity(raw_conflict.get("severity_level", 2))
            interpretation = str(raw_conflict.get("interpretation", "")).strip()
            authority_summary = str(raw_conflict.get("authority_summary", "")).strip()
            resolution_path = [
                str(step).strip()
                for step in raw_conflict.get("resolution_path", [])
                if str(step).strip()
            ]

            claim_subjects: list[str] = []
            claim_objects: list[str] = []
            for raw_claim in raw_conflict.get("claims_involved", []):
                if not isinstance(raw_claim, Mapping):
                    continue
                subject = str(raw_claim.get("subject", "")).strip()
                obj = str(raw_claim.get("object", "")).strip()
                if subject:
                    claim_subjects.append(subject)
                if obj:
                    claim_objects.append(obj)

            subject_label = claim_subjects[0] if claim_subjects else "the disputed claim"
            severity_level = raw_conflict.get("severity_level", 2)
            if isinstance(severity_level, (int, float)):
                severity_confidence = 0.58 + (0.1 * min(3, int(severity_level)))
            else:
                severity_confidence = 0.68
            angle = _build_analysis_angle(
                bundle,
                f"analysis_conflict_{index}",
                f"Resolve conflict on '{subject_label}'",
                (
                    f"Write a contrast paragraph around '{subject_label}': summarize the disagreement, "
                    f"state the boundary condition, then use this action path to resolve or bound the claim: "
                    f"{'; '.join(resolution_path[:2]) or interpretation or authority_summary}"
                ),
                subject_label,
                interpretation,
                authority_summary,
                *claim_objects,
                confidence=severity_confidence,
            )
            if angle is not None:
                extra_angles.append(angle)

            recommendation = (
                resolution_path[0]
                if resolution_path
                else authority_summary
                or "State the conflicting conditions before using this claim as stable support."
            )
            extra_gaps.append(
                WritingEvidenceGap(
                    gap=f"Conflicting evidence around '{subject_label}' is not yet resolved",
                    severity=severity,
                    recommendation=recommendation,
                )
            )
            extra_prompts.append(
                f"In the next paragraph, acknowledge the disagreement on '{subject_label}' and explain which condition controls the difference."
            )
            extra_queries.append(f"{subject_label} consensus review".strip())

    return extra_angles, extra_prompts, extra_gaps, extra_queries


def _extract_association_output_enrichment(
    bundle: WritingAssociationBundle,
    payload: Mapping[str, Any],
) -> tuple[list[WritingAssociationAngle], list[str], list[WritingEvidenceGap], list[str]]:
    """Translate structural risk and logic-tracing payloads into writing guidance."""
    association_output = _extract_association_output_payload(payload)
    if association_output is None:
        return [], [], [], []

    extra_angles: list[WritingAssociationAngle] = []
    extra_prompts: list[str] = []
    extra_gaps: list[WritingEvidenceGap] = []
    extra_queries: list[str] = []

    raw_risks = association_output.get("structural_risks", [])
    if isinstance(raw_risks, Sequence):
        for index, raw_risk in enumerate(raw_risks[:2], start=1):
            if not isinstance(raw_risk, Mapping):
                continue
            description = str(raw_risk.get("description", "")).strip()
            suggestion = str(raw_risk.get("suggestion", "")).strip()
            severity = _normalize_gap_severity(raw_risk.get("severity", "medium"))
            if not description:
                continue
            extra_gaps.append(
                WritingEvidenceGap(
                    gap=description,
                    severity=severity,
                    recommendation=suggestion or "Use the next paragraph to repair this structural weakness before expanding the claim.",
                )
            )
            angle = _build_analysis_angle(
                bundle,
                f"analysis_risk_{index}",
                f"Repair structural risk: {raw_risk.get('type', 'argument gap')}",
                (
                    f"Use the next paragraph to repair this structural weakness: {description}. "
                    f"Preferred repair move: {suggestion or 'add explicit evidence and state the boundary condition'}."
                ),
                str(raw_risk.get("type", "")),
                description,
                suggestion,
                confidence=0.62,
            )
            if angle is not None:
                extra_angles.append(angle)
            if suggestion:
                extra_prompts.append(
                    f"Before expanding the section, address this risk explicitly: {suggestion}"
                )

    logic_path = association_output.get("logic_tracing_path")
    if isinstance(logic_path, Mapping):
        entry_claim = str(logic_path.get("entry_claim", "")).strip()
        steps = logic_path.get("steps", [])
        last_step = steps[-1] if isinstance(steps, Sequence) and steps else {}
        last_reason = str(last_step.get("reason", "")).strip() if isinstance(last_step, Mapping) else ""
        last_result = str(last_step.get("result", "")).strip() if isinstance(last_step, Mapping) else ""
        if entry_claim:
            angle = _build_analysis_angle(
                bundle,
                "analysis_logic_trace",
                "Continue the traced reasoning path",
                (
                    f"Bridge from the current claim '{entry_claim}' to the next paragraph by following the traced reasoning path, "
                    f"ending with {last_result or last_reason or 'the next evidence-backed conclusion'}."
                ),
                entry_claim,
                last_reason,
                last_result,
                confidence=0.66,
            )
            if angle is not None:
                extra_angles.append(angle)
            extra_prompts.append(
                f"Use the logic trace to transition from '{entry_claim}' toward the next evidence-backed conclusion."
            )

    conflict_report = association_output.get("conflict_report")
    if isinstance(conflict_report, Mapping):
        nested_angles, nested_prompts, nested_gaps, nested_queries = _extract_cross_paper_enrichment(
            bundle,
            conflict_report,
        )
        extra_angles.extend(nested_angles)
        extra_prompts.extend(nested_prompts)
        extra_gaps.extend(nested_gaps)
        extra_queries.extend(nested_queries)

    return extra_angles, extra_prompts, extra_gaps, extra_queries


def _extract_cross_paper_enrichment(
    bundle: WritingAssociationBundle,
    payload: Mapping[str, Any],
) -> tuple[list[WritingAssociationAngle], list[str], list[WritingEvidenceGap], list[str]]:
    """Translate cross-paper consensus and disagreement payloads into writing moves."""
    conflict_payload, trend_payload = _extract_cross_paper_payload(payload)
    if conflict_payload is None:
        return [], [], [], []

    extra_angles: list[WritingAssociationAngle] = []
    extra_prompts: list[str] = []
    extra_gaps: list[WritingEvidenceGap] = []
    extra_queries: list[str] = []

    high_conflicts = conflict_payload.get("high_conflict_parameters", [])
    if isinstance(high_conflicts, Sequence):
        for index, raw_conflict in enumerate(high_conflicts[:2], start=1):
            if not isinstance(raw_conflict, Mapping):
                continue
            parameter = str(raw_conflict.get("parameter", "")).strip() or "the disputed parameter"
            claim_texts = [
                str(item.get("text", "")).strip()
                for item in raw_conflict.get("claims", [])
                if isinstance(item, Mapping) and str(item.get("text", "")).strip()
            ]
            angle = _build_analysis_angle(
                bundle,
                f"analysis_cross_conflict_{index}",
                f"Contrast disagreement on '{parameter}'",
                (
                    f"Use '{parameter}' as a contrast axis: summarize the competing claims, "
                    "then explain which experimental or argumentative condition may account for the divergence."
                ),
                parameter,
                *claim_texts,
                confidence=0.73,
            )
            if angle is not None:
                extra_angles.append(angle)
            extra_gaps.append(
                WritingEvidenceGap(
                    gap=f"Cross-source evidence on '{parameter}' remains divergent",
                    severity="high",
                    recommendation=(
                        f"Compare the claim variants for '{parameter}' and state the boundary conditions before presenting it as stable support."
                    ),
                )
            )
            extra_prompts.append(
                f"Add a contrast sentence for '{parameter}' before claiming broad agreement."
            )
            extra_queries.append(f"{parameter} disagreement boundary conditions".strip())

    consensus_parameters = conflict_payload.get("consensus_parameters", [])
    if isinstance(consensus_parameters, Sequence) and consensus_parameters:
        consensus_item = consensus_parameters[0]
        if isinstance(consensus_item, Mapping):
            parameter = str(consensus_item.get("parameter", "")).strip()
            if parameter:
                angle = _build_analysis_angle(
                    bundle,
                    "analysis_consensus_baseline",
                    f"Use consensus on '{parameter}' as the baseline",
                    (
                        f"Start the next paragraph with the stable consensus around '{parameter}', "
                        "then transition into the more nuanced or disputed evidence."
                    ),
                    parameter,
                    confidence=0.64,
                )
                if angle is not None:
                    extra_angles.append(angle)

    if isinstance(trend_payload, Mapping):
        trend_map = trend_payload.get("parameter_trends", {})
        if isinstance(trend_map, Mapping):
            divergent_parameters = [
                str(param).strip()
                for param, info in trend_map.items()
                if isinstance(info, Mapping) and info.get("consensus") is False and str(param).strip()
            ]
            if divergent_parameters:
                extra_queries.append(
                    " ".join([bundle.query, divergent_parameters[0], "trend"]).strip()
                )

    return extra_angles, extra_prompts, extra_gaps, extra_queries


def _get_angle_signature(angle: WritingAssociationAngle) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    """Generate a normalized content signature for an association angle."""
    return (
        str(angle.title).strip().lower(),
        str(angle.prompt).strip().lower(),
        tuple(sorted(str(source_id).strip() for source_id in angle.supporting_source_ids)),
        tuple(sorted(str(term).strip().lower() for term in angle.shared_terms)),
    )


def _get_gap_signature(gap: WritingEvidenceGap) -> tuple[str, str, str]:
    """Generate a normalized content signature for an evidence gap."""
    return (
        str(gap.gap).strip().lower(),
        str(gap.severity).strip().lower(),
        str(gap.recommendation).strip().lower(),
    )


def check_association_enrichment_increment(
    base: WritingAssociationBundle,
    enriched: WritingAssociationBundle,
) -> bool:
    """
    Check if the enriched bundle actually contains more or different writing suggestions than the base bundle.

    Why:
        A deterministic baseline (no_ai) should only be marked as 'enriched' if the
        analysis platform provided actionable increments or content updates
        beyond the standard retrieval results.
    """
    if not isinstance(base, WritingAssociationBundle) or not isinstance(enriched, WritingAssociationBundle):
        return False
    
    # 1. Compare lengths first as a fast path
    if (len(enriched.association_angles) > len(base.association_angles) or
        len(enriched.evidence_gaps) > len(base.evidence_gaps) or
        len(enriched.continuation_prompts) > len(base.continuation_prompts) or
        len(enriched.recommended_memory_queries) > len(base.recommended_memory_queries)):
        return True

    # 2. Compare content signatures if lengths are the same
    #    Use Counters so repeated suggestions remain visible even when the
    #    unique content set is unchanged.
    # Angles
    base_angle_sigs = Counter(_get_angle_signature(a) for a in base.association_angles)
    enriched_angle_sigs = Counter(_get_angle_signature(a) for a in enriched.association_angles)
    if enriched_angle_sigs != base_angle_sigs:
        return True

    # Gaps
    base_gap_sigs = Counter(_get_gap_signature(g) for g in base.evidence_gaps)
    enriched_gap_sigs = Counter(_get_gap_signature(g) for g in enriched.evidence_gaps)
    if enriched_gap_sigs != base_gap_sigs:
        return True

    # Continuation Prompts (String list comparison)
    base_prompt_sigs = Counter(str(p).strip().lower() for p in base.continuation_prompts)
    enriched_prompt_sigs = Counter(str(p).strip().lower() for p in enriched.continuation_prompts)
    if enriched_prompt_sigs != base_prompt_sigs:
        return True

    # Recommended Memory Queries (String list comparison)
    base_query_sigs = Counter(str(q).strip().lower() for q in base.recommended_memory_queries)
    enriched_query_sigs = Counter(str(q).strip().lower() for q in enriched.recommended_memory_queries)
    if enriched_query_sigs != base_query_sigs:
        return True

    return False


def apply_analysis_enrichment_to_bundle(
    bundle: WritingAssociationBundle,
    analysis_payloads: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[WritingAssociationBundle, bool]:
    """
    Apply analysis enrichment to a bundle and detect if actionable content actually changed.

    Why:
        Centralizes the 'enrich -> compare -> flag' logic to ensure consistency
        between workflow and pipeline paths and reduce implementation divergence.
    """
    if not analysis_payloads:
        return bundle, False

    enriched_bundle = enrich_association_bundle_with_analysis(bundle, analysis_payloads)
    was_enriched = check_association_enrichment_increment(bundle, enriched_bundle)
    return enriched_bundle, was_enriched


def enrich_association_bundle_with_analysis(
    bundle: WritingAssociationBundle,
    analysis_payloads: Sequence[Mapping[str, Any]] | None = None,
    *,
    extra_angle_budget: int = 2,
    extra_gap_budget: int = 3,
    extra_prompt_budget: int = 2,
    extra_query_budget: int = 2,
) -> WritingAssociationBundle:
    """
    Fold scientific-analysis artifacts into the writing bundle without changing evidence grounding.

    Why:
        The analysis platform already surfaces conflicts, structural risks, and
        thematic syntheses. This adapter turns those outputs into writing-facing
        angles and evidence gaps so the same product can support drafting.
    """
    if analysis_payloads is None:
        return bundle
    if extra_angle_budget < 0 or extra_gap_budget < 0 or extra_prompt_budget < 0 or extra_query_budget < 0:
        raise ValueError("analysis enrichment budgets must be non-negative")

    extra_angles: list[WritingAssociationAngle] = []
    extra_prompts: list[str] = []
    extra_gaps: list[WritingEvidenceGap] = []
    extra_queries: list[str] = []

    for extractor in (
        _extract_association_output_enrichment,
        _extract_reasoning_enrichment,
        _extract_cross_paper_enrichment,
        _extract_scoring_enrichment,
    ):
        for payload in analysis_payloads:
            if not isinstance(payload, Mapping) or not payload:
                continue
            angles, prompts, gaps, queries = extractor(bundle, payload)
            extra_angles.extend(angles)
            extra_prompts.extend(prompts)
            extra_gaps.extend(gaps)
            extra_queries.extend(queries)

    if not extra_angles and not extra_prompts and not extra_gaps and not extra_queries:
        return bundle

    merged_angles = _merge_unique_angles(
        bundle.association_angles,
        extra_angles,
        limit=max(len(bundle.association_angles), 1) + extra_angle_budget,
    )
    merged_gaps = _merge_unique_gaps(
        bundle.evidence_gaps,
        extra_gaps,
        limit=max(len(bundle.evidence_gaps), 1) + extra_gap_budget,
    )
    merged_prompts = _merge_unique_strings(
        bundle.continuation_prompts,
        extra_prompts,
        limit=max(len(bundle.continuation_prompts), 1) + extra_prompt_budget,
    )
    merged_queries = _merge_unique_strings(
        bundle.recommended_memory_queries,
        extra_queries,
        limit=max(len(bundle.recommended_memory_queries), 1) + extra_query_budget,
    )
    return _rebuild_association_bundle(
        bundle,
        mode=bundle.mode,
        ai_enhanced=bundle.ai_enhanced,
        association_angles=merged_angles,
        continuation_prompts=merged_prompts,
        evidence_gaps=merged_gaps,
        recommended_memory_queries=merged_queries,
    )


def _rebuild_association_bundle(
    base_bundle: WritingAssociationBundle,
    *,
    mode: str,
    ai_enhanced: bool,
    association_angles: Sequence[WritingAssociationAngle] | None = None,
    continuation_prompts: Sequence[str] | None = None,
    evidence_gaps: Sequence[WritingEvidenceGap] | None = None,
    recommended_memory_queries: Sequence[str] | None = None,
) -> WritingAssociationBundle:
    """Clone a bundle while replacing only the mode-specific writing outputs."""
    return WritingAssociationBundle(
        project_id=base_bundle.project_id,
        query=base_bundle.query,
        generated_at=base_bundle.generated_at,
        draft_id=base_bundle.draft_id,
        section_id=base_bundle.section_id,
        mode=mode,
        ai_enhanced=ai_enhanced,
        focus_terms=list(base_bundle.focus_terms),
        memory_used=base_bundle.memory_used,
        memory_hit_count=base_bundle.memory_hit_count,
        related_signals=list(base_bundle.related_signals),
        association_angles=list(
            association_angles if association_angles is not None else base_bundle.association_angles
        ),
        continuation_prompts=list(
            continuation_prompts if continuation_prompts is not None else base_bundle.continuation_prompts
        ),
        evidence_gaps=list(evidence_gaps if evidence_gaps is not None else base_bundle.evidence_gaps),
        recommended_memory_queries=list(
            recommended_memory_queries
            if recommended_memory_queries is not None
            else base_bundle.recommended_memory_queries
        ),
    )


def apply_association_mode(
    bundle: WritingAssociationBundle,
    mode: str,
    ai_adapter: Any | None = None,
    angle_limit: int = 3,
) -> WritingAssociationBundle:
    """
    Apply AI or No-AI post-processing without changing the grounded evidence base.

    Why:
        The no-AI path must remain a deterministic baseline. AI mode is layered
        on top of the same ranked signals so the writing assistant remains
        traceable and can always fall back safely.
    """
    normalized_mode = str(mode or "no_ai").strip().lower()
    if normalized_mode != "ai":
        return _rebuild_association_bundle(bundle, mode="no_ai", ai_enhanced=False)

    if ai_adapter is None or not getattr(ai_adapter, "enabled", False):
        return _rebuild_association_bundle(bundle, mode="ai", ai_enhanced=False)

    enhanced = ai_adapter.enhance_writing_association(
        query=bundle.query,
        focus_terms=list(bundle.focus_terms),
        related_signals=[signal.to_dict() for signal in bundle.related_signals],
        association_angles=[angle.to_dict() for angle in bundle.association_angles],
        continuation_prompts=list(bundle.continuation_prompts),
        evidence_gaps=[gap.to_dict() for gap in bundle.evidence_gaps],
        recommended_memory_queries=list(bundle.recommended_memory_queries),
        angle_limit=angle_limit,
    )
    if not isinstance(enhanced, Mapping) or not enhanced:
        return _rebuild_association_bundle(bundle, mode="ai", ai_enhanced=False)

    known_source_ids = {signal.source_id for signal in bundle.related_signals}
    fallback_source_ids = [signal.source_id for signal in bundle.related_signals[:2]]
    fallback_shared_terms = list(bundle.focus_terms[:2])
    fallback_confidence = 0.0
    if bundle.related_signals:
        top_signals = bundle.related_signals[:2]
        fallback_confidence = sum(signal.score for signal in top_signals) / len(top_signals)

    ai_angles: list[WritingAssociationAngle] = []
    for index, raw_angle in enumerate(enhanced.get("association_angles", []), start=1):
        if not isinstance(raw_angle, Mapping):
            continue
        prompt_text = str(raw_angle.get("prompt", "")).strip()
        if not prompt_text:
            continue
        supporting_source_ids = [
            source_id
            for source_id in (
                str(source_id).strip()
                for source_id in raw_angle.get("supporting_source_ids", [])
            )
            if source_id in known_source_ids
        ]
        shared_terms = [
            str(term).strip()
            for term in raw_angle.get("shared_terms", [])
            if str(term).strip()
        ]
        try:
            confidence = float(raw_angle.get("confidence", fallback_confidence))
        except (TypeError, ValueError):
            confidence = fallback_confidence
        ai_angles.append(
            WritingAssociationAngle(
                angle_id=f"ai_angle_{index}",
                title=str(raw_angle.get("title", "")).strip() or f"AI Angle {index}",
                prompt=prompt_text,
                supporting_source_ids=supporting_source_ids or fallback_source_ids,
                shared_terms=shared_terms or fallback_shared_terms,
                confidence=_normalize_score(confidence),
            )
        )

    ai_gaps: list[WritingEvidenceGap] = []
    for raw_gap in enhanced.get("evidence_gaps", []):
        if not isinstance(raw_gap, Mapping):
            continue
        gap_text = str(raw_gap.get("gap", "")).strip()
        recommendation = str(raw_gap.get("recommendation", "")).strip()
        if not gap_text or not recommendation:
            continue
        severity = str(raw_gap.get("severity", "medium")).strip().lower()
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        ai_gaps.append(
            WritingEvidenceGap(
                gap=gap_text,
                severity=severity,
                recommendation=recommendation,
            )
        )

    ai_prompts = [
        str(prompt).strip()
        for prompt in enhanced.get("continuation_prompts", [])
        if str(prompt).strip()
    ]
    ai_queries = [
        str(query_text).strip()
        for query_text in enhanced.get("recommended_memory_queries", [])
        if str(query_text).strip()
    ]
    ai_changed = bool(ai_angles or ai_prompts or ai_gaps or ai_queries)
    return _rebuild_association_bundle(
        bundle,
        mode="ai",
        ai_enhanced=ai_changed,
        association_angles=ai_angles if ai_angles else None,
        continuation_prompts=ai_prompts if ai_prompts else None,
        evidence_gaps=ai_gaps if ai_gaps else None,
        recommended_memory_queries=ai_queries if ai_queries else None,
    )


def build_association_bundle_from_runtime_context(
    query: str,
    draft_seed: str,
    focused_points: Sequence[str],
    retrieval_hits: Sequence[Mapping[str, Any]] | None = None,
    memory_hits: Sequence[Mapping[str, Any]] | None = None,
    analysis_payloads: Sequence[Mapping[str, Any]] | None = None,
    mode: str = "no_ai",
    project_id: str | None = None,
    draft_id: str | None = None,
    section_id: str | None = None,
    ai_adapter: Any | None = None,
    signal_limit: int = 6,
    angle_limit: int = 3,
) -> tuple[WritingAssociationBundle, bool]:
    """
    Build a writing association bundle from runtime context, with ephemeral fallback.

    Why:
        The writing assistant should be able to attach associative output to
        existing project resources when available, while still working for
        pipeline/workflow contexts that do not yet have a persisted project.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if signal_limit <= 0:
        raise ValueError("signal_limit must be a positive integer")
    if angle_limit <= 0:
        raise ValueError("angle_limit must be a positive integer")

    store: WritingResourceStore
    effective_project_id = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
    effective_draft_id = draft_id.strip() if isinstance(draft_id, str) and draft_id.strip() else None
    effective_section_id = section_id.strip() if isinstance(section_id, str) and section_id.strip() else None
    ephemeral_store = False

    if effective_project_id:
        store = get_writing_resource_store()
        existing_project = store.get_project(effective_project_id)
        if existing_project is None:
            effective_project_id = None

    if effective_project_id is None:
        store = WritingResourceStore()
        ephemeral_store = True
        title_seed = " / ".join(
            point.strip()
            for point in focused_points[:3]
            if isinstance(point, str) and point.strip()
        )
        ephemeral_project = store.create_project(
            title=title_seed or query[:60] or "Association Query",
            description=query.strip(),
            content_type=ContentType.ACADEMIC,
            tags=["runtime", "association", "ephemeral"],
        )
        ephemeral_section = store.create_section(
            ephemeral_project.project_id,
            title="Runtime Context",
            order=1,
            description=query.strip(),
        )
        ephemeral_draft = store.create_draft(
            ephemeral_project.project_id,
            section_id=ephemeral_section.section_id,
            title="Runtime Draft Seed",
            content=draft_seed.strip(),
        )
        effective_project_id = ephemeral_project.project_id
        effective_section_id = ephemeral_section.section_id
        effective_draft_id = ephemeral_draft.draft_id

    bundle = store.build_association_bundle(
        project_id=effective_project_id,
        query=query,
        draft_id=effective_draft_id,
        section_id=effective_section_id,
        memory_hits=memory_hits,
        retrieval_hits=retrieval_hits,
        signal_limit=signal_limit,
        angle_limit=angle_limit,
    )
    bundle = enrich_association_bundle_with_analysis(bundle, analysis_payloads=analysis_payloads)
    return apply_association_mode(bundle, mode, ai_adapter=ai_adapter, angle_limit=angle_limit), ephemeral_store


class WritingResourceStore:
    """
    In-memory store for writing resources.
    
    Future: Replace with persistent database.
    For now, supports Phase 3 implementation with clean interfaces.
    """

    def __init__(self):
        """Initialize empty resource store."""
        self._projects: dict[str, WritingProject] = {}
        self._sections: dict[str, WritingSection] = {}
        self._drafts: dict[str, WritingDraft] = {}
        self._revisions: dict[str, WritingRevision] = {}
        self._draft_revisions: dict[str, list[str]] = {}  # draft_id -> [revision_ids]

    # ==========================================================================
    # Project Operations
    # ==========================================================================

    def create_project(
        self,
        title: str,
        description: str = "",
        content_type: ContentType = ContentType.GENERAL,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> WritingProject:
        """Create a new writing project."""
        project = WritingProject.create(
            title=title,
            description=description,
            content_type=content_type,
            user_id=user_id,
            metadata=metadata,
            tags=tags,
        )
        self._projects[project.project_id] = project
        return project

    def get_project(self, project_id: str) -> WritingProject | None:
        """Get a project by ID."""
        return self._projects.get(project_id)

    def list_projects(self, user_id: str | None = None) -> list[WritingProject]:
        """List all projects, optionally filtered by user."""
        projects = list(self._projects.values())
        if user_id:
            projects = [p for p in projects if p.user_id == user_id]
        return sorted(projects, key=lambda p: p.created_at, reverse=True)

    def update_project_status(self, project_id: str, status: ProjectStatus) -> WritingProject | None:
        """Update project status."""
        project = self.get_project(project_id)
        if project:
            updated = project.with_status(status)
            self._projects[project_id] = updated
            return updated
        return None

    # ==========================================================================
    # Section Operations
    # ==========================================================================

    def create_section(
        self,
        project_id: str,
        title: str,
        order: int,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WritingSection:
        """Create a section within a project."""
        section = WritingSection.create(
            project_id=project_id,
            title=title,
            order=order,
            description=description,
            metadata=metadata,
        )
        self._sections[section.section_id] = section
        return section

    def get_section(self, section_id: str) -> WritingSection | None:
        """Get a section by ID."""
        return self._sections.get(section_id)

    def list_sections(self, project_id: str) -> list[WritingSection]:
        """List all sections in a project."""
        sections = [s for s in self._sections.values() if s.project_id == project_id]
        return sorted(sections, key=lambda s: s.order)

    # ==========================================================================
    # Draft Operations
    # ==========================================================================

    def create_draft(
        self,
        project_id: str,
        title: str = "",
        content: str = "",
        section_id: str | None = None,
        edited_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingDraft:
        """Create a new draft."""
        draft = WritingDraft.create(
            project_id=project_id,
            title=title,
            content=content,
            section_id=section_id,
            last_edited_by=edited_by,
            metadata=metadata,
        )
        self._drafts[draft.draft_id] = draft
        self._draft_revisions[draft.draft_id] = []
        return draft

    def get_draft(self, draft_id: str) -> WritingDraft | None:
        """Get a draft by ID."""
        return self._drafts.get(draft_id)

    def save_draft(
        self,
        draft_id: str,
        content: str,
        edited_by: str | None = None,
        create_revision: bool = True,
    ) -> WritingDraft | None:
        """Save draft content and optionally create a revision."""
        draft = self.get_draft(draft_id)
        if not draft:
            return None

        updated_draft = draft.with_content(content, edited_by=edited_by)
        self._drafts[draft_id] = updated_draft

        # Auto-create revision on save
        if create_revision:
            revision_number = len(self._draft_revisions.get(draft_id, [])) + 1
            revision = WritingRevision.create(
                draft_id=draft_id,
                project_id=draft.project_id,
                content=content,
                revision_number=revision_number,
                created_by=edited_by,
                message="Manual save",
            )
            self._revisions[revision.revision_id] = revision
            self._draft_revisions[draft_id].append(revision.revision_id)

        return updated_draft

    def list_drafts(self, project_id: str, section_id: str | None = None) -> list[WritingDraft]:
        """List all drafts, optionally filtered by section."""
        drafts = [d for d in self._drafts.values() if d.project_id == project_id]
        if section_id:
            drafts = [d for d in drafts if d.section_id == section_id]
        return sorted(drafts, key=lambda d: d.created_at, reverse=True)

    # ==========================================================================
    # Revision Operations
    # ==========================================================================

    def get_revision(self, revision_id: str) -> WritingRevision | None:
        """Get a revision by ID."""
        return self._revisions.get(revision_id)

    def list_revisions(self, draft_id: str) -> list[WritingRevision]:
        """List all revisions for a draft."""
        revision_ids = self._draft_revisions.get(draft_id, [])
        revisions = [self._revisions[rid] for rid in revision_ids if rid in self._revisions]
        return sorted(revisions, key=lambda r: r.revision_number)

    def restore_revision(self, draft_id: str, revision_id: str) -> WritingDraft | None:
        """Restore a draft from a revision."""
        draft = self.get_draft(draft_id)
        revision = self.get_revision(revision_id)
        if not draft or not revision:
            return None

        # Update draft content to revision content
        restored_draft = draft.with_content(revision.content, edited_by="system")
        self._drafts[draft_id] = restored_draft

        # Create new revision for the restore action
        revision_number = len(self._draft_revisions.get(draft_id, [])) + 1
        new_revision = WritingRevision.create(
            draft_id=draft_id,
            project_id=draft.project_id,
            content=revision.content,
            revision_number=revision_number,
            created_by="system",
            message=f"Restored from revision {revision_id}",
        )
        self._revisions[new_revision.revision_id] = new_revision
        self._draft_revisions[draft_id].append(new_revision.revision_id)

        return restored_draft

    # ==========================================================================
    # Associative Writing Operations
    # ==========================================================================

    def build_association_bundle(
        self,
        project_id: str,
        query: str,
        draft_id: str | None = None,
        section_id: str | None = None,
        memory_hits: Sequence[Mapping[str, Any]] | None = None,
        retrieval_hits: Sequence[Mapping[str, Any]] | None = None,
        signal_limit: int = 6,
        angle_limit: int = 3,
    ) -> WritingAssociationBundle:
        """
        Build a project-scoped associative writing bundle.

        Why:
            Retrieval alone does not help the writer unless the system surfaces
            bridgeable evidence, continuation prompts, and missing coverage.

        Args:
            project_id: Target project identifier.
            query: Writing intent, topic, or question to expand.
            draft_id: Optional current draft used as local context.
            section_id: Optional current section used as local context.
            memory_hits: Optional long-term memory hits already retrieved upstream.
            retrieval_hits: Optional current-query retrieval evidence from the analysis layer.
            signal_limit: Maximum number of related signals to keep.
            angle_limit: Maximum number of writing angles to synthesize.

        Returns:
            WritingAssociationBundle containing ranked signals and writing prompts.
        """
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if signal_limit <= 0:
            raise ValueError("signal_limit must be a positive integer")
        if angle_limit <= 0:
            raise ValueError("angle_limit must be a positive integer")

        project = self.get_project(project_id)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")

        current_section = self._resolve_association_section(project_id, section_id)
        current_draft = self._resolve_association_draft(project_id, draft_id)

        focus_context: list[str] = [query, project.title, project.description]
        if current_section is not None:
            focus_context.extend([current_section.title, current_section.description])
        if current_draft is not None:
            focus_context.extend([current_draft.title, current_draft.content])

        focus_terms = _extract_focus_terms(focus_context, limit=10)
        candidates = self._collect_association_candidates(
            project_id=project_id,
            current_draft_id=current_draft.draft_id if current_draft is not None else None,
            current_section_id=current_section.section_id if current_section is not None else None,
            memory_hits=memory_hits,
            retrieval_hits=retrieval_hits,
        )
        related_signals = self._score_association_candidates(
            query=query,
            focus_terms=focus_terms,
            candidates=candidates,
            signal_limit=signal_limit,
        )
        association_angles = self._build_association_angles(
            query=query,
            signals=related_signals,
            angle_limit=angle_limit,
        )
        continuation_prompts = self._build_continuation_prompts(
            query=query,
            signals=related_signals,
            angles=association_angles,
        )
        evidence_gaps = self._build_evidence_gaps(
            query=query,
            focus_terms=focus_terms,
            signals=related_signals,
            memory_hit_count=len(memory_hits or []),
        )
        recommended_memory_queries = self._build_recommended_memory_queries(
            query=query,
            focus_terms=focus_terms,
            signals=related_signals,
            gaps=evidence_gaps,
        )

        return WritingAssociationBundle(
            project_id=project_id,
            query=query.strip(),
            draft_id=current_draft.draft_id if current_draft is not None else None,
            section_id=current_section.section_id if current_section is not None else None,
            focus_terms=focus_terms,
            memory_used=bool(memory_hits),
            memory_hit_count=len(memory_hits or []),
            related_signals=related_signals,
            association_angles=association_angles,
            continuation_prompts=continuation_prompts,
            evidence_gaps=evidence_gaps,
            recommended_memory_queries=recommended_memory_queries,
        )

    def _resolve_association_section(
        self,
        project_id: str,
        section_id: str | None,
    ) -> WritingSection | None:
        """Resolve a section and verify that it belongs to the requested project."""
        if section_id is None:
            return None
        section = self.get_section(section_id)
        if section is None:
            raise ValueError(f"Section not found: {section_id}")
        if section.project_id != project_id:
            raise ValueError(f"Section {section_id} does not belong to project {project_id}")
        return section

    def _resolve_association_draft(
        self,
        project_id: str,
        draft_id: str | None,
    ) -> WritingDraft | None:
        """Resolve a draft and verify that it belongs to the requested project."""
        if draft_id is None:
            return None
        draft = self.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"Draft not found: {draft_id}")
        if draft.project_id != project_id:
            raise ValueError(f"Draft {draft_id} does not belong to project {project_id}")
        return draft

    def _collect_association_candidates(
        self,
        project_id: str,
        current_draft_id: str | None,
        current_section_id: str | None,
        memory_hits: Sequence[Mapping[str, Any]] | None,
        retrieval_hits: Sequence[Mapping[str, Any]] | None,
    ) -> list[_AssociationCandidate]:
        """Collect project-local and memory-backed candidates for association scoring."""
        candidates: list[_AssociationCandidate] = []

        for section in self.list_sections(project_id):
            if section.section_id == current_section_id:
                continue
            summary = " ".join(part for part in [section.title, section.description] if part).strip()
            if not summary:
                continue
            candidates.append(
                _AssociationCandidate(
                    source_type="section",
                    source_id=section.section_id,
                    title=section.title,
                    excerpt=_trim_preview(summary, 260),
                    terms=tuple(_extract_terms(summary)),
                    raw_score_boost=0.04,
                )
            )

        for draft in self.list_drafts(project_id):
            if draft.draft_id == current_draft_id:
                continue
            content_seed = " ".join(part for part in [draft.title, draft.content] if part).strip()
            if not content_seed:
                continue
            candidates.append(
                _AssociationCandidate(
                    source_type="draft",
                    source_id=draft.draft_id,
                    title=draft.title or f"Draft {draft.draft_id}",
                    excerpt=_trim_preview(draft.content or draft.title, 300),
                    terms=tuple(_extract_terms(content_seed)),
                    raw_score_boost=0.08,
                )
            )

        for raw_hit in memory_hits or []:
            if not isinstance(raw_hit, Mapping):
                continue
            text = str(raw_hit.get("text", "")).strip()
            if not text:
                continue
            source_file = str(raw_hit.get("source_file", "")).strip()
            wing = str(raw_hit.get("wing", "")).strip()
            room = str(raw_hit.get("room", "")).strip()
            title = source_file or "Memory Evidence"
            if wing or room:
                location = "/".join(part for part in [wing, room] if part)
                title = f"{title} ({location})" if location else title
            try:
                similarity = float(raw_hit.get("similarity", 0.0))
            except (TypeError, ValueError):
                similarity = 0.0
            candidates.append(
                _AssociationCandidate(
                    source_type="memory",
                    source_id=source_file or f"memory_{len(candidates) + 1}",
                    title=title,
                    excerpt=_trim_preview(text, 320),
                    terms=tuple(_extract_terms(text)),
                    raw_score_boost=max(0.08, min(0.22, similarity * 0.2)),
                )
            )

        for raw_hit in retrieval_hits or []:
            if not isinstance(raw_hit, Mapping):
                continue

            text = str(raw_hit.get("text") or raw_hit.get("content") or "").strip()
            if not text:
                continue

            metadata = raw_hit.get("metadata", {})
            if not isinstance(metadata, Mapping):
                metadata = {}

            source_label = str(
                raw_hit.get("source")
                or metadata.get("title")
                or metadata.get("document_keyword")
                or "Retrieved Evidence"
            ).strip()
            source_id = str(
                raw_hit.get("id")
                or metadata.get("document_id")
                or source_label
                or f"retrieval_{len(candidates) + 1}"
            ).strip()
            normalized_score = _coerce_unit_score(
                raw_hit.get("score", raw_hit.get("similarity", 0.0))
            )
            seed_text = " ".join(part for part in [source_label, text] if part).strip()
            candidates.append(
                _AssociationCandidate(
                    source_type="retrieval",
                    source_id=source_id or f"retrieval_{len(candidates) + 1}",
                    title=source_label or "Retrieved Evidence",
                    excerpt=_trim_preview(text, 320),
                    terms=tuple(_extract_terms(seed_text)),
                    raw_score_boost=max(0.06, min(0.18, 0.04 + (normalized_score * 0.2))),
                )
            )

        return candidates

    def _score_association_candidates(
        self,
        query: str,
        focus_terms: Sequence[str],
        candidates: Sequence[_AssociationCandidate],
        signal_limit: int,
    ) -> list[WritingAssociationSignal]:
        """Score candidates against the active writing intent and focus terms."""
        query_terms = _extract_terms(query)
        scoring_terms = list(dict.fromkeys([*query_terms, *focus_terms]))
        if not scoring_terms:
            scoring_terms = focus_terms[:]

        ranked_signals: list[WritingAssociationSignal] = []
        for candidate in candidates:
            candidate_terms = set(candidate.terms)
            if not candidate_terms:
                continue

            shared_terms = [term for term in scoring_terms if term in candidate_terms]
            if not shared_terms and candidate.source_type not in {"memory", "retrieval"}:
                continue

            title_terms = set(_extract_terms(candidate.title))
            coverage = len(shared_terms) / max(1, min(len(scoring_terms), 6))
            title_overlap = len(title_terms.intersection(shared_terms))
            density = len(shared_terms) / max(1, min(len(candidate_terms), 10))
            score = _normalize_score(
                (coverage * 0.58)
                + (density * 0.18)
                + min(0.12, title_overlap * 0.04)
                + candidate.raw_score_boost
            )
            if score < 0.12:
                continue

            if shared_terms:
                rationale = "Shared focus: " + ", ".join(shared_terms[:3])
            elif candidate.source_type == "memory":
                rationale = "Memory evidence provides adjacent retrieval context"
            elif candidate.source_type == "retrieval":
                rationale = "Retrieved evidence extends the current analysis path"
            else:
                rationale = f"{candidate.source_type.title()} evidence may extend the current argument"

            ranked_signals.append(
                WritingAssociationSignal(
                    source_type=candidate.source_type,
                    source_id=candidate.source_id,
                    title=candidate.title,
                    excerpt=candidate.excerpt,
                    score=score,
                    shared_terms=shared_terms[:6],
                    rationale=rationale,
                )
            )

        ranked_signals.sort(
            key=lambda signal: (
                -signal.score,
                signal.source_type,
                signal.title.lower(),
            )
        )
        return ranked_signals[:signal_limit]

    def _build_association_angles(
        self,
        query: str,
        signals: Sequence[WritingAssociationSignal],
        angle_limit: int,
    ) -> list[WritingAssociationAngle]:
        """Synthesize bridgeable writing angles from the strongest signals."""
        if not signals:
            return []

        signal_map = {signal.source_id: signal for signal in signals}
        term_counter: Counter[str] = Counter()
        term_sources: dict[str, list[str]] = {}
        for signal in signals:
            for term in signal.shared_terms:
                term_counter[term] += 1
                term_sources.setdefault(term, []).append(signal.source_id)

        ranked_terms = [
            term for term, count in sorted(
                term_counter.items(),
                key=lambda item: (-item[1], -len(item[0]), item[0]),
            )
            if count >= 1
        ]
        if not ranked_terms:
            fallback_terms = _extract_focus_terms([query, *(signal.title for signal in signals)], limit=angle_limit)
            ranked_terms = fallback_terms

        angles: list[WritingAssociationAngle] = []
        for index, term in enumerate(ranked_terms[:angle_limit], start=1):
            supporting_ids = list(dict.fromkeys(term_sources.get(term, [])))
            supporting_signals = [signal_map[source_id] for source_id in supporting_ids if source_id in signal_map]
            if not supporting_signals:
                supporting_signals = list(signals[:2])
                supporting_ids = [signal.source_id for signal in supporting_signals]

            title_parts = ", ".join(signal.title for signal in supporting_signals[:2])
            prompt = (
                f"Use '{term}' as the bridge term: explain what {title_parts} contribute, "
                f"then connect that evidence back to '{query.strip()}'."
            )
            mean_confidence = sum(signal.score for signal in supporting_signals) / max(1, len(supporting_signals))
            angles.append(
                WritingAssociationAngle(
                    angle_id=f"angle_{index}",
                    title=f"Bridge around '{term}'",
                    prompt=prompt,
                    supporting_source_ids=supporting_ids,
                    shared_terms=[term],
                    confidence=_normalize_score(mean_confidence),
                )
            )
        return angles

    def _build_continuation_prompts(
        self,
        query: str,
        signals: Sequence[WritingAssociationSignal],
        angles: Sequence[WritingAssociationAngle],
    ) -> list[str]:
        """Generate bounded continuation prompts from top angles and evidence."""
        prompts: list[str] = []
        for angle in angles[:3]:
            prompts.append(angle.prompt)

        if signals:
            strongest = signals[0]
            shared = ", ".join(strongest.shared_terms[:3]) if strongest.shared_terms else strongest.source_type
            prompts.append(
                f"After the current paragraph, add a short transition that links '{shared}' to {strongest.title}."
            )

        prompts.append(
            f"Close the next paragraph by stating why the linked evidence changes how '{query.strip()}' should be framed."
        )
        deduped: list[str] = []
        for prompt in prompts:
            if prompt not in deduped:
                deduped.append(prompt)
        return deduped[:4]

    def _build_evidence_gaps(
        self,
        query: str,
        focus_terms: Sequence[str],
        signals: Sequence[WritingAssociationSignal],
        memory_hit_count: int,
    ) -> list[WritingEvidenceGap]:
        """Identify coverage gaps that weaken associative writing quality."""
        gaps: list[WritingEvidenceGap] = []
        covered_terms = {term for signal in signals for term in signal.shared_terms}
        query_terms = set(_extract_terms(query))
        missing_terms = [term for term in focus_terms if term in query_terms and term not in covered_terms]
        if missing_terms:
            gaps.append(
                WritingEvidenceGap(
                    gap="Critical query terms remain weakly supported",
                    severity="high",
                    recommendation="Retrieve or draft evidence for: " + ", ".join(missing_terms[:4]),
                )
            )

        signal_types = {signal.source_type for signal in signals}
        if len(signal_types) < 2:
            gaps.append(
                WritingEvidenceGap(
                    gap="Association evidence is not source-diverse",
                    severity="medium",
                    recommendation="Pull at least one additional section, draft, or memory source before expanding the argument.",
                )
            )

        if memory_hit_count == 0:
            gaps.append(
                WritingEvidenceGap(
                    gap="No long-term memory evidence was incorporated",
                    severity="medium",
                    recommendation="Run a memory search with the strongest focus term combination before drafting the next revision.",
                )
            )

        if not signals:
            gaps.append(
                WritingEvidenceGap(
                    gap="The current query produced no associative writing signals",
                    severity="high",
                    recommendation="Narrow the query or add a draft/section anchor so the system can infer stronger links.",
                )
            )

        return gaps

    def _build_recommended_memory_queries(
        self,
        query: str,
        focus_terms: Sequence[str],
        signals: Sequence[WritingAssociationSignal],
        gaps: Sequence[WritingEvidenceGap],
    ) -> list[str]:
        """Generate retrieval follow-ups that can strengthen the next writing step."""
        recommendations: list[str] = [query.strip()]
        if focus_terms:
            recommendations.append(" ".join([query.strip(), focus_terms[0]]).strip())
        if len(focus_terms) > 1:
            recommendations.append(" ".join([focus_terms[0], focus_terms[1]]).strip())

        if signals:
            strongest = signals[0]
            if strongest.shared_terms:
                recommendations.append(
                    " ".join([query.strip(), strongest.shared_terms[0], strongest.source_type]).strip()
                )

        if gaps:
            recommendations.append("missing evidence for " + ", ".join(focus_terms[:2]))

        deduped: list[str] = []
        for query_text in recommendations:
            normalized = query_text.strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped[:4]

    # ==========================================================================
    # State Export
    # ==========================================================================

    def export_state(self) -> dict[str, Any]:
        """Export all resource state."""
        return {
            "projects": {pid: p.to_dict() for pid, p in self._projects.items()},
            "sections": {sid: s.to_dict() for sid, s in self._sections.items()},
            "drafts": {did: d.to_dict() for did, d in self._drafts.items()},
            "revisions": {rid: r.to_dict() for rid, r in self._revisions.items()},
            "draft_revisions": dict(self._draft_revisions),
        }


# Global singleton instance
_resource_store: WritingResourceStore | None = None


def get_writing_resource_store() -> WritingResourceStore:
    """Get or create the global WritingResourceStore instance."""
    global _resource_store
    if _resource_store is None:
        _resource_store = WritingResourceStore()
    return _resource_store
