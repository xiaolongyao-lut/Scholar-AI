"""
Centralized Pydantic models for python_adapter_server.

All request/response models are consolidated here for easier maintenance and discovery.
"""

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
)

# Skills models
from .skills import (
    SkillCompatibilityPayload,
    ScriptPolicyPayload,
    SkillDescriptorPayload,
    SkillPackPayload,
    CapabilityPayload,
    WritingActionPayload,
    RunActionRequest,
    RunActionAcceptedPayload,
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
    DraftPayload,
    RevisionPayload,
    AssociationSignalPayload,
    AssociationAnglePayload,
    EvidenceGapPayload,
    WritingAssociationPayload,
    CreateProjectRequest,
    CreateSectionRequest,
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
    "SkillPackPayload",
    "CapabilityPayload",
    "WritingActionPayload",
    "RunActionRequest",
    "RunActionAcceptedPayload",
    # Runtime
    "TaskState",
    "CreateSessionRequest",
    "SessionPayload",
    "CreateJobRequest",
    "JobPayload",
    "JobStatusPayload",
    "EventPayload",
    "ArtifactPayload",
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
    "DraftPayload",
    "RevisionPayload",
    "AssociationSignalPayload",
    "AssociationAnglePayload",
    "EvidenceGapPayload",
    "WritingAssociationPayload",
    "CreateProjectRequest",
    "CreateSectionRequest",
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
