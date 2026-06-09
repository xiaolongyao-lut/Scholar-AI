// Evolution layer wire types.
//
// Hand-mirror of literature_assistant/core/models/evolution.py. The backend
// remains authoritative for risk, dedupe, eligibility, and promotion; this
// file only describes what the wire payloads look like to the frontend.
//
// When the backend models change, update this file by hand. We intentionally
// avoid `npm run generate:openapi` here because that script touches the wider
// generated OpenAPI surface; mirroring by hand keeps this UI client focused.
//
// ---------------------------------------------------------------------------
// Enums (string literal unions — matches Pydantic `str, Enum`)
// ---------------------------------------------------------------------------

export type CandidateSourceType =
  | 'inspiration'
  | 'discussion'
  | 'rag_answer'
  | 'runtime_job'
  | 'skill_run'
  | 'pdf_annotation'
  | 'mcp_tool_use'
  | 'manual'
  | 'curator';

export type CandidateMemoryType =
  | 'user_preference'
  | 'project_fact'
  | 'literature_procedure'
  | 'domain_knowledge'
  | 'evidence_rule'
  | 'agent_role_lesson'
  | 'tool_reliability'
  | 'skill_draft';

export type CandidateStatus =
  | 'captured'
  | 'pending'
  | 'accepted'
  | 'rejected'
  | 'snoozed'
  | 'expired'
  | 'promoted_to_memory'
  | 'promoted_to_skill_draft'
  | 'rolled_back'
  | 'blocked';

export type CandidateRiskLevel = 'low' | 'medium' | 'high';

export type PromotionTarget = 'memory' | 'skill_draft' | 'none';

// ---------------------------------------------------------------------------
// Core record
// ---------------------------------------------------------------------------

export type EvidenceRef = Record<string, unknown>;

export interface ExperienceCandidate {
  candidate_id: string;
  workspace_id: string;
  user_id: string | null;
  project_id: string | null;

  source_type: CandidateSourceType;
  source_id: string;
  source_route: string | null;
  source_summary: string;

  memory_type: CandidateMemoryType;
  title: string;
  claim: string;
  future_use: string;

  evidence_refs: EvidenceRef[];
  confidence: number;
  risk_level: CandidateRiskLevel;

  status: CandidateStatus;
  dedupe_hash: string;
  decision_reason: string | null;
  rollback_ref: string | null;

  created_at: string;
  updated_at: string;
  decided_at: string | null;
  promoted_at: string | null;
}

// ---------------------------------------------------------------------------
// Status / list payloads
// ---------------------------------------------------------------------------

export interface EvolutionStatusPayload {
  enabled: boolean;
  recall_enabled: boolean;
  candidate_capture_enabled: boolean;
  review_ui_enabled: boolean;
  promotion_enabled: boolean;
  curator_enabled: boolean;
  db_path: string;
  candidate_counts: Record<string, number>;
  reason: string | null;
}

export interface CandidateListPayload {
  items: ExperienceCandidate[];
  total: number;
}

// ---------------------------------------------------------------------------
// Transition request / response (accept / reject / snooze / rollback)
// ---------------------------------------------------------------------------

export interface CandidateDecisionRequest {
  decision_reason?: string | null;
  rollback_ref?: string | null;
}

export interface CandidateDecisionPayload {
  candidate_id: string;
  previous_status: CandidateStatus;
  new_status: CandidateStatus;
  decided_at: string;
  decision_reason: string | null;
}

// ---------------------------------------------------------------------------
// Promote (no request body — backend infers target from memory_type)
// ---------------------------------------------------------------------------

export interface CandidatePromotionPayload {
  candidate_id: string;
  previous_status: CandidateStatus;
  new_status: CandidateStatus;
  promoted: boolean;
  target: PromotionTarget;
  rollback_ref: string | null;
  reason: string;
  promoted_at: string | null;
}

// ---------------------------------------------------------------------------
// Curator maintenance payload
// ---------------------------------------------------------------------------

export type CuratorConflict = Record<string, unknown>;
export type CuratorDedupeGroup = Record<string, unknown>;

export interface CuratorRunPayload {
  enabled: boolean;
  workspace_id: string | null;
  scanned: number;
  expired: string[];
  demoted: string[];
  conflicts: CuratorConflict[];
  dedupe_groups: CuratorDedupeGroup[];
  skipped: Record<string, number>;
  reason: string | null;
}

// ---------------------------------------------------------------------------
// Audit roll-up payload
// ---------------------------------------------------------------------------

/** One row in `EvolutionAuditPayload.recent_decisions`.
 *
 * `decision_reason` is always non-empty (the store filters empty/null rows
 * server-side) and is truncated to ≤240 chars by the backend so this list
 * can never echo more than a small fixed amount per row.
 */
export interface EvolutionAuditRecentDecision {
  candidate_id: string;
  status: CandidateStatus;
  decision_reason: string;
  decided_at: string | null;
}

/** `GET /evolution/audit` response shape.
 *
 * All count maps use the corresponding enum value as the key. Maps include
 * only buckets that actually have rows — absent keys mean "0".
 */
export interface EvolutionAuditPayload {
  workspace_id: string | null;
  total: number;
  by_status: Partial<Record<CandidateStatus, number>>;
  by_memory_type: Partial<Record<CandidateMemoryType, number>>;
  by_source_type: Partial<Record<CandidateSourceType, number>>;
  promotion_outcomes: Partial<
    Record<'promoted_to_memory' | 'promoted_to_skill_draft' | 'rolled_back', number>
  >;
  recent_decisions: EvolutionAuditRecentDecision[];
}

// ---------------------------------------------------------------------------
// UI constants for default review actions.
// ---------------------------------------------------------------------------

export const SNOOZE_DURATION_DAYS = 7;

export const SNOOZE_REASON_TAG = `ui_snooze_${SNOOZE_DURATION_DAYS}d`;

export const REJECT_REASON_TAG = 'ui_reject_permanent';
