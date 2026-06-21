import { createDefaultApiClient } from './httpClient';
import type { components } from '@/generated/openapi';
import type { WritingJob } from '@/types/runtime';

export type AgentWorkflowHealthCheck = components['schemas']['HealthCheckResponse'];
export type ZoteroAttachmentHealth = components['schemas']['ZoteroAttachmentHealthResponse'];

export interface AgentWorkspaceArtifact {
  path: string;
  name: string;
  kind: string;
  size_bytes: number;
  modified_at: string;
  preview: string;
  truncated: boolean;
}

export interface AgentWorkspaceAuditRecord {
  timestamp: string;
  tool_name: string;
  args_summary: Record<string, unknown>;
  touched_paths: string[];
  allow_block_reason: string;
  result_preview: string;
  duration_ms: number;
  error_code: string | null;
}

export interface AgentWorkspaceStatus {
  artifact_root: string;
  artifact_count: number;
  audit_count: number;
  total_artifact_bytes: number;
  latest_activity_at: string | null;
  artifacts: AgentWorkspaceArtifact[];
  audit_records: AgentWorkspaceAuditRecord[];
}

export interface AgentBridgeStatus {
  enabled: boolean;
  pending_count: number;
  running_count: number;
  recent: WritingJob[];
}

export interface RuntimeJobsStatus {
  recent: WritingJob[];
}

export type WorkflowPassportStageStatus =
  | 'not_started'
  | 'in_progress'
  | 'complete'
  | 'warn'
  | 'blocked'
  | 'unresolved';

export type ResearchGateStatus = 'pass' | 'warn' | 'block' | 'unresolved' | 'not_applicable';

export type ResearchGateSeverity = 'none' | 'note' | 'warn' | 'block';

export interface WorkflowPassportGate {
  gate_id: string;
  status: ResearchGateStatus;
  severity: ResearchGateSeverity;
  reason: string;
  evidence: Record<string, unknown>[];
  blockers: string[];
  unresolved: string[];
  requires_user_confirmation: boolean;
}

export interface WorkflowPassportStage {
  stage_id: string;
  label: string;
  status: WorkflowPassportStageStatus;
  required_artifacts: string[];
  present_artifacts: Record<string, unknown>[];
  object_ids: string[];
  event_types: string[];
  gate: WorkflowPassportGate;
  next_actions: string[];
  updated_at: string | null;
}

