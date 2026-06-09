// Evolution layer API client.
//
// Thin typed wrapper around `/evolution/*` FastAPI endpoints. Mirrors the
// pattern in `httpClient.ts` (shared baseURL/timeout/error handling +
// per-endpoint functions returning typed payloads). The backend is
// authoritative for all state transitions and security gates — this client
// only serializes requests and surfaces typed responses; it does not validate
// or rewrite candidates locally.
//
import { createApiClient } from './httpClient.ts';
import {
  REJECT_REASON_TAG,
  SNOOZE_REASON_TAG,
} from './evolutionTypes.ts';
import type {
  CandidateDecisionPayload,
  CandidateDecisionRequest,
  CandidateListPayload,
  CandidateMemoryType,
  CandidatePromotionPayload,
  CandidateStatus,
  CuratorRunPayload,
  EvolutionAuditPayload,
  EvolutionStatusPayload,
} from './evolutionTypes.ts';

const PATH = '/evolution';

let _client: ReturnType<typeof createApiClient> | null = null;
function client(): ReturnType<typeof createApiClient> {
  if (!_client) {
    _client = createApiClient();
  }
  return _client;
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

export async function getEvolutionStatus(): Promise<EvolutionStatusPayload> {
  const resp = await client().get<EvolutionStatusPayload>(`${PATH}/status`);
  return resp.data;
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

export interface ListCandidatesOptions {
  workspaceId?: string;
  projectId?: string;
  status?: CandidateStatus;
  memoryType?: CandidateMemoryType;
  sortBy?: CandidateSortBy;
  limit?: number;
  offset?: number;
}

export type CandidateSortBy = 'updated_at' | 'created_at' | 'confidence';

export async function listCandidates(
  opts: ListCandidatesOptions = {},
): Promise<CandidateListPayload> {
  const params: Record<string, string | number> = {
    limit: opts.limit ?? 20,
    offset: opts.offset ?? 0,
  };
  if (opts.workspaceId) params.workspace_id = opts.workspaceId;
  if (opts.projectId) params.project_id = opts.projectId;
  if (opts.status) params.status = opts.status;
  if (opts.memoryType) params.memory_type = opts.memoryType;
  if (opts.sortBy) params.sort_by = opts.sortBy;

  const resp = await client().get<CandidateListPayload>(`${PATH}/candidates`, {
    params,
  });
  return resp.data;
}

// ---------------------------------------------------------------------------
// Transitions (accept / reject / snooze / rollback)
// ---------------------------------------------------------------------------

type TransitionAction = 'accept' | 'reject' | 'snooze' | 'rollback';

async function _transition(
  candidateId: string,
  action: TransitionAction,
  body: CandidateDecisionRequest = {},
): Promise<CandidateDecisionPayload> {
  const resp = await client().post<CandidateDecisionPayload>(
    `${PATH}/candidates/${encodeURIComponent(candidateId)}/${action}`,
    body,
  );
  return resp.data;
}

export function acceptCandidate(
  candidateId: string,
  decisionReason?: string,
): Promise<CandidateDecisionPayload> {
  return _transition(candidateId, 'accept', { decision_reason: decisionReason });
}

export function rejectCandidate(
  candidateId: string,
  decisionReason?: string,
): Promise<CandidateDecisionPayload> {
  return _transition(candidateId, 'reject', {
    decision_reason: decisionReason ?? REJECT_REASON_TAG,
  });
}

export function snoozeCandidate(
  candidateId: string,
  decisionReason?: string,
): Promise<CandidateDecisionPayload> {
  return _transition(candidateId, 'snooze', {
    decision_reason: decisionReason ?? SNOOZE_REASON_TAG,
  });
}

export interface RollbackCandidateOptions {
  decisionReason?: string;
  rollbackRef?: string;
}

export function rollbackCandidate(
  candidateId: string,
  options: RollbackCandidateOptions = {},
): Promise<CandidateDecisionPayload> {
  return _transition(candidateId, 'rollback', {
    decision_reason: options.decisionReason,
    rollback_ref: options.rollbackRef,
  });
}

// ---------------------------------------------------------------------------
// Promote (no request body — backend infers target from memory_type)
// ---------------------------------------------------------------------------

export async function promoteCandidate(
  candidateId: string,
): Promise<CandidatePromotionPayload> {
  const resp = await client().post<CandidatePromotionPayload>(
    `${PATH}/candidates/${encodeURIComponent(candidateId)}/promote`,
  );
  return resp.data;
}

// ---------------------------------------------------------------------------
// Curator maintenance
// ---------------------------------------------------------------------------

export async function runCurator(workspaceId?: string): Promise<CuratorRunPayload> {
  const params: Record<string, string> = {};
  if (workspaceId) params.workspace_id = workspaceId;
  const resp = await client().post<CuratorRunPayload>(
    `${PATH}/curate/run`,
    undefined,
    { params },
  );
  return resp.data;
}

// ---------------------------------------------------------------------------
// Audit roll-up
// ---------------------------------------------------------------------------

export interface GetEvolutionAuditOptions {
  workspaceId?: string;
  /** Backend clamps to [0, 50]; default 10. Passing 0 returns an empty
   *  `recent_decisions` list but still returns the counts. */
  recentDecisionLimit?: number;
}

export async function getEvolutionAudit(
  opts: GetEvolutionAuditOptions = {},
): Promise<EvolutionAuditPayload> {
  const params: Record<string, string | number> = {};
  if (opts.workspaceId) params.workspace_id = opts.workspaceId;
  if (opts.recentDecisionLimit !== undefined) {
    params.recent_decision_limit = opts.recentDecisionLimit;
  }
  const resp = await client().get<EvolutionAuditPayload>(`${PATH}/audit`, {
    params,
  });
  return resp.data;
}

// ---------------------------------------------------------------------------
// Re-exports for consumer ergonomics
// ---------------------------------------------------------------------------

export type {
  CandidateDecisionPayload,
  CandidateListPayload,
  CandidatePromotionPayload,
  CuratorRunPayload,
  EvolutionAuditPayload,
  EvolutionStatusPayload,
};
