"""
Runtime-related Pydantic models for REST API.

Includes models for writing sessions, jobs, events, and artifacts.
"""

from typing import Any, Dict, List, Literal, Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator


_MATERIAL_PROCESSING_PAGE_RANGE_MODES = {"all", "range", "pages"}
_MATERIAL_PROCESSING_ALLOWED_MODES = {
    "fast_text",
    "layout_aware",
    "ocr_fallback",
    "translation_sidecar",
}
_MATERIAL_PROCESSING_CACHE_POLICIES = {"use", "refresh", "bypass"}
_MATERIAL_PROCESSING_CACHE_DECISIONS = {"pending", "hit", "miss", "bypass", "refresh", "invalidated"}
_MATERIAL_PROCESSING_OUTPUT_TARGETS = {
    "chunks",
    "locators",
    "figures",
    "tables",
    "layout_sidecar",
    "text_sidecar",
    "bilingual_sidecar",
    "docx",
    "evidence_refs",
}


class TaskState(str, Enum):
    """Lifecycle state for background pipeline tasks."""

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class CreateSessionRequest(BaseModel):
    """Request to create a writing session."""

    mode: str  # "prompt", "skill", "hybrid"
    user_id: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    workspace_root: Optional[str] = None
    entry_cwd: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionPayload(BaseModel):
    """Writing session response."""

    session_id: str
    user_id: Optional[str]
    mode: str
    created_at: str
    settings: Dict[str, Any]
    tags: List[str]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreateJobRequest(BaseModel):
    """Request to create a job in a session."""

    session_id: str
    kind: str  # "prompt_action", "skill_action", "pipeline_run", etc.
    input_text: str = ""
    action_id: Optional[str] = None
    skill_id: Optional[str] = None
    scope: Optional[str] = None
    output_mode: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobPayload(BaseModel):
    """Job response payload."""

    job_id: str
    session_id: str
    kind: str
    status: str
    input_text: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    action_id: Optional[str] = None
    skill_id: Optional[str] = None
    error: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    writing_workflow_state_summary: Dict[str, Any] = Field(default_factory=dict)
    material_processing_task_summary: Dict[str, Any] = Field(default_factory=dict)


class JobStatusPayload(BaseModel):
    """Detailed job status response."""

    job_id: str
    session_id: str
    status: str
    kind: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    is_paused: bool
    is_cancelled: bool
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventPayload(BaseModel):
    """Event response payload."""

    event_id: str
    job_id: str
    session_id: str
    event_type: str
    timestamp: str
    sequence: int = Field(ge=0)
    data: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobEventSnapshotPayload(BaseModel):
    """Refresh-safe job snapshot plus cursor-paginated event page."""

    job_id: str
    session_id: str
    job: JobPayload
    status: JobStatusPayload
    events: List[EventPayload] = Field(default_factory=list)
    next_after_sequence: Optional[int] = None
    latest_sequence: int = Field(ge=0)
    has_more: bool = False


class ArtifactPayload(BaseModel):
    """Artifact response payload."""

    artifact_id: str
    job_id: str
    session_id: str
    artifact_type: str
    content: str | Dict[str, Any]
    created_at: str
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    mime_type: str = "application/json"


class WritingWorkflowStateRequest(BaseModel):
    """Request to persist a writing workflow-state snapshot for one runtime job."""

    phase: str = Field(min_length=1, max_length=120)
    intake: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    citation_bank: List[Dict[str, Any]] = Field(default_factory=list)
    lint_report: Dict[str, Any] = Field(default_factory=dict)
    export_manifest: Dict[str, Any] = Field(default_factory=dict)
    change_log: List[Dict[str, Any]] = Field(default_factory=list)


class WritingWorkflowStatePayload(BaseModel):
    """Writing workflow-state response payload."""

    schema_version: str
    job_id: str
    session_id: str
    phase: str
    updated_at: str
    intake: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    citation_bank: List[Dict[str, Any]] = Field(default_factory=list)
    lint_report: Dict[str, Any] = Field(default_factory=dict)
    export_manifest: Dict[str, Any] = Field(default_factory=dict)
    change_log: List[Dict[str, Any]] = Field(default_factory=list)
    readiness: Dict[str, bool] = Field(default_factory=dict)


class MaterialProcessingPageRangePayload(BaseModel):
    """Explicit page-selection contract for material processing."""

    mode: str = Field(default="all", min_length=1, max_length=40)
    start_page: Optional[int] = Field(default=None, ge=1)
    end_page: Optional[int] = Field(default=None, ge=1)
    pages: List[int] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in _MATERIAL_PROCESSING_PAGE_RANGE_MODES:
            raise ValueError(f"mode must be one of {sorted(_MATERIAL_PROCESSING_PAGE_RANGE_MODES)}")
        return normalized

    @field_validator("pages")
    @classmethod
    def _validate_pages(cls, value: List[int]) -> List[int]:
        pages = [int(page) for page in value]
        if any(page < 1 for page in pages):
            raise ValueError("pages must contain positive 1-based page numbers")
        return sorted(dict.fromkeys(pages))

    @model_validator(mode="after")
    def _validate_shape(self) -> "MaterialProcessingPageRangePayload":
        if self.mode == "range":
            if self.start_page is None or self.end_page is None:
                raise ValueError("range mode requires start_page and end_page")
            if self.end_page < self.start_page:
                raise ValueError("end_page must be greater than or equal to start_page")
        if self.mode == "pages" and not self.pages:
            raise ValueError("pages mode requires at least one page")
        return self


class MaterialProcessingPreservePayload(BaseModel):
    """Document features the processor should preserve or track."""

    formulas: bool = True
    tables: bool = True
    figures: bool = True
    citations: bool = True
    annotations: bool = True