export interface WorkflowPassportProjection {
  schema_version: string;
  generated_at: string;
  scope: Record<string, unknown>;
  stages: WorkflowPassportStage[];
  current_stage_id: string | null;
  gate_summary: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export interface EvidenceIntegritySignal {
  signal_id: string;
  category: string;
  status: Exclude<ResearchGateStatus, 'not_applicable'> | 'not_applicable';
  severity: ResearchGateSeverity;
  message: string;
  evidence: Record<string, unknown>[];
  next_actions: string[];
  metadata: Record<string, unknown>;
}

export type WorkflowReadinessClaimStatus = 'ready' | 'warning' | 'unresolved' | 'blocked';

export interface WorkflowReadinessClaim {
  claim_id: string;
  label: string;
  status: WorkflowReadinessClaimStatus;
  reason: string;
  required_readiness: string[];
  missing_readiness: string[];
  source_gate_status: string | null;
  blockers: string[];
  unresolved: string[];
  evidence: Record<string, unknown>[];
}

export interface WorkflowReadinessClaimsProjection {
  schema_version: 'scholar_ai_workflow_enforcement_v1';
  status: WorkflowReadinessClaimStatus;
  claims: WorkflowReadinessClaim[];
  summary: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export type WorkflowActionPreflightStatus = 'ready' | 'unresolved' | 'blocked' | 'stale';

export type WorkflowActionPreflightFreshnessStatus = 'fresh' | 'stale' | 'unknown';

export interface WorkflowActionPreflightFreshness {
  schema_version: 'scholar_ai_action_preflight_freshness_v1';
  status: WorkflowActionPreflightFreshnessStatus;
  refresh_required: boolean;
  max_age_seconds: number;
  age_seconds: number | null;
  oldest_evidence_at: string | null;
  newest_evidence_at?: string | null;
  expires_at: string | null;
  checked_at: string;
  reasons: string[];
  refresh_actions: string[];
  sources: Record<string, unknown>[];
  oldest_source?: string;
  newest_source?: string;
}

export interface WorkflowActionPreflightProjection {
  schema_version: 'scholar_ai_action_preflight_v1';
  generated_at: string;
  action_id: string;
  required_claim_id: string;
  require_ready: boolean;
  status: WorkflowActionPreflightStatus;
  can_proceed: boolean;
  claim_status: string;
  gate_status: string;
  current_stage_id: string | null;
  freshness?: WorkflowActionPreflightFreshness;
  refresh_required?: boolean;
  blockers: string[];
  unresolved: string[];
  evidence: Record<string, unknown>[];
  summary: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export interface EvidenceIntegrityGateProjection {
  schema_version: 'scholar_ai_evidence_integrity_gate_v1';
  generated_at: string;
  scope: Record<string, unknown>;
  status: Exclude<ResearchGateStatus, 'not_applicable'>;
  signals: EvidenceIntegritySignal[];
  summary: Record<string, unknown>;
  blockers: string[];
  unresolved: string[];
  enforcement?: WorkflowReadinessClaimsProjection;
  provenance: Record<string, unknown>;
}

export interface AgentHandoffCardProjection {
  schema_version: 'scholar_ai_agent_handoff_card_v1';
  generated_at: string;
  request_id: string | null;
  job_id: string;
  session_id: string;
  project_id: string | null;
  status: string;
  agent_host: string | null;
  intent: string | null;
  current_stage_id: string | null;
  completed_evidence: Record<string, unknown>[];
  blockers: string[];
  unresolved: string[];
  readiness_claims?: WorkflowReadinessClaimsProjection;
  action_preflight?: WorkflowActionPreflightProjection;
  resource_refs: Record<string, unknown>[];
  artifacts: Record<string, unknown>[];
  resume_probes: Record<string, unknown>[];
  forbidden_actions: string[];
  resume_prompt: string;
  provenance: Record<string, unknown>;
}

const client = createDefaultApiClient({ timeoutMs: 20_000 });

export async function getAgentWorkspaceStatus(opts?: {
  artifactLimit?: number;
  auditLimit?: number;
  previewChars?: number;
}): Promise<AgentWorkspaceStatus> {
  const response = await client.get<AgentWorkspaceStatus>('/api/agent-workspace/status', {
    params: {
      artifact_limit: opts?.artifactLimit ?? 200,
      audit_limit: opts?.auditLimit ?? 300,
      preview_chars: opts?.previewChars ?? 4000,
    },
  });
  return response.data;
}

export async function getAgentBridgeStatus(opts?: {
  limit?: number;
}): Promise<AgentBridgeStatus> {
  const response = await client.get<AgentBridgeStatus>('/api/agent-bridge/status', {
    params: {
      limit: opts?.limit ?? 20,
    },
  });
  return response.data;
}

export async function listRuntimeJobs(opts?: {
  limit?: number;
}): Promise<RuntimeJobsStatus> {
  const response = await client.get<WritingJob[]>('/runtime/jobs', {
    params: {
      limit: opts?.limit ?? 100,
    },
  });
  return { recent: response.data };
}

export async function getWorkflowPassport(opts?: {
  sessionId?: string | null;
  jobId?: string | null;
  projectId?: string | null;
  limit?: number;
}): Promise<WorkflowPassportProjection> {
  const response = await client.get<WorkflowPassportProjection>('/runtime/workflow-passport', {
    params: {
      session_id: opts?.sessionId ?? undefined,
      job_id: opts?.jobId ?? undefined,
      project_id: opts?.projectId ?? undefined,
      limit: opts?.limit ?? 500,
    },
  });
  return response.data;
}

export async function getEvidenceIntegrityGate(opts?: {
  sessionId?: string | null;
  jobId?: string | null;
  projectId?: string | null;
  limit?: number;
}): Promise<EvidenceIntegrityGateProjection> {
  const response = await client.get<EvidenceIntegrityGateProjection>('/runtime/evidence-integrity-gate', {
    params: {
      session_id: opts?.sessionId ?? undefined,
      job_id: opts?.jobId ?? undefined,
      project_id: opts?.projectId ?? undefined,
      limit: opts?.limit ?? 500,
    },
  });
  return response.data;
}

export async function getAgentHandoffCard(jobId: string): Promise<AgentHandoffCardProjection> {
  if (!jobId.trim()) {
    throw new Error('jobId is required to read an agent handoff card');
  }
  const response = await client.get<AgentHandoffCardProjection>(
    `/runtime/job/${encodeURIComponent(jobId)}/agent-handoff-card`,
  );
  return response.data;
}

/**
 * Return passive local workflow readiness without spending provider quota.
 *
 * Args:
 *   opts: Whether to ask the backend to record explicit live-probe intent.
 *
 * Returns:
 *   Versioned readiness checks and ToolOutcome next-action guidance.
 */
export async function getAgentWorkflowHealth(opts?: {
  includeLive?: boolean;
}): Promise<AgentWorkflowHealthCheck> {
  const response = await client.get<AgentWorkflowHealthCheck>('/api/health/check', {
    params: {
      include_live: opts?.includeLive ?? false,
    },
  });
  return response.data;
}

/**
 * Return read-only Zotero attachment diagnostics for UI guidance.
 *
 * Args:
 *   opts: Optional local Zotero path controls and report-writing policy.
 *
 * Returns:
 *   Versioned Zotero health report. The backend reads a snapshot only and never
 *   writes Zotero repair state.
 */
export async function getZoteroAttachmentHealth(opts?: {
  zoteroDataDir?: string | null;
  allowedRoot?: string | null;
  minTextChars?: number;
  maxItems?: number;
  writeReports?: boolean;
}): Promise<ZoteroAttachmentHealth> {
  const response = await client.get<ZoteroAttachmentHealth>('/api/zotero/attachment-health', {
    params: {
      zotero_data_dir: opts?.zoteroDataDir ?? undefined,
      allowed_root: opts?.allowedRoot ?? undefined,
      min_text_chars: opts?.minTextChars ?? undefined,
      max_items: opts?.maxItems ?? 20,
      write_reports: opts?.writeReports ?? false,
    },
  });
  return response.data;
}
