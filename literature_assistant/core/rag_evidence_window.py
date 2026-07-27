# -*- coding: utf-8 -*-
"""Shadow evidence-window relation artifacts for RAG retrieval.

Phase 5A intentionally does not implement parent retrieval.  It records a
derived, version-bound relation manifest that explains which structured chunks
could extend a selected narrative chunk, and why that extension is safe to
audit.  The manifest is a shadow artifact: callers may persist it for
inspection, but it must not change prompt context, TOLF nodes, or final rank.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from literature_assistant.core._atomic_io import atomic_write_json
    from literature_assistant.core.chunk_hashing import (
        CHUNK_HASH_VERSION,
        compute_chunk_hashes,
        compute_chunk_store_version,
    )
    from literature_assistant.core.project_paths import generated_path
    from literature_assistant.core.rag_structured_sibling_inclusion import (
        DEFAULT_STRUCTURED_TYPES,
        select_structured_siblings,
    )
else:
    from _atomic_io import atomic_write_json
    from chunk_hashing import CHUNK_HASH_VERSION, compute_chunk_hashes, compute_chunk_store_version
    from project_paths import generated_path
    from rag_structured_sibling_inclusion import DEFAULT_STRUCTURED_TYPES, select_structured_siblings


EXTRACTOR_CONTRACT_VERSION = "scholar-ai-extractor-contract/v1"
EVIDENCE_RELATION_SOURCE_RULE_VERSION = "figure-table-formula-sibling/v1"
_FIGURE_REF_RE = re.compile(r"\b(?:Fig\.?|Figure)\s*[\.\(\[]?\s*\d+\b", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<!Fig\.)(?<!fig\.)(?<=[.!?。！？])\s+|\n+")

RelationType = Literal[
    "figure_caption",
    "figure_image",
    "table",
    "formula",
    "same_section_sibling",
    "in_text_figure_ref",
    "same_page_local",
]
EvidencePartRole = Literal[
    "narrative",
    "figure_caption",
    "figure_image",
    "table",
    "formula",
    "nearby_context",
]
CitationAllowed = Literal["exact_bbox", "multi_locator", "page_span", "context_span", "none"]
CitationLevel = Literal["exact_bbox", "multi_locator", "page_span", "context_span", "unattributed"]
WindowMode = Literal["child_only", "shadow_expanded"]
FigureAssetKind = Literal["embedded_figure", "extracted_region", "page_screenshot", "missing"]
AssetStatus = Literal["present", "missing", "not_applicable", "unknown"]
ManifestStaleReason = Literal[
    "current",
    "chunk_store_version_mismatch",
    "extractor_contract_hash_mismatch",
    "relation_chunk_missing",
    "relation_chunk_hash_mismatch",
]
_CITATION_ALLOWED_VALUES = frozenset({"exact_bbox", "multi_locator", "page_span", "context_span", "none"})
_EVIDENCE_PART_ROLES = frozenset({"narrative", "figure_caption", "figure_image", "table", "formula", "nearby_context"})
_ASSET_STATUS_VALUES = frozenset({"present", "missing", "not_applicable", "unknown"})


@dataclass(frozen=True)
class EvidencePart:
    """Auditable evidence part derived from one chunk.

    Args:
        part_id: Stable id scoped to a relation manifest.
        chunk_id: Source chunk id.
        role: Evidence role used by citation policy in later phases.
        locator_refs: Bounded page/chunk/bbox locators; never provider secrets.
        citation_allowed: Maximum citation precision the part may support.
        source_reason: Deterministic reason this part was included.
        asset_status: Whether a required visual/structured asset is present.
    """

    part_id: str
    chunk_id: str
    role: EvidencePartRole
    locator_refs: list[dict[str, Any]] = field(default_factory=list)
    citation_allowed: CitationAllowed = "context_span"
    source_reason: str = ""
    asset_status: AssetStatus = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return {
            "part_id": self.part_id,
            "chunk_id": self.chunk_id,
            "role": self.role,
            "locator_refs": self.locator_refs,
            "citation_allowed": self.citation_allowed,
            "source_reason": self.source_reason,
            "asset_status": self.asset_status,
        }


@dataclass(frozen=True)
class CitationPolicyDecision:
    """Bounded citation decision for a shadow audit window.

    Args:
        citation_level: Explicit level shown by Inspector/UI.  Missing backend
            decisions should be rendered as "未标注" by the frontend instead of
            being inferred from bbox.
        locator_refs: Locators that justify the level.
        downgrade_reason: Empty when no downgrade happened.
        confidence: Deterministic diagnostic confidence in [0, 1].
    """

    citation_level: CitationLevel
    locator_refs: list[dict[str, Any]] = field(default_factory=list)
    downgrade_reason: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return {
            "citation_level": self.citation_level,
            "locator_refs": self.locator_refs,
            "downgrade_reason": self.downgrade_reason,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class AuditWindow:
    """Shadow-only evidence window assembled for Inspector diagnostics."""

    window_id: str
    anchor_chunk_id: str
    strategy: str
    parts: list[EvidencePart]
    expansion_reason: str
    budget_report: dict[str, Any]
    citation_mode: CitationPolicyDecision
    excluded_parts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return {
            "window_id": self.window_id,
            "anchor_chunk_id": self.anchor_chunk_id,
            "strategy": self.strategy,
            "parts": [part.to_dict() for part in self.parts],
            "expansion_reason": self.expansion_reason,
            "budget_report": self.budget_report,
            "citation_mode": self.citation_mode.to_dict(),
            "excluded_parts": self.excluded_parts,
        }


@dataclass(frozen=True)
class WindowDiff:
    """Difference between child-only context and a shadow-expanded window."""

    window_id: str
    anchor_chunk_id: str
    child_only_context: list[str]
    expanded_window_context: list[str]
    added_parts: list[str]
    removed_parts: list[str]
    citation_level_changes: dict[str, Any]
    expected_visual_assets: list[str] = field(default_factory=list)
    missing_visual_assets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return {
            "window_id": self.window_id,
            "anchor_chunk_id": self.anchor_chunk_id,
            "child_only_context": self.child_only_context,
            "expanded_window_context": self.expanded_window_context,
            "added_parts": self.added_parts,
            "removed_parts": self.removed_parts,
            "citation_level_changes": self.citation_level_changes,
            "expected_visual_assets": self.expected_visual_assets,
            "missing_visual_assets": self.missing_visual_assets,
        }


@dataclass(frozen=True)
class FigureEvidenceCard:
    """Shadow card describing figure/caption asset binding and exclusions."""

    figure_id: str
    image_asset: str | None
    caption: str
    in_text_mentions: list[str]
    page: int | str | None
    bbox: list[Any] | None
    included_in_prompt: bool
    exclusion_reason: str
    asset_status: AssetStatus
    asset_kind: FigureAssetKind

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return {
            "figure_id": self.figure_id,
            "image_asset": self.image_asset,
            "caption": self.caption,
            "in_text_mentions": self.in_text_mentions,
            "page": self.page,
            "bbox": self.bbox,
            "included_in_prompt": self.included_in_prompt,
            "exclusion_reason": self.exclusion_reason,
            "asset_status": self.asset_status,
            "asset_kind": self.asset_kind,
        }


@dataclass(frozen=True)
class ContextDebtReport:
    """Small Phase 5A debt sample surfaced through the Inspector artifact."""

    half_sentence_chunk_count: int = 0
    figure_caption_missing_asset_count: int = 0
    table_missing_structured_data_count: int = 0
    in_text_figure_ref_unbound_count: int = 0
    downgraded_citation_count: int = 0
    samples: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return {
            "half_sentence_chunk_count": self.half_sentence_chunk_count,
            "figure_caption_missing_asset_count": self.figure_caption_missing_asset_count,
            "table_missing_structured_data_count": self.table_missing_structured_data_count,
            "in_text_figure_ref_unbound_count": self.in_text_figure_ref_unbound_count,
            "downgraded_citation_count": self.downgraded_citation_count,
            "samples": self.samples,
        }


@dataclass(frozen=True)
class EvidenceRelationManifest:
    """Derived relation between an anchor chunk and one evidence part.

    The relation is valid only while its project/material version metadata and
    per-chunk ``chunk_hash_set`` still match the current chunk store.
    """

    relation_id: str
    project_id: str
    material_id: str
    anchor_chunk_id: str
    related_chunk_id: str
    relation_type: RelationType
    locator_refs: list[dict[str, Any]]
    confidence: float
    source_rule: str
    chunk_hash_set: dict[str, str]
    structure_version: str
    chunk_store_version: str
    extractor_contract_hash: str
    created_at: str
    evidence_part_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return {
            "relation_id": self.relation_id,
            "project_id": self.project_id,
            "material_id": self.material_id,
            "anchor_chunk_id": self.anchor_chunk_id,
            "related_chunk_id": self.related_chunk_id,
            "relation_type": self.relation_type,
            "locator_refs": self.locator_refs,
            "confidence": self.confidence,
            "source_rule": self.source_rule,
            "chunk_hash_set": self.chunk_hash_set,
            "structure_version": self.structure_version,
            "chunk_store_version": self.chunk_store_version,
            "extractor_contract_hash": self.extractor_contract_hash,
            "created_at": self.created_at,
            "evidence_part_ids": self.evidence_part_ids,
        }


@dataclass(frozen=True)
class EvidenceRelationBuildResult:
    """Output of the Phase 5A-1 shadow relation strategy."""

    project_id: str
    chunk_store_version: str
    extractor_contract_hash: str
    created_at: str
    relations: list[EvidenceRelationManifest]
    parts: list[EvidencePart]
    audit_windows: list[AuditWindow] = field(default_factory=list)
    window_diffs: list[WindowDiff] = field(default_factory=list)
    figure_cards: list[FigureEvidenceCard] = field(default_factory=list)
    context_debt_report: ContextDebtReport | None = None
    warnings: list[str] = field(default_factory=list)

    def meta_dict(self) -> dict[str, Any]:
        """Return manifest metadata for ``relation_manifest.meta.json``."""

        return {
            "project_id": self.project_id,
            "chunk_store_version": self.chunk_store_version,
            "extractor_contract_hash": self.extractor_contract_hash,
            "created_at": self.created_at,
            "source_rule_versions": {
                "figure_table_formula_relation_strategy": EVIDENCE_RELATION_SOURCE_RULE_VERSION,
                "chunk_hash": CHUNK_HASH_VERSION,
            },
            "stats": {
                "relation_count": len(self.relations),
                "part_count": len(self.parts),
                "audit_window_count": len(self.audit_windows),
                "window_diff_count": len(self.window_diffs),
                "figure_card_count": len(self.figure_cards),
                "warning_count": len(self.warnings),
            },
            "warnings": list(self.warnings),
        }

    def inspector_dict(self) -> dict[str, Any]:
        """Return the Shadow MVP Inspector JSON payload."""

        debt_report = self.context_debt_report or ContextDebtReport()
        return {
            "project_id": self.project_id,
            "chunk_store_version": self.chunk_store_version,
            "extractor_contract_hash": self.extractor_contract_hash,
            "created_at": self.created_at,
            "summary": {
                "relation_count": len(self.relations),
                "part_count": len(self.parts),
                "audit_window_count": len(self.audit_windows),
                "window_diff_count": len(self.window_diffs),
                "figure_card_count": len(self.figure_cards),
                "downgraded_citation_count": debt_report.downgraded_citation_count,
            },
            "relations": [relation.to_dict() for relation in self.relations],
            "parts": [part.to_dict() for part in self.parts],
            "audit_windows": [window.to_dict() for window in self.audit_windows],
            "window_diffs": [diff.to_dict() for diff in self.window_diffs],
            "figure_evidence_cards": [card.to_dict() for card in self.figure_cards],
            "context_debt_report": debt_report.to_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ManifestStaleCheck:
    """Result of comparing a manifest or relation against current truth."""

    stale: bool
    reason: ManifestStaleReason
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return {"stale": self.stale, "reason": self.reason, "detail": self.detail}


def utc_now_iso() -> str:
    """Return a stable UTC timestamp for generated artifacts."""

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def extractor_contract_hash(value: str = EXTRACTOR_CONTRACT_VERSION) -> str:
    """Return a deterministic hash for the current extraction contract label."""

    return _sha256_text(value)


def is_evidence_window_shadow_enabled() -> bool:
    """Resolve the Phase 5A shadow feature flag.

    Unknown flag registries and legacy launches fall back to the environment.
    """

    try:
        if TYPE_CHECKING:
            from literature_assistant.core.feature_flags import is_enabled
        else:
            from feature_flags import is_enabled

        return bool(is_enabled("rag_evidence_window_shadow"))
    except (ImportError, KeyError):
        raw = os.getenv("RAG_EVIDENCE_WINDOW_SHADOW_ENABLED", "")
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "shadow"}


class CitationPolicy:
    """Deterministically downgrade citation precision for shadow windows.

    P0 deliberately avoids sentence-level attribution.  This policy only uses
    evidence-part count, window mode, locator quality, and explicit
    attribution evidence; it never infers a precise citation from bbox alone
    once a sibling/window participates.
    """

    def evaluate(
        self,
        *,
        used_parts: Sequence[EvidencePart | Mapping[str, Any]],
        window_mode: WindowMode,
        answer_claim_scope: str | None = None,
        locator_quality: str | None = None,
        attribution_evidence: str | None = None,
    ) -> CitationPolicyDecision:
        """Return the maximum safe citation level for a candidate claim.

        Args:
            used_parts: Evidence parts that support the claim/window.
            window_mode: ``child_only`` for a single selected child chunk, or
                ``shadow_expanded`` when sibling/window evidence is involved.
            answer_claim_scope: Reserved diagnostic field for future
                sentence-level attribution.
            locator_quality: Optional explicit locator status. ``missing`` or
                ``none`` forces an unattributed decision.
            attribution_evidence: Optional explicit attribution status.
                ``missing`` or ``none`` forces an unattributed decision.

        Returns:
            Explicit citation level plus locators and downgrade reason.
        """

        if window_mode not in {"child_only", "shadow_expanded"}:
            raise ValueError("window_mode must be child_only or shadow_expanded")
        if isinstance(used_parts, (str, bytes)) or not isinstance(used_parts, Sequence):
            raise TypeError("used_parts must be a sequence")

        normalized_parts = [_part_from_policy_input(part) for part in used_parts]
        usable_parts = [part for part in normalized_parts if part.citation_allowed != "none"]
        locator_refs = _merge_locator_refs([part.locator_refs for part in usable_parts])
        if not usable_parts:
            return _citation_decision("unattributed", locator_refs, "no_usable_evidence_part")

        normalized_locator_quality = str(locator_quality or "").strip().lower()
        normalized_attribution = str(attribution_evidence or "").strip().lower()
        if normalized_locator_quality in {"missing", "none"}:
            return _citation_decision("unattributed", locator_refs, "locator_quality_missing")
        if normalized_attribution in {"missing", "none"}:
            return _citation_decision("unattributed", locator_refs, "attribution_evidence_missing")

        has_bbox = any(_locator_has_bbox(locator) for locator in locator_refs)
        has_page = any(locator.get("page") is not None for locator in locator_refs)
        if len(usable_parts) == 1 and window_mode == "child_only":
            part = usable_parts[0]
            if part.citation_allowed == "exact_bbox" and has_bbox:
                return _citation_decision("exact_bbox", locator_refs, "")
            if part.citation_allowed == "multi_locator" and has_bbox:
                return _citation_decision("multi_locator", locator_refs, "part_requires_multi_locator")
            if part.citation_allowed == "page_span" and has_page:
                return _citation_decision("page_span", locator_refs, "bbox_missing")
            return _citation_decision("context_span", locator_refs, "locator_not_precise")

        if has_bbox:
            return _citation_decision("multi_locator", locator_refs, "expanded_window_requires_multi_locator")
        if has_page:
            return _citation_decision("page_span", locator_refs, "expanded_window_without_bbox")
        if answer_claim_scope:
            return _citation_decision("context_span", locator_refs, "claim_scope_without_locator")
        return _citation_decision("context_span", locator_refs, "expanded_window_context_only")


class FigureTableFormulaRelationStrategy:
    """Build Phase 5A relation artifacts from structured sibling inclusion.

    The strategy wraps ``select_structured_siblings`` and does not replace its
    matching rules.  It emits relations and evidence parts for shadow telemetry
    only; callers retain their original retrieval result ordering.
    """

    def __init__(self, *, max_siblings: int = 2) -> None:
        if not isinstance(max_siblings, int) or max_siblings < 0:
            raise ValueError("max_siblings must be a non-negative integer")
        self._max_siblings = max_siblings

    def build(
        self,
        *,
        project_id: str,
        validated_child_candidates: Sequence[Mapping[str, Any]],
        all_chunks: Sequence[Mapping[str, Any]],
        chunk_store_version: str | None = None,
        extractor_hash: str | None = None,
        created_at: str | None = None,
    ) -> EvidenceRelationBuildResult:
        """Return relation artifacts without mutating retrieval candidates.

        Args:
            project_id: Project that owns the chunk store.
            validated_child_candidates: Current retrieval candidates, normally
                after rerank/top-k truncation.
            all_chunks: Chunk pool used to find structured siblings.
            chunk_store_version: Optional precomputed version.  When omitted,
                a version is computed from ``all_chunks`` grouped by material.
            extractor_hash: Optional extractor contract hash.
            created_at: Optional UTC timestamp for deterministic tests.

        Returns:
            Relation and part artifacts.  The input candidates are not mutated.
        """

        normalized_project_id = _bounded_required_text(project_id, "project_id", max_chars=160)
        candidates = _copy_mapping_sequence(validated_child_candidates, "validated_child_candidates")
        chunk_pool = _copy_mapping_sequence(all_chunks, "all_chunks")
        created = created_at or utc_now_iso()
        expected_extractor = extractor_hash or extractor_contract_hash()
        version = chunk_store_version or compute_chunk_store_version(_group_chunks_by_material(chunk_pool))
        chunk_by_id = _chunk_by_id(chunk_pool)
        warnings: list[str] = []
        relations: list[EvidenceRelationManifest] = []
        parts: list[EvidencePart] = []

        siblings = select_structured_siblings(
            candidates,
            chunk_pool,
            max_siblings=self._max_siblings,
            structured_types=DEFAULT_STRUCTURED_TYPES,
        )
        candidate_by_id = _chunk_by_id(candidates)
        for sibling in siblings:
            anchor_id = _bounded_required_text(sibling.get("sibling_anchor"), "sibling_anchor", max_chars=240)
            related_id = _bounded_required_text(sibling.get("chunk_id"), "chunk_id", max_chars=240)
            anchor = candidate_by_id.get(anchor_id) or chunk_by_id.get(anchor_id)
            related = chunk_by_id.get(related_id) or sibling
            if anchor is None:
                warnings.append(f"missing anchor chunk for sibling relation: {anchor_id}")
                continue
            try:
                relation = _build_relation(
                    project_id=normalized_project_id,
                    anchor=anchor,
                    related=related,
                    sibling=sibling,
                    chunk_store_version=version,
                    extractor_hash=expected_extractor,
                    created_at=created,
                )
                part = _build_part(related=related, sibling=sibling, relation=relation)
            except (TypeError, ValueError) as exc:
                warnings.append(f"skipped relation {anchor_id}->{related_id}: {exc}")
                continue
            relations.append(relation)
            parts.append(part)

        audit_windows, window_diffs, figure_cards = _build_audit_artifacts(
            project_id=normalized_project_id,
            candidate_by_id=candidate_by_id,
            chunk_by_id=chunk_by_id,
            relations=relations,
            parts=parts,
        )
        debt_report = _build_context_debt_report(
            candidates=candidates,
            relations=relations,
            parts=parts,
            audit_windows=audit_windows,
            figure_cards=figure_cards,
            chunk_by_id=chunk_by_id,
        )

        return EvidenceRelationBuildResult(
            project_id=normalized_project_id,
            chunk_store_version=version,
            extractor_contract_hash=expected_extractor,
            created_at=created,
            relations=relations,
            parts=parts,
            audit_windows=audit_windows,
            window_diffs=window_diffs,
            figure_cards=figure_cards,
            context_debt_report=debt_report,
            warnings=warnings,
        )


def manifest_paths(project_id: str, *, root: Path | None = None) -> dict[str, Path]:
    """Return Phase 5A artifact paths for one project.

    Args:
        project_id: Project id used as the artifact directory name after safe
            normalization.
        root: Optional test root.  Defaults to
            ``workspace_artifacts/generated/evidence_relations``.
    """

    safe_project = _safe_project_id(project_id)
    base = (root or generated_path("evidence_relations")).joinpath(safe_project)
    return {
        "root": base,
        "relations": base / "relation_manifest.jsonl",
        "parts": base / "evidence_parts.jsonl",
        "audit_windows": base / "audit_windows.jsonl",
        "window_diffs": base / "window_diffs.jsonl",
        "figure_cards": base / "figure_evidence_cards.jsonl",
        "meta": base / "relation_manifest.meta.json",
        "inspector": base / "inspector.json",
    }


def persist_relation_manifest(result: EvidenceRelationBuildResult, *, root: Path | None = None) -> dict[str, Path]:
    """Persist Phase 5A shadow artifacts as JSONL plus metadata.

    The files intentionally live under generated artifacts and contain only
    bounded locator/hash metadata, not provider keys, request headers,
    credentials, PDF full text, or raw logs.
    """

    paths = manifest_paths(result.project_id, root=root)
    paths["root"].mkdir(parents=True, exist_ok=True)
    _atomic_write_jsonl(paths["relations"], [relation.to_dict() for relation in result.relations])
    _atomic_write_jsonl(paths["parts"], [part.to_dict() for part in result.parts])
    _atomic_write_jsonl(paths["audit_windows"], [window.to_dict() for window in result.audit_windows])
    _atomic_write_jsonl(paths["window_diffs"], [diff.to_dict() for diff in result.window_diffs])
    _atomic_write_jsonl(paths["figure_cards"], [card.to_dict() for card in result.figure_cards])
    atomic_write_json(paths["meta"], result.meta_dict(), indent=2)
    atomic_write_json(paths["inspector"], result.inspector_dict(), indent=2)
    return paths


def check_manifest_meta_stale(
    meta: Mapping[str, Any],
    *,
    expected_chunk_store_version: str,
    expected_extractor_contract_hash: str,
) -> ManifestStaleCheck:
    """Check project-level manifest staleness."""

    if not isinstance(meta, Mapping):
        raise TypeError("meta must be a mapping")
    expected_version = _bounded_required_text(
        expected_chunk_store_version,
        "expected_chunk_store_version",
        max_chars=160,
    )
    expected_extractor = _bounded_required_text(
        expected_extractor_contract_hash,
        "expected_extractor_contract_hash",
        max_chars=160,
    )
    actual_version = str(meta.get("chunk_store_version") or "").strip()
    if actual_version != expected_version:
        return ManifestStaleCheck(
            stale=True,
            reason="chunk_store_version_mismatch",
            detail=f"expected {expected_version}, found {actual_version or '<missing>'}",
        )
    actual_extractor = str(meta.get("extractor_contract_hash") or "").strip()
    if actual_extractor != expected_extractor:
        return ManifestStaleCheck(
            stale=True,
            reason="extractor_contract_hash_mismatch",
            detail=f"expected {expected_extractor}, found {actual_extractor or '<missing>'}",
        )
    return ManifestStaleCheck(stale=False, reason="current")


def check_relation_stale(
    relation: EvidenceRelationManifest | Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
) -> ManifestStaleCheck:
    """Check per-relation chunk hash staleness against current chunks."""

    relation_dict = relation.to_dict() if isinstance(relation, EvidenceRelationManifest) else dict(relation)
    chunk_hash_set = relation_dict.get("chunk_hash_set")
    if not isinstance(chunk_hash_set, Mapping):
        raise TypeError("relation chunk_hash_set must be a mapping")
    chunk_by_id = _chunk_by_id(_copy_mapping_sequence(chunks, "chunks"))
    for chunk_id, expected_hash_raw in chunk_hash_set.items():
        normalized_chunk_id = _bounded_required_text(chunk_id, "chunk_hash_set key", max_chars=240)
        expected_hash = _bounded_required_text(expected_hash_raw, "chunk_hash_set value", max_chars=160)
        chunk = chunk_by_id.get(normalized_chunk_id)
        if chunk is None:
            return ManifestStaleCheck(
                stale=True,
                reason="relation_chunk_missing",
                detail=f"missing chunk: {normalized_chunk_id}",
            )
        actual_hash = _chunk_hash(chunk, material_id_hint=_material_id(chunk))
        if actual_hash != expected_hash:
            return ManifestStaleCheck(
                stale=True,
                reason="relation_chunk_hash_mismatch",
                detail=f"{normalized_chunk_id}: expected {expected_hash}, found {actual_hash}",
            )
    return ManifestStaleCheck(stale=False, reason="current")


def record_shadow_relations_if_enabled(
    *,
    project_id: str,
    validated_child_candidates: Sequence[Mapping[str, Any]],
    all_chunks: Sequence[Mapping[str, Any]],
    root: Path | None = None,
) -> EvidenceRelationBuildResult | None:
    """Build and persist shadow relations when the feature flag is enabled.

    Returns ``None`` when the flag is disabled.  The function never mutates the
    candidate sequence and does not return modified retrieval results.
    """

    if not is_evidence_window_shadow_enabled():
        return None
    result = FigureTableFormulaRelationStrategy().build(
        project_id=project_id,
        validated_child_candidates=validated_child_candidates,
        all_chunks=all_chunks,
    )
    persist_relation_manifest(result, root=root)
    return result


def _build_audit_artifacts(
    *,
    project_id: str,
    candidate_by_id: Mapping[str, Mapping[str, Any]],
    chunk_by_id: Mapping[str, Mapping[str, Any]],
    relations: Sequence[EvidenceRelationManifest],
    parts: Sequence[EvidencePart],
) -> tuple[list[AuditWindow], list[WindowDiff], list[FigureEvidenceCard]]:
    part_by_id = {part.part_id: part for part in parts}
    relation_ids_by_anchor: dict[str, list[EvidenceRelationManifest]] = {}
    anchor_order: list[str] = []
    for relation in relations:
        if relation.anchor_chunk_id not in relation_ids_by_anchor:
            anchor_order.append(relation.anchor_chunk_id)
        relation_ids_by_anchor.setdefault(relation.anchor_chunk_id, []).append(relation)

    policy = CitationPolicy()
    audit_windows: list[AuditWindow] = []
    window_diffs: list[WindowDiff] = []
    figure_cards: list[FigureEvidenceCard] = []
    for anchor_id in anchor_order:
        anchor = candidate_by_id.get(anchor_id) or chunk_by_id.get(anchor_id)
        if anchor is None:
            continue
        anchor_relations = relation_ids_by_anchor[anchor_id]
        anchor_part = _anchor_part(anchor)
        related_parts = [
            part_by_id[part_id]
            for relation in anchor_relations
            for part_id in relation.evidence_part_ids
            if part_id in part_by_id
        ]
        used_parts = [anchor_part, *related_parts]
        child_decision = policy.evaluate(used_parts=[anchor_part], window_mode="child_only")
        expanded_decision = policy.evaluate(used_parts=used_parts, window_mode="shadow_expanded")
        window_id = _window_id(project_id, anchor_id, anchor_relations)

        cards_for_window: list[FigureEvidenceCard] = []
        for relation in anchor_relations:
            related = chunk_by_id.get(relation.related_chunk_id)
            if related is None or _part_role(related) != "figure_caption":
                continue
            card = _build_figure_card(anchor=anchor, related=related, relation=relation)
            cards_for_window.append(card)
            figure_cards.append(card)

        audit_windows.append(
            AuditWindow(
                window_id=window_id,
                anchor_chunk_id=anchor_id,
                strategy=EVIDENCE_RELATION_SOURCE_RULE_VERSION,
                parts=used_parts,
                expansion_reason=_expansion_reason(anchor_relations),
                budget_report={
                    "mode": "shadow_only",
                    "included_in_prompt": False,
                    "child_only_part_count": 1,
                    "expanded_part_count": len(used_parts),
                    "added_part_count": len(related_parts),
                },
                citation_mode=expanded_decision,
                excluded_parts=[],
            )
        )
        expected_visual_assets = [card.figure_id for card in cards_for_window]
        missing_visual_assets = [
            card.figure_id
            for card in cards_for_window
            if card.asset_status != "present" or card.asset_kind == "page_screenshot"
        ]
        window_diffs.append(
            WindowDiff(
                window_id=window_id,
                anchor_chunk_id=anchor_id,
                child_only_context=[anchor_id],
                expanded_window_context=[anchor_id, *[relation.related_chunk_id for relation in anchor_relations]],
                added_parts=[part.part_id for part in related_parts],
                removed_parts=[],
                citation_level_changes={
                    "before": child_decision.citation_level,
                    "after": expanded_decision.citation_level,
                    "downgrade_reason": expanded_decision.downgrade_reason,
                },
                expected_visual_assets=expected_visual_assets,
                missing_visual_assets=missing_visual_assets,
            )
        )
    return audit_windows, window_diffs, figure_cards


def _build_context_debt_report(
    *,
    candidates: Sequence[Mapping[str, Any]],
    relations: Sequence[EvidenceRelationManifest],
    parts: Sequence[EvidencePart],
    audit_windows: Sequence[AuditWindow],
    figure_cards: Sequence[FigureEvidenceCard],
    chunk_by_id: Mapping[str, Mapping[str, Any]],
) -> ContextDebtReport:
    samples: list[dict[str, Any]] = []
    half_sentence_chunk_ids = [
        str(chunk.get("chunk_id") or "")
        for chunk in candidates
        if isinstance(chunk, Mapping) and _looks_half_sentence(str(chunk.get("content") or ""))
    ]
    for chunk_id in half_sentence_chunk_ids[:5]:
        if chunk_id:
            samples.append({"type": "half_sentence_chunk", "chunk_id": chunk_id})

    figure_bound_anchor_ids = {
        relation.anchor_chunk_id
        for relation in relations
        if relation.relation_type == "figure_caption"
    }
    unbound_figure_refs: list[str] = []
    for chunk in candidates:
        if not isinstance(chunk, Mapping):
            continue
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if chunk_id and chunk_id not in figure_bound_anchor_ids and _in_text_mentions(str(chunk.get("content") or "")):
            unbound_figure_refs.append(chunk_id)
    for chunk_id in unbound_figure_refs[:5]:
        samples.append({"type": "in_text_figure_ref_unbound", "chunk_id": chunk_id})

    missing_figures = [
        card.figure_id
        for card in figure_cards
        if card.asset_status != "present" or card.asset_kind == "page_screenshot"
    ]
    for figure_id in missing_figures[:5]:
        samples.append({"type": "figure_caption_missing_asset", "figure_id": figure_id})

    missing_tables = [
        part.chunk_id
        for part in parts
        if part.role == "table" and _table_missing_structured_data(chunk_by_id.get(part.chunk_id))
    ]
    for chunk_id in missing_tables[:5]:
        samples.append({"type": "table_missing_structured_data", "chunk_id": chunk_id})

    downgraded_count = sum(1 for window in audit_windows if window.citation_mode.downgrade_reason)
    return ContextDebtReport(
        half_sentence_chunk_count=len([chunk_id for chunk_id in half_sentence_chunk_ids if chunk_id]),
        figure_caption_missing_asset_count=len(missing_figures),
        table_missing_structured_data_count=len(missing_tables),
        in_text_figure_ref_unbound_count=len(unbound_figure_refs),
        downgraded_citation_count=downgraded_count,
        samples=samples[:20],
    )


def _anchor_part(anchor: Mapping[str, Any]) -> EvidencePart:
    chunk_id = _bounded_required_text(anchor.get("chunk_id"), "anchor_chunk_id", max_chars=240)
    return EvidencePart(
        part_id=_part_id(chunk_id, "anchor"),
        chunk_id=chunk_id,
        role=_part_role(anchor),
        locator_refs=[_locator_ref(anchor)],
        citation_allowed=_citation_allowed(anchor, {}),
        source_reason=f"{EVIDENCE_RELATION_SOURCE_RULE_VERSION}:retrieved_child",
        asset_status=_asset_status(anchor),
    )


def _build_figure_card(
    *,
    anchor: Mapping[str, Any],
    related: Mapping[str, Any],
    relation: EvidenceRelationManifest,
) -> FigureEvidenceCard:
    image_paths = _image_paths(related)
    asset_kind = _figure_asset_kind(related)
    image_asset = image_paths[0] if image_paths else None
    return FigureEvidenceCard(
        figure_id=f"fig_{relation.relation_id.removeprefix('rel_')}",
        image_asset=image_asset,
        caption=_bounded_optional_text(related.get("content"), max_chars=800),
        in_text_mentions=_in_text_mentions(str(anchor.get("content") or "")),
        page=related.get("page") if isinstance(related.get("page"), int | str) else None,
        bbox=related.get("bbox") if isinstance(related.get("bbox"), list) else None,
        included_in_prompt=False,
        exclusion_reason="shadow_mode_not_rendered",
        asset_status=_asset_status(related),
        asset_kind=asset_kind,
    )


def _part_from_policy_input(part: EvidencePart | Mapping[str, Any]) -> EvidencePart:
    if isinstance(part, EvidencePart):
        return part
    if not isinstance(part, Mapping):
        raise TypeError("used_parts must contain EvidencePart or mapping values")
    role = str(part.get("role") or "").strip()
    if role not in _EVIDENCE_PART_ROLES:
        raise ValueError("part role is invalid")
    citation_allowed = str(part.get("citation_allowed") or "").strip()
    if citation_allowed not in _CITATION_ALLOWED_VALUES:
        raise ValueError("part citation_allowed is invalid")
    locator_refs_raw = part.get("locator_refs")
    locator_refs: list[dict[str, Any]] = []
    if isinstance(locator_refs_raw, Sequence) and not isinstance(locator_refs_raw, (str, bytes)):
        for locator in locator_refs_raw:
            if not isinstance(locator, Mapping):
                raise TypeError("part locator_refs must contain mappings")
            locator_refs.append(dict(locator))
            if len(locator_refs) >= 12:
                break
    asset_status = str(part.get("asset_status") or "unknown").strip() or "unknown"
    if asset_status not in _ASSET_STATUS_VALUES:
        raise ValueError("part asset_status is invalid")
    return EvidencePart(
        part_id=_bounded_required_text(part.get("part_id"), "part_id", max_chars=240),
        chunk_id=_bounded_required_text(part.get("chunk_id"), "chunk_id", max_chars=240),
        role=cast(EvidencePartRole, role),
        locator_refs=locator_refs,
        citation_allowed=cast(CitationAllowed, citation_allowed),
        source_reason=str(part.get("source_reason") or ""),
        asset_status=cast(AssetStatus, asset_status),
    )


def _window_id(project_id: str, anchor_id: str, relations: Sequence[EvidenceRelationManifest]) -> str:
    payload = {
        "project_id": project_id,
        "anchor_chunk_id": anchor_id,
        "relation_ids": [relation.relation_id for relation in relations],
    }
    return f"win_{_sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:24]}"


def _expansion_reason(relations: Sequence[EvidenceRelationManifest]) -> str:
    reasons = []
    for relation in relations:
        reason = relation.source_rule.rsplit(":", 1)[-1]
        if reason not in reasons:
            reasons.append(reason)
    return ",".join(reasons) if reasons else "none"


def _merge_locator_refs(groups: Sequence[Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for group in groups:
        if isinstance(group, (str, bytes)) or not isinstance(group, Sequence):
            continue
        for locator in group:
            if not isinstance(locator, Mapping):
                continue
            locator_dict = {str(key): value for key, value in locator.items() if value not in ("", None)}
            key = json.dumps(locator_dict, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            merged.append(locator_dict)
            if len(merged) >= 12:
                return merged
    return merged


def _citation_decision(level: CitationLevel, locator_refs: list[dict[str, Any]], reason: str) -> CitationPolicyDecision:
    confidence_by_level: dict[CitationLevel, float] = {
        "exact_bbox": 0.9,
        "multi_locator": 0.75,
        "page_span": 0.6,
        "context_span": 0.45,
        "unattributed": 0.1,
    }
    return CitationPolicyDecision(
        citation_level=level,
        locator_refs=locator_refs,
        downgrade_reason=reason,
        confidence=confidence_by_level[level],
    )


def _locator_has_bbox(locator: Mapping[str, Any]) -> bool:
    bbox = locator.get("bbox")
    return isinstance(bbox, list) and len(bbox) >= 4


def _build_relation(
    *,
    project_id: str,
    anchor: Mapping[str, Any],
    related: Mapping[str, Any],
    sibling: Mapping[str, Any],
    chunk_store_version: str,
    extractor_hash: str,
    created_at: str,
) -> EvidenceRelationManifest:
    anchor_id = _bounded_required_text(anchor.get("chunk_id"), "anchor_chunk_id", max_chars=240)
    related_id = _bounded_required_text(related.get("chunk_id"), "related_chunk_id", max_chars=240)
    material_id = _material_id(related) or _material_id(anchor)
    if not material_id:
        raise ValueError("material_id is required")
    relation_type = _relation_type(related, sibling)
    relation_id = _sha256_text(
        json.dumps(
            {
                "project_id": project_id,
                "anchor_chunk_id": anchor_id,
                "related_chunk_id": related_id,
                "relation_type": relation_type,
                "source_rule": _source_rule(sibling),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )[:24]
    anchor_hash = _chunk_hash(anchor, material_id_hint=material_id)
    related_hash = _chunk_hash(related, material_id_hint=material_id)
    part_id = _part_id(related_id, relation_id)
    return EvidenceRelationManifest(
        relation_id=f"rel_{relation_id}",
        project_id=project_id,
        material_id=material_id,
        anchor_chunk_id=anchor_id,
        related_chunk_id=related_id,
        relation_type=relation_type,
        locator_refs=[_locator_ref(anchor), _locator_ref(related)],
        confidence=_confidence_for_reason(str(sibling.get("sibling_reason") or "")),
        source_rule=_source_rule(sibling),
        chunk_hash_set={anchor_id: anchor_hash, related_id: related_hash},
        structure_version=CHUNK_HASH_VERSION,
        chunk_store_version=chunk_store_version,
        extractor_contract_hash=extractor_hash,
        created_at=created_at,
        evidence_part_ids=[part_id],
    )


def _build_part(
    *,
    related: Mapping[str, Any],
    sibling: Mapping[str, Any],
    relation: EvidenceRelationManifest,
) -> EvidencePart:
    chunk_id = _bounded_required_text(related.get("chunk_id"), "chunk_id", max_chars=240)
    return EvidencePart(
        part_id=relation.evidence_part_ids[0],
        chunk_id=chunk_id,
        role=_part_role(related),
        locator_refs=[_locator_ref(related)],
        citation_allowed=_citation_allowed(related, sibling),
        source_reason=relation.source_rule,
        asset_status=_asset_status(related),
    )


def _relation_type(related: Mapping[str, Any], sibling: Mapping[str, Any]) -> RelationType:
    chunk_type = str(related.get("chunk_type") or "").strip()
    reason = str(sibling.get("sibling_reason") or "").strip()
    if chunk_type == "figure_caption":
        return "figure_caption"
    if chunk_type == "table":
        return "table"
    if chunk_type in {"formula", "equation"}:
        return "formula"
    if reason == "same_page":
        return "same_page_local"
    return "same_section_sibling"


def _part_role(related: Mapping[str, Any]) -> EvidencePartRole:
    chunk_type = str(related.get("chunk_type") or "").strip()
    if chunk_type == "figure_caption":
        return "figure_caption"
    if chunk_type == "table":
        return "table"
    if chunk_type in {"formula", "equation"}:
        return "formula"
    if chunk_type == "narrative":
        return "narrative"
    return "nearby_context"


def _citation_allowed(related: Mapping[str, Any], sibling: Mapping[str, Any]) -> CitationAllowed:
    if _has_bbox(related) and not str(sibling.get("sibling_reason") or "").strip():
        return "exact_bbox"
    if _has_bbox(related):
        return "multi_locator"
    if related.get("page") is not None:
        return "page_span"
    return "context_span"


def _asset_status(related: Mapping[str, Any]) -> AssetStatus:
    chunk_type = str(related.get("chunk_type") or "").strip()
    if chunk_type == "figure_caption":
        kind = _figure_asset_kind(related)
        return "present" if kind in {"embedded_figure", "extracted_region"} else "missing"
    if chunk_type in {"table", "formula", "equation"}:
        return "present"
    return "not_applicable"


def _figure_asset_kind(chunk: Mapping[str, Any]) -> FigureAssetKind:
    image_paths = _image_paths(chunk)
    if not image_paths:
        return "missing"
    joined = " ".join(image_paths).lower()
    if "page_screenshot" in joined or "screenshot" in joined:
        return "page_screenshot"
    if _has_bbox(chunk):
        return "extracted_region"
    return "embedded_figure"


def _image_paths(chunk: Mapping[str, Any]) -> list[str]:
    raw_paths = chunk.get("image_paths")
    if isinstance(raw_paths, str) or not isinstance(raw_paths, Sequence):
        return []
    paths: list[str] = []
    for value in raw_paths:
        text = _bounded_optional_text(value, max_chars=500)
        if text:
            paths.append(text)
        if len(paths) >= 8:
            break
    return paths


def _in_text_mentions(content: str) -> list[str]:
    if not content:
        return []
    mentions: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(content):
        if not _FIGURE_REF_RE.search(sentence):
            continue
        text = _bounded_optional_text(sentence, max_chars=360)
        if text and text not in mentions:
            mentions.append(text)
        if len(mentions) >= 5:
            break
    return mentions


def _looks_half_sentence(content: str) -> bool:
    text = re.sub(r"^(?:\[[^\[\]]*\])+\n?", "", content or "").strip()
    if len(text) < 20:
        return False
    first_alpha = next((char for char in text if char.isalpha()), "")
    starts_mid_sentence = bool(first_alpha and first_alpha.islower())
    ends_mid_sentence = text[-1] not in ".。!！?？;；:：)]}”’\"'"
    return starts_mid_sentence or ends_mid_sentence


def _table_missing_structured_data(chunk: Mapping[str, Any] | None) -> bool:
    if chunk is None:
        return True
    if str(chunk.get("chunk_type") or "").strip() != "table":
        return False
    structured_fields = ("table_csv", "table_html", "table_json", "structured_data", "cells")
    return not any(chunk.get(field) for field in structured_fields)


def _source_rule(sibling: Mapping[str, Any]) -> str:
    reason = str(sibling.get("sibling_reason") or "unknown").strip() or "unknown"
    return f"{EVIDENCE_RELATION_SOURCE_RULE_VERSION}:{reason}"


def _confidence_for_reason(reason: str) -> float:
    if reason == "section_path":
        return 0.9
    if reason == "section_title":
        return 0.75
    if reason == "same_page":
        return 0.55
    return 0.5


def _locator_ref(chunk: Mapping[str, Any]) -> dict[str, Any]:
    locator: dict[str, Any] = {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "material_id": _material_id(chunk),
        "page": chunk.get("page"),
        "bbox": chunk.get("bbox") if isinstance(chunk.get("bbox"), list) else None,
        "section_path": chunk.get("section_path") if isinstance(chunk.get("section_path"), list) else None,
        "chunk_type": str(chunk.get("chunk_type") or ""),
    }
    return {key: value for key, value in locator.items() if value not in ("", None)}


def _has_bbox(chunk: Mapping[str, Any]) -> bool:
    bbox = chunk.get("bbox")
    return isinstance(bbox, list) and len(bbox) >= 4


def _chunk_hash(chunk: Mapping[str, Any], *, material_id_hint: str | None = None) -> str:
    existing = str(chunk.get("chunk_hash") or "").strip()
    if len(existing) == 64:
        return existing
    hashes: object = compute_chunk_hashes(chunk, material_id_hint=material_id_hint)
    if not isinstance(hashes, Mapping):
        raise TypeError("chunk hash provider must return a mapping")
    chunk_hash = hashes.get("chunk_hash")
    if not isinstance(chunk_hash, str) or len(chunk_hash) != 64:
        raise ValueError("chunk hash provider returned an invalid chunk_hash")
    return chunk_hash


def _chunk_by_id(chunks: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if chunk_id and chunk_id not in result:
            result[chunk_id] = chunk
    return result


def _group_chunks_by_material(chunks: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for chunk in chunks:
        material_id = _material_id(chunk)
        if not material_id:
            raise ValueError("all_chunks must include material_id for chunk_store_version")
        grouped.setdefault(material_id, []).append(chunk)
    return grouped


def _copy_mapping_sequence(value: Sequence[Mapping[str, Any]], name: str) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of mappings")
    copied: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"{name} must contain only mappings")
        copied.append(dict(item))
    return copied


def _material_id(chunk: Mapping[str, Any]) -> str:
    return str(chunk.get("material_id") or "").strip()


def _part_id(chunk_id: str, relation_id: str) -> str:
    digest = _sha256_text(f"{relation_id}:{chunk_id}")[:24]
    return f"part_{digest}"


def _safe_project_id(project_id: str) -> str:
    safe_id = "".join(char for char in str(project_id).strip() if char.isalnum() or char in "_-")
    if not safe_id:
        raise ValueError("project_id cannot be empty")
    return safe_id[:160]


def _bounded_required_text(value: Any, name: str, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} cannot be empty")
    if len(text) > max_chars:
        raise ValueError(f"{name} is too long")
    if any(ord(char) < 32 for char in text):
        raise ValueError(f"{name} contains control characters")
    return text


def _bounded_optional_text(value: Any, *, max_chars: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    cleaned = "".join(char for char in text if ord(char) >= 32 or char == "\n")
    return cleaned[:max_chars]


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if Path(tmp_name).exists():
                Path(tmp_name).unlink()
        except OSError:
            pass


__all__ = [
    "EVIDENCE_RELATION_SOURCE_RULE_VERSION",
    "EXTRACTOR_CONTRACT_VERSION",
    "AuditWindow",
    "CitationPolicy",
    "CitationPolicyDecision",
    "ContextDebtReport",
    "EvidencePart",
    "EvidenceRelationBuildResult",
    "EvidenceRelationManifest",
    "FigureEvidenceCard",
    "FigureTableFormulaRelationStrategy",
    "ManifestStaleCheck",
    "WindowDiff",
    "check_manifest_meta_stale",
    "check_relation_stale",
    "extractor_contract_hash",
    "is_evidence_window_shadow_enabled",
    "manifest_paths",
    "persist_relation_manifest",
    "record_shadow_relations_if_enabled",
]
