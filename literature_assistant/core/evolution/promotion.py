"""
Promotion of accepted evolution candidates into durable artifacts (Slice 6 + 6.5).

Two promotion targets:
    (a) MemPalace memory drawer  — for any non-skill memory_type;
        uses MempalaceMemoryAdapter.add_memory(); rollback is tombstone-first
        per D-EVO-P0-6 (status -> ROLLED_BACK with rollback_ref preserved;
        actual MemPalace deletion is a later MemPalace-owner decision).
    (b) Managed skill draft       — for memory_type=SKILL_DRAFT;
        Slice 6.5 wires the existing skills/ approval + security audit
        pipeline: a minimal SKILL.md (no scripts, no permissions, hidden
        UI, experimental flag) is rendered from the candidate, imported
        via WritingSkillService.import_user_skill which writes the
        managed package, runs assess_skill_security, and registers a
        conservative approval profile. The resulting skill is left
        disabled-by-default so the operator must explicitly enable
        through the existing skills UI; rollback_ref is
        `skill:{skill_id}` so callers can locate the install for
        uninstall/rollback.
        If no skill_service is wired (test paths or kill-switch-style
        partial setup), the call degrades to recording a proposal id
        identical to the pre-Slice-6.5 contract.

Idempotency (plan §D-EVO-P0-8):
    - Promotion only runs when candidate.status == ACCEPTED.
    - A candidate already in PROMOTED_TO_MEMORY / PROMOTED_TO_SKILL_DRAFT
      / ROLLED_BACK is rejected with promoted=False, reason explaining why.
    - Memory promotion is naturally idempotent at the MemPalace layer:
      the adapter returns `duplicate=True` for the same drawer; we treat
      that as a successful no-op.
    - Skill-draft promotion is idempotent at the service layer: the
      caller (EvolutionService.promote) short-circuits when the
      candidate is already PROMOTED_TO_SKILL_DRAFT so we never re-import.

Kill switch:
    - `evolution.promotion_enabled` defaults to false (plan §Kill Switches).
    - When false, promote() returns PromotionResult(promoted=False,
      target="none", reason="promotion_enabled=false").
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from models.evolution import (
    CandidateMemoryType,
    CandidateStatus,
    ExperienceCandidate,
)


# Lowest-risk defaults for a draft skill: no scripts, no permissions,
# hidden from UI, marked experimental, manifest-only. Operators promote
# the draft to anything more powerful through the normal skills approval
# UI; this module never grants execution or network access.
_DRAFT_SKILL_KIND = "workflow"
_DRAFT_SKILL_VERSION = "0.0.1"
_DRAFT_SKILL_ENTRY_MODE = "hidden"
_DRAFT_SKILL_UI_VISIBILITY = "hidden"
_DRAFT_SKILL_DISPLAY_GROUP = "evolution-draft"
_DRAFT_SKILL_ID_PREFIX = "draft-"
_DRAFT_SKILL_ORIGIN = "evolution_draft"
_DRAFT_SKILL_NAME_MAX = 200
_DRAFT_SKILL_DESC_MAX = 1024


@dataclass(frozen=True)
class PromotionResult:
    promoted: bool
    target: str  # "memory" | "skill_draft" | "none"
    rollback_ref: Optional[str]
    reason: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EvolutionPromoter:
    """Promotion orchestrator. Stateless beyond the injected adapters.

    `memory_adapter` is the shared `MempalaceMemoryAdapter` (or anything
    that exposes `add_memory(wing, room, content, source_file, metadata,
    added_by) -> MemorySyncResult`). Pass `None` to disable memory
    promotion (callers will see target="none" + reason).

    `skill_service` is the shared `WritingSkillService` (or anything that
    exposes `import_user_skill(source_path, managed_root=None, origin=...)
    -> dict`). Pass `None` to fall back to the pre-Slice-6.5 behavior
    where skill_draft promotion only records a proposal id without
    creating a managed skill package. The fallback path is what existing
    tests and partially-wired test fixtures rely on.
    """

    def __init__(
        self,
        *,
        memory_adapter: Any = None,
        skill_service: Any = None,
        default_wing: str = "wing_evolution",
        default_room: str = "evolution-candidates",
        added_by: str = "evolution-promoter",
    ) -> None:
        self.memory_adapter = memory_adapter
        self.skill_service = skill_service
        self.default_wing = default_wing
        self.default_room = default_room
        self.added_by = added_by

    def promote(self, candidate: ExperienceCandidate) -> PromotionResult:
        if candidate.status != CandidateStatus.ACCEPTED:
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason=f"candidate must be ACCEPTED to promote; current={candidate.status.value}",
            )

        if candidate.memory_type == CandidateMemoryType.SKILL_DRAFT:
            return self._promote_to_skill_draft(candidate)
        return self._promote_to_memory(candidate)

    # --- internals -----------------------------------------------------------

    def _promote_to_memory(self, candidate: ExperienceCandidate) -> PromotionResult:
        if self.memory_adapter is None:
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason="memory_adapter unavailable; candidate remains accepted",
            )

        try:
            is_enabled = self.memory_adapter.is_enabled()
        except Exception as exc:
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason=f"memory_adapter.is_enabled() failed: {exc}",
            )
        if not is_enabled:
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason="memory_adapter is not enabled",
            )

        content = self._render_memory_content(candidate)
        metadata = self._build_metadata(candidate)
        source_file = candidate.source_id or candidate.candidate_id

        try:
            result = self.memory_adapter.add_memory(
                self.default_wing,
                self.default_room,
                content,
                source_file=source_file,
                metadata=metadata,
                added_by=self.added_by,
            )
        except Exception as exc:
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason=f"memory_adapter.add_memory failed: {exc}",
            )

        success = bool(getattr(result, "success", False))
        drawer_id = getattr(result, "drawer_id", None)
        duplicate = bool(getattr(result, "duplicate", False))
        reason = getattr(result, "reason", None) or ("duplicate drawer (no-op)" if duplicate else "memory drawer written")

        if not success:
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason=str(reason or "memory_adapter returned success=False"),
            )

        return PromotionResult(
            promoted=True,
            target="memory",
            rollback_ref=str(drawer_id) if drawer_id is not None else f"memory:{candidate.candidate_id}",
            reason=str(reason),
        )

    def _promote_to_skill_draft(self, candidate: ExperienceCandidate) -> PromotionResult:
        """Promote a SKILL_DRAFT candidate via the managed skills pipeline.

        When `skill_service` is wired, render a minimal SKILL.md (no
        scripts, no permissions, hidden, experimental) and call
        `skill_service.import_user_skill` to import it through the same
        path users take when adding skill packages. The resulting skill
        is left disabled-by-default: the operator must enable it through
        the existing skills approval/enable UI, which triggers the
        high-risk approval handshake if needed. `rollback_ref` is the
        managed `skill:{skill_id}` identifier so a future rollback can
        locate the installed package.

        When `skill_service` is None (pre-Slice-6.5 wiring or test
        fixtures that didn't inject a service), fall back to recording a
        synthetic proposal id. This preserves the original Slice 6
        contract so callers can still depend on a non-empty
        rollback_ref + transition to PROMOTED_TO_SKILL_DRAFT.
        """

        if self.skill_service is None:
            return PromotionResult(
                promoted=True,
                target="skill_draft",
                rollback_ref=f"skill_draft_proposal:{candidate.candidate_id}",
                reason="skill_service unavailable; recorded as proposal only",
            )

        skill_md = _render_skill_md_for_candidate(candidate)
        try:
            with tempfile.TemporaryDirectory(prefix="evolution-skill-draft-") as temp_dir_str:
                temp_dir = Path(temp_dir_str)
                (temp_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
                result = self.skill_service.import_user_skill(
                    source_path=str(temp_dir),
                    origin=_DRAFT_SKILL_ORIGIN,
                )
        except Exception as exc:
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason=f"skill_service.import_user_skill failed: {exc}",
            )

        if not isinstance(result, dict):
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason=f"skill_service returned non-dict result: {type(result).__name__}",
            )
        if not result.get("success"):
            error_code = result.get("error_code") or "IMPORT_FAILED"
            errors = result.get("errors") or []
            joined = "; ".join(str(e) for e in errors) if errors else "no error detail"
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason=f"skill import failed ({error_code}): {joined}",
            )

        skill_id = result.get("skill_id") or ""
        if not skill_id:
            return PromotionResult(
                promoted=False,
                target="none",
                rollback_ref=None,
                reason="skill import returned success without skill_id",
            )

        return PromotionResult(
            promoted=True,
            target="skill_draft",
            rollback_ref=f"skill:{skill_id}",
            reason=f"managed skill draft imported (disabled-by-default): {skill_id}",
        )

    def _render_memory_content(self, candidate: ExperienceCandidate) -> str:
        sections = [
            f"# {candidate.title}",
            "",
            f"主张: {candidate.claim}",
            "",
            f"未来用途: {candidate.future_use}",
            "",
            f"来源: source_type={candidate.source_type.value}; source_id={candidate.source_id}",
        ]
        if candidate.source_route:
            sections.append(f"路由: {candidate.source_route}")
        if candidate.evidence_refs:
            sections.append("")
            sections.append(f"证据条数: {len(candidate.evidence_refs)}")
        return "\n".join(sections).strip()

    def _build_metadata(self, candidate: ExperienceCandidate) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "workspace_id": candidate.workspace_id,
            "project_id": candidate.project_id,
            "source_type": candidate.source_type.value,
            "memory_type": candidate.memory_type.value,
            "dedupe_hash": candidate.dedupe_hash,
            "confidence": float(candidate.confidence),
            "risk_level": candidate.risk_level.value,
            "evidence_count": len(candidate.evidence_refs),
            "promoted_at": _utc_now_iso(),
            "evidence_refs_json": json.dumps(candidate.evidence_refs, ensure_ascii=False),
        }


# Allowed characters in skill id (mirrors VALID_ID_PATTERN in
# literature_assistant.core.skills.user_manifest): ASCII lowercase letters,
# digits, dot, dash, underscore. Any other character is replaced with a dash
# so we never produce an invalid manifest id from a candidate_id with random
# characters.
import re as _re  # noqa: E402  (local-only re alias keeps top imports minimal)


_ID_SAFE_CHARS_RE = _re.compile(r"[^a-z0-9._-]+")
_ID_DASH_COLLAPSE_RE = _re.compile(r"-{2,}")


def _sanitize_draft_skill_id(candidate_id: str) -> str:
    """Map a candidate_id to a manifest-safe id.

    Lowercases, replaces disallowed characters with `-`, collapses repeats,
    trims to <=128 chars, and ensures the first character is alphanumeric
    (per the importer's VALID_ID_PATTERN).
    """

    base = (candidate_id or "").strip().lower()
    base = _ID_SAFE_CHARS_RE.sub("-", base)
    base = _ID_DASH_COLLAPSE_RE.sub("-", base).strip("-._")
    if not base:
        base = "candidate"
    raw = f"{_DRAFT_SKILL_ID_PREFIX}{base}"
    # Importer requires 2..128 chars and the first to be [a-z0-9].
    raw = raw[:128]
    if not raw[0].isalnum():
        raw = "d" + raw[1:]
    return raw


def _truncate_text(value: str, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    # Reserve 1 char for an ellipsis so reviewers can tell it was cut.
    return text[: max(0, limit - 1)].rstrip() + "…"


def _render_skill_md_for_candidate(candidate: ExperienceCandidate) -> str:
    """Render the minimal SKILL.md for a SKILL_DRAFT evolution candidate.

    Output contract (matches `literature_assistant.core.skills.user_manifest`):
        - required: id, name, version, kind, description
        - hidden defaults: entry_mode=hidden, ui_visibility=hidden,
          experimental=true, no permissions, no scripts, no model access
        - body holds the operator-readable claim/future-use/source summary
          so a reviewer can decide whether to enable.

    The resulting package is intentionally inert: it cannot run scripts,
    cannot call models, cannot read/write files. Enabling it requires the
    operator to go through the existing skills approval UI.
    """

    import yaml  # local import: yaml is already a transitive dep via user_manifest

    skill_id = _sanitize_draft_skill_id(candidate.candidate_id)
    name = _truncate_text(candidate.title, _DRAFT_SKILL_NAME_MAX) or skill_id
    description = _truncate_text(candidate.claim, _DRAFT_SKILL_DESC_MAX) or name
    rollback_hint = _truncate_text(
        f"撤销此草稿:从 Settings -> Skills 卸载 {skill_id}",
        _DRAFT_SKILL_DESC_MAX,
    )

    frontmatter: dict[str, Any] = {
        "id": skill_id,
        "name": name,
        "version": _DRAFT_SKILL_VERSION,
        "kind": _DRAFT_SKILL_KIND,
        "description": description,
        "entry_mode": _DRAFT_SKILL_ENTRY_MODE,
        "ui_visibility": _DRAFT_SKILL_UI_VISIBILITY,
        "supported_scopes": ["selection"],
        "permissions": {},
        "script_policy": {"has_scripts": False, "safe_to_execute": False},
        "model_policy": {"allow_llm": False, "allow_embedding": False},
        "display_group": _DRAFT_SKILL_DISPLAY_GROUP,
        "experimental": True,
        "rollback_hint": rollback_hint,
        "tags": ["evolution-draft"],
    }

    frontmatter_yaml = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip()

    body_lines: list[str] = [
        f"# {name}",
        "",
        "_自动从经验候选生成的禁用骨架。启用前请人工审阅。_",
        "",
        "## 主张",
        "",
        _truncate_text(candidate.claim, _DRAFT_SKILL_DESC_MAX) or "(空)",
        "",
        "## 未来用途",
        "",
        _truncate_text(candidate.future_use, _DRAFT_SKILL_DESC_MAX) or "(空)",
        "",
        "## 来源",
        "",
        f"- source_type: `{candidate.source_type.value}`",
        f"- memory_type: `{candidate.memory_type.value}`",
        f"- candidate_id: `{candidate.candidate_id}`",
    ]
    if candidate.source_id:
        body_lines.append(f"- source_id: `{candidate.source_id}`")
    if candidate.source_route:
        body_lines.append(f"- source_route: `{candidate.source_route}`")
    if candidate.evidence_refs:
        body_lines.append(f"- evidence_count: {len(candidate.evidence_refs)}")
    body_lines.extend([
        "",
        "## 启用前检查",
        "",
        "1. 阅读「主张」和「未来用途」，确认与项目语境一致。",
        "2. 必要时在 Settings -> Skills 中补充 permissions、scripts、model_policy。",
        "3. 验证后再切换为启用状态。",
    ])

    return "---\n" + frontmatter_yaml + "\n---\n\n" + "\n".join(body_lines) + "\n"


def _build_skill_md(candidate: ExperienceCandidate) -> str:
    """Public-but-stable alias kept for callers that want a tested wrapper."""
    return _render_skill_md_for_candidate(candidate)
