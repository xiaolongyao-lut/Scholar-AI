"""Inspiration P3 prep-only scaffold (FD-10 Order 6a, 2026-05-21).

This module provides **prep-only infrastructure** for FD-10 Inspiration P3
(causal DAG NER+RE semanticization), shipped per `docs/plans/active/
2026-05-21-bug-fix-plan.md` §7.3.3 Order 6a. The full P3 feature track is
blocked on (a) a user-authored goldset and (b) a real-AI eval budget; this
module ships only the deterministic, no-paid-AI, default-off pieces:

- :data:`INSPIRATION_P3_ENABLED` — module-level feature flag resolved from
  env var ``INSPIRATION_P3_ENABLED`` (string ``"1"`` / ``"true"`` / ``"yes"``
  → True; anything else, including unset, → False). Production callers
  MUST check this before invoking any real extraction path. Default off.

- :class:`ExpectedNode` / :class:`ExpectedEdge` / :class:`InspirationP3GoldsetEntry`
  Pydantic v2 schema for the per-spark goldset. Mirrors
  :class:`graph_payload.GraphNode` / :class:`graph_payload.GraphEdge`
  controlled vocab so a future extractor can be evaluated against the same
  controlled types it must emit.

- :func:`inspiration_p3_cache_key` — deterministic ``sha256`` over
  ``SparkEvidenceRef.text`` joined with ``"\\n---\\n"``. Per-spark cache key
  for the future async backfill path (D-IP3-4).

- :func:`compute_extraction_metrics` — given a predicted extraction output
  and an expected goldset entry, returns per-type precision / recall / F1
  for both nodes and edges. Pure function, no LLM call. Suitable for tiny
  synthetic fixtures and for the eventual real eval harness.

**Out of scope for this module** (gated on full P3 / user goldset / real AI):
the actual ``nodes_from_evidence`` / ``edges_from_evidence`` LLM extractors,
wiring into ``inspiration_engine.generate_sparks``, frontend rendering, and
the 8–15-call eval against a user goldset.
"""

from __future__ import annotations

import hashlib
import os
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Feature flag (default off; explicit env opt-in)
# ---------------------------------------------------------------------------


