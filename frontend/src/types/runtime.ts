/**
 * Writing runtime protocol types.
 *
 * The core transport models are generated from the backend OpenAPI schema
 * so frontend runtime calls stay aligned with the adapter contract.
 */

import type { components } from "../generated/openapi";

// ==========================================================================
// Session Types
// ==========================================================================

export type SessionMode = 'prompt' | 'skill' | 'hybrid';

export type WritingSession = components["schemas"]["SessionPayload"];

export type CreateSessionRequest = components["schemas"]["CreateSessionRequest"];

// ==========================================================================
// Job Types
// ==========================================================================

export type JobKind =
  | 'prompt_action'
  | 'skill_action'
  | 'pipeline_run'
  | 'approval'
  | 'artifact_export'
  | 'smart_read'
  | 'discussion'
  | 'ai_review'
  | 'figure_load'
  | 'agent_request'
  | 'resource_ingest';

export type JobStatus =
  | 'created'
  | 'queued'
  | 'started'
  | 'paused'
  | 'in_progress'
  | 'approval_pending'
  | 'approval_rejected'
  | 'completed'
  | 'failed'
  | 'cancelled';

type RuntimeMetadata = Record<string, unknown>;

export type WritingJob = components["schemas"]["JobPayload"] & {
  tags?: string[];
  metadata?: RuntimeMetadata;
};

export type CreateJobRequest = components["schemas"]["CreateJobRequest"] & {
  metadata?: RuntimeMetadata;
};

export type JobStatusDetail = components["schemas"]["JobStatusPayload"] & {
  metadata?: RuntimeMetadata;
};

// ==========================================================================
// Event Types
// ==========================================================================

export type EventType =
  | 'job_created'
  | 'job_started'
  | 'job_progress'
  | 'tool_requested'
  | 'tool_blocked'
  | 'approval_required'
  | 'approval_granted'
  | 'approval_rejected'
  | 'artifact_created'
  | 'artifact_updated'
  | 'job_paused'
  | 'job_resumed'
  | 'job_completed'
  | 'job_failed'
  | 'job_cancelled';

export type WritingEvent = components["schemas"]["EventPayload"] & {
  sequence: number;
  metadata?: RuntimeMetadata;
};

export interface JobEventQueryOptions {
  sinceTimestamp?: string | null;
  afterEventId?: string | null;
  afterSequence?: number | null;
  limit?: number;
}

export interface JobEventSnapshot {
  job_id: string;
  session_id: string;
  job: WritingJob;
  status: JobStatusDetail;
  events: WritingEvent[];
  next_after_sequence?: number | null;
  latest_sequence: number;
  has_more: boolean;
}

export interface ListJobsQuery {
  sessionId?: string | null;
  status?: JobStatus | null;
  limit?: number;
}

// ==========================================================================
// Artifact Types
// ==========================================================================

export type ArtifactType =
  | 'transformed_text'
  | 'draft'
  | 'review_note'
  | 'export_request'
  | 'audit_record'
  | 'metadata';

export type WritingArtifact = components["schemas"]["ArtifactPayload"];

// ==========================================================================
// Approval Types
// ==========================================================================

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';

export interface WritingApprovalRequest {
  approval_id: string;
  job_id: string;
  session_id: string;
  status: ApprovalStatus;
  requested_at: string;  // ISO 8601
  reason: string;
  content_preview?: string | null;
  response_by?: string | null;
  responded_at?: string | null;
  metadata?: Record<string, unknown>;
}

// ==========================================================================
// RuntimeClient - Interface for consuming backend APIs
// ==========================================================================

export interface WritingRuntimeClient {
  // Session management
  createSession(request: CreateSessionRequest): Promise<WritingSession>;
  getSession(sessionId: string): Promise<WritingSession>;
  
  // Job management
  createJob(request: CreateJobRequest): Promise<WritingJob>;
  listJobs(query?: ListJobsQuery): Promise<WritingJob[]>;
  getJob(jobId: string): Promise<WritingJob>;
  getJobStatus(jobId: string): Promise<JobStatusDetail>;
  getJobEvents(jobId: string, options?: JobEventQueryOptions): Promise<WritingEvent[]>;
  getJobEventSnapshot(jobId: string, options?: JobEventQueryOptions): Promise<JobEventSnapshot>;
  getJobArtifacts(jobId: string): Promise<WritingArtifact[]>;
  
