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

export interface AgentWorkspaceDirectoryState {
  label: string;
  path: string;
  exists: boolean;
  file_count: number;
  total_bytes: number;
  truncated: boolean;
}

export interface AgentWorkspaceGitState {
  available: boolean;
  branch: string | null;
  ahead: number;
  behind: number;
  changed_count: number;
  staged_count: number;
  unstaged_count: number;
  untracked_count: number;
  conflicted_count: number;
  dirty_paths: string[];
  error: string | null;
}

export interface AgentWorkspaceRecoveryProbe {
  label: string;
  route: string;
  read_only: boolean;
  requires_identifier: boolean;
  identifier_hint: string | null;
  purpose: string;
  mcp_tool: string | null;
}

export interface AgentWorkspaceGoalState {
  available: boolean;
  path: string | null;
  updated_at: string | null;
  checkpoint_id: string | null;
  requirement_count: number;
  proved_count: number;
  incomplete_count: number;
  out_of_scope_count: number;
  latest_requirement_id: string | null;
  next_authorized_local_actions: string[];
  stop_boundaries: string[];
  error: string | null;
}

export interface AgentWorkspaceState {
  schema_version: 'scholar_ai_agent_workspace_state_v1';
  generated_at: string;
  workspace_ready: boolean;
  read_only: boolean;
  artifact_root: AgentWorkspaceDirectoryState;
  runtime_state_root: AgentWorkspaceDirectoryState;
  output_root: AgentWorkspaceDirectoryState;
  git: AgentWorkspaceGitState;
  goal_state: AgentWorkspaceGoalState;
  recovery_probes: AgentWorkspaceRecoveryProbe[];
  boundaries: string[];
  next_safe_local_actions: string[];
}