def _resolve_inspiration_p3_enabled() -> bool:
    """Read ``INSPIRATION_P3_ENABLED`` env at module load time.

    Truthy set: ``"1"``, ``"true"``, ``"yes"`` (case-insensitive). Anything
    else, including unset / empty / ``"0"`` / ``"false"`` / ``"no"``, → False.

    A function (not an inline constant assignment) so callers can
    monkeypatch this in tests via ``importlib.reload`` if they need the
    pre-import behavior. The module-level constant below is the canonical
    runtime value for normal callers.
    """
    raw = (os.environ.get("INSPIRATION_P3_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes"}


INSPIRATION_P3_ENABLED: bool = _resolve_inspiration_p3_enabled()


# ---------------------------------------------------------------------------
# Goldset schema (mirrors graph_payload.NodeType / EdgeRelation controlled
# vocabularies so extractor predictions and goldset annotations share types)
# ---------------------------------------------------------------------------

GoldsetNodeType = Literal[
    "claim",
    "method",
    "dataset",
    "metric",
    "limitation",
    "concept",
    "material",
    "agent",
    "evidence",
]

GoldsetEdgeRelation = Literal[
    "supports",
    "contradicts",
    "extends",
    "uses",
    "produces",
    "measures",
    "cites",
    "related",
]


class ExpectedNode(BaseModel):
    """One annotated node in a goldset entry.

    ``id`` is a stable string within an entry (e.g. ``"n1"``); ``label`` is
    the human-readable surface form; ``type`` is the controlled vocab.
    """

    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    type: GoldsetNodeType


class ExpectedEdge(BaseModel):
    """One annotated edge in a goldset entry.

    ``source`` and ``target`` must refer to ``ExpectedNode.id`` values
    within the same entry. Direction is from source to target.
    """

    model_config = ConfigDict(extra="forbid")
    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    relation: GoldsetEdgeRelation


class InspirationP3GoldsetEntry(BaseModel):
    """One annotated spark in the P3 goldset (the eventual user-authored
    JSONL file under ``workspace_tests/evaluation_data/`` will contain one
    of these per line).

    Synthetic fixtures may set ``query`` to a short marker string so the
    deterministic eval harness can run without any real spark generation.

    Cross-field invariant: every ``ExpectedEdge.source`` / ``.target`` must
    refer to an existing ``ExpectedNode.id`` within the same entry. The
    eval harness's ``_resolve`` step would otherwise silently degrade an
    unknown id into a literal string, masking authoring bugs in goldset
    JSONL — which violates the project-wide "拒绝静默失败" rule.
    """

    model_config = ConfigDict(extra="forbid")
    query: str = Field(..., min_length=1)
    expected_nodes: list[ExpectedNode] = Field(default_factory=list)
    expected_edges: list[ExpectedEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _edges_reference_known_nodes(self) -> "InspirationP3GoldsetEntry":
        node_ids = {n.id for n in self.expected_nodes}
        dangling: list[str] = []
        for idx, edge in enumerate(self.expected_edges):
            if edge.source not in node_ids:
                dangling.append(f"edges[{idx}].source={edge.source!r}")
            if edge.target not in node_ids:
                dangling.append(f"edges[{idx}].target={edge.target!r}")
        if dangling:
            raise ValueError(
                "ExpectedEdge references unknown node id(s): "
                + ", ".join(dangling)
                + f" (known ids: {sorted(node_ids)})"
            )
        return self


# ---------------------------------------------------------------------------
# Per-spark cache key (D-IP3-4: sha256 over refs[].text)
# ---------------------------------------------------------------------------


def inspiration_p3_cache_key(refs: Iterable[object]) -> str:
    """Deterministic per-spark cache key for the future async-backfill path.

    Hashes the ``.text`` attribute of each evidence ref (typically
    :class:`literature_assistant.core.routers.inspiration_router.SparkEvidenceRef`)
    joined with the literal separator ``"\\n---\\n"``. Empty input → the
    sha256 of the empty string (canonical empty-cache key).

    Accepts any iterable of objects with a ``.text`` attribute so this
    module does not have to import the router-defined ``SparkEvidenceRef``
    type (which would create an inspiration_engine → inspiration_router
    layering inversion).
    """
    parts: list[str] = []
    for ref in refs:
        text = getattr(ref, "text", "")
        parts.append(str(text or ""))
    joined = "\n---\n".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Deterministic eval — precision/recall/F1 per node type + relation type
# ---------------------------------------------------------------------------


def _safe_div(num: float, den: float) -> float:
    return (num / den) if den > 0 else 0.0


def _prf1(true_positives: int, predicted: int, expected: int) -> dict[str, float]:
    precision = _safe_div(true_positives, predicted)
    recall = _safe_div(true_positives, expected)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def compute_extraction_metrics(
    predicted_nodes: list[dict],
    predicted_edges: list[dict],
    expected_entry: InspirationP3GoldsetEntry,
) -> dict[str, object]:
    """Compute per-type precision / recall / F1 for one (predicted, goldset) pair.

    ``predicted_nodes`` and ``predicted_edges`` accept dicts (not Pydantic
    instances) so the eval harness can consume raw JSON extractor output
    without re-parsing. Each predicted node must have ``label`` + ``type``;
    each predicted edge must have ``source`` + ``target`` + ``relation``
    where ``source``/``target`` refer to predicted-node labels.

    Match key per node: ``(label.lower(), type)`` — exact match within a
    type. Match key per edge: ``(source_label.lower(), target_label.lower(),
    relation)``. A predicted item matches at most one expected item; ties
    pick the first expected match.

    Returns a dict with three keys:
      * ``nodes_by_type``: ``{type: {"precision","recall","f1"}}``
      * ``edges_by_relation``: ``{relation: {"precision","recall","f1"}}``
      * ``overall``: ``{"nodes": {...}, "edges": {...}}`` (micro-averaged
        across all types).

    Pure function; no LLM call.
    """
    # --- Nodes -------------------------------------------------------------
    expected_node_by_id = {n.id: n for n in expected_entry.expected_nodes}
    nodes_by_type: dict[str, dict[str, float]] = {}
    total_node_tp = total_node_pred = total_node_exp = 0

    for type_name in set(
        [n.type for n in expected_entry.expected_nodes]
        + [str(n.get("type", "")) for n in predicted_nodes if n.get("type")]
    ):
        if not type_name:
            continue
        exp_keys = {
            (n.label.strip().lower(), n.type)
            for n in expected_entry.expected_nodes
            if n.type == type_name
        }
        pred_keys = {
            (str(p.get("label", "")).strip().lower(), str(p.get("type", "")))
            for p in predicted_nodes
            if p.get("type") == type_name
        }
        tp = len(exp_keys & pred_keys)
        nodes_by_type[type_name] = _prf1(tp, len(pred_keys), len(exp_keys))
        total_node_tp += tp
        total_node_pred += len(pred_keys)
        total_node_exp += len(exp_keys)

    # --- Edges -------------------------------------------------------------
    # Build a label-resolved view of expected edges (source/target are ids
    # in the goldset; resolve via expected_node_by_id).
    def _resolve(eid: str) -> str:
        node = expected_node_by_id.get(eid)
        return (node.label if node else eid).strip().lower()

    edges_by_relation: dict[str, dict[str, float]] = {}
    total_edge_tp = total_edge_pred = total_edge_exp = 0

    for rel in set(
        [e.relation for e in expected_entry.expected_edges]
        + [str(e.get("relation", "")) for e in predicted_edges if e.get("relation")]
    ):
        if not rel:
            continue
        exp_keys = {
            (_resolve(e.source), _resolve(e.target), e.relation)
            for e in expected_entry.expected_edges
            if e.relation == rel
        }
        pred_keys = {
            (
                str(p.get("source", "")).strip().lower(),
                str(p.get("target", "")).strip().lower(),
                str(p.get("relation", "")),
            )
            for p in predicted_edges
            if p.get("relation") == rel
        }
        tp = len(exp_keys & pred_keys)
        edges_by_relation[rel] = _prf1(tp, len(pred_keys), len(exp_keys))
        total_edge_tp += tp
        total_edge_pred += len(pred_keys)
        total_edge_exp += len(exp_keys)

    return {
        "nodes_by_type": nodes_by_type,
        "edges_by_relation": edges_by_relation,
        "overall": {
            "nodes": _prf1(total_node_tp, total_node_pred, total_node_exp),
            "edges": _prf1(total_edge_tp, total_edge_pred, total_edge_exp),
        },
    }


__all__ = [
    "INSPIRATION_P3_ENABLED",
    "GoldsetEdgeRelation",
    "GoldsetNodeType",
    "ExpectedNode",
    "ExpectedEdge",
    "InspirationP3GoldsetEntry",
    "inspiration_p3_cache_key",
    "compute_extraction_metrics",
    "_resolve_inspiration_p3_enabled",  # exported for reload-based tests
]
