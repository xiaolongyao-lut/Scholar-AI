"""
Pure-function candidate extraction for RAG project answers.

Maps `RAGResult` (returned by `main_rag_workflow.RAGWorkflow.ask_my_literature`)
to the kwargs `EvolutionService.capture()` needs. The intelligent_chat_router
wraps the RAG call so this extractor runs server-side before any response
shape transformation.

Eligibility:
    - skip when result.trace contains an "error" key (RAG itself failed)
    - skip when generated_answer is empty/whitespace
    - skip when evidence_refs is empty (no evidence → cannot promote as
      evidence rule)
    - otherwise emit ONE candidate with memory_type=EVIDENCE_RULE

Memory queries / focused_points / memory_hits-based candidates are a
later slice — they need richer user-feedback signals to gauge relevance.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from models.evolution import (
    CandidateMemoryType,
    CandidateRiskLevel,
    CandidateSourceType,
)
from evolution._capture_args import CaptureCandidateArgs


def extract_from_rag_result(
    result: Any,
    *,
    query: str,
    project_id: Optional[str],
    workspace_id: str = "default",
    source_route: str = "/intelligent_chat/project-rag",
) -> Optional[CaptureCandidateArgs]:
    """Return one capture-arg payload from a RAGResult, or None when ineligible.

    `result` is duck-typed:
        - .generated_answer (str)
        - .evidence_refs (list[EvidenceReference] or list[dict])
        - .trace (dict) — checked for "error" key
        - .confidence_score (float, optional)
    """

    if result is None:
        return None

    trace = getattr(result, "trace", None)
    if isinstance(trace, dict) and "error" in trace:
        return None

    answer = getattr(result, "generated_answer", "") or ""
    if not answer.strip():
        return None

    refs_raw = list(getattr(result, "evidence_refs", None) or [])
    refs = [_ref_to_dict(ref) for ref in refs_raw]
    if not refs:
        return None  # evidence-less rules cannot be promoted

    try:
        confidence = float(getattr(result, "confidence_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    short_query = _shorten(query, 200)
    # claim is rendered in the card default view by default, so it must NOT
    # leak raw JSON shapes from the answer payload. 280 chars is plenty for the user-facing summary;
    # the full answer is still reconstructable from the source materials
    # via the 详情 drawer and the project RAG run trace.
    short_answer = _shorten(answer, 280)
    return CaptureCandidateArgs(
        workspace_id=workspace_id,
        source_type=CandidateSourceType.RAG_ANSWER,
        source_id=f"rag:{_stable_hash(query, project_id)}",
        source_summary=(
            f"项目 RAG · 查询: {short_query} · evidence_count={len(refs)}"
        ),
        memory_type=CandidateMemoryType.EVIDENCE_RULE,
        title=f"RAG 证据规则: {_shorten(query, 60)}",
        claim=short_answer,
        future_use=(
            f"未来 “{_shorten(query, 60)}” 类查询命中相同证据时，"
            f"该回答可作为可靠模板"
        ),
        confidence=confidence,
        project_id=project_id,
        source_route=source_route,
        evidence_refs=refs,
        risk_level=CandidateRiskLevel.LOW,
    )


# --- helpers -----------------------------------------------------------------

def _ref_to_dict(ref: Any) -> Dict[str, Any]:
    if isinstance(ref, dict):
        return ref
    dump = getattr(ref, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:
            pass
    dataclass_dict = getattr(ref, "__dict__", None)
    if isinstance(dataclass_dict, dict) and dataclass_dict:
        return {k: v for k, v in dataclass_dict.items() if not k.startswith("_")}
    return {"raw": str(ref)}


def _shorten(text: str, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _stable_hash(query: str, project_id: Optional[str]) -> str:
    """Short deterministic hash for source_id; dedupe is owned by service.compute_dedupe_hash."""

    import hashlib
    payload = f"{project_id or ''}|{query or ''}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
