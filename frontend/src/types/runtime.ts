/**
 * WritingRuntime Protocol Types (Phase 2)
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
  | 'artifact_export';

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

export type WritingJob = components["schemas"]["JobPayload"];

export type CreateJobRequest = components["schemas"]["CreateJobRequest"];

export type JobStatusDetail = components["schemas"]["JobStatusPayload"];

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

export type WritingEvent = components["schemas"]["EventPayload"];

export interface JobEventQueryOptions {
  sinceTimestamp?: string | null;
  afterEventId?: string | null;
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
  getJob(jobId: string): Promise<WritingJob>;
  getJobStatus(jobId: string): Promise<JobStatusDetail>;
  getJobEvents(jobId: string, options?: JobEventQueryOptions): Promise<WritingEvent[]>;
  getJobArtifacts(jobId: string): Promise<WritingArtifact[]>;
  
  // Job lifecycle control
  startJob(jobId: string): Promise<{ job_id: string; status: JobStatus }>;
  pauseJob(jobId: string): Promise<{ job_id: string; status: JobStatus }>;
  resumeJob(jobId: string): Promise<{ job_id: string; status: JobStatus }>;
  cancelJob(jobId: string): Promise<{ job_id: string; status: JobStatus }>;
  
  // Event subscription
  subscribeToEvents(
    sessionId: string,
    onEvent: (event: WritingEvent) => void,
  ): () => void;  // Returns unsubscribe function
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
