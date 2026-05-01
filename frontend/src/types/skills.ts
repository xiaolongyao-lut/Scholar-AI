/**
 * Frontend types for user skill management (TASK-189).
 *
 * These types mirror the backend SkillDescriptor and user manifest models.
 */

/** Permission keys as defined by the backend permission model */
export const PERMISSION_KEYS = [
  'model.llm',
  'model.embedding',
  'retrieval.read',
  'draft.read',
  'draft.write',
  'references.read',
  'files.read',
  'files.write',
  'network',
  'script.execute',
  'storage',
] as const;

export type PermissionKey = (typeof PERMISSION_KEYS)[number];

export const HIGH_RISK_PERMISSIONS: readonly PermissionKey[] = [
  'script.execute',
  'network',
  'files.write',
];

export interface SkillDescriptor {
  id: string;
  name: string;
  description: string;
  kind: string;
  source: 'builtin' | 'imported' | 'experimental';
  entry_mode: string;
  supported_scopes: string[];
  ui_visibility: string;
  requires_assets: boolean;
  prompt_template_refs: string[];
  script_refs: string[];
  reference_refs: string[];
  tags: string[];
  version: string;
  display_group: string;
  experimental: boolean;
  safe_to_execute: boolean;
  capability_refs: string[];
  default_parameters: Record<string, unknown>;
  import_origin: string | null;
  summary_hint: string | null;
  compatibility: {
    fallback_action_id: string | null;
    min_app_version: string | null;
    max_app_version: string | null;
  };
  disabled_reason: string | null;
  script_policy: {
    has_scripts: boolean;
    safe_to_execute: boolean;
    disabled_reason: string | null;
  };
  trust_level: 'trusted' | 'limited' | 'untrusted';
}

export interface SkillEvidenceRef {
  chunk_id?: string;
  source_id?: string;
  title?: string;
  content?: string;
  quote?: string;
  score?: number;
  [key: string]: unknown;
}

export interface SkillStructuredOutput {
  skill_id?: string;
  skill_kind?: string;
  execution_mode?: string;
  scope?: string;
  output_mode?: string;
  prompt_preview?: string;
  permissions?: Partial<Record<PermissionKey, boolean>>;
  requires_model_call?: boolean;
  error_code?: string;
  error?: string;
  security_assessment?: SkillSecurityAssessment;
  [key: string]: unknown;
}

export interface SkillSecurityAssessment {
  skill_id: string;
  source: string;
  risk_level: 'low' | 'medium' | 'high' | 'critical' | string;
  runtime_gate: string;
  runtime_executable: boolean;
  enable_requires_approval: boolean;
  high_risk_flags: string[];
  denied_operations: string[];
  allowed_operations: string[];
  required_sandbox_controls: string[];
  approval_reason: string | null;
  block_reason: string | null;
}

export interface ImportResult {
  success: boolean;
  skill_id: string;
  installed_path: string;
  content_hash: string;
  origin: string;
  installed_at: string;
  errors: string[];
  warnings: string[];
  manifest?: {
    id: string;
    name: string;
    version: string;
    kind: string;
    high_risk_flags: string[];
  };
}

export interface SkillAuditEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  job_id: string | null;
  capability_id: string | null;
  description: string;
  severity: string;
  error_message: string | null;
}

export interface SkillEnableResult {
  skill_id: string;
  enabled: boolean;
  reason?: string;
}

export interface SkillTestRunResult {
  job_id: string;
  skill_id: string;
  status: string;
  input_text: string;
  output_text: string;
  timestamp: string;
  execution_time_ms: number;
  warnings: string[];
  metadata: Record<string, unknown>;
  structured_output: SkillStructuredOutput;
  evidence_refs: SkillEvidenceRef[];
  audit_id: string | null;
}

export interface SkillApprovalRequest {
  request_id: string;
  capability_id: string;
  capability_name: string;
  reason: string;
  timestamp: string;
  context: Record<string, unknown>;
}

export type SkillApprovalDecision = 'approved' | 'denied' | 'deferred';

export interface SkillApprovalDecisionResult {
  request_id: string;
  decision: SkillApprovalDecision;
  user_id: string | null;
  timestamp: string;
  reason: string | null;
}

export interface SkillUninstallResult {
  skill_id: string;
  uninstalled: boolean;
  dry_run: boolean;
  backup_path: string | null;
  removed_path: string | null;
  warnings: string[];
}

export interface SkillRollbackResult {
  skill_id: string;
  rolled_back: boolean;
  restored_path: string;
  backup_path: string;
  warnings: string[];
}