class MaterialProcessingInputRefPayload(BaseModel):
    """Bounded local input reference for one material-processing task."""

    ref_type: str = Field(default="material", min_length=1, max_length=80)
    material_id: str = Field(min_length=1, max_length=200)
    source_path_label: Optional[str] = Field(default=None, max_length=500)
    content_digest: Optional[str] = Field(default=None, max_length=160)
    size_bytes: Optional[int] = Field(default=None, ge=0)

    @field_validator("ref_type", "material_id", "source_path_label", "content_digest", mode="before")
    @classmethod
    def _strip_optional_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        return str(value).strip()


class MaterialProcessingCachePayload(BaseModel):
    """Replay/cache identity and decision metadata."""

    policy: str = Field(default="use", min_length=1, max_length=40)
    content_digest: Optional[str] = Field(default=None, max_length=160)
    parameter_digest: Optional[str] = Field(default=None, max_length=160)
    cache_key: Optional[str] = Field(default=None, max_length=240)
    decision: str = Field(default="pending", min_length=1, max_length=40)
    decision_record: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("policy")
    @classmethod
    def _validate_policy(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in _MATERIAL_PROCESSING_CACHE_POLICIES:
            raise ValueError(f"policy must be one of {sorted(_MATERIAL_PROCESSING_CACHE_POLICIES)}")
        return normalized

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in _MATERIAL_PROCESSING_CACHE_DECISIONS:
            raise ValueError(f"decision must be one of {sorted(_MATERIAL_PROCESSING_CACHE_DECISIONS)}")
        return normalized

    @field_validator("content_digest", "parameter_digest", "cache_key", mode="before")
    @classmethod
    def _strip_optional_digest_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        return str(value).strip()


class MaterialProcessingArtifactPayload(BaseModel):
    """Typed artifact summary produced by a material-processing task."""

    artifact_type: str = Field(min_length=1, max_length=120)
    output_target: str = Field(min_length=1, max_length=120)
    count: Optional[int] = Field(default=None, ge=0)
    path: Optional[str] = Field(default=None, max_length=1000)
    digest: Optional[str] = Field(default=None, max_length=160)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("artifact_type", "output_target", "path", "digest", mode="before")
    @classmethod
    def _strip_artifact_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        return str(value).strip()

    @field_validator("output_target")
    @classmethod
    def _validate_output_target(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if normalized not in _MATERIAL_PROCESSING_OUTPUT_TARGETS:
            raise ValueError(f"output_target must be one of {sorted(_MATERIAL_PROCESSING_OUTPUT_TARGETS)}")
        return normalized


class MaterialProcessingTaskRequest(BaseModel):
    """Versioned request contract for resumable material processing."""

    schema_version: str = Field(default="material_processing_task_v1", min_length=1)
    project_id: str = Field(min_length=1, max_length=200)
    material_id: str = Field(min_length=1, max_length=200)
    input_ref: MaterialProcessingInputRefPayload
    page_range: MaterialProcessingPageRangePayload = Field(default_factory=MaterialProcessingPageRangePayload)
    processing_mode: str = Field(default="fast_text", min_length=1, max_length=80)
    language_in: Optional[str] = Field(default=None, max_length=40)
    language_out: Optional[str] = Field(default=None, max_length=40)
    preserve: MaterialProcessingPreservePayload = Field(default_factory=MaterialProcessingPreservePayload)
    provider_ref: Optional[str] = Field(default=None, max_length=200)
    cache: MaterialProcessingCachePayload = Field(default_factory=MaterialProcessingCachePayload)
    output_targets: List[str] = Field(default_factory=lambda: ["chunks"])
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if normalized != "material_processing_task_v1":
            raise ValueError("schema_version must be material_processing_task_v1")
        return normalized

    @field_validator("project_id", "material_id", "processing_mode", "language_in", "language_out", "provider_ref", mode="before")
    @classmethod
    def _strip_request_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        return str(value).strip()

    @field_validator("processing_mode")
    @classmethod
    def _validate_processing_mode(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in _MATERIAL_PROCESSING_ALLOWED_MODES:
            raise ValueError(f"processing_mode must be one of {sorted(_MATERIAL_PROCESSING_ALLOWED_MODES)}")
        return normalized

    @field_validator("output_targets")
    @classmethod
    def _validate_output_targets(cls, value: List[str]) -> List[str]:
        targets = [str(item or "").strip() for item in value]
        if not targets:
            raise ValueError("output_targets must contain at least one target")
        invalid = [target for target in targets if target not in _MATERIAL_PROCESSING_OUTPUT_TARGETS]
        if invalid:
            raise ValueError(f"output_targets contains unsupported targets: {sorted(set(invalid))}")
        return list(dict.fromkeys(targets))

    @model_validator(mode="after")
    def _validate_input_ref(self) -> "MaterialProcessingTaskRequest":
        if self.input_ref.material_id != self.material_id:
            raise ValueError("input_ref.material_id must match material_id")
        return self


class MaterialProcessingTaskPayload(BaseModel):
    """Runtime-visible material-processing task record."""

    schema_version: str
    job_id: str
    session_id: str
    status: str
    created_at: str
    updated_at: str
    request: MaterialProcessingTaskRequest
    result: Dict[str, Any] = Field(default_factory=dict)
    cache: MaterialProcessingCachePayload = Field(default_factory=MaterialProcessingCachePayload)
    artifacts: List[MaterialProcessingArtifactPayload] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class ResearchObjectPayload(BaseModel):
    """Read-only research-domain object projected from runtime records."""

    object_id: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    status: str = Field(min_length=1)
    project_id: Optional[str] = None
    material_id: Optional[str] = None
    title: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    source_refs: List[Dict[str, Any]] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    state: Dict[str, Any] = Field(default_factory=dict)
    confirmation_boundary: Dict[str, Any] = Field(default_factory=dict)
    effects: Dict[str, Any] = Field(default_factory=dict)


class ResearchEventPayload(BaseModel):
    """CloudEvents/PROV-inspired event projection for research objects."""

    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    source: str = "scholar-ai.runtime"
    subject: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    job_id: Optional[str] = None
    timestamp: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    status: Optional[str] = None
    actor: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    confirmation_boundary: Dict[str, Any] = Field(default_factory=dict)


class ResearchProjectionPayload(BaseModel):
    """Read-only research object/event projection over runtime state."""

    schema_version: str
    generated_at: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    objects: List[ResearchObjectPayload] = Field(default_factory=list)
    events: List[ResearchEventPayload] = Field(default_factory=list)
    approval_boundaries: List[Dict[str, Any]] = Field(default_factory=list)
    status_projection: Dict[str, Any] = Field(default_factory=dict)


class WorkflowPassportGatePayload(BaseModel):
    """Stage gate summary for reproducible research workflow state.

    Args:
        gate_id: Stable gate identifier scoped by stage id.
        status: Gate state; unresolved must not be rendered as passed.
        severity: UI/MCP severity for blocking, warning, or note-level items.
        reason: Human-readable bounded reason for the status.
        evidence: Bounded refs to runtime objects, events, artifacts, or tasks.
        blockers: Items that must be resolved before the stage can be complete.
        unresolved: Checks that still need human, offline, or external review.
        requires_user_confirmation: Whether a pending approval blocks progress.
    """

    gate_id: str = Field(min_length=1, max_length=160)
    status: Literal["pass", "warn", "block", "unresolved", "not_applicable"] = "unresolved"
    severity: Literal["none", "note", "warn", "block"] = "note"
    reason: str = Field(min_length=1, max_length=500)
    evidence: List[Dict[str, Any]] = Field(default_factory=list, max_length=16)
    blockers: List[str] = Field(default_factory=list, max_length=12)
    unresolved: List[str] = Field(default_factory=list, max_length=12)
    requires_user_confirmation: bool = False


class WorkflowPassportStagePayload(BaseModel):
    """Read-only stage ledger row for the research workflow passport.

    Args:
        stage_id: Scholar AI workflow stage id.
        label: User-facing short label.
        status: Stage progress derived from existing runtime state.
        required_artifacts: Artifact families expected for a reproducible stage.
        present_artifacts: Bounded runtime/material artifacts found locally.
        object_ids: Research object ids that provide this stage evidence.
        event_types: Domain events observed for this stage.
        gate: Integrity/reproducibility gate projection for this stage.
        diagnostics: Bounded quality counters and unresolved local facts.
        reproducibility: Parameter/cache/replay facts needed to re-run or audit.
        next_actions: Bounded local actions that can move the stage forward.
        updated_at: Latest timestamp observed for this stage.
    """

    stage_id: Literal[
        "material_ingest",
        "material_read",
        "evidence_pack",
        "outline",
        "draft",
        "citation_review",
        "export",
        "agent_handoff",
    ]
    label: str = Field(min_length=1, max_length=120)
    status: Literal["not_started", "in_progress", "complete", "warn", "blocked", "unresolved"]
    required_artifacts: List[str] = Field(default_factory=list, max_length=16)
    present_artifacts: List[Dict[str, Any]] = Field(default_factory=list, max_length=24)
    object_ids: List[str] = Field(default_factory=list, max_length=48)
    event_types: List[str] = Field(default_factory=list, max_length=48)
    gate: WorkflowPassportGatePayload
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    reproducibility: Dict[str, Any] = Field(default_factory=dict)
    next_actions: List[str] = Field(default_factory=list, max_length=12)
    updated_at: Optional[str] = None


class WorkflowPassportPayload(BaseModel):
    """Read-only workflow passport over runtime objects, events, and artifacts.

    Args:
        schema_version: Versioned additive API contract.
        generated_at: UTC generation time for this projection.
        scope: Runtime filters used to build the passport.
        stages: Ordered stage ledger rows.
        current_stage_id: First stage that is not complete, or final stage.
        gate_summary: Aggregate gate counts and blocking state.
        provenance: Sources used to derive this read-only passport.
    """

    schema_version: str = "scholar_ai_workflow_passport_v1"
    generated_at: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    stages: List[WorkflowPassportStagePayload] = Field(default_factory=list)
    current_stage_id: Optional[str] = None
    gate_summary: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class BlockingActionBoundaryRecoveryDrilldownPayload(BaseModel):
    """Bounded recovery row linking one boundary signal to local replay evidence.

    Args:
        signal_id: Evidence Integrity Gate signal that caused recovery work.
        category: Signal category used to find the owning workflow stage.
        status: Signal status at the time the boundary was derived.
        severity: Signal severity at the time the boundary was derived.
        message: Compact signal message for human inspection.
        linked_stage_id: Workflow Passport stage that should be rebuilt first.
        source_ref: Path-safe source digest and source-kind metadata.
        checked_facts: Bounded facts used to reproduce the signal decision.
        evidence_refs: Bounded evidence refs that support the signal.
        replay_refs: Replay or receipt refs that can reproduce the decision.
        recovery_refs: Cross-projection refs a resumed agent can inspect.
        local_read_only_probes: Safe GET probes to refresh records locally.
        next_safe_local_actions: Local-only actions that may unblock the signal.
        requires_human_review: Whether the signal must remain unresolved until review.
        blocks_claims: Whether the signal directly blocks readiness claims.
        read_only: Whether the drilldown adds only read-only recovery context.
        raw_path_exposed: Whether any raw local path was exposed.
    """

    signal_id: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, max_length=120)
    status: Optional[str] = Field(default=None, max_length=80)
    severity: Optional[str] = Field(default=None, max_length=80)
    message: Optional[str] = Field(default=None, max_length=600)
    linked_stage_id: Optional[str] = Field(default=None, max_length=120)
    source_ref: Dict[str, Any] = Field(default_factory=dict)
    checked_facts: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=12)
    replay_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=8)
    recovery_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=16)
    local_read_only_probes: List[Dict[str, Any]] = Field(default_factory=list, max_length=8)
    next_safe_local_actions: List[str] = Field(default_factory=list, max_length=8)
    requires_human_review: bool = False
    blocks_claims: bool = False
    read_only: bool = True
    raw_path_exposed: bool = False


