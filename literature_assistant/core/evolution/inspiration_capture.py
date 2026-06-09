"""
Pure-function candidate extraction for `/inspiration/generate`.

Maps `SparkResponse` rows (the gated public spark payload returned by
`literature_assistant/core/routers/inspiration_router.py:_gate_sparks`) to
the kwargs `EvolutionService.capture()` needs. Eligibility rules below are
intentionally conservative — most sparks will *not* yield a candidate so
the review queue does not fill with low-signal noise on day one.

Eligibility:
    - spark has at least one evidence_ref → eligible (project_fact or
      domain_knowledge depending on spark_type)
    - spark_type == "memory_association" → eligible (user_preference)
    - everything else → skipped (no candidate)

Memory-type mapping:
    memory_association → user_preference
    causal_extension   → literature_procedure
    conflict           → agent_role_lesson
    gap                → project_fact
    synthesis          → domain_knowledge
    other              → project_fact (safe default)

Risk-level mapping:
    domain_knowledge / synthesis without evidence_refs → blocked-equivalent
        (the secret-scan / state machine cannot block these so the extractor
         returns None to keep them out of the queue altogether)
    evidence-backed sparks → low
    memory_association     → low

This module is import-safe and has no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.evolution import (
    CandidateMemoryType,
    CandidateRiskLevel,
    CandidateSourceType,
)
from evolution._capture_args import CaptureCandidateArgs


_MEMORY_TYPE_BY_SPARK_TYPE: Dict[str, CandidateMemoryType] = {
    "memory_association": CandidateMemoryType.USER_PREFERENCE,
    "causal_extension": CandidateMemoryType.LITERATURE_PROCEDURE,
    "conflict": CandidateMemoryType.AGENT_ROLE_LESSON,
    "gap": CandidateMemoryType.PROJECT_FACT,
    "synthesis": CandidateMemoryType.DOMAIN_KNOWLEDGE,
}


def extract_from_spark(
    spark: Any,
    *,
    query: str,
    project_id: Optional[str],
    workspace_id: str = "default",
    source_route: str = "/inspiration/generate",
) -> Optional[CaptureCandidateArgs]:
    """Return capture kwargs for a single spark, or None if not eligible.

    `spark` is duck-typed: must expose `id`, `content`, `spark_type`,
    `confidence`, and `evidence_refs` (list of pydantic models or dicts).
    The function never raises on missing fields — missing data downgrades
    the spark to ineligible.
    """

    spark_id = getattr(spark, "id", None)
    content = getattr(spark, "content", None)
    spark_type = getattr(spark, "spark_type", None)
    confidence = getattr(spark, "confidence", 0.0)
    evidence_refs_raw = getattr(spark, "evidence_refs", None) or []

    if not (spark_id and content and spark_type):
        return None

    evidence_refs = [_ref_to_dict(ref) for ref in evidence_refs_raw]
    has_evidence = len(evidence_refs) > 0
    is_memory_assoc = spark_type == "memory_association"

    if not (has_evidence or is_memory_assoc):
        return None  # speculation without grounding — skip

    memory_type = _MEMORY_TYPE_BY_SPARK_TYPE.get(
        spark_type, CandidateMemoryType.PROJECT_FACT
    )

    # Domain knowledge / synthesis without evidence is blocked entirely:
    # block. We translate "block" to "do not enqueue" here so the review
    # queue stays free of unreviewable items.
    if memory_type in (CandidateMemoryType.DOMAIN_KNOWLEDGE,) and not has_evidence:
        return None

    title = _shorten(content, 200)
    claim = _shorten(content, 4000)
    future_use = _future_use_template(spark_type, query)
    source_summary = (
        f"灵感生成 · 查询: {_shorten(query, 200)} · spark_type={spark_type}"
        f" · evidence_count={len(evidence_refs)}"
    )

    try:
        confidence_f = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence_f = 0.0

    return CaptureCandidateArgs(
        workspace_id=workspace_id,
        source_type=CandidateSourceType.INSPIRATION,
        source_id=str(spark_id),
        source_summary=source_summary,
        memory_type=memory_type,
        title=title,
        claim=claim,
        future_use=future_use,
        confidence=confidence_f,
        project_id=project_id,
        source_route=source_route,
        evidence_refs=evidence_refs,
        risk_level=CandidateRiskLevel.LOW,
    )


def extract_from_sparks(
    sparks: List[Any],
    *,
    query: str,
    project_id: Optional[str],
    workspace_id: str = "default",
    source_route: str = "/inspiration/generate",
) -> List[CaptureCandidateArgs]:
    """Map a spark list to the subset that should produce candidates."""

    out: List[CaptureCandidateArgs] = []
    for spark in sparks:
        args = extract_from_spark(
            spark,
            query=query,
            project_id=project_id,
            workspace_id=workspace_id,
            source_route=source_route,
        )
        if args is not None:
            out.append(args)
    return out


# --- helpers -----------------------------------------------------------------

def _ref_to_dict(ref: Any) -> Dict[str, Any]:
    """Normalize evidence_ref to a JSON-safe dict."""

    if isinstance(ref, dict):
        return ref
    dump = getattr(ref, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:
            pass
    return {"raw": str(ref)}


def _shorten(text: str, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _future_use_template(spark_type: str, query: str) -> str:
    """Stable per-spark-type guidance string for the review queue."""

    short_query = _shorten(query, 60)
    base = {
        "memory_association": f"复用此项目记忆联想，未来可在 “{short_query}” 类查询中作为候选证据",
        "causal_extension": f"作为 “{short_query}” 主题的延伸路径备查",
        "conflict": f"作为 “{short_query}” 中互斥结论的备忘，避免后续回答忽视",
        "gap": f"作为 “{short_query}” 知识缺口的研究方向备忘",
        "synthesis": f"作为 “{short_query}” 综合视角的复用候选",
    }
    return base.get(spark_type, f"作为 “{short_query}” 的灵感候选备查")
