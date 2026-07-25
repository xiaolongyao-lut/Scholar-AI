export const VISUAL_OBSERVATION_REF_SCHEMA_VERSION = 'scholar-ai-visual-observation-ref/v1' as const;
export const VISUAL_OBSERVATION_MAX_COUNT = 12;
export const VISUAL_OBSERVATION_LIFECYCLE_REQUEST_SCHEMA_VERSION = 'scholar-ai-visual-observation-lifecycle-request/v1' as const;

export type VisualObservationRoute = 'direct_model' | 'vision_aux_mcp';
export type VisualObservationGenerationStatus = 'succeeded' | 'failed';
export type VisualObservationReviewStatus = 'candidate' | 'accepted' | 'rejected' | 'withdrawn';
export type VisualObservationFreshnessStatus = 'fresh' | 'stale';
export type VisualObservationReferenceReviewStatus = VisualObservationReviewStatus | 'stale';
export type VisualObservationCacheStatus = 'hit' | 'miss' | 'bypassed' | 'unavailable';
export type VisualObservationLifecycleAxis = 'review' | 'freshness';

export interface VisualObservationLifecycleTransitionInput {
  operationId: string;
  expectedReviewStatus: VisualObservationReviewStatus;
  expectedFreshnessStatus: VisualObservationFreshnessStatus;
  targetReviewStatus?: Exclude<VisualObservationReviewStatus, 'candidate'>;
  targetFreshnessStatus?: VisualObservationFreshnessStatus;
  reason: string;
  changedBy: string;
}

export interface VisualObservationLifecycleRequest {
  schema_version: typeof VISUAL_OBSERVATION_LIFECYCLE_REQUEST_SCHEMA_VERSION;
  operation_id: string;
  expected_review_status: VisualObservationReviewStatus;
  expected_freshness_status: VisualObservationFreshnessStatus;
  target_review_status?: Exclude<VisualObservationReviewStatus, 'candidate'>;
  target_freshness_status?: VisualObservationFreshnessStatus;
  reason: string;
  changed_by: string;
}

export interface VisualObservationReference {
  schema_version: typeof VISUAL_OBSERVATION_REF_SCHEMA_VERSION;
  candidate_id: string;
  turn_id: string;
  route: VisualObservationRoute;
  generation_status: VisualObservationGenerationStatus;
  review_status: VisualObservationReferenceReviewStatus;
  selection_ids: string[];
  output_sha256?: string;
  cache_status: VisualObservationCacheStatus;
  cache_key_hash?: string;
  read_endpoint: string;
}

const REFERENCE_KEYS = new Set([
  'schema_version',
  'candidate_id',
  'turn_id',
  'route',
  'generation_status',
  'review_status',
  'selection_ids',
  'output_sha256',
  'cache_status',
  'cache_key_hash',
  'read_endpoint',
]);
const IDENTIFIER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOnlyReferenceKeys(value: Record<string, unknown>): boolean {
  return Object.keys(value).every((key) => REFERENCE_KEYS.has(key));
}

function readIdentifier(value: unknown): string | null {
  return typeof value === 'string' && IDENTIFIER_PATTERN.test(value) ? value : null;
}

function readOptionalHash(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return undefined;
  return typeof value === 'string' && SHA256_PATTERN.test(value) ? value : null;
}

function readSelectionIds(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > VISUAL_OBSERVATION_MAX_COUNT) return null;
  const ids: string[] = [];
  for (const item of value) {
    const id = readIdentifier(item);
    if (!id || ids.includes(id)) return null;
    ids.push(id);
  }
  return ids;
}

/**
 * Validate one output-free visual observation reference crossing an API or
 * persistence boundary. Unknown fields are rejected instead of copied so
 * model output, encoded pixels, request indexes, and private paths cannot
 * hitchhike inside a normal chat message.
 */
export function parseVisualObservationReference(value: unknown): VisualObservationReference | null {
  if (!isRecord(value) || !hasOnlyReferenceKeys(value)) return null;
  if (value.schema_version !== VISUAL_OBSERVATION_REF_SCHEMA_VERSION) return null;

  const candidateId = readIdentifier(value.candidate_id);
  const turnId = readIdentifier(value.turn_id);
  const selectionIds = readSelectionIds(value.selection_ids);
  const outputSha256 = readOptionalHash(value.output_sha256);
  const cacheKeyHash = readOptionalHash(value.cache_key_hash);
  if (!candidateId || !turnId || selectionIds === null || outputSha256 === null || cacheKeyHash === null) {
    return null;
  }
  if (value.route !== 'direct_model' && value.route !== 'vision_aux_mcp') return null;
  if (value.generation_status !== 'succeeded' && value.generation_status !== 'failed') return null;
  if (
    value.review_status !== 'candidate'
    && value.review_status !== 'accepted'
    && value.review_status !== 'rejected'
    && value.review_status !== 'withdrawn'
    && value.review_status !== 'stale'
  ) {
    return null;
  }
  if (
    value.cache_status !== 'hit'
    && value.cache_status !== 'miss'
    && value.cache_status !== 'bypassed'
    && value.cache_status !== 'unavailable'
  ) {
    return null;
  }
  if (value.generation_status === 'succeeded' && !outputSha256) return null;
  if (value.generation_status === 'failed' && outputSha256) return null;
  if (value.cache_status === 'hit' && !cacheKeyHash) return null;

  const expectedEndpoint = `/api/chat/visual-observations/${candidateId}`;
  if (value.read_endpoint !== expectedEndpoint) return null;

  return {
    schema_version: VISUAL_OBSERVATION_REF_SCHEMA_VERSION,
    candidate_id: candidateId,
    turn_id: turnId,
    route: value.route,
    generation_status: value.generation_status,
    review_status: value.review_status,
    selection_ids: selectionIds,
    ...(outputSha256 ? { output_sha256: outputSha256 } : {}),
    cache_status: value.cache_status,
    ...(cacheKeyHash ? { cache_key_hash: cacheKeyHash } : {}),
    read_endpoint: expectedEndpoint,
  };
}

/** Validate a bounded list and drop malformed or duplicate candidates independently. */
export function sanitizeVisualObservationReferences(value: unknown): VisualObservationReference[] {
  if (!Array.isArray(value)) return [];
  const references: VisualObservationReference[] = [];
  const candidateIds = new Set<string>();
  for (const item of value.slice(0, VISUAL_OBSERVATION_MAX_COUNT)) {
    const reference = parseVisualObservationReference(item);
    if (!reference || candidateIds.has(reference.candidate_id)) continue;
    candidateIds.add(reference.candidate_id);
    references.push(reference);
  }
  return references;
}
