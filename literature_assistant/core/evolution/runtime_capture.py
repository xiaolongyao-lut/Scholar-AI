"""
Pure-function candidate extraction for terminal-state runtime jobs.

Maps a WritingJob in COMPLETED / FAILED state to the kwargs
EvolutionService.capture() needs. CANCELLED jobs produce no candidate
(cancellation carries no signal about procedure quality or tool reliability).

Mapping:
    COMPLETED  → literature_procedure   (the procedure that ran end-to-end)
    FAILED     → tool_reliability       (something to remember about reliability)
    CANCELLED  → no candidate (skipped)

Source contract:
    source_type   = runtime_job
    source_id     = job.job_id
    source_route  = "/runtime/job/{job_id}"   (synthetic — there is no
                    completion-callback HTTP route per se; the route value
                    identifies where the candidate originated)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.evolution import (
    CandidateMemoryType,
    CandidateRiskLevel,
    CandidateSourceType,
)
from evolution._capture_args import CaptureCandidateArgs


def extract_from_job(
    job: Any,
    *,
    error: Optional[str] = None,
    workspace_id: str = "default",
) -> Optional[CaptureCandidateArgs]:
    """Return capture kwargs for one terminal-state job, or None if skipped.

    `job` is duck-typed against WritingJob:
        job_id, session_id, kind, status, metadata (dict)
    """

    job_id = getattr(job, "job_id", None)
    if not job_id:
        return None

    status = getattr(job, "status", None)
    status_name = _enum_name(status)

    if status_name not in {"COMPLETED", "FAILED"}:
        return None  # CANCELLED / PAUSED / STARTED / IN_PROGRESS — no signal

    kind = getattr(job, "kind", None)
    kind_name = _enum_name(kind) or "unknown"
    session_id = getattr(job, "session_id", "") or ""
    project_id = _get_project_id(job)
    source_route = f"/runtime/job/{job_id}"
    if kind_name == "AGENT_REQUEST":
        return _extract_agent_request_job(
            job,
            job_id=job_id,
            session_id=session_id,
            status_name=status_name,
            project_id=project_id,
            source_route=source_route,
            error=error,
            workspace_id=workspace_id,
        )

    if status_name == "COMPLETED":
        return CaptureCandidateArgs(
            workspace_id=workspace_id,
            source_type=CandidateSourceType.RUNTIME_JOB,
            source_id=job_id,
            source_summary=(
                f"runtime_job · kind={kind_name} · session={session_id}"
                f" · status=completed"
            ),
            memory_type=CandidateMemoryType.LITERATURE_PROCEDURE,
            title=f"runtime job 成功: {kind_name}",
            claim=(
                f"本次{_kind_chinese(kind_name)}任务在会话中端到端完成，"
                f"可作为同类任务的流程参考"
            ),
            future_use=(
                f"未来{_kind_chinese(kind_name)}类任务可复用此流程；"
                f"评审后可酝酿为流程草稿"
            ),
            confidence=0.6,
            project_id=project_id,
            source_route=source_route,
            evidence_refs=[],
            risk_level=CandidateRiskLevel.LOW,
        )

    # FAILED branch
    err_text = error or "no error message captured"
    return CaptureCandidateArgs(
        workspace_id=workspace_id,
        source_type=CandidateSourceType.RUNTIME_JOB,
        source_id=f"{job_id}:fail",
        source_summary=(
            f"runtime_job · kind={kind_name} · session={session_id}"
            f" · status=failed"
        ),
        memory_type=CandidateMemoryType.TOOL_RELIABILITY,
        title=f"runtime job 失败: {kind_name}",
        claim=_shorten(err_text, 280),
        future_use=(
            f"记录{_kind_chinese(kind_name)}类任务的失败模式，"
            f"未来运行同类任务时排查"
        ),
        confidence=0.55,
        project_id=project_id,
        source_route=source_route,
        evidence_refs=[],
        risk_level=CandidateRiskLevel.MEDIUM,
    )


# --- helpers -----------------------------------------------------------------

# JobKind enum (harness_protocols.py) → Chinese label for user-facing text.
# Keep in sync if new JobKind values are added. Unknown values fall back to
# the lower-cased enum string (no exception — the dogfood UX rule is
# "user-facing fields should be Chinese-first" but not at the cost of
# silently dropping new kinds).
_KIND_LABELS: dict[str, str] = {
    "PROMPT_ACTION": "提示词执行",
    "SKILL_ACTION": "技能执行",
    "PIPELINE_RUN": "流水线运行",
    "APPROVAL": "审批",
    "ARTIFACT_EXPORT": "结果导出",
    "AGENT_REQUEST": "智能体任务",
}


def _kind_chinese(kind_name: str) -> str:
    if not kind_name:
        return "通用"
    return _KIND_LABELS.get(kind_name.upper(), kind_name.lower())


def _enum_name(value: Any) -> Optional[str]:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    raw = str(value)
    return raw.rsplit(".", 1)[-1]


def _get_project_id(job: Any) -> Optional[str]:
    metadata = getattr(job, "metadata", None)
    if isinstance(metadata, dict):
        candidate = metadata.get("project_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    direct = getattr(job, "project_id", None)
    if isinstance(direct, str) and direct:
        return direct
    return None


def _extract_agent_request_job(
    job: Any,
    *,
    job_id: str,
    session_id: str,
    status_name: str,
    project_id: Optional[str],
    source_route: str,
    error: Optional[str],
    workspace_id: str,
) -> Optional[CaptureCandidateArgs]:
    metadata = getattr(job, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
    request_id = str(metadata.get("agent_request_id") or job_id).strip()
    intent = str(metadata.get("intent") or "agent_request").strip()
    evidence_refs = _dict_list(metadata.get("evidence_refs"), limit=64)
    result_text = _agent_result_text(metadata)

    if status_name == "FAILED":
        err_text = error or str(getattr(job, "error", "") or "no error message captured")
        return CaptureCandidateArgs(
            workspace_id=workspace_id,
            source_type=CandidateSourceType.RUNTIME_JOB,
            source_id=f"agent:{request_id}:fail",
            source_summary=(
                f"agent_request · intent={intent} · session={session_id}"
                f" · status=failed"
            ),
            memory_type=CandidateMemoryType.TOOL_RELIABILITY,
            title=f"智能体任务失败: {_shorten(intent, 80)}",
            claim=_shorten(err_text, 280),
            future_use="记录智能体协作失败模式，未来处理同类 MCP/桌面协作任务时排查",
            confidence=0.55,
            project_id=project_id,
            source_route=source_route,
            evidence_refs=evidence_refs,
            risk_level=CandidateRiskLevel.MEDIUM,
        )

    if not result_text.strip() or not evidence_refs:
        return CaptureCandidateArgs(
            workspace_id=workspace_id,
            source_type=CandidateSourceType.RUNTIME_JOB,
            source_id=f"agent:{request_id}",
            source_summary=(
                f"agent_request · intent={intent} · session={session_id}"
                f" · status=completed · evidence_count={len(evidence_refs)}"
            ),
            memory_type=CandidateMemoryType.LITERATURE_PROCEDURE,
            title=f"智能体任务完成: {_shorten(intent, 80)}",
            claim="本次智能体任务已通过桌面运行时完成，可作为同类协作流程参考",
            future_use="未来需要 Codex/Claude 介入文献助手任务时，可复用该桌面运行时协作流程",
            confidence=0.6,
            project_id=project_id,
            source_route=source_route,
            evidence_refs=evidence_refs,
            risk_level=CandidateRiskLevel.LOW,
        )

    return CaptureCandidateArgs(
        workspace_id=workspace_id,
        source_type=CandidateSourceType.RUNTIME_JOB,
        source_id=f"agent:{request_id}",
        source_summary=(
            f"agent_request · intent={intent} · session={session_id}"
            f" · evidence_count={len(evidence_refs)}"
        ),
        memory_type=CandidateMemoryType.EVIDENCE_RULE,
        title=f"智能体证据结论: {_shorten(intent, 80)}",
        claim=_shorten(result_text, 280),
        future_use=(
            f"未来处理 “{_shorten(intent, 60)}” 类问题且命中相同证据时，"
            "该智能体结论可作为候选参考"
        ),
        confidence=0.68,
        project_id=project_id,
        source_route=source_route,
        evidence_refs=evidence_refs,
        risk_level=CandidateRiskLevel.LOW,
    )


def _agent_result_text(metadata: dict[str, Any]) -> str:
    result = metadata.get("agent_result")
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("text", "summary", "claim", "answer"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _dict_list(value: Any, *, limit: int) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs: List[Dict[str, Any]] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            refs.append(dict(item))
    return refs


def _shorten(text: str, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