  // Job lifecycle control
  startJob(jobId: string): Promise<{ job_id: string; status: JobStatus }>;
  pauseJob(jobId: string): Promise<{ job_id: string; status: JobStatus }>;
  resumeJob(jobId: string): Promise<{ job_id: string; status: JobStatus }>;
  cancelJob(jobId: string): Promise<{ job_id: string; status: JobStatus }>;
  deleteJob(jobId: string): Promise<{ job_id: string; deleted: boolean }>;
  
  // Event subscription
  subscribeToEvents(
    sessionId: string,
    onEvent: (event: WritingEvent) => void,
  ): () => void;  // Returns unsubscribe function
}

// ==========================================================================
// Session Persistence
// ==========================================================================
//
// These types mirror `models/runtime.py` Pydantic classes and stay in lockstep
// with the backend contract until `frontend/src/generated/openapi.ts` covers
// the session timeline schemas.

/** Session summary used in list / drawer UI. */
export interface SessionSummary {
  session_id: string;
  user_id?: string | null;
  mode: string;                          // "prompt" | "skill" | "hybrid"
  created_at: string;                    // ISO 8601
  settings: Record<string, unknown>;
  tags: string[];
  metadata: Record<string, unknown>;     // may contain workspace_root / entry_cwd / title / parent_session_id / branch_point_checkpoint_id
}

/** Single append-only transcript event. */
export interface TimelineEvent {
  event_id: string;
  session_id: string;
  event_kind: string;                    // "user" | "assistant" | "tool_call" | "tool_result" | "checkpoint"
  timestamp: string;                     // ISO 8601
  workspace_key: string;
  payload: Record<string, unknown>;      // kept as record; consumers narrow by event_kind
  parent_event_id?: string | null;
  /** Optional blob reference for spill (>64 KB tool results). Populated only when payload points to an external blob. */
  ref?: string;
}

/** Cursor-paginated transcript page. */
export interface TimelinePage {
  session_id: string;
  head_event_id?: string | null;
  items: TimelineEvent[];
  next_cursor?: string | null;
}

/** Checkpoint summary attached to a timeline event. */
export interface CheckpointMeta {
  checkpoint_id: string;
  session_id: string;
  event_id: string;
  created_at: string;                    // ISO 8601
  kind: string;                          // "auto" | "manual" | "rewind" | "fork"
  metadata: Record<string, unknown>;
  active: boolean;
}

/** Response from POST /runtime/session/{id}/resume, /rewind, /fork. */
export interface ResumeSessionResult {
  session: SessionSummary;
  head_event_id?: string | null;
  head_checkpoint_id?: string | null;
  timeline: TimelineEvent[];
  next_cursor?: string | null;
}

/** Request body for POST /runtime/session/{id}/rewind. */
export interface RewindSessionRequest {
  checkpoint_id: string;
  /** "conversation_only" (default) keeps workspace files intact; "with_files" restores via .rollback_snapshots/. */
  mode?: 'conversation_only' | 'with_files';
}

/** Request body for POST /runtime/session/{id}/fork. */
export interface ForkSessionRequest {
  checkpoint_id: string;
  title?: string | null;
}

/** Query params for GET /runtime/sessions. */
export interface ListSessionsQuery {
  workspace_root?: string;
  workspace_key?: string;
}

/** Query params for GET /runtime/session/current. */
export interface GetCurrentSessionQuery {
  workspace_root?: string;
  workspace_key?: string;
  entry_cwd?: string;
}

/** Query params for GET /runtime/session/{id}/timeline. */
export interface GetTimelineQuery {
  after_event_id?: string;
  /** 1..1000, default 100 (server-side clamp). */
  limit?: number;
}

// ==========================================================================
// Compatibility - Legacy action execution through runtime
// ==========================================================================

export interface RunActionRequest {
  action_id: string;
  input_text?: string;
  scope?: string;
  output_mode?: string;
}

export interface RunActionResponse {
  jobId: string;
  status: JobStatus;
  kind: string;
  message: string;
}

export interface TransformResult {
  jobId: string;
  actionId: string;
  skillId?: string;
  inputText: string;
  outputText: string;
  scope?: string;
  outputMode?: string;
  createdAt: string;
  applied: boolean;
}