class BlockingActionBoundaryPayload(BaseModel):
    """Read-only boundary between blocked workflow actions and safe local probes.

    Args:
        schema_version: Versioned additive projection contract.
        action_id: Local action being evaluated by the boundary.
        required_claim_id: Readiness claim that must be ready and fresh.
        status: Boundary state; unresolved or blocked must not be treated as pass.
        can_proceed: Whether local execution can continue without bypassing a gate.
        require_ready: Whether the action requires a ready claim.
        refresh_required: Whether source projections must be refreshed first.
        blocked_claims: Bounded claim rows explaining the action block.
        blockers: Blocking messages copied from gate and claim projections.
        unresolved: Review or stale-evidence messages that remain unresolved.
        blocked_signal_refs: Signal summaries that block the action.
        unresolved_signal_refs: Signal summaries that need refresh or review.
        recovery_drilldowns: Bounded signal-to-record recovery drilldowns.
        evidence_refs: Bounded evidence refs proving the boundary decision.
        local_read_only_probes: Safe GET probes for recovery before mutation.
        next_safe_local_actions: Local-only actions that may unblock the boundary.
        forbidden_actions: Actions that remain outside user authorization.
        provenance: Runtime sources used to derive this projection.
    """

    schema_version: Literal["scholar_ai_blocking_action_boundary_v1"] = (
        "scholar_ai_blocking_action_boundary_v1"
    )
    action_id: str = Field(min_length=1, max_length=160)
    required_claim_id: str = Field(min_length=1, max_length=160)
    status: Literal["ready", "unresolved", "blocked"]
    can_proceed: bool = False
    require_ready: bool = False
    refresh_required: bool = False
    blocked_claims: List[Dict[str, Any]] = Field(default_factory=list, max_length=8)
    blockers: List[str] = Field(default_factory=list, max_length=12)
    unresolved: List[str] = Field(default_factory=list, max_length=12)
    blocked_signal_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=8)
    unresolved_signal_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=8)
    recovery_drilldowns: List[BlockingActionBoundaryRecoveryDrilldownPayload] = Field(default_factory=list, max_length=8)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=12)
    local_read_only_probes: List[Dict[str, Any]] = Field(default_factory=list, max_length=8)
    next_safe_local_actions: List[str] = Field(default_factory=list, max_length=8)
    forbidden_actions: List[str] = Field(default_factory=list, max_length=8)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class EvidenceIntegritySignalPayload(BaseModel):
    """One reproducible integrity check signal for evidence-bound workflows.

    Args:
        signal_id: Stable signal id scoped by category and runtime source.
        category: Research-integrity area checked by the signal.
        status: Gate state; unresolved/offline checks must not be counted as pass.
        severity: UI/MCP severity used for blocking and review ordering.
        message: Bounded explanation of what the signal means.
        evidence: Bounded runtime refs or diagnostic excerpts, never full source text.
        next_actions: Local repair or review actions for this signal.
        metadata: JSON-safe counters and provenance details for repeatability.
        drilldown: Bounded checked facts and replay refs explaining this signal.
    """

    signal_id: str = Field(min_length=1, max_length=200)
    category: Literal[
        "locator",
        "retrieval_quality",
        "citation_verification",
        "citation_overlap",
        "writing_lint",
        "export_readiness",
        "behavior_eval",
        "workflow_stage",
        "approval_boundary",
    ]
    status: Literal["pass", "warn", "block", "unresolved", "not_applicable"] = "unresolved"
    severity: Literal["none", "note", "warn", "block"] = "note"
    message: str = Field(min_length=1, max_length=600)
    evidence: List[Dict[str, Any]] = Field(default_factory=list, max_length=16)
    next_actions: List[str] = Field(default_factory=list, max_length=8)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    drilldown: Dict[str, Any] = Field(default_factory=dict)


