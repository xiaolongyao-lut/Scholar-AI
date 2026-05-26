"""
Centralized Pydantic models for python_adapter_server.

All request/response models are consolidated here for easier maintenance and discovery.
"""

# Common models (error envelopes, pagination, streaming)
from .common import (
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    PaginationMeta,
    PaginatedResponse,
    paginate,
    SuccessResponse,
    MessageResponse,
    ChatStreamEvent,
    ChatStreamDelta,
)

# Autopilot models
from .autopilot import (
    AutopilotStatusResponse,
    AutopilotEnableRequest,
    AutopilotPolicySetRequest,
    AutopilotEmergencyActionRequest,
    PolicyInfo,
    EventLogEntry,
)

# Pipeline models
from .pipeline import (
    PipelineRequest,
    PipelineTaskSubmitResponse,
    PipelineTaskStatusResponse,
    BatchProcessRequest,
)

# Skills models
from .skills import (
    SkillCompatibilityPayload,
    ScriptPolicyPayload,
    SkillDescriptorPayload,
    SkillSecurityAssessmentPayload,
    SkillPackPayload,
    CapabilityPayload,
    WritingActionPayload,
    RunActionRequest,
    RunActionAcceptedPayload,
    ImportUserSkillRequest,
    ImportUserSkillManifestPayload,
    ImportUserSkillResponse,
    SkillToggleResponse,
    SkillTestRunResponse,
    SkillApprovalRequestCreate,
    SkillApprovalRequestPayload,
    SkillApprovalDecisionCreate,
    SkillApprovalDecisionPayload,
    SkillApprovalDetailPayload,
    SkillUninstallResponse,
    SkillRollbackRequest,
    SkillRollbackResponse,
    SkillExportResponse,
)

# Runtime models
from .runtime import (
    TaskState,
    CreateSessionRequest,
    SessionPayload,
    CreateJobRequest,
    JobPayload,
    JobStatusPayload,
    EventPayload,
    ArtifactPayload,
    TimelineItemPayload,
    TimelinePagePayload,
    CheckpointPayload,
    ResumeSessionPayload,
    RewindSessionRequest,
    ForkSessionRequest,
    SkillRunResultPayload,
)

# Memory models
from .memory import (
    MemoryStatusPayload,
    MemorySearchRequest,
    MemorySearchHitPayload,
    MemorySearchResponsePayload,
    MemoryWakeupPayload,
    MemorySyncPayload,
)

# Resources models
from .resources import (
    ProjectPayload,
    SectionPayload,
    MaterialPayload,
    FigureTableCandidatePayload,
    DraftPayload,
    RevisionPayload,
    ProjectExportEvidenceProvenancePayload,
    ProjectExportEvidenceRowPayload,
    ProjectExportCitationChainPayload,
    ProjectExportReviewFindingPayload,
    ProjectExportPayload,
    AssociationSignalPayload,
    AssociationAnglePayload,
    EvidenceGapPayload,
    WritingAssociationPayload,
    CreateProjectRequest,
    CreateSectionRequest,
    CreateMaterialRequest,
    CreateDraftRequest,
    SaveDraftRequest,
    BuildAssociationRequest,
)

# Recovery models
from .recovery import (
    RecoveryEventPayload,
    EventTimelinePayload,
    MemoryFactPayload,
    MemorySnapshotPayload,
    InvalidFactRequest,
    FactInvalidationPayload,
    EventFilterPayload,
    TimelineQueryRequest,
    TimelineQueryResponse,
    RecommendationEvidencePayload,
    RecoveryRecommendationPayload,
    RecommendationsResponsePayload,
)

__all__ = [
    # Common
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "PaginationMeta",
    "PaginatedResponse",
    "paginate",
    "SuccessResponse",
    "MessageResponse",
    "ChatStreamEvent",
    "ChatStreamDelta",
    # Autopilot
    "AutopilotStatusResponse",
    "AutopilotEnableRequest",
    "AutopilotPolicySetRequest",
    "AutopilotEmergencyActionRequest",
    "PolicyInfo",
    "EventLogEntry",
    # Pipeline
    "PipelineRequest",
    "PipelineTaskSubmitResponse",
    "PipelineTaskStatusResponse",
    # Skills
    "SkillCompatibilityPayload",
    "ScriptPolicyPayload",
    "SkillDescriptorPayload",
    "SkillSecurityAssessmentPayload",
    "SkillPackPayload",
    "CapabilityPayload",
    "WritingActionPayload",
    "RunActionRequest",
    "RunActionAcceptedPayload",
    "ImportUserSkillRequest",
    "ImportUserSkillManifestPayload",
    "ImportUserSkillResponse",
    "SkillToggleResponse",
    "SkillTestRunResponse",
    "SkillApprovalRequestCreate",
    "SkillApprovalRequestPayload",
    "SkillApprovalDecisionCreate",
    "SkillApprovalDecisionPayload",
    "SkillApprovalDetailPayload",
    "SkillUninstallResponse",
    "SkillRollbackRequest",
    "SkillRollbackResponse",
    "SkillExportResponse",
    # Runtime
    "TaskState",
    "CreateSessionRequest",
    "SessionPayload",
    "CreateJobRequest",
    "JobPayload",
    "JobStatusPayload",
    "EventPayload",
    "ArtifactPayload",
    "TimelineItemPayload",
    "TimelinePagePayload",
    "CheckpointPayload",
    "ResumeSessionPayload",
    "RewindSessionRequest",
    "ForkSessionRequest",
    "SkillRunResultPayload",
    # Memory
    "MemoryStatusPayload",
    "MemorySearchRequest",
    "MemorySearchHitPayload",
    "MemorySearchResponsePayload",
    "MemoryWakeupPayload",
    "MemorySyncPayload",
    # Resources
    "ProjectPayload",
    "SectionPayload",
    "MaterialPayload",
    "FigureTableCandidatePayload",
    "DraftPayload",
    "RevisionPayload",
    "ProjectExportEvidenceProvenancePayload",
    "ProjectExportEvidenceRowPayload",
    "ProjectExportCitationChainPayload",
    "ProjectExportReviewFindingPayload",
    "ProjectExportPayload",
    "AssociationSignalPayload",
    "AssociationAnglePayload",
    "EvidenceGapPayload",
    "WritingAssociationPayload",
    "CreateProjectRequest",
    "CreateSectionRequest",
    "CreateMaterialRequest",
    "CreateDraftRequest",
    "SaveDraftRequest",
    "BuildAssociationRequest",
    # Recovery
    "RecoveryEventPayload",
    "EventTimelinePayload",
    "MemoryFactPayload",
    "MemorySnapshotPayload",
    "InvalidFactRequest",
    "FactInvalidationPayload",
    "EventFilterPayload",
    "TimelineQueryRequest",
    "TimelineQueryResponse",
    "RecommendationEvidencePayload",
    "RecoveryRecommendationPayload",
    "RecommendationsResponsePayload",
]