export interface AgentWorkspaceStatus {
  artifact_root: string;
  artifact_count: number;
  audit_count: number;
  total_artifact_bytes: number;
  latest_activity_at: string | null;
  workspace_state: AgentWorkspaceState;
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
  diagnostics: Record<string, unknown>;
  reproducibility: Record<string, unknown>;
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
  drilldown?: Record<string, unknown>;
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

export type BlockingActionBoundaryStatus = 'ready' | 'unresolved' | 'blocked';

export interface BlockingActionBoundaryClaim {
  claim_id: string;
  label?: string;
  status: string;
  reason?: string;
  blocker_count?: number;
  unresolved_count?: number;
  [key: string]: unknown;
}

export interface BlockingActionBoundarySignalRef {
  signal_id: string;
  category?: string | null;
  status?: string | null;
  severity?: string | null;
  message?: string | null;
  blocks_claims?: boolean;
  replay_ref_count?: number;
  [key: string]: unknown;
}

export interface BlockingActionBoundaryProbe {
  label?: string;
  name?: string;
  url?: string;
  method?: string;
  read_only?: boolean;
  params?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface BlockingActionBoundaryRecoveryDrilldown {
  signal_id: string;
  category?: string | null;
  status?: string | null;
  severity?: string | null;
  message?: string | null;
  linked_stage_id?: string | null;
  source_ref: Record<string, unknown>;
  checked_facts: Record<string, unknown>;
  evidence_refs: Record<string, unknown>[];
  replay_refs: Record<string, unknown>[];
  recovery_refs: Record<string, unknown>[];
  local_read_only_probes: BlockingActionBoundaryProbe[];
  next_safe_local_actions: string[];
  requires_human_review: boolean;
  blocks_claims: boolean;
  read_only: boolean;
  raw_path_exposed: boolean;
  [key: string]: unknown;
}

export interface BlockingActionBoundaryProjection {
  schema_version: 'scholar_ai_blocking_action_boundary_v1';
  action_id: string;
  required_claim_id: string;
  status: BlockingActionBoundaryStatus;
  can_proceed: boolean;
  require_ready: boolean;
  refresh_required: boolean;
  blocked_claims: BlockingActionBoundaryClaim[];
  blockers: string[];
  unresolved: string[];
  blocked_signal_refs: BlockingActionBoundarySignalRef[];
  unresolved_signal_refs: BlockingActionBoundarySignalRef[];
  recovery_drilldowns?: BlockingActionBoundaryRecoveryDrilldown[];
  evidence_refs: Record<string, unknown>[];
  local_read_only_probes: BlockingActionBoundaryProbe[];
  next_safe_local_actions: string[];
  forbidden_actions: string[];
  provenance: Record<string, unknown>;
}

export interface WorkflowReadinessClaimsProjection {
  schema_version: 'scholar_ai_workflow_enforcement_v1';
  status: WorkflowReadinessClaimStatus;
  claims: WorkflowReadinessClaim[];
  blocking_action_boundary?: BlockingActionBoundaryProjection;
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

export interface PreflightRefreshReceiptProjection {
  schema_version: 'scholar_ai_preflight_refresh_receipt_v1';
  receipt_id: string;
  generated_at: string;
  action_id: string;
  required_claim_id: string;
  scope: Record<string, unknown>;
  status: WorkflowActionPreflightStatus;
  can_proceed: boolean;
  refresh_required: boolean;
  projection_digests: Record<string, string>;
  projection_refs: Record<string, unknown>[];
  freshness: Record<string, unknown>;
  validation: Record<string, unknown>;
  replay: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export interface WorkflowReplayReceiptSummary {
  ordinal: number;
  receipt_id: string | null;
  generated_at: string | null;
  action_id: string | null;
  required_claim_id: string | null;
  status: WorkflowActionPreflightStatus;
  can_proceed: boolean;
  refresh_required: boolean;
  blocker_count: number;
  unresolved_count: number;
  digest_keys: string[];
  projection_digests: Record<string, string>;
  external_mutation: boolean;
  source_material_mutation: boolean;
}

export interface WorkflowReplayLineageProjection {
  schema_version: 'scholar_ai_workflow_replay_lineage_v1';
  generated_at: string;
  job_id: string;
  session_id: string;
  project_id: string | null;
  scope: Record<string, unknown>;
  receipt_count: number;
  returned_count: number;
  latest_receipt_id: string | null;
  latest: Record<string, unknown>;
  previous: Record<string, unknown>;
  items: WorkflowReplayReceiptSummary[];
  comparison: Record<string, unknown>;
  blockers: string[];
  unresolved: string[];
  resume_probes: Record<string, unknown>[];
  summary: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export interface WorkflowReplayIndexItem {
  ordinal: number;
  job_id: string;
  session_id: string;
  project_id: string | null;
  job_kind: string;
  job_status: string;
  session_title: string | null;
  receipt_count: number;
  latest_receipt_id: string | null;
  latest_generated_at: string | null;
  latest_status: WorkflowActionPreflightStatus;
  latest_action_id: string | null;
  latest_required_claim_id: string | null;
  latest_can_proceed: boolean;
  latest_refresh_required: boolean;
  latest_blocker_count: number;
  latest_unresolved_count: number;
  changed_digest_keys: string[];
  comparison: Record<string, unknown>;
  recovery_priority: number;
  metadata_receipt_count: number;
  artifact_receipt_count: number;
  resume_probes: Record<string, unknown>[];
  read_only: boolean;
}

export interface WorkflowReplayIndexProjection {
  schema_version: 'scholar_ai_workflow_replay_index_v1';
  generated_at: string;
  scope: Record<string, unknown>;
  total_jobs_scanned: number;
  total_receipts_seen: number;
  matching_job_count: number;
  returned_count: number;
  items: WorkflowReplayIndexItem[];
  blockers: string[];
  unresolved: string[];
  resume_probes: Record<string, unknown>[];
  summary: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export type ResearchActionLifecycleStatus =
  | 'proposed'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'blocked'
  | 'unresolved'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type ResearchActionLifecycleType =
  | 'wiki_candidate'
  | 'graph_patch'
  | 'export_overwrite'
  | 'batch_material_reprocess'
  | 'artifact_export'
  | 'agent_handoff'
  | 'approval_gate'
  | 'unknown';

export interface ResearchActionLifecycleItemProjection {
  action_uid: string;
  action_id: string;
  action_type: ResearchActionLifecycleType;
  status: ResearchActionLifecycleStatus;
  project_id: string | null;
  session_id: string;
  job_id: string;
  object_refs: Record<string, unknown>[];
  approval: Record<string, unknown>;
  preflight: Record<string, unknown>;
  gate_refs: Record<string, unknown>[];
  effect_summary: Record<string, unknown>;
  effect_refs: Record<string, unknown>[];
  recovery: Record<string, unknown>;
  forbidden_actions: string[];
  provenance: Record<string, unknown>;
}

export interface ResearchActionLifecycleProjection {
  schema_version: 'scholar_ai_research_action_lifecycle_v1';
  generated_at: string;
  scope: Record<string, unknown>;
  actions: ResearchActionLifecycleItemProjection[];
  summary: Record<string, unknown>;
  blockers: string[];
  unresolved: string[];
  resume_probes: Record<string, unknown>[];
  provenance: Record<string, unknown>;
}

export type BehaviorEvalSeverity = 'warn' | 'block';

export type BehaviorEvalStatus = 'pass' | 'warn' | 'block' | 'unresolved';

export type BehaviorEvalStructuralStatus = 'pass' | 'fail' | 'not_applicable';

export interface BehaviorEvalCaseProjection {
  case_id: string;
  category: string;
  severity: BehaviorEvalSeverity;
  objective: string;
  red_flags: string[];
  pass_criteria: string;
}

export interface BehaviorEvalFindingProjection {
  finding_id: string;
  case_id: string;
  category: string;
  severity: BehaviorEvalSeverity;
  message: string;
  evidence: Record<string, unknown>[];
  next_actions: string[];
}

export interface BehaviorEvalResultProjection {
  case_id: string;
  observation_id: string;
  evaluation_goal: 'red_flag_detected' | 'behavior_safe';
  behavior_status: BehaviorEvalStatus;
  structural_status: BehaviorEvalStructuralStatus;
  red_flag_detected: boolean;
  finding_count: number;
  findings: BehaviorEvalFindingProjection[];
}

export interface BehaviorEvalSummaryProjection {
  case_count: number;
  observation_count: number;
  red_flag_count: number;
  block_count: number;
  warn_count: number;
  unresolved_count: number;
  structural_status: BehaviorEvalStructuralStatus;
  behavior_status: BehaviorEvalStatus;
  structural_note: string;
}

export interface BehaviorEvalPackProjection {
  schema_version: 'scholar_ai_behavior_eval_pack_v1';
  generated_at: string;
  mode: 'canary' | 'observations';
  summary: BehaviorEvalSummaryProjection;
  results: BehaviorEvalResultProjection[];
  blockers: string[];
  warnings: string[];
  next_actions: string[];
  provenance: Record<string, unknown>;
  cases: BehaviorEvalCaseProjection[];
  run_record: Record<string, unknown>;
}

export interface AgentHandoffReplayRecoveryProjection {
  schema_version: 'scholar_ai_agent_handoff_replay_recovery_v1';
  current_receipt: Record<string, unknown>;
  lineage: Record<string, unknown>;
  index: Record<string, unknown>;
  highest_priority_attempt: Record<string, unknown>;
  resume_probes: Record<string, unknown>[];
  recovery_required: boolean;
  read_only: boolean;
  source_material_mutation: boolean;
  external_mutation: boolean;
}

export interface AgentHandoffActionLifecycleRecoveryProjection {
  schema_version: 'scholar_ai_handoff_action_lifecycle_recovery_v1';
  read_only: boolean;
  action_ref_count: number;
  scoped_action_ref_count: number;
  blocked_action_count: number;
  pending_confirmation_count: number;
  missing_preflight_count: number;
  action_refs: Record<string, unknown>[];
  resume_probes: Record<string, unknown>[];
  forbidden_actions: string[];
  provenance: Record<string, unknown>;
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
  refresh_receipt_id?: string;
  refresh_receipt?: PreflightRefreshReceiptProjection;
  blockers: string[];
  unresolved: string[];
  evidence: Record<string, unknown>[];
  blocking_action_boundary?: BlockingActionBoundaryProjection;
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
  blocking_action_boundary?: BlockingActionBoundaryProjection;
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
  action_lifecycle_recovery?: AgentHandoffActionLifecycleRecoveryProjection;
  replay_recovery?: AgentHandoffReplayRecoveryProjection;
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

export async function getWorkflowReplayLineage(jobId: string, opts?: {
  limit?: number;
}): Promise<WorkflowReplayLineageProjection> {
  if (!jobId.trim()) {
    throw new Error('jobId is required to read workflow replay lineage');
  }
  const response = await client.get<WorkflowReplayLineageProjection>(
    `/runtime/job/${encodeURIComponent(jobId)}/workflow-replay-lineage`,
    {
      params: {
        limit: opts?.limit ?? 12,
      },
    },
  );
  return response.data;
}

export async function getWorkflowReplayIndex(opts?: {
  projectId?: string | null;
  sessionId?: string | null;
  status?: WorkflowActionPreflightStatus | null;
  actionId?: string | null;
  limit?: number;
}): Promise<WorkflowReplayIndexProjection> {
  const response = await client.get<WorkflowReplayIndexProjection>('/runtime/workflow-replay-index', {
    params: {
      project_id: opts?.projectId ?? undefined,
      session_id: opts?.sessionId ?? undefined,
      status: opts?.status ?? undefined,
      action_id: opts?.actionId ?? undefined,
      limit: opts?.limit ?? 25,
    },
  });
  return response.data;
}

export async function getResearchActionLifecycle(opts?: {
  sessionId?: string | null;
  jobId?: string | null;
  projectId?: string | null;
  limit?: number;
}): Promise<ResearchActionLifecycleProjection> {
  const response = await client.get<ResearchActionLifecycleProjection>('/runtime/research-action-lifecycle', {
    params: {
      session_id: opts?.sessionId ?? undefined,
      job_id: opts?.jobId ?? undefined,
      project_id: opts?.projectId ?? undefined,
      limit: opts?.limit ?? 50,
    },
  });
  return response.data;
}

export async function getBehaviorEvalPack(opts?: {
  includeCases?: boolean;
}): Promise<BehaviorEvalPackProjection> {
  const response = await client.get<BehaviorEvalPackProjection>('/runtime/behavior-eval-pack', {
    params: {
      include_cases: opts?.includeCases ?? true,
    },
  });
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