class EvidenceIntegrityGatePayload(BaseModel):
    """Read-only integrity gate over locators, citations, lint, and workflow state.

    Args:
        schema_version: Versioned additive API contract.
        generated_at: UTC generation time for this projection.
        scope: Runtime filters used to build this gate.
        status: Aggregate gate state; any block or unresolved signal prevents pass.
        signals: Ordered actionable integrity signals.
        summary: Counts and source coverage used by agents and UI panels.
        blockers: Block-level messages that should stop export or handoff claims.
        unresolved: Offline/human-review checks that must stay visibly unresolved.
        provenance: Read-only runtime sources used to derive the gate.
    """

    schema_version: Literal["scholar_ai_evidence_integrity_gate_v1"] = (
        "scholar_ai_evidence_integrity_gate_v1"
    )
    generated_at: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    status: Literal["pass", "warn", "block", "unresolved"]
    signals: List[EvidenceIntegritySignalPayload] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    blockers: List[str] = Field(default_factory=list, max_length=16)
    unresolved: List[str] = Field(default_factory=list, max_length=16)
    enforcement: Dict[str, Any] = Field(default_factory=dict)
    blocking_action_boundary: BlockingActionBoundaryPayload | None = None
    provenance: Dict[str, Any] = Field(default_factory=dict)


