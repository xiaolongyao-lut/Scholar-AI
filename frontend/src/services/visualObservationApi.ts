import axios from 'axios';

import { getApiBaseUrl } from './apiBaseUrl';
import {
  VISUAL_OBSERVATION_LIFECYCLE_REQUEST_SCHEMA_VERSION,
  parseVisualObservationReference,
  type VisualObservationCacheStatus,
  type VisualObservationFreshnessStatus,
  type VisualObservationGenerationStatus,
  type VisualObservationLifecycleAxis,
  type VisualObservationLifecycleRequest,
  type VisualObservationLifecycleTransitionInput,
  type VisualObservationReference,
  type VisualObservationReviewStatus,
  type VisualObservationRoute,
} from '@/types/visualObservation';

const VISUAL_OBSERVATION_SCHEMA_VERSION = 'scholar-ai-visual-observation/v1';
const VISUAL_OBSERVATION_EVENT_SCHEMA_VERSION = 'scholar-ai-visual-lifecycle-event/v1';
const VISUAL_OBSERVATION_RECEIPT_SCHEMA_VERSION = 'scholar-ai-visual-lifecycle-receipt/v1';
const IDENTIFIER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/;
const ERROR_CODE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/;
const UNSAFE_ERROR_TEXT_PATTERN = /(?:[A-Za-z]:[\\/]|(?:https?|file|data):\/\/|authorization|api[_-]?key|access[_-]?token|bearer\s|client[_-]?secret|private[_-]?key)/i;
const CANDIDATE_KEYS = new Set([
  'schema_version',
  'candidate_id',
  'run_id',
  'session_id',
  'turn_id',
  'order',
  'route',
  'output_scope',
  'project_id',
  'selection_ids',
  'image_inputs',
  'producer',
  'request_sha256',
  'cache_status',
  'cache_key_hash',
  'generation_status',
  'review_status',
  'freshness_status',
  'output_text',
  'output_sha256',
  'error',
  'source_fingerprints',
  'created_at',
  'updated_at',
]);
const IMAGE_INPUT_KEYS = new Set([
  'image_id',
  'content_sha256',
  'mime',
  'size',
  'selection_ids',
  'derived_artifact_ref',
  'artifact_sha256',
]);
const PRODUCER_KEYS = new Set([
  'provider',
  'model',
  'model_version',
  'tool_name',
  'tool_version',
  'server_slug',
  'server_id',
  'server_fingerprint',
  'fingerprint_version',
]);
const ERROR_KEYS = new Set(['code', 'message', 'recoverable']);
const EVENT_KEYS = new Set([
  'schema_version',
  'event_id',
  'operation_id',
  'candidate_id',
  'session_id',
  'project_id',
  'axis',
  'from_status',
  'to_status',
  'previous_review_status',
  'previous_freshness_status',
  'result_review_status',
  'result_freshness_status',
  'reason',
  'changed_by',
  'occurred_at',
  'source_revision_receipt_id',
  'source_revision_operation',
  'source_revision',
  'source_revision_impact_fingerprint',
]);
const RECEIPT_KEYS = new Set([
  'schema_version',
  'receipt_id',
  'operation_id',
  'request_sha256',
  'event_id',
  'candidate_id',
  'session_id',
  'project_id',
  'axis',
  'from_status',
  'to_status',
  'previous_review_status',
  'previous_freshness_status',
  'result_review_status',
  'result_freshness_status',
  'reason',
  'changed_by',
  'occurred_at',
]);
const SOURCE_REVISION_KEYS = new Set([
  'previous_source_fingerprint',
  'current_source_fingerprint',
]);
const MUTATION_RESPONSE_KEYS = new Set(['candidate', 'event', 'receipt', 'replayed']);
const ALLOWED_IMAGE_MIME = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);

export interface VisualObservationDetailError {
  code: string;
  message: string;
  recoverable: boolean;
}

export interface VisualObservationDetail {
  candidateId: string;
  sessionId: string;
  projectId?: string;
  turnId: string;
  route: VisualObservationRoute;
  generationStatus: VisualObservationGenerationStatus;
  reviewStatus: VisualObservationReviewStatus;
  freshnessStatus: VisualObservationFreshnessStatus;
  selectionIds: string[];
  updatedAt: string;
  outputText?: string;
  error?: VisualObservationDetailError;
}

