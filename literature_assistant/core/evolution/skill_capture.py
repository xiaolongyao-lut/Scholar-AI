"""
Pure-function candidate extraction for skill execution results.

Maps `SkillRunResult` (literature_assistant.core.skills.runtime.SkillRunResult)
to the kwargs `EvolutionService.capture()` needs. Called from
`writing_runtime.WritingRuntime._finalize_executor_result` after the skill
result is normalized but before the job lifecycle transitions to terminal
state.

Two candidate types:
    SUCCESS / PARTIAL → memory_type=SKILL_DRAFT
        Captures the skill+input+output as a candidate that could later be
        promoted into a managed disabled skill draft.
    FAILED / TIMEOUT / CANCELLED → memory_type=TOOL_RELIABILITY
        Captures the failure so future runs of the same skill can be
        compared against this reliability lesson.

For skill drafts, v1 captures every success; reviewers decide which to promote.
Deduplication (skill_id + normalized input) keeps the queue clean.

Promotion is handled by the promoter. This module only captures the draft proposal.
"""

from __future__ import annotations

from typing import Any, Optional

from models.evolution import (
    CandidateMemoryType,
    CandidateRiskLevel,
    CandidateSourceType,
)
from evolution._capture_args import CaptureCandidateArgs


def extract_from_skill_run(
    result: Any,
    *,
    job: Any = None,
    workspace_id: str = "default",
) -> Optional[CaptureCandidateArgs]:
    """Return capture-args payload from a SkillRunResult, or None if skipped.

    `result` is duck-typed against SkillRunResult:
        job_id, skill_id, status (.value), input_text, output_text,
        warnings, evidence_refs (list[dict]), metadata
    `status` must expose .value or have a string repr ending in a known name.
    """

    if result is None:
        return None

    job_id = getattr(result, "job_id", None)
    skill_id = getattr(result, "skill_id", None)
    if not (job_id and skill_id):
        return None

    status_name = _status_name(result)
    if status_name not in {"SUCCESS", "PARTIAL", "FAILED", "TIMEOUT", "CANCELLED"}:
        return None

    project_id = _project_id_from_job(job)
    input_text = getattr(result, "input_text", "") or ""
    output_text = getattr(result, "output_text", "") or ""
    warnings = list(getattr(result, "warnings", None) or [])
    evidence_refs = list(getattr(result, "evidence_refs", None) or [])

    if status_name in {"SUCCESS", "PARTIAL"}:
        memory_type = CandidateMemoryType.SKILL_DRAFT
        title = f"skill_draft: {skill_id}"
        claim = _shorten(
            f"输入: {_shorten(input_text, 1500)}\n→\n输出: {_shorten(output_text, 2000)}",
            4000,
        )
        future_use = (
            f"若 skill {skill_id} 在同类输入上多次成功，可酝酿为 disabled "
            f"skill draft 供审阅后启用"
        )
        confidence = 0.7 if status_name == "SUCCESS" else 0.55
        risk_level = CandidateRiskLevel.MEDIUM  # skill drafts touch execution policy
        source_id = f"skill:{job_id}"
    else:
        memory_type = CandidateMemoryType.TOOL_RELIABILITY
        title = f"skill 失败: {skill_id}"
        # FAILED skills surface their output_text or warning chain as the
        # diagnostic claim — mirrors the message _finalize_executor_result
        # uses when calling fail_job.
        diag = (
            output_text
            or "; ".join(warnings)
            or f"skill execution {status_name.lower()}"
        )
        claim = _shorten(diag, 4000)
        future_use = (
            f"记录 skill {skill_id} 的失败模式（{status_name.lower()}），"
            f"未来排查类似失败时参考"
        )
        confidence = 0.5
        risk_level = CandidateRiskLevel.MEDIUM
        source_id = f"skill:{job_id}:fail"

    return CaptureCandidateArgs(
        workspace_id=workspace_id,
        source_type=CandidateSourceType.SKILL_RUN,
        source_id=source_id,
        source_summary=(
            f"skill_run · skill={skill_id} · status={status_name.lower()}"
            f" · evidence_count={len(evidence_refs)}"
        ),
        memory_type=memory_type,
        title=title,
        claim=claim,
        future_use=future_use,
        confidence=confidence,
        project_id=project_id,
        source_route=f"/runtime/job/{job_id}/skill",
        evidence_refs=evidence_refs,
        risk_level=risk_level,
    )


# --- helpers -----------------------------------------------------------------

def _status_name(result: Any) -> str:
    status = getattr(result, "status", None)
    if status is None:
        return ""
    name = getattr(status, "name", None)
    if isinstance(name, str):
        return name
    raw = str(status)
    return raw.rsplit(".", 1)[-1].upper()


def _project_id_from_job(job: Any) -> Optional[str]:
    if job is None:
        return None
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