class ResearchActionLifecycleItemPayload(BaseModel):
    """One read-only action lifecycle row for auditable research workflow effects.

    Args:
        action_uid: Stable lifecycle-row id derived from local runtime evidence.
        action_id: Domain action name, such as ``agent.wiki_candidate``.
        action_type: Coarse action family used by UI and MCP clients.
        status: Lifecycle state derived from approval, preflight, and job state.
        project_id: Optional Scholar AI project scope.
        session_id: Runtime session that owns the action evidence.
        job_id: Runtime job that owns the action evidence.
        object_refs: Bounded research object refs affected by the action.
        approval: Approval request status and user-confirmation facts.
        preflight: Freshness and blocking facts from action preflight receipts.
        gate_refs: Workflow Passport and Evidence Integrity Gate refs.
        effect_summary: Expected/actual local effects without executing actions.
        effect_refs: Bounded artifact/wiki/graph/export refs created or proposed.
        recovery: Safe read-only probes and next local checks for this action.
        forbidden_actions: Mutations that remain outside this read-only boundary.
        provenance: Runtime sources used to derive the row.
    """

    action_uid: str = Field(min_length=1, max_length=220)
    action_id: str = Field(min_length=1, max_length=160)
    action_type: Literal[
        "wiki_candidate",
        "graph_patch",
        "export_overwrite",
        "batch_material_reprocess",
        "artifact_export",
        "agent_handoff",
        "approval_gate",
        "unknown",
    ] = "unknown"
    status: Literal[
        "proposed",
        "pending_approval",
        "approved",
        "rejected",
        "blocked",
        "unresolved",
        "completed",
        "failed",
        "cancelled",
    ] = "proposed"
    project_id: str | None = Field(default=None, max_length=200)
    session_id: str = Field(min_length=1, max_length=160)
    job_id: str = Field(min_length=1, max_length=160)
    object_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=24)
    approval: Dict[str, Any] = Field(default_factory=dict)
    preflight: Dict[str, Any] = Field(default_factory=dict)
    gate_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=16)
    effect_summary: Dict[str, Any] = Field(default_factory=dict)
    effect_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=24)
    recovery: Dict[str, Any] = Field(default_factory=dict)
    forbidden_actions: List[str] = Field(default_factory=list, max_length=8)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class ResearchActionLifecyclePayload(BaseModel):
    """Read-only projection over proposed, approved, blocked, and completed actions.

    Args:
        schema_version: Versioned additive API contract.
        generated_at: UTC generation time for this projection.
        scope: Runtime filters used to derive lifecycle rows.
        actions: Bounded action rows sorted by blocking priority and recency.
        summary: Aggregate counts and read-only guarantees.
        blockers: Blocking messages that stop action or readiness claims.
        unresolved: Review/offline checks that remain visibly unresolved.
        resume_probes: Safe local GET probes for resuming action review.
        provenance: Runtime projections and mature patterns used to derive rows.
    """

    schema_version: Literal["scholar_ai_research_action_lifecycle_v1"] = (
        "scholar_ai_research_action_lifecycle_v1"
    )
    generated_at: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    actions: List[ResearchActionLifecycleItemPayload] = Field(default_factory=list, max_length=100)
    summary: Dict[str, Any] = Field(default_factory=dict)
    blockers: List[str] = Field(default_factory=list, max_length=16)
    unresolved: List[str] = Field(default_factory=list, max_length=16)
    resume_probes: List[Dict[str, Any]] = Field(default_factory=list, max_length=12)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class BehaviorEvalCasePayload(BaseModel):
    """One deterministic behavior-eval case in the local MCP/agent suite.

    Args:
        case_id: Stable case id used in run records.
        category: Research workflow risk area covered by the case.
        severity: Expected actionability when the red flag appears.
        objective: Behavior invariant the local evaluator protects.
        red_flags: Observable failure shapes the case should catch.
        pass_criteria: Deterministic criterion used by the evaluator.
    """

    case_id: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=120)
    severity: Literal["warn", "block"]
    objective: str = Field(min_length=1, max_length=600)
    red_flags: List[str] = Field(default_factory=list, max_length=12)
    pass_criteria: str = Field(min_length=1, max_length=800)


class BehaviorEvalFindingPayload(BaseModel):
    """One red-flag finding emitted by a deterministic behavior evaluator.

    Args:
        finding_id: Stable finding id scoped by case and category.
        case_id: Behavior eval case that emitted this finding.
        category: Research workflow risk area covered by the finding.
        severity: Blocking or warning severity for workflow handoff.
        message: Bounded explanation of the behavior risk.
        evidence: Redacted diagnostic evidence, never raw secrets or full text.
        next_actions: Local repair or review actions for this finding.
    """

    finding_id: str = Field(min_length=1, max_length=220)
    case_id: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=120)
    severity: Literal["warn", "block"]
    message: str = Field(min_length=1, max_length=700)
    evidence: List[Dict[str, Any]] = Field(default_factory=list, max_length=16)
    next_actions: List[str] = Field(default_factory=list, max_length=8)


