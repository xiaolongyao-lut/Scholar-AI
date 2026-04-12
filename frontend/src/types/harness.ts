/**
 * Harness Protocol Types - TypeScript strict type definitions for protocol layer
 * 
 * Mirrors Python harness_protocols.py for type safety across IPC boundary.
 * All types are immutable-first and serialization-safe.
 */

// ===== Enums =====

export enum SessionMode {
  PROMPT = 'prompt',      // Prompt-only, first-class mode
  SKILL = 'skill',        // Skill-assisted mode with backend support
  HYBRID = 'hybrid',      // Combined prompt + skill support
}

export enum JobKind {
  PROMPT_ACTION = 'prompt_action',
  SKILL_ACTION = 'skill_action',
  PIPELINE_RUN = 'pipeline_run',
  APPROVAL = 'approval',
  ARTIFACT_EXPORT = 'artifact_export',
}

export enum JobStatus {
  CREATED = 'created',
  QUEUED = 'queued',
  STARTED = 'started',
  PAUSED = 'paused',
  IN_PROGRESS = 'in_progress',
  APPROVAL_PENDING = 'approval_pending',
  APPROVAL_REJECTED = 'approval_rejected',
  COMPLETED = 'completed',
  FAILED = 'failed',
  CANCELLED = 'cancelled',
}

export enum EventType {
  JOB_CREATED = 'job_created',
  JOB_STARTED = 'job_started',
  JOB_PROGRESS = 'job_progress',
  TOOL_REQUESTED = 'tool_requested',
  TOOL_BLOCKED = 'tool_blocked',
  APPROVAL_REQUIRED = 'approval_required',
  APPROVAL_GRANTED = 'approval_granted',
  APPROVAL_REJECTED = 'approval_rejected',
  ARTIFACT_CREATED = 'artifact_created',
  ARTIFACT_UPDATED = 'artifact_updated',
  JOB_PAUSED = 'job_paused',
  JOB_RESUMED = 'job_resumed',
  JOB_COMPLETED = 'job_completed',
  JOB_FAILED = 'job_failed',
  JOB_CANCELLED = 'job_cancelled',
}

export enum ArtifactType {
  TRANSFORMED_TEXT = 'transformed_text',
  DRAFT = 'draft',
  REVIEW_NOTE = 'review_note',
  EXPORT_REQUEST = 'export_request',
  AUDIT_RECORD = 'audit_record',
  METADATA = 'metadata',
}

export enum ApprovalStatus {
  PENDING = 'pending',
  APPROVED = 'approved',
  REJECTED = 'rejected',
  CANCELLED = 'cancelled',
}

// ===== Interfaces =====

export interface WritingSession {
  readonly session_id: string;
  readonly user_id: string | null;
  readonly mode: SessionMode;
  readonly created_at: string;  // ISO 8601
  readonly settings: Record<string, unknown>;
  readonly tags: readonly string[];
  readonly metadata: Record<string, unknown>;
}

export interface WritingJob {
  readonly job_id: string;
  readonly session_id: string;
  readonly kind: JobKind;
  readonly status: JobStatus;
  readonly input_text: string;
  readonly created_at: string;  // ISO 8601
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly action_id?: string | null;
  readonly skill_id?: string | null;
  readonly scope?: string | null;
  readonly output_mode?: string | null;
  readonly error?: string | null;
  readonly tags: readonly string[];
  readonly metadata: Record<string, unknown>;
}

export interface WritingEvent {
  readonly event_id: string;
  readonly job_id: string;
  readonly session_id: string;
  readonly event_type: EventType;
  readonly timestamp: string;  // ISO 8601
  readonly data: Record<string, unknown>;
  readonly metadata: Record<string, unknown>;
}

export interface WritingArtifact {
  readonly artifact_id: string;
  readonly job_id: string;
  readonly session_id: string;
  readonly artifact_type: ArtifactType;
  readonly content: string | Record<string, unknown>;
  readonly created_at: string;  // ISO 8601
  readonly created_by: string | null;
  readonly metadata: Record<string, unknown>;
  readonly mime_type: string;
}

export interface WritingApprovalRequest {
  readonly approval_id: string;
  readonly job_id: string;
  readonly session_id: string;
  readonly status: ApprovalStatus;
  readonly requested_at: string;  // ISO 8601
  readonly reason: string;
  readonly content_preview: string | null;
  readonly response_by: string | null;
  readonly responded_at: string | null;
  readonly metadata: Record<string, unknown>;
}

// ===== Factory Functions =====

export const createWritingSession = (
  mode: SessionMode,
  userId?: string | null,
  settings?: Record<string, unknown>,
  tags?: string[],
  metadata?: Record<string, unknown>
): WritingSession => {
  const sessionId = `session_${Math.random().toString(16).slice(2, 10)}`;
  return {
    session_id: sessionId,
    user_id: userId || null,
    mode,
    created_at: new Date().toISOString(),
    settings: settings || {},
    tags: tags || [],
    metadata: metadata || {},
  };
};

export const createWritingJob = (
  sessionId: string,
  kind: JobKind,
  inputText?: string,
  actionId?: string | null,
  skillId?: string | null,
  scope?: string | null,
  outputMode?: string | null,
  tags?: string[],
  metadata?: Record<string, unknown>
): WritingJob => {
  const jobId = `job_${Math.random().toString(16).slice(2, 10)}`;
  return {
    job_id: jobId,
    session_id: sessionId,
    kind,
    status: JobStatus.CREATED,
    input_text: inputText || '',
    created_at: new Date().toISOString(),
    started_at: null,
    completed_at: null,
    action_id: actionId || undefined,
    skill_id: skillId || undefined,
    scope: scope || undefined,
    output_mode: outputMode || undefined,
    tags: tags || [],
    metadata: metadata || {},
  };
};

export const createWritingEvent = (
  jobId: string,
  sessionId: string,
  eventType: EventType,
  data?: Record<string, unknown>,
  metadata?: Record<string, unknown>
): WritingEvent => {
  const eventId = `event_${Math.random().toString(16).slice(2, 10)}`;
  return {
    event_id: eventId,
    job_id: jobId,
    session_id: sessionId,
    event_type: eventType,
    timestamp: new Date().toISOString(),
    data: data || {},
    metadata: metadata || {},
  };
};

export const createWritingArtifact = (
  jobId: string,
  sessionId: string,
  artifactType: ArtifactType,
  content: string | Record<string, unknown>,
  createdBy?: string | null,
  metadata?: Record<string, unknown>,
  mimeType?: string
): WritingArtifact => {
  const artifactId = `artifact_${Math.random().toString(16).slice(2, 10)}`;
  return {
    artifact_id: artifactId,
    job_id: jobId,
    session_id: sessionId,
    artifact_type: artifactType,
    content,
    created_at: new Date().toISOString(),
    created_by: createdBy || null,
    metadata: metadata || {},
    mime_type: mimeType || 'application/json',
  };
};

export const createWritingApprovalRequest = (
  jobId: string,
  sessionId: string,
  reason: string,
  contentPreview?: string | null,
  metadata?: Record<string, unknown>
): WritingApprovalRequest => {
  const approvalId = `approval_${Math.random().toString(16).slice(2, 10)}`;
  return {
    approval_id: approvalId,
    job_id: jobId,
    session_id: sessionId,
    status: ApprovalStatus.PENDING,
    requested_at: new Date().toISOString(),
    reason,
    content_preview: contentPreview || null,
    response_by: null,
    responded_at: null,
    metadata: metadata || {},
  };
};

// ===== Protocol Version =====

export const PROTOCOL_VERSION = '1.0.0';