export interface VisualObservationLifecycleReceiptSummary {
  axis: VisualObservationLifecycleAxis;
  previousReviewStatus: VisualObservationReviewStatus;
  previousFreshnessStatus: VisualObservationFreshnessStatus;
  resultReviewStatus: VisualObservationReviewStatus;
  resultFreshnessStatus: VisualObservationFreshnessStatus;
  occurredAt: string;
}

export interface VisualObservationLifecycleMutation {
  candidate: VisualObservationDetail;
  receipt: VisualObservationLifecycleReceiptSummary;
  replayed: boolean;
}

interface ParsedCandidate extends VisualObservationDetail {
  cacheStatus: VisualObservationCacheStatus;
  cacheKeyHash?: string;
  outputSha256?: string;
}

interface ParsedLifecycleRecord {
  recordId: string;
  operationId: string;
  eventId: string;
  candidateId: string;
  sessionId: string;
  projectId?: string;
  axis: VisualObservationLifecycleAxis;
  fromStatus: string;
  toStatus: string;
  previousReviewStatus: VisualObservationReviewStatus;
  previousFreshnessStatus: VisualObservationFreshnessStatus;
  resultReviewStatus: VisualObservationReviewStatus;
  resultFreshnessStatus: VisualObservationFreshnessStatus;
  reason: string;
  changedBy: string;
  occurredAt: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function assertOnlyKeys(value: Record<string, unknown>, allowed: ReadonlySet<string>, context: string): void {
  if (Object.keys(value).some((key) => !allowed.has(key))) {
    throw new Error(`Invalid ${context}: unexpected field`);
  }
}

function readBoundedString(value: unknown, context: string, maxLength: number): string {
  if (typeof value !== 'string') throw new Error(`Invalid ${context}`);
  const normalized = value.trim();
  if (!normalized || normalized.length > maxLength) throw new Error(`Invalid ${context}`);
  return normalized;
}

function readOptionalBoundedString(value: unknown, context: string, maxLength: number): string | undefined {
  if (value === undefined || value === null) return undefined;
  return readBoundedString(value, context, maxLength);
}

function readIdentifier(value: unknown, context: string, maxLength = 256): string {
  const normalized = readBoundedString(value, context, maxLength);
  if (!IDENTIFIER_PATTERN.test(normalized)) throw new Error(`Invalid ${context}`);
  return normalized;
}

function readOptionalIdentifier(value: unknown, context: string, maxLength = 256): string | undefined {
  if (value === undefined || value === null) return undefined;
  return readIdentifier(value, context, maxLength);
}

function readHash(value: unknown, context: string): string {
  const normalized = readBoundedString(value, context, 71).toLowerCase();
  if (!SHA256_PATTERN.test(normalized)) throw new Error(`Invalid ${context}`);
  return normalized;
}

function readOptionalHash(value: unknown, context: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  return readHash(value, context);
}

function readTimestamp(value: unknown, context: string): string {
  const timestamp = readBoundedString(value, context, 64);
  if (Number.isNaN(Date.parse(timestamp))) throw new Error(`Invalid ${context}`);
  return timestamp;
}

function readReviewStatus(value: unknown, context: string): VisualObservationReviewStatus {
  if (value === 'candidate' || value === 'accepted' || value === 'rejected' || value === 'withdrawn') {
    return value;
  }
  throw new Error(`Invalid ${context}`);
}

function readFreshnessStatus(value: unknown, context: string): VisualObservationFreshnessStatus {
  if (value === 'fresh' || value === 'stale') return value;
  throw new Error(`Invalid ${context}`);
}

function readGenerationStatus(value: unknown): VisualObservationGenerationStatus {
  if (value === 'succeeded' || value === 'failed') return value;
  throw new Error('Invalid visual observation generation status');
}

function readRoute(value: unknown): VisualObservationRoute {
  if (value === 'direct_model' || value === 'vision_aux_mcp') return value;
  throw new Error('Invalid visual observation route');
}

function readCacheStatus(value: unknown): VisualObservationCacheStatus {
  if (value === 'hit' || value === 'miss' || value === 'bypassed' || value === 'unavailable') {
    return value;
  }
  throw new Error('Invalid visual observation cache status');
}

function readAxis(value: unknown): VisualObservationLifecycleAxis {
  if (value === 'review' || value === 'freshness') return value;
  throw new Error('Invalid visual observation lifecycle axis');
}

function readSelectionIds(value: unknown, context: string, maxCount = 12): string[] {
  if (!Array.isArray(value) || value.length > maxCount) throw new Error(`Invalid ${context}`);
  const identifiers = value.map((item) => readIdentifier(item, context));
  if (new Set(identifiers).size !== identifiers.length) throw new Error(`Invalid ${context}`);
  return identifiers;
}

function arraysEqual(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function parseSafeError(value: unknown): VisualObservationDetailError {
  if (!isRecord(value)) throw new Error('Invalid visual observation error');
  assertOnlyKeys(value, ERROR_KEYS, 'visual observation error');
  const code = readBoundedString(value.code, 'visual observation error code', 96);
  const rawMessage = readBoundedString(value.message, 'visual observation error message', 500)
    .replaceAll('\0', '');
  if (!ERROR_CODE_PATTERN.test(code) || typeof value.recoverable !== 'boolean') {
    throw new Error('Invalid visual observation error');
  }
  return {
    code,
    message: UNSAFE_ERROR_TEXT_PATTERN.test(rawMessage)
      ? '视觉观察失败详情已隐藏。'
      : rawMessage,
    recoverable: value.recoverable,
  };
}

function parseImageInputs(value: unknown): void {
  if (!Array.isArray(value) || value.length < 1 || value.length > 6) {
    throw new Error('Invalid visual observation image inputs');
  }
  value.forEach((item) => {
    if (!isRecord(item)) throw new Error('Invalid visual observation image input');
    assertOnlyKeys(item, IMAGE_INPUT_KEYS, 'visual observation image input');
    readIdentifier(item.image_id, 'visual observation image id', 128);
    readHash(item.content_sha256, 'visual observation image hash');
    if (typeof item.mime !== 'string' || !ALLOWED_IMAGE_MIME.has(item.mime)) {
      throw new Error('Invalid visual observation image MIME');
    }
    if (!Number.isInteger(item.size) || Number(item.size) < 1 || Number(item.size) > 32 * 1024 * 1024) {
      throw new Error('Invalid visual observation image size');
    }
    readSelectionIds(item.selection_ids, 'visual observation image selection ids');
    const artifactRef = readOptionalBoundedString(
      item.derived_artifact_ref,
      'visual observation artifact reference',
      500,
    );
    if (
      artifactRef
      && (
        artifactRef.startsWith('/')
        || artifactRef.startsWith('\\')
        || artifactRef.includes('\\')
        || artifactRef.includes(':')
        || artifactRef.split('/').some((part) => !part || part === '.' || part === '..')
      )
    ) {
      throw new Error('Invalid visual observation artifact reference');
    }
    readOptionalHash(item.artifact_sha256, 'visual observation artifact hash');
  });
}

function parseProducer(value: unknown): void {
  if (!isRecord(value)) throw new Error('Invalid visual observation producer');
  assertOnlyKeys(value, PRODUCER_KEYS, 'visual observation producer');
  for (const key of PRODUCER_KEYS) {
    if (key === 'server_fingerprint') {
      readOptionalHash(value[key], 'visual observation producer fingerprint');
    } else {
      readOptionalBoundedString(value[key], `visual observation producer ${key}`, 200);
    }
  }
}

function parseSourceFingerprints(value: unknown): void {
  if (!Array.isArray(value) || value.length > 12) {
    throw new Error('Invalid visual observation source fingerprints');
  }
  const fingerprints = value.map((item) => readHash(item, 'visual observation source fingerprint'));
  if (new Set(fingerprints).size !== fingerprints.length) {
    throw new Error('Invalid visual observation source fingerprints');
  }
}

function parseCandidate(
  value: unknown,
  expectedCandidateId?: string,
  reference?: VisualObservationReference,
): ParsedCandidate {
  if (!isRecord(value)) throw new Error('Invalid visual observation detail response');
  assertOnlyKeys(value, CANDIDATE_KEYS, 'visual observation detail response');
  if (value.schema_version !== VISUAL_OBSERVATION_SCHEMA_VERSION) {
    throw new Error('Invalid visual observation detail response');
  }

  const candidateId = readIdentifier(value.candidate_id, 'visual observation candidate id');
  readIdentifier(value.run_id, 'visual observation run id');
  const sessionId = readIdentifier(value.session_id, 'visual observation session id');
  const turnId = readIdentifier(value.turn_id, 'visual observation turn id');
  if (!Number.isInteger(value.order) || Number(value.order) < 0 || Number(value.order) >= 12) {
    throw new Error('Invalid visual observation order');
  }
  const route = readRoute(value.route);
  if (
    (route === 'direct_model' && value.output_scope !== 'answer_joint')
    || (route === 'vision_aux_mcp' && value.output_scope !== 'image_note')
  ) {
    throw new Error('Invalid visual observation output scope');
  }
  const projectId = readOptionalIdentifier(value.project_id, 'visual observation project id', 128);
  const selectionIds = readSelectionIds(value.selection_ids, 'visual observation selection ids');
  parseImageInputs(value.image_inputs);
  parseProducer(value.producer);
  readHash(value.request_sha256, 'visual observation request hash');
  const cacheStatus = readCacheStatus(value.cache_status);
  const cacheKeyHash = readOptionalHash(value.cache_key_hash, 'visual observation cache key hash');
  const generationStatus = readGenerationStatus(value.generation_status);
  const reviewStatus = readReviewStatus(value.review_status, 'visual observation review status');
  const freshnessStatus = readFreshnessStatus(value.freshness_status, 'visual observation freshness status');
  const outputText = readOptionalBoundedString(value.output_text, 'visual observation output', 64_000);
  const outputSha256 = readOptionalHash(value.output_sha256, 'visual observation output hash');
  const error = value.error === undefined || value.error === null ? undefined : parseSafeError(value.error);
  parseSourceFingerprints(value.source_fingerprints);
  readTimestamp(value.created_at, 'visual observation created timestamp');
  const updatedAt = readTimestamp(value.updated_at, 'visual observation updated timestamp');

  if (generationStatus === 'succeeded' && (!outputText || !outputSha256 || error)) {
    throw new Error('Invalid visual observation successful outcome');
  }
  if (
    generationStatus === 'failed'
    && (!error || outputText || outputSha256 || cacheStatus !== 'unavailable' || cacheKeyHash)
  ) {
    throw new Error('Invalid visual observation failed outcome');
  }
  if (generationStatus === 'failed' && reviewStatus === 'accepted') {
    throw new Error('Invalid accepted failed visual observation');
  }
  if (cacheStatus === 'hit' && !cacheKeyHash) {
    throw new Error('Invalid visual observation cache hit');
  }
  if (expectedCandidateId && candidateId !== expectedCandidateId) {
    throw new Error('Visual observation detail does not match requested candidate');
  }
  if (reference) {
    if (
      candidateId !== reference.candidate_id
      || turnId !== reference.turn_id
      || route !== reference.route
      || generationStatus !== reference.generation_status
      || cacheStatus !== reference.cache_status
      || outputSha256 !== reference.output_sha256
      || cacheKeyHash !== reference.cache_key_hash
      || !arraysEqual(selectionIds, reference.selection_ids)
    ) {
      throw new Error('Visual observation detail does not match immutable reference fields');
    }
  }

  return {
    candidateId,
    sessionId,
    ...(projectId ? { projectId } : {}),
    turnId,
    route,
    generationStatus,
    reviewStatus,
    freshnessStatus,
    selectionIds,
    updatedAt,
    ...(outputText ? { outputText } : {}),
    ...(error ? { error } : {}),
    cacheStatus,
    ...(cacheKeyHash ? { cacheKeyHash } : {}),
    ...(outputSha256 ? { outputSha256 } : {}),
  };
}

function projectCandidate(candidate: ParsedCandidate): VisualObservationDetail {
  return {
    candidateId: candidate.candidateId,
    sessionId: candidate.sessionId,
    ...(candidate.projectId ? { projectId: candidate.projectId } : {}),
    turnId: candidate.turnId,
    route: candidate.route,
    generationStatus: candidate.generationStatus,
    reviewStatus: candidate.reviewStatus,
    freshnessStatus: candidate.freshnessStatus,
    selectionIds: [...candidate.selectionIds],
    updatedAt: candidate.updatedAt,
    ...(candidate.outputText ? { outputText: candidate.outputText } : {}),
    ...(candidate.error ? { error: candidate.error } : {}),
  };
}

function validateTransitionInput(input: VisualObservationLifecycleTransitionInput): VisualObservationLifecycleRequest {
  const operationId = readIdentifier(input.operationId, 'visual observation operation id');
  const changedBy = readIdentifier(input.changedBy, 'visual observation actor');
  const reason = readBoundedString(input.reason, 'visual observation review reason', 2_000);
  const expectedReviewStatus = readReviewStatus(
    input.expectedReviewStatus,
    'visual observation expected review status',
  );
  const expectedFreshnessStatus = readFreshnessStatus(
    input.expectedFreshnessStatus,
    'visual observation expected freshness status',
  );
  const reviewRequested = input.targetReviewStatus !== undefined;
  const freshnessRequested = input.targetFreshnessStatus !== undefined;
  if (reviewRequested === freshnessRequested) {
    throw new Error('Exactly one visual observation lifecycle target is required');
  }

  if (reviewRequested) {
    const target = readReviewStatus(input.targetReviewStatus, 'visual observation target review status');
    if (target === 'candidate' || target === expectedReviewStatus) {
      throw new Error('Invalid visual observation target review status');
    }
    return {
      schema_version: VISUAL_OBSERVATION_LIFECYCLE_REQUEST_SCHEMA_VERSION,
      operation_id: operationId,
      expected_review_status: expectedReviewStatus,
      expected_freshness_status: expectedFreshnessStatus,
      target_review_status: target,
      reason,
      changed_by: changedBy,
    };
  }

  const target = readFreshnessStatus(
    input.targetFreshnessStatus,
    'visual observation target freshness status',
  );
  if (target === expectedFreshnessStatus) {
    throw new Error('Invalid visual observation target freshness status');
  }
  return {
    schema_version: VISUAL_OBSERVATION_LIFECYCLE_REQUEST_SCHEMA_VERSION,
    operation_id: operationId,
    expected_review_status: expectedReviewStatus,
    expected_freshness_status: expectedFreshnessStatus,
    target_freshness_status: target,
    reason,
    changed_by: changedBy,
  };
}

function parseLifecycleRecord(value: unknown, kind: 'event' | 'receipt'): ParsedLifecycleRecord {
  if (!isRecord(value)) throw new Error(`Invalid visual observation lifecycle ${kind}`);
  assertOnlyKeys(value, kind === 'event' ? EVENT_KEYS : RECEIPT_KEYS, `visual observation lifecycle ${kind}`);
  const expectedSchema = kind === 'event'
    ? VISUAL_OBSERVATION_EVENT_SCHEMA_VERSION
    : VISUAL_OBSERVATION_RECEIPT_SCHEMA_VERSION;
  if (value.schema_version !== expectedSchema) {
    throw new Error(`Invalid visual observation lifecycle ${kind}`);
  }

  const recordId = readIdentifier(
    kind === 'event' ? value.event_id : value.receipt_id,
    `visual observation lifecycle ${kind} id`,
  );
  const operationId = readIdentifier(value.operation_id, 'visual observation lifecycle operation id');
  const eventId = kind === 'event'
    ? recordId
    : readIdentifier(value.event_id, 'visual observation lifecycle receipt event id');
  if (kind === 'receipt') readHash(value.request_sha256, 'visual observation lifecycle request hash');
  const candidateId = readIdentifier(value.candidate_id, 'visual observation lifecycle candidate id');
  const sessionId = readIdentifier(value.session_id, 'visual observation lifecycle session id');
  const projectId = readOptionalIdentifier(value.project_id, 'visual observation lifecycle project id');
  const axis = readAxis(value.axis);
  const fromStatus = readBoundedString(value.from_status, 'visual observation lifecycle from status', 16);
  const toStatus = readBoundedString(value.to_status, 'visual observation lifecycle to status', 16);
  const previousReviewStatus = readReviewStatus(
    value.previous_review_status,
    'visual observation lifecycle previous review status',
  );
  const previousFreshnessStatus = readFreshnessStatus(
    value.previous_freshness_status,
    'visual observation lifecycle previous freshness status',
  );
  const resultReviewStatus = readReviewStatus(
    value.result_review_status,
    'visual observation lifecycle result review status',
  );
  const resultFreshnessStatus = readFreshnessStatus(
    value.result_freshness_status,
    'visual observation lifecycle result freshness status',
  );
  const reason = readBoundedString(value.reason, 'visual observation lifecycle reason', 2_000);
  const changedBy = readIdentifier(value.changed_by, 'visual observation lifecycle actor');
  const occurredAt = readTimestamp(value.occurred_at, 'visual observation lifecycle timestamp');

  const expectedFrom = axis === 'review' ? previousReviewStatus : previousFreshnessStatus;
  const expectedTo = axis === 'review' ? resultReviewStatus : resultFreshnessStatus;
  if (
    fromStatus !== expectedFrom
    || toStatus !== expectedTo
    || fromStatus === toStatus
    || (axis === 'review' && previousFreshnessStatus !== resultFreshnessStatus)
    || (axis === 'freshness' && previousReviewStatus !== resultReviewStatus)
  ) {
    throw new Error(`Invalid visual observation lifecycle ${kind} axes`);
  }

  if (kind === 'event') {
    const sourceFields = [
      value.source_revision_receipt_id,
      value.source_revision_operation,
      value.source_revision,
      value.source_revision_impact_fingerprint,
    ];
    const hasSourceRevision = sourceFields.some((item) => item !== undefined && item !== null);
    if (hasSourceRevision) {
      readIdentifier(value.source_revision_receipt_id, 'visual source revision receipt id');
      if (value.source_revision_operation !== 'mark_stale' && value.source_revision_operation !== 'revalidate') {
        throw new Error('Invalid visual source revision operation');
      }
      if (!isRecord(value.source_revision)) throw new Error('Invalid visual source revision identity');
      assertOnlyKeys(value.source_revision, SOURCE_REVISION_KEYS, 'visual source revision identity');
      readHash(value.source_revision.previous_source_fingerprint, 'visual source previous fingerprint');
      readHash(value.source_revision.current_source_fingerprint, 'visual source current fingerprint');
      readHash(value.source_revision_impact_fingerprint, 'visual source revision impact fingerprint');
      if (axis !== 'freshness') throw new Error('Invalid visual source revision lifecycle axis');
    }
  }

  return {
    recordId,
    operationId,
    eventId,
    candidateId,
    sessionId,
    ...(projectId ? { projectId } : {}),
    axis,
    fromStatus,
    toStatus,
    previousReviewStatus,
    previousFreshnessStatus,
    resultReviewStatus,
    resultFreshnessStatus,
    reason,
    changedBy,
    occurredAt,
  };
}

function parseMutationResponse(
  value: unknown,
  candidate: VisualObservationDetail,
  request: VisualObservationLifecycleRequest,
): VisualObservationLifecycleMutation {
  if (!isRecord(value)) throw new Error('Invalid visual observation lifecycle response');
  assertOnlyKeys(value, MUTATION_RESPONSE_KEYS, 'visual observation lifecycle response');
  if (typeof value.replayed !== 'boolean') {
    throw new Error('Invalid visual observation lifecycle response replay state');
  }
  const authoritativeCandidate = parseCandidate(value.candidate, candidate.candidateId);
  const event = parseLifecycleRecord(value.event, 'event');
  const receipt = parseLifecycleRecord(value.receipt, 'receipt');
  const requestedAxis: VisualObservationLifecycleAxis = request.target_review_status ? 'review' : 'freshness';
  const requestedTarget = request.target_review_status ?? request.target_freshness_status;

  if (
    receipt.operationId !== request.operation_id
    || receipt.candidateId !== candidate.candidateId
    || receipt.sessionId !== authoritativeCandidate.sessionId
    || receipt.projectId !== authoritativeCandidate.projectId
    || receipt.axis !== requestedAxis
    || receipt.previousReviewStatus !== request.expected_review_status
    || receipt.previousFreshnessStatus !== request.expected_freshness_status
    || receipt.toStatus !== requestedTarget
    || receipt.reason !== request.reason
    || receipt.changedBy !== request.changed_by
    || receipt.resultReviewStatus !== authoritativeCandidate.reviewStatus
    || receipt.resultFreshnessStatus !== authoritativeCandidate.freshnessStatus
  ) {
    throw new Error('Visual observation lifecycle receipt does not match request or candidate');
  }
  if (
    event.operationId !== receipt.operationId
    || event.eventId !== receipt.eventId
    || event.candidateId !== receipt.candidateId
    || event.sessionId !== receipt.sessionId
    || event.projectId !== receipt.projectId
    || event.axis !== receipt.axis
    || event.fromStatus !== receipt.fromStatus
    || event.toStatus !== receipt.toStatus
    || event.previousReviewStatus !== receipt.previousReviewStatus
    || event.previousFreshnessStatus !== receipt.previousFreshnessStatus
    || event.resultReviewStatus !== receipt.resultReviewStatus
    || event.resultFreshnessStatus !== receipt.resultFreshnessStatus
    || event.reason !== receipt.reason
    || event.changedBy !== receipt.changedBy
    || event.occurredAt !== receipt.occurredAt
  ) {
    throw new Error('Visual observation lifecycle event does not match receipt');
  }

  return {
    candidate: projectCandidate(authoritativeCandidate),
    receipt: {
      axis: receipt.axis,
      previousReviewStatus: receipt.previousReviewStatus,
      previousFreshnessStatus: receipt.previousFreshnessStatus,
      resultReviewStatus: receipt.resultReviewStatus,
      resultFreshnessStatus: receipt.resultFreshnessStatus,
      occurredAt: receipt.occurredAt,
    },
    replayed: value.replayed,
  };
}

function boundedTimeout(timeoutMs: number): number {
  return Number.isFinite(timeoutMs)
    ? Math.max(1, Math.min(60_000, Math.trunc(timeoutMs)))
    : 15_000;
}

/** Read one candidate and return its authoritative current lifecycle state. */
export async function readVisualObservationDetail(
  reference: VisualObservationReference,
  timeoutMs: number = 15_000,
): Promise<VisualObservationDetail> {
  const validatedReference = parseVisualObservationReference(reference);
  if (!validatedReference) throw new Error('Invalid visual observation reference');
  const { data } = await axios.get<unknown>(
    `${getApiBaseUrl()}${validatedReference.read_endpoint}`,
    { timeout: boundedTimeout(timeoutMs) },
  );
  return projectCandidate(parseCandidate(data, validatedReference.candidate_id, validatedReference));
}

/** Commit one dual-axis-CAS lifecycle transition and validate its durable receipt. */
export async function transitionVisualObservation(
  candidate: VisualObservationDetail,
  input: VisualObservationLifecycleTransitionInput,
  timeoutMs: number = 15_000,
): Promise<VisualObservationLifecycleMutation> {
  if (
    candidate.reviewStatus !== input.expectedReviewStatus
    || candidate.freshnessStatus !== input.expectedFreshnessStatus
  ) {
    throw new Error('Visual observation lifecycle input is based on stale candidate state');
  }
  const request = validateTransitionInput(input);
  const { data } = await axios.post<unknown>(
    `${getApiBaseUrl()}/api/chat/visual-observations/${encodeURIComponent(candidate.candidateId)}/transition`,
    request,
    { timeout: boundedTimeout(timeoutMs) },
  );
  return parseMutationResponse(data, candidate, request);
}