class BehaviorEvalResultPayload(BaseModel):
    """One behavior-eval observation result.

    Args:
        case_id: Evaluated case id or ad-hoc observation marker.
        observation_id: Stable bounded observation id.
        evaluation_goal: Whether the run expects canary red flags or safe behavior.
        behavior_status: Aggregate behavior result for the observation.
        structural_status: Canary structural result for evaluator health.
        red_flag_detected: Whether any red-flag finding was emitted.
        finding_count: Number of findings attached to the observation.
        findings: Redacted finding details.
    """

    case_id: str = Field(min_length=1, max_length=160)
    observation_id: str = Field(min_length=1, max_length=160)
    evaluation_goal: Literal["red_flag_detected", "behavior_safe"]
    behavior_status: Literal["pass", "warn", "block", "unresolved"]
    structural_status: Literal["pass", "fail", "not_applicable"]
    red_flag_detected: bool
    finding_count: int = Field(ge=0)
    findings: List[BehaviorEvalFindingPayload] = Field(default_factory=list, max_length=32)


class BehaviorEvalSummaryPayload(BaseModel):
    """Aggregate deterministic behavior-eval status.

    Args:
        case_count: Number of behavior cases registered in the suite.
        observation_count: Number of observations evaluated in the run.
        red_flag_count: Total findings emitted across observations.
        block_count: Observations whose highest severity is block.
        warn_count: Observations whose highest severity is warn.
        unresolved_count: Observations with insufficient behavior signal.
        structural_status: Canary structural health of the suite.
        behavior_status: Aggregate behavior status across observations.
        structural_note: Bounded explanation of structural-status semantics.
    """

    case_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    red_flag_count: int = Field(ge=0)
    block_count: int = Field(ge=0)
    warn_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    structural_status: Literal["pass", "fail", "not_applicable"]
    behavior_status: Literal["pass", "warn", "block", "unresolved"]
    structural_note: str = Field(min_length=1, max_length=400)


class BehaviorEvalPackPayload(BaseModel):
    """Read-only local behavior-eval pack for MCP/agent workflow red flags.

    Args:
        schema_version: Versioned additive API contract.
        generated_at: UTC generation time for the local eval run.
        mode: Canary or supplied-observation mode.
        summary: Aggregate structural and behavior status.
        results: Bounded per-observation eval results.
        blockers: Unique block-level messages that should stop overclaims.
        warnings: Unique warning messages for bounded follow-up.
        next_actions: Local repair or review actions suggested by findings.
        provenance: Local evaluator provenance and no-network guarantees.
        cases: Optional case manifest when requested by the caller.
        run_record: Optional local artifact pointer when a separate MCP tool
            explicitly persists a run; this read-only route does not write one.
    """

    schema_version: Literal["scholar_ai_behavior_eval_pack_v1"] = (
        "scholar_ai_behavior_eval_pack_v1"
    )
    generated_at: str
    mode: Literal["canary", "observations"]
    summary: BehaviorEvalSummaryPayload
    results: List[BehaviorEvalResultPayload] = Field(default_factory=list, max_length=100)
    blockers: List[str] = Field(default_factory=list, max_length=16)
    warnings: List[str] = Field(default_factory=list, max_length=16)
    next_actions: List[str] = Field(default_factory=list, max_length=16)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    cases: List[BehaviorEvalCasePayload] = Field(default_factory=list, max_length=32)
    run_record: Dict[str, Any] = Field(default_factory=dict)


class PreflightRefreshReceiptPayload(BaseModel):
    """Replay receipt for refreshed action-preflight workflow projections.

    Args:
        schema_version: Versioned additive contract for local replay evidence.
        receipt_id: Stable id derived from refreshed projection evidence.
        generated_at: UTC time when the refresh/replay receipt was generated.
        action_id: Local action whose preflight was refreshed.
        required_claim_id: Readiness claim evaluated for the action.
        scope: Runtime filters used to rebuild the projections.
        status: Action-preflight status after replay.
        can_proceed: Whether hard command execution may proceed.
        refresh_required: Whether the replay still reports stale/unknown inputs.
        projection_digests: Stable digests for rebuilt projections.
        projection_refs: Bounded refs to rebuilt projection outputs.
        freshness: Freshness diagnostics copied from action preflight.
        validation: Gate/checkpoint-like validation summary.
        replay: Local replay steps and mutation guarantees.
        provenance: Standards and runtime projections used to derive the receipt.
    """

    schema_version: Literal["scholar_ai_preflight_refresh_receipt_v1"] = (
        "scholar_ai_preflight_refresh_receipt_v1"
    )
    receipt_id: str = Field(min_length=1, max_length=200)
    generated_at: str
    action_id: str = Field(min_length=1, max_length=160)
    required_claim_id: str = Field(min_length=1, max_length=160)
    scope: Dict[str, Any] = Field(default_factory=dict)
    status: Literal["ready", "unresolved", "blocked", "stale"]
    can_proceed: bool
    refresh_required: bool
    projection_digests: Dict[str, str] = Field(default_factory=dict)
    projection_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=16)
    freshness: Dict[str, Any] = Field(default_factory=dict)
    validation: Dict[str, Any] = Field(default_factory=dict)
    replay: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class WorkflowReplayReceiptSummaryPayload(BaseModel):
    """Compact receipt row in a workflow replay lineage.

    Args:
        ordinal: 1-based position in the replay lineage after time ordering.
        receipt_id: Stable persisted receipt identifier.
        generated_at: UTC time when the receipt was generated.
        action_id: Local action whose preflight was refreshed.
        required_claim_id: Readiness claim evaluated for the action.
        status: Action-preflight status after replay.
        can_proceed: Whether the action was allowed by the receipt.
        refresh_required: Whether stale/unknown evidence still required refresh.
        blocker_count: Blocking checks reported by the receipt validation.
        unresolved_count: Unresolved checks reported by the receipt validation.
        digest_keys: Projection digest names present in this receipt.
        projection_digests: Bounded digest map for comparison.
        external_mutation: Whether the replay performed external mutation.
        source_material_mutation: Whether source material was mutated.
    """

    ordinal: int = Field(ge=1)
    receipt_id: str | None = Field(default=None, max_length=200)
    generated_at: str | None = None
    action_id: str | None = Field(default=None, max_length=160)
    required_claim_id: str | None = Field(default=None, max_length=160)
    status: Literal["ready", "unresolved", "blocked", "stale"] = "unresolved"
    can_proceed: bool = False
    refresh_required: bool = False
    blocker_count: int = Field(default=0, ge=0)
    unresolved_count: int = Field(default=0, ge=0)
    digest_keys: List[str] = Field(default_factory=list, max_length=16)
    projection_digests: Dict[str, str] = Field(default_factory=dict)
    external_mutation: bool = False
    source_material_mutation: bool = False


