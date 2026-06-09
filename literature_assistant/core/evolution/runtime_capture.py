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


def _shorten(text: str, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
