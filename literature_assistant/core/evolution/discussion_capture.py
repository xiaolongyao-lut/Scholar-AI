"""
Pure-function candidate extraction for /discussion/runs.

Maps `DiscussionRunResult` (the full trace returned by the orchestrator) to
the kwargs `EvolutionService.capture()` needs. Eligibility rules below are
conservative — most discussion runs will produce 0-3 candidates so the
review queue does not flood when dogfooders run many short discussions.

Three candidate sources for v1:
    (a) per-agent role lessons   — memory_type=AGENT_ROLE_LESSON
        Latest successful answer of each agent across all turns, gated on
        non-empty cited_evidence_ids (evidence-backed only).
    (b) synthesis pattern        — memory_type=DOMAIN_KNOWLEDGE
        synthesis.text when synthesis.success and aggregated cited evidence
        across all agents is non-empty (otherwise dropped per §Fail-closed
        "Domain knowledge without evidence refs: block").
    (c) failed agent reliability — memory_type=TOOL_RELIABILITY
        Per agent with success=False and an error payload. No evidence
        required (reliability lessons are about the agent itself).

Convergence / unresolved-conflict candidates are intentionally deferred —
they need richer conflict-detection signals that the current trace does
not surface in a clean form.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from models.evolution import (
    CandidateMemoryType,
    CandidateRiskLevel,
    CandidateSourceType,
)
from evolution._capture_args import CaptureCandidateArgs


def extract_from_discussion_result(
    result: Any,
    *,
    workspace_id: str = "default",
    source_route: str = "/discussion/runs",
) -> List[CaptureCandidateArgs]:
    """Return capture kwargs for one discussion run.

    `result` is duck-typed against `DiscussionRunResult`:
      run_id (str), project_id (str | None), query (str),
      turns: list of trace records each with `.agent_traces`
      synthesis (optional): `.text`, `.success`
    """

    run_id = getattr(result, "run_id", None)
    if not run_id:
        return []

    project_id = getattr(result, "project_id", None)
    query = getattr(result, "query", "") or ""
    turns = list(getattr(result, "turns", []) or [])

    candidates: List[CaptureCandidateArgs] = []

    # --- (a) per-agent role lessons -----------------------------------------

    latest_by_agent: Dict[str, Any] = {}
    for turn in turns:
        for trace in (getattr(turn, "agent_traces", None) or []):
            agent_id = getattr(trace, "agent_id", None)
            if not agent_id:
                continue
            latest_by_agent[agent_id] = trace  # later turns overwrite earlier

    cited_overall: Set[str] = set()
    for trace in latest_by_agent.values():
        cited_overall.update(getattr(trace, "cited_evidence_ids", None) or [])
        if not getattr(trace, "success", False):
            # Failed agents handled separately below
            continue
        cited = list(getattr(trace, "cited_evidence_ids", None) or [])
        if not cited:
            continue  # evidence-backed lessons only

        answer = getattr(trace, "answer", "") or ""
        if not answer.strip():
            continue

        role = getattr(trace, "role", "") or "unknown"
        role_label = getattr(trace, "role_label", "") or role
        agent_id = getattr(trace, "agent_id", "")
        candidates.append(CaptureCandidateArgs(
            workspace_id=workspace_id,
            source_type=CandidateSourceType.DISCUSSION,
            source_id=f"{run_id}:{agent_id}",
            source_summary=(
                f"讨论 · 查询: {_shorten(query, 200)}"
                f" · 角色: {role_label}({role}) · evidence_count={len(cited)}"
            ),
            memory_type=CandidateMemoryType.AGENT_ROLE_LESSON,
            title=f"讨论角色经验: {role_label or role}",
            claim=_shorten(answer, 4000),
            future_use=(
                f"复用 {role_label or role} 角色的论证模式："
                f"针对 “{_shorten(query, 60)}” 类查询，该角色提供过证据支撑的回应"
            ),
            confidence=0.65,
            project_id=project_id,
            source_route=source_route,
            evidence_refs=[{"chunk_id": cid} for cid in cited],
            risk_level=CandidateRiskLevel.LOW,
        ))

    # --- (b) synthesis pattern ----------------------------------------------

    synthesis = getattr(result, "synthesis", None)
    if synthesis is not None:
        synth_text = getattr(synthesis, "text", "") or ""
        synth_success = bool(getattr(synthesis, "success", False))
        if synth_success and synth_text.strip() and cited_overall:
            candidates.append(CaptureCandidateArgs(
                workspace_id=workspace_id,
                source_type=CandidateSourceType.DISCUSSION,
                source_id=f"{run_id}:synthesis",
                source_summary=(
                    f"讨论 · 综合 · 查询: {_shorten(query, 200)}"
                    f" · aggregated evidence_count={len(cited_overall)}"
                ),
                memory_type=CandidateMemoryType.DOMAIN_KNOWLEDGE,
                title=f"讨论综合: {_shorten(query, 60)}",
                claim=_shorten(synth_text, 4000),
                future_use=(
                    f"复用此综合视角作为 “{_shorten(query, 60)}” 的"
                    f"研究方向起点；含 {len(cited_overall)} 条证据"
                ),
                confidence=0.7,
                project_id=project_id,
                source_route=source_route,
                evidence_refs=[{"chunk_id": cid} for cid in sorted(cited_overall)],
                risk_level=CandidateRiskLevel.LOW,
            ))

    # --- (c) failed-agent reliability lessons --------------------------------

    for trace in latest_by_agent.values():
        if getattr(trace, "success", False):
            continue
        err = getattr(trace, "error", None)
        if not err:
            continue
        agent_id = getattr(trace, "agent_id", "") or ""
        role = getattr(trace, "role", "") or "unknown"
        role_label = getattr(trace, "role_label", "") or role
        provider = getattr(trace, "provider", "") or ""
        model = getattr(trace, "model", "") or ""
        message = ""
        if isinstance(err, dict):
            message = str(err.get("message") or err.get("type") or "agent failed")
        else:
            message = "agent failed"

        candidates.append(CaptureCandidateArgs(
            workspace_id=workspace_id,
            source_type=CandidateSourceType.DISCUSSION,
            source_id=f"{run_id}:{agent_id}:fail",
            source_summary=(
                f"讨论失败 · 角色: {role_label}({role})"
                f" · provider={provider} · model={model}"
            ),
            memory_type=CandidateMemoryType.TOOL_RELIABILITY,
            title=f"讨论失败案例: {role_label or role} on {provider}/{model}",
            claim=_shorten(message, 4000),
            future_use=(
                f"记录此 provider/model 在 {role_label or role} 角色下的失败模式，"
                f"未来选模型时参考"
            ),
            confidence=0.5,
            project_id=project_id,
            source_route=source_route,
            evidence_refs=[],
            risk_level=CandidateRiskLevel.MEDIUM,
        ))

    return candidates


# --- helpers -----------------------------------------------------------------

def _shorten(text: str, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