class WorkflowReplayLineagePayload(BaseModel):
    """Read-only replay lineage for one job's persisted workflow receipts.

    Args:
        schema_version: Versioned additive API contract.
        generated_at: UTC generation time for this lineage projection.
        job_id: Runtime job id that owns the receipts.
        session_id: Runtime session id for resume probes.
        project_id: Optional Scholar AI project recovered from runtime scope.
        scope: Runtime scope used for the projection.
        receipt_count: Total unique receipts found locally.
        returned_count: Number of compact receipt rows returned.
        latest_receipt_id: Latest receipt id after time ordering.
        latest: Compact summary of the latest receipt.
        previous: Compact summary of the previous receipt, if any.
        items: Bounded compact receipt rows in chronological order.
        comparison: Latest-vs-previous status/count/digest deltas.
        blockers: Blocking messages that should stop readiness claims.
        unresolved: Unresolved messages that must remain visible.
        resume_probes: Read-only calls agents should run before retrying.
        summary: Aggregate counts and read-only guarantees.
        provenance: Runtime sources and mature patterns used to derive lineage.
    """

    schema_version: Literal["scholar_ai_workflow_replay_lineage_v1"] = (
        "scholar_ai_workflow_replay_lineage_v1"
    )
    generated_at: str
    job_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    project_id: str | None = Field(default=None, max_length=200)
    scope: Dict[str, Any] = Field(default_factory=dict)
    receipt_count: int = Field(default=0, ge=0)
    returned_count: int = Field(default=0, ge=0)
    latest_receipt_id: str | None = Field(default=None, max_length=200)
    latest: Dict[str, Any] = Field(default_factory=dict)
    previous: Dict[str, Any] = Field(default_factory=dict)
    items: List[WorkflowReplayReceiptSummaryPayload] = Field(default_factory=list, max_length=50)
    comparison: Dict[str, Any] = Field(default_factory=dict)
    blockers: List[str] = Field(default_factory=list, max_length=8)
    unresolved: List[str] = Field(default_factory=list, max_length=8)
    resume_probes: List[Dict[str, Any]] = Field(default_factory=list, max_length=8)
    summary: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class WorkflowReplayIndexItemPayload(BaseModel):
    """Compact cross-job replay-index row for agent recovery.

    Args:
        ordinal: 1-based position after recovery-priority ordering.
        job_id: Runtime job that owns the replay receipts.
        session_id: Runtime session that owns the job.
        project_id: Optional Scholar AI project id recovered from scope.
        job_kind: Runtime job kind for scan context.
        job_status: Runtime job lifecycle state.
        session_title: Optional session title for human recovery.
        receipt_count: Unique receipts found for this job.
        latest_receipt_id: Latest receipt id after time ordering.
        latest_generated_at: Latest receipt timestamp.
        latest_status: Latest action preflight state.
        latest_action_id: Local action evaluated by the latest receipt.
        latest_required_claim_id: Readiness claim evaluated by the receipt.
        latest_can_proceed: Whether the latest receipt allowed action execution.
        latest_refresh_required: Whether refreshed projections are still stale.
        latest_blocker_count: Blocking checks reported by latest receipt.
        latest_unresolved_count: Unresolved checks reported by latest receipt.
        changed_digest_keys: Projection digest keys changed since prior receipt.
        comparison: Latest-vs-previous delta summary.
        recovery_priority: Deterministic ordering score for recovery triage.
        metadata_receipt_count: Receipt rows found in job metadata.
        artifact_receipt_count: Receipt artifacts found for the job.
        resume_probes: Read-only calls a resumed agent should run first.
        read_only: Whether this row was derived without mutation.
    """

    ordinal: int = Field(ge=1)
    job_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    project_id: str | None = Field(default=None, max_length=200)
    job_kind: str = Field(min_length=1, max_length=80)
    job_status: str = Field(min_length=1, max_length=80)
    session_title: str | None = Field(default=None, max_length=200)
    receipt_count: int = Field(default=0, ge=0)
    latest_receipt_id: str | None = Field(default=None, max_length=200)
    latest_generated_at: str | None = None
    latest_status: Literal["ready", "unresolved", "blocked", "stale"] = "unresolved"
    latest_action_id: str | None = Field(default=None, max_length=160)
    latest_required_claim_id: str | None = Field(default=None, max_length=160)
    latest_can_proceed: bool = False
    latest_refresh_required: bool = False
    latest_blocker_count: int = Field(default=0, ge=0)
    latest_unresolved_count: int = Field(default=0, ge=0)
    changed_digest_keys: List[str] = Field(default_factory=list, max_length=16)
    comparison: Dict[str, Any] = Field(default_factory=dict)
    recovery_priority: int = Field(default=0, ge=0)
    metadata_receipt_count: int = Field(default=0, ge=0)
    artifact_receipt_count: int = Field(default=0, ge=0)
    resume_probes: List[Dict[str, Any]] = Field(default_factory=list, max_length=8)
    read_only: bool = True


