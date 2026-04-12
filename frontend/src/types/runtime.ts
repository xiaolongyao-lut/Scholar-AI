/**
 * WritingRuntime Protocol Types (Phase 2)
 * 
 * TypeScript type definitions for the long-lived writing runtime backend.
 * These types parallel the Python harness_protocols.py entities.
 */

// ==========================================================================
// Session Types
// ==========================================================================

export type SessionMode = 'prompt' | 'skill' | 'hybrid';

export interface WritingSession {
  session_id: string;
  user_id: string | null;
  mode: SessionMode;
  created_at: string;  // ISO 8601
  settings: Record<string, unknown>;
  tags: string[];
  metadata?: Record<string, unknown>;
}

export interface CreateSessionRequest {
  mode: SessionMode;
  user_id?: string | null;
  settings?: Record<string, unknown>;
  tags?: string[];
}

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

export interface WritingJob {
  job_id: string;
  session_id: string;
  kind: JobKind;
  status: JobStatus;
  input_text: string;
  created_at: string;  // ISO 8601
  started_at: string | null;
  completed_at: string | null;
  action_id?: string | null;
  skill_id?: string | null;
  scope?: string | null;
  output_mode?: string | null;
  error?: string | null;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

export interface CreateJobRequest {
  session_id: string;
  kind: JobKind;
  input_text?: string;
  action_id?: string | null;
  skill_id?: string | null;
  scope?: string | null;
  output_mode?: string | null;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

export interface JobStatusDetail {
  job_id: string;
  session_id: string;
  status: JobStatus;
  kind: JobKind;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  is_paused: boolean;
  is_cancelled: boolean;
  error: string | null;
}

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

export interface WritingEvent {
  event_id: string;
  job_id: string;
  session_id: string;
  event_type: EventType;
  timestamp: string;  // ISO 8601
  data?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
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

export interface WritingArtifact {
  artifact_id: string;
  job_id: string;
  session_id: string;
  artifact_type: ArtifactType;
  content: string | Record<string, unknown>;
  created_at: string;  // ISO 8601
  created_by?: string | null;
  metadata?: Record<string, unknown>;
  mime_type?: string;
}

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
  getJobEvents(jobId: string): Promise<WritingEvent[]>;
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