class WorkflowReplayIndexPayload(BaseModel):
    """Read-only project/session index over persisted workflow replay receipts.

    Args:
        schema_version: Versioned additive API contract.
        generated_at: UTC generation time for this index projection.
        scope: Runtime filters used to build the index.
        total_jobs_scanned: Runtime jobs scanned after session/project filters.
        total_receipts_seen: Unique receipts seen before status/action filters.
        matching_job_count: Jobs with receipts after status/action filters.
        returned_count: Bounded index rows returned.
        items: Recovery-prioritized replay index rows.
        blockers: Blocking messages that should stop readiness claims.
        unresolved: Unresolved messages that must remain visible.
        resume_probes: Read-only calls agents should run before retrying.
        summary: Aggregate counts and read-only guarantees.
        provenance: Runtime sources and mature patterns used to derive index.
    """

    schema_version: Literal["scholar_ai_workflow_replay_index_v1"] = (
        "scholar_ai_workflow_replay_index_v1"
    )
    generated_at: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    total_jobs_scanned: int = Field(default=0, ge=0)
    total_receipts_seen: int = Field(default=0, ge=0)
    matching_job_count: int = Field(default=0, ge=0)
    returned_count: int = Field(default=0, ge=0)
    items: List[WorkflowReplayIndexItemPayload] = Field(default_factory=list, max_length=50)
    blockers: List[str] = Field(default_factory=list, max_length=12)
    unresolved: List[str] = Field(default_factory=list, max_length=12)
    resume_probes: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    summary: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class AgentHandoffCardPayload(BaseModel):
    """Recoverable handoff card for one runtime-visible agent request.

    Args:
        schema_version: Versioned additive API contract.
        generated_at: UTC generation time for this card.
        request_id: Agent bridge request id when present.
        job_id: Runtime job id that owns the handoff card.
        session_id: Runtime session id used for resume probes.
        project_id: Optional project id recovered from job/session metadata.
        status: Terminal or current job lifecycle state.
        current_stage_id: Workflow passport stage that should be inspected next.
        completed_evidence: Bounded refs to completed runtime evidence.
        blockers: Block-level integrity or lifecycle messages.
        unresolved: Review/offline checks that must remain visible.
        readiness_claims: Gate-derived handoff/export readiness state.
        action_preflight: Read-only command preflight and refresh receipt used
            to decide whether the handoff can be trusted.
        action_lifecycle_recovery: Read-only research-action lifecycle refs a
            resumed agent should inspect before mutating local state.
        replay_recovery: Compact replay-index and lineage context a resumed
            agent should inspect before mutating local state.
        resource_refs: Bounded resource refs supplied to the delegated agent.
        artifacts: Bounded artifacts attached to the runtime job.
        resume_probes: Read-only calls a new agent should run before mutating.
        forbidden_actions: Actions that remain outside the local handoff boundary.
        resume_prompt: Compact instruction block for the next agent session.
        provenance: Runtime sources used to derive the card.
    """

    schema_version: Literal["scholar_ai_agent_handoff_card_v1"] = (
        "scholar_ai_agent_handoff_card_v1"
    )
    generated_at: str
    request_id: str | None = None
    job_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    project_id: str | None = Field(default=None, max_length=200)
    status: str = Field(min_length=1, max_length=80)
    agent_host: str | None = Field(default=None, max_length=80)
    intent: str | None = Field(default=None, max_length=160)
    current_stage_id: str | None = Field(default=None, max_length=120)
    completed_evidence: List[Dict[str, Any]] = Field(default_factory=list, max_length=24)
    blockers: List[str] = Field(default_factory=list, max_length=16)
    unresolved: List[str] = Field(default_factory=list, max_length=16)
    readiness_claims: Dict[str, Any] = Field(default_factory=dict)
    action_preflight: Dict[str, Any] = Field(default_factory=dict)
    action_lifecycle_recovery: Dict[str, Any] = Field(default_factory=dict)
    replay_recovery: Dict[str, Any] = Field(default_factory=dict)
    resource_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=50)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list, max_length=24)
    resume_probes: List[Dict[str, Any]] = Field(default_factory=list, max_length=16)
    forbidden_actions: List[str] = Field(default_factory=list, max_length=16)
    resume_prompt: str = Field(min_length=1, max_length=4000)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class TimelineItemPayload(BaseModel):
    """Append-only transcript event payload."""

    event_id: str
    session_id: str
    event_kind: str
    timestamp: str
    workspace_key: str
    payload: Dict[str, Any]
    parent_event_id: Optional[str] = None


class TimelinePagePayload(BaseModel):
    """Cursor-paginated transcript page."""

    session_id: str
    head_event_id: Optional[str] = None
    items: List[TimelineItemPayload] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class CheckpointPayload(BaseModel):
    """Checkpoint summary payload."""

    checkpoint_id: str
    session_id: str
    event_id: str
    created_at: str
    kind: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    active: bool = False


class ResumeSessionPayload(BaseModel):
    """Session resume response payload."""

    session: SessionPayload
    head_event_id: Optional[str] = None
    head_checkpoint_id: Optional[str] = None
    timeline: List[TimelineItemPayload] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class RewindSessionRequest(BaseModel):
    """Request to rewind a session to a checkpoint."""

    checkpoint_id: str
    mode: str = "conversation_only"


class ForkSessionRequest(BaseModel):
    """Request to fork a session from a checkpoint."""

    checkpoint_id: str
    title: Optional[str] = None


class SkillRunResultPayload(BaseModel):
    """Transform result payload returned to the frontend."""

    jobId: str
    actionId: str
    skillId: str
    inputText: str
    outputText: str
    scope: str
    outputMode: str
    createdAt: str
    applied: bool
