import axios from 'axios';

import { getApiBaseUrl } from './apiBaseUrl';

const API_BASE = getApiBaseUrl();

export type AcquisitionCapability = 'search' | 'download';
export type SearchRunStatus = 'created' | 'running' | 'completed' | 'partial' | 'failed';
export type DownloadJobStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'human_required'
  | 'validating'
  | 'completed'
  | 'failed'
  | 'cancelled';
export type ImportStatus = 'queued' | 'completed' | 'duplicate' | 'failed';
export type ImportReceiptSchemaVersion =
  | 'scholar-ai-import-receipt/v1'
  | 'scholar-ai-import-receipt/v2';
export type ImportPublicationState = 'unverified_legacy' | 'pending' | 'verified' | 'failed';
export type GateStatus = 'open' | 'resolved';
export type DownloadControlAction = 'pause' | 'resume' | 'cancel';

export interface SourcePolicy {
  source_id: string;
  capabilities: AcquisitionCapability[];
  metadata_hosts: string[];
  download_hosts: string[];
  evidence_kinds: Array<'official_repository' | 'oa_api' | 'manual_review'>;
  requires_authentication: boolean;
  enabled: boolean;
  min_interval_seconds: number;
  max_results_per_query: number;
  terms_url: string;
}

export interface SearchQuery {
  project_id: string;
  query: string;
  sources: string[];
  max_results: number;
  year_from: number | null;
  year_to: number | null;
}

export interface AccessEvidence {
  evidence_id: string;
  candidate_id: string;
  source_platform: string;
  kind: 'official_repository' | 'oa_api' | 'manual_review';
  access_route: 'open_access' | 'institution_browser' | 'manual_review' | 'unavailable';
  pdf_url: string;
  statement: string;
  license: string | null;
  observed_at: string;
}

export interface PdfCandidate {
  pdf_url: string;
  source_platform: string;
  access_evidence: AccessEvidence;
}

export interface CandidateManifest {
  candidate_id: string;
  run_id: string;
  project_id: string;
  title: string;
  authors: string[];
  year: number | null;
  published_date: string | null;
  abstract: string | null;
  doi: string | null;
  arxiv_id: string | null;
  source_platforms: string[];
  landing_urls: string[];
  pdf_candidates: PdfCandidate[];
  merged_from_candidate_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface SourceError {
  source_id: string;
  code: string;
  message: string;
}

export interface SearchRun {
  run_id: string;
  query: SearchQuery;
  status: SearchRunStatus;
  requested_sources: string[];
  attempted_sources: string[];
  candidates: CandidateManifest[];
  source_errors: SourceError[];
  version: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface DownloadJob {
  job_id: string;
  project_id: string;
  candidate_id: string;
  access_evidence_id: string;
  source_platform: string;
  source_url: string;
  artifact_path: string;
  status: DownloadJobStatus;
  attempts: number;
  bytes_downloaded: number;
  max_bytes: number;
  version: number;
  error_code: string | null;
  error_message: string | null;
  gate_id: string | null;
  artifact_id: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface HumanAccessGate {
  gate_id: string;
  project_id: string;
  job_id: string | null;
  platform: string;
  gate_type: string;
  url: string;
  message: string;
  status: GateStatus;
  resume_status: DownloadJobStatus;
  next_action: string;
  version: number;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface ImportPublicationEvidence {
  schema_version: 'scholar-ai-import-publication-evidence/v1';
  verifier_version: 'scholar-ai-material-publication-verifier/v1';
  project_id: string;
  material_id: string;
  source_fingerprint: string;
  source_size_bytes: number;
  document_content_sha256: string;
  chunk_manifest_version: 2;
  chunk_manifest_sha256: string;
  chunk_hash_version: string;
  material_chunk_file_sha256: string;
  material_chunk_count: number;
  material_chunk_root_sha256: string;
  chunk_store_version: string;
  fts_schema_version: string;
  fts_chunk_store_version: string;
  fts_indexed_count: number;
  fts_skipped_count: number;
  fts_material_indexed_count: number;
  revision_fingerprint: string;
  revision_receipt_id: string;
  revision_applied_at: string;
  verified_at: string;
  evidence_fingerprint: string;
}

export interface ImportReceipt {
  receipt_id: string;
  artifact_id: string;
  project_id: string;
  candidate_id: string;
  material_id: string;
  status: ImportStatus;
  source_fingerprint: string;
  receipt_schema_version: ImportReceiptSchemaVersion;
  publication_state: ImportPublicationState;
  publication_evidence: ImportPublicationEvidence | null;
  runtime_session_id: string | null;
  runtime_job_id: string | null;
  open_url: string;
  error_message: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export type VerifiedImportReceipt = ImportReceipt & {
  status: 'completed' | 'duplicate';
  receipt_schema_version: 'scholar-ai-import-receipt/v2';
  publication_state: 'verified';
  publication_evidence: ImportPublicationEvidence;
};

export interface AcquisitionStatus {
  sources: SourcePolicy[];
  download_jobs: DownloadJob[];
  gates: HumanAccessGate[];
}

export interface AcquisitionSearchInput {
  projectId: string;
  query: string;
  sources: string[];
  maxResults?: number;
  yearFrom?: number | null;
  yearTo?: number | null;
}

export class AcquisitionApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = 'AcquisitionApiError';
    this.status = status;
    this.code = code;
  }
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new AcquisitionApiError(`${label} must be an object`, 500, 'invalid_response');
  }
  return value as Record<string, unknown>;
}

function readString(record: Record<string, unknown>, key: string, label: string): string {
  const value = record[key];
  if (typeof value !== 'string' || !value.trim()) {
    throw new AcquisitionApiError(`${label}.${key} must be a non-empty string`, 500, 'invalid_response');
  }
  return value;
}

function readNullableString(record: Record<string, unknown>, key: string, label: string): string | null {
  const value = record[key];
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') {
    throw new AcquisitionApiError(`${label}.${key} must be a string or null`, 500, 'invalid_response');
  }
  return value;
}

function readNumber(record: Record<string, unknown>, key: string, label: string): number {
  const value = record[key];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new AcquisitionApiError(`${label}.${key} must be a finite number`, 500, 'invalid_response');
  }
  return value;
}

function readInteger(
  record: Record<string, unknown>,
  key: string,
  label: string,
  minimum: number,
  maximum: number,
): number {
  const value = readNumber(record, key, label);
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new AcquisitionApiError(
      `${label}.${key} must be an integer between ${minimum} and ${maximum}`,
      500,
      'invalid_response',
    );
  }
  return value;
}

function readPrefixedSha256(record: Record<string, unknown>, key: string, label: string): string {
  const value = readString(record, key, label);
  if (!/^sha256:[0-9a-f]{64}$/.test(value)) {
    throw new AcquisitionApiError(`${label}.${key} must be a sha256 fingerprint`, 500, 'invalid_response');
  }
  return value;
}

function readPlainSha256(record: Record<string, unknown>, key: string, label: string): string {
  const value = readString(record, key, label);
  if (!/^[0-9a-f]{64}$/.test(value)) {
    throw new AcquisitionApiError(`${label}.${key} must be a sha256 digest`, 500, 'invalid_response');
  }
  return value;
}

function readChunkManifestVersion(record: Record<string, unknown>, key: string, label: string): 2 {
  readInteger(record, key, label, 2, 2);
  return 2;
}

function readNullableNumber(record: Record<string, unknown>, key: string, label: string): number | null {
  const value = record[key];
  if (value === null || value === undefined) return null;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new AcquisitionApiError(`${label}.${key} must be a number or null`, 500, 'invalid_response');
  }
  return value;
}

function readBoolean(record: Record<string, unknown>, key: string, label: string): boolean {
  const value = record[key];
  if (typeof value !== 'boolean') {
    throw new AcquisitionApiError(`${label}.${key} must be a boolean`, 500, 'invalid_response');
  }
  return value;
}

function readArray(record: Record<string, unknown>, key: string, label: string): unknown[] {
  const value = record[key];
  if (!Array.isArray(value)) {
    throw new AcquisitionApiError(`${label}.${key} must be an array`, 500, 'invalid_response');
  }
  return value;
}

function readStringArray(record: Record<string, unknown>, key: string, label: string): string[] {
  const values = readArray(record, key, label);
  if (values.some((value) => typeof value !== 'string')) {
    throw new AcquisitionApiError(`${label}.${key} must contain strings`, 500, 'invalid_response');
  }
  return values as string[];
}

function readEnum<T extends string>(
  record: Record<string, unknown>,
  key: string,
  label: string,
  allowed: readonly T[],
): T {
  const value = readString(record, key, label);
  if (!allowed.includes(value as T)) {
    throw new AcquisitionApiError(`${label}.${key} is unsupported`, 500, 'invalid_response');
  }
  return value as T;
}

function parseSourcePolicy(value: unknown): SourcePolicy {
  const record = asRecord(value, 'source policy');
  const capabilities = readStringArray(record, 'capabilities', 'source policy');
  const evidenceKinds = readStringArray(record, 'evidence_kinds', 'source policy');
  if (capabilities.some((item) => item !== 'search' && item !== 'download')) {
    throw new AcquisitionApiError('source policy capability is unsupported', 500, 'invalid_response');
  }
  if (evidenceKinds.some((item) => !['official_repository', 'oa_api', 'manual_review'].includes(item))) {
    throw new AcquisitionApiError('source policy evidence kind is unsupported', 500, 'invalid_response');
  }
  return {
    source_id: readString(record, 'source_id', 'source policy'),
    capabilities: capabilities as AcquisitionCapability[],
    metadata_hosts: readStringArray(record, 'metadata_hosts', 'source policy'),
    download_hosts: readStringArray(record, 'download_hosts', 'source policy'),
    evidence_kinds: evidenceKinds as SourcePolicy['evidence_kinds'],
    requires_authentication: readBoolean(record, 'requires_authentication', 'source policy'),
    enabled: readBoolean(record, 'enabled', 'source policy'),
    min_interval_seconds: readNumber(record, 'min_interval_seconds', 'source policy'),
    max_results_per_query: readNumber(record, 'max_results_per_query', 'source policy'),
    terms_url: readString(record, 'terms_url', 'source policy'),
  };
}

function parseSearchQuery(value: unknown): SearchQuery {
  const record = asRecord(value, 'search query');
  return {
    project_id: readString(record, 'project_id', 'search query'),
    query: readString(record, 'query', 'search query'),
    sources: readStringArray(record, 'sources', 'search query'),
    max_results: readNumber(record, 'max_results', 'search query'),
    year_from: readNullableNumber(record, 'year_from', 'search query'),
    year_to: readNullableNumber(record, 'year_to', 'search query'),
  };
}

function parseAccessEvidence(value: unknown): AccessEvidence {
  const record = asRecord(value, 'access evidence');
  return {
    evidence_id: readString(record, 'evidence_id', 'access evidence'),
    candidate_id: readString(record, 'candidate_id', 'access evidence'),
    source_platform: readString(record, 'source_platform', 'access evidence'),
    kind: readEnum(record, 'kind', 'access evidence', ['official_repository', 'oa_api', 'manual_review']),
    access_route: readEnum(
      record,
      'access_route',
      'access evidence',
      ['open_access', 'institution_browser', 'manual_review', 'unavailable'],
    ),
    pdf_url: readString(record, 'pdf_url', 'access evidence'),
    statement: readString(record, 'statement', 'access evidence'),
    license: readNullableString(record, 'license', 'access evidence'),
    observed_at: readString(record, 'observed_at', 'access evidence'),
  };
}

function parsePdfCandidate(value: unknown): PdfCandidate {
  const record = asRecord(value, 'PDF candidate');
  return {
    pdf_url: readString(record, 'pdf_url', 'PDF candidate'),
    source_platform: readString(record, 'source_platform', 'PDF candidate'),
    access_evidence: parseAccessEvidence(record.access_evidence),
  };
}

export function parseCandidateManifest(value: unknown): CandidateManifest {
  const record = asRecord(value, 'candidate');
  return {
    candidate_id: readString(record, 'candidate_id', 'candidate'),
    run_id: readString(record, 'run_id', 'candidate'),
    project_id: readString(record, 'project_id', 'candidate'),
    title: readString(record, 'title', 'candidate'),
    authors: readStringArray(record, 'authors', 'candidate'),
    year: readNullableNumber(record, 'year', 'candidate'),
    published_date: readNullableString(record, 'published_date', 'candidate'),
    abstract: readNullableString(record, 'abstract', 'candidate'),
    doi: readNullableString(record, 'doi', 'candidate'),
    arxiv_id: readNullableString(record, 'arxiv_id', 'candidate'),
    source_platforms: readStringArray(record, 'source_platforms', 'candidate'),
    landing_urls: readStringArray(record, 'landing_urls', 'candidate'),
    pdf_candidates: readArray(record, 'pdf_candidates', 'candidate').map(parsePdfCandidate),
    merged_from_candidate_ids: readStringArray(record, 'merged_from_candidate_ids', 'candidate'),
    created_at: readString(record, 'created_at', 'candidate'),
    updated_at: readString(record, 'updated_at', 'candidate'),
  };
}

function parseSourceError(value: unknown): SourceError {
  const record = asRecord(value, 'source error');
  return {
    source_id: readString(record, 'source_id', 'source error'),
    code: readString(record, 'code', 'source error'),
    message: readString(record, 'message', 'source error'),
  };
}

export function parseSearchRun(value: unknown): SearchRun {
  const record = asRecord(value, 'search run');
  return {
    run_id: readString(record, 'run_id', 'search run'),
    query: parseSearchQuery(record.query),
    status: readEnum(record, 'status', 'search run', ['created', 'running', 'completed', 'partial', 'failed']),
    requested_sources: readStringArray(record, 'requested_sources', 'search run'),
    attempted_sources: readStringArray(record, 'attempted_sources', 'search run'),
    candidates: readArray(record, 'candidates', 'search run').map(parseCandidateManifest),
    source_errors: readArray(record, 'source_errors', 'search run').map(parseSourceError),
    version: readNumber(record, 'version', 'search run'),
    created_at: readString(record, 'created_at', 'search run'),
    updated_at: readString(record, 'updated_at', 'search run'),
    completed_at: readNullableString(record, 'completed_at', 'search run'),
  };
}

export function parseDownloadJob(value: unknown): DownloadJob {
  const record = asRecord(value, 'download job');
  return {
    job_id: readString(record, 'job_id', 'download job'),
    project_id: readString(record, 'project_id', 'download job'),
    candidate_id: readString(record, 'candidate_id', 'download job'),
    access_evidence_id: readString(record, 'access_evidence_id', 'download job'),
    source_platform: readString(record, 'source_platform', 'download job'),
    source_url: readString(record, 'source_url', 'download job'),
    artifact_path: readString(record, 'artifact_path', 'download job'),
    status: readEnum(
      record,
      'status',
      'download job',
      ['queued', 'running', 'paused', 'human_required', 'validating', 'completed', 'failed', 'cancelled'],
    ),
    attempts: readNumber(record, 'attempts', 'download job'),
    bytes_downloaded: readNumber(record, 'bytes_downloaded', 'download job'),
    max_bytes: readNumber(record, 'max_bytes', 'download job'),
    version: readNumber(record, 'version', 'download job'),
    error_code: readNullableString(record, 'error_code', 'download job'),
    error_message: readNullableString(record, 'error_message', 'download job'),
    gate_id: readNullableString(record, 'gate_id', 'download job'),
    artifact_id: readNullableString(record, 'artifact_id', 'download job'),
    created_at: readString(record, 'created_at', 'download job'),
    updated_at: readString(record, 'updated_at', 'download job'),
    started_at: readNullableString(record, 'started_at', 'download job'),
    completed_at: readNullableString(record, 'completed_at', 'download job'),
  };
}

export function parseHumanAccessGate(value: unknown): HumanAccessGate {
  const record = asRecord(value, 'access gate');
  return {
    gate_id: readString(record, 'gate_id', 'access gate'),
    project_id: readString(record, 'project_id', 'access gate'),
    job_id: readNullableString(record, 'job_id', 'access gate'),
    platform: readString(record, 'platform', 'access gate'),
    gate_type: readString(record, 'gate_type', 'access gate'),
    url: readString(record, 'url', 'access gate'),
    message: readString(record, 'message', 'access gate'),
    status: readEnum(record, 'status', 'access gate', ['open', 'resolved']),
    resume_status: readEnum(
      record,
      'resume_status',
      'access gate',
      ['queued', 'running', 'paused', 'human_required', 'validating', 'completed', 'failed', 'cancelled'],
    ),
    next_action: readString(record, 'next_action', 'access gate'),
    version: readNumber(record, 'version', 'access gate'),
    created_at: readString(record, 'created_at', 'access gate'),
    updated_at: readString(record, 'updated_at', 'access gate'),
    resolved_at: readNullableString(record, 'resolved_at', 'access gate'),
  };
}

function parseImportPublicationEvidence(value: unknown): ImportPublicationEvidence {
  const label = 'import publication evidence';
  const record = asRecord(value, label);
  const evidence: ImportPublicationEvidence = {
    schema_version: readEnum(record, 'schema_version', label, ['scholar-ai-import-publication-evidence/v1']),
    verifier_version: readEnum(record, 'verifier_version', label, ['scholar-ai-material-publication-verifier/v1']),
    project_id: readString(record, 'project_id', label),
    material_id: readString(record, 'material_id', label),
    source_fingerprint: readPrefixedSha256(record, 'source_fingerprint', label),
    source_size_bytes: readInteger(record, 'source_size_bytes', label, 4096, 1_099_511_627_776),
    document_content_sha256: readPrefixedSha256(record, 'document_content_sha256', label),
    chunk_manifest_version: readChunkManifestVersion(record, 'chunk_manifest_version', label),
    chunk_manifest_sha256: readPrefixedSha256(record, 'chunk_manifest_sha256', label),
    chunk_hash_version: readString(record, 'chunk_hash_version', label),
    material_chunk_file_sha256: readPrefixedSha256(record, 'material_chunk_file_sha256', label),
    material_chunk_count: readInteger(record, 'material_chunk_count', label, 1, 10_000_000),
    material_chunk_root_sha256: readPrefixedSha256(record, 'material_chunk_root_sha256', label),
    chunk_store_version: readPlainSha256(record, 'chunk_store_version', label),
    fts_schema_version: readString(record, 'fts_schema_version', label),
    fts_chunk_store_version: readPlainSha256(record, 'fts_chunk_store_version', label),
    fts_indexed_count: readInteger(record, 'fts_indexed_count', label, 1, 100_000_000),
    fts_skipped_count: readInteger(record, 'fts_skipped_count', label, 0, 100_000_000),
    fts_material_indexed_count: readInteger(record, 'fts_material_indexed_count', label, 1, 10_000_000),
    revision_fingerprint: readPrefixedSha256(record, 'revision_fingerprint', label),
    revision_receipt_id: readString(record, 'revision_receipt_id', label),
    revision_applied_at: readString(record, 'revision_applied_at', label),
    verified_at: readString(record, 'verified_at', label),
    evidence_fingerprint: readPrefixedSha256(record, 'evidence_fingerprint', label),
  };
  if (
    evidence.fts_chunk_store_version !== evidence.chunk_store_version
    || evidence.fts_material_indexed_count !== evidence.material_chunk_count
    || evidence.fts_indexed_count < evidence.fts_material_indexed_count
  ) {
    throw new AcquisitionApiError(`${label} contains inconsistent index proof`, 500, 'invalid_response');
  }
  return evidence;
}

export function parseImportReceipt(value: unknown): ImportReceipt {
  const record = asRecord(value, 'import receipt');
  const receiptSchemaVersion = readEnum(record, 'receipt_schema_version', 'import receipt', [
    'scholar-ai-import-receipt/v1',
    'scholar-ai-import-receipt/v2',
  ]);
  const publicationState = readEnum(record, 'publication_state', 'import receipt', [
    'unverified_legacy',
    'pending',
    'verified',
    'failed',
  ]);
  const publicationEvidence = record.publication_evidence === null
    ? null
    : parseImportPublicationEvidence(record.publication_evidence);
  const receipt: ImportReceipt = {
    receipt_id: readString(record, 'receipt_id', 'import receipt'),
    artifact_id: readString(record, 'artifact_id', 'import receipt'),
    project_id: readString(record, 'project_id', 'import receipt'),
    candidate_id: readString(record, 'candidate_id', 'import receipt'),
    material_id: readString(record, 'material_id', 'import receipt'),
    status: readEnum(record, 'status', 'import receipt', ['queued', 'completed', 'duplicate', 'failed']),
    source_fingerprint: readPrefixedSha256(record, 'source_fingerprint', 'import receipt'),
    receipt_schema_version: receiptSchemaVersion,
    publication_state: publicationState,
    publication_evidence: publicationEvidence,
    runtime_session_id: readNullableString(record, 'runtime_session_id', 'import receipt'),
    runtime_job_id: readNullableString(record, 'runtime_job_id', 'import receipt'),
    open_url: readString(record, 'open_url', 'import receipt'),
    error_message: readNullableString(record, 'error_message', 'import receipt'),
    version: readNumber(record, 'version', 'import receipt'),
    created_at: readString(record, 'created_at', 'import receipt'),
    updated_at: readString(record, 'updated_at', 'import receipt'),
  };
  if (receipt.receipt_schema_version === 'scholar-ai-import-receipt/v1') {
    if (receipt.publication_state !== 'unverified_legacy' || receipt.publication_evidence !== null) {
      throw new AcquisitionApiError('legacy import receipt cannot claim verified publication', 500, 'invalid_response');
    }
    return receipt;
  }

  const allowedStates: Record<
    ImportStatus,
    readonly ImportPublicationState[]
  > = {
    queued: ['pending'],
    completed: ['pending', 'verified'],
    duplicate: ['pending', 'verified'],
    failed: ['failed'],
  };
  if (!allowedStates[receipt.status].includes(receipt.publication_state)) {
    throw new AcquisitionApiError('import receipt status does not match publication state', 500, 'invalid_response');
  }
  if (receipt.publication_state === 'verified') {
    const evidence = receipt.publication_evidence;
    if (
      evidence === null
      || evidence.project_id !== receipt.project_id
      || evidence.material_id !== receipt.material_id
      || evidence.source_fingerprint !== receipt.source_fingerprint
    ) {
      throw new AcquisitionApiError('verified import receipt has mismatched publication evidence', 500, 'invalid_response');
    }
  } else if (receipt.publication_evidence !== null) {
    throw new AcquisitionApiError('unverified import receipt cannot contain publication evidence', 500, 'invalid_response');
  }
  return receipt;
}

export function isVerifiedImportReceipt(receipt: ImportReceipt): receipt is VerifiedImportReceipt {
  return receipt.receipt_schema_version === 'scholar-ai-import-receipt/v2'
    && receipt.publication_state === 'verified'
    && receipt.publication_evidence !== null
    && (receipt.status === 'completed' || receipt.status === 'duplicate');
}

export function parseAcquisitionStatus(value: unknown): AcquisitionStatus {
  const record = asRecord(value, 'acquisition status');
  return {
    sources: readArray(record, 'sources', 'acquisition status').map(parseSourcePolicy),
    download_jobs: readArray(record, 'download_jobs', 'acquisition status').map(parseDownloadJob),
    gates: readArray(record, 'gates', 'acquisition status').map(parseHumanAccessGate),
  };
}

function normalizedIdentifier(value: string, label: string): string {
  const normalized = value.trim();
  if (!normalized || normalized.length > 256) {
    throw new AcquisitionApiError(`${label} is invalid`, 400, 'invalid_request');
  }
  return normalized;
}

function sanitizedApiMessage(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (!normalized || normalized.length > 240) return null;
  if (/(?:https?:\/\/|[A-Za-z]:[\\/]|\.sqlite|api[_ -]?key|authorization|bearer|token|secret|env=)/i.test(normalized)) {
    return null;
  }
  return normalized;
}

function asApiError(error: unknown, fallback: string): AcquisitionApiError {
  if (error instanceof AcquisitionApiError) return error;
  if (axios.isAxiosError(error)) {
    const status = error.response?.status ?? 0;
    const response = error.response?.data;
    const root = typeof response === 'object' && response !== null && !Array.isArray(response)
      ? response as Record<string, unknown>
      : null;
    const detailValue = root?.detail;
    const detail = typeof detailValue === 'object' && detailValue !== null && !Array.isArray(detailValue)
      ? detailValue as Record<string, unknown>
      : null;
    const code = typeof detail?.code === 'string' ? detail.code : null;
    const message = sanitizedApiMessage(detail?.message) ?? sanitizedApiMessage(detailValue) ?? fallback;
    return new AcquisitionApiError(message, status, code);
  }
  return new AcquisitionApiError(fallback, 0, null);
}

export function acquisitionErrorMessage(error: unknown, fallback = '操作失败，请稍后重试。'): string {
  if (error instanceof AcquisitionApiError) {
    const translations: Record<string, string> = {
      project_not_found: '当前项目不存在，请重新选择项目。',
      candidate_not_found: '检索结果已失效，请重新检索。',
      not_open_access: '该文献没有可核验的开放获取下载依据。',
      evidence_not_allowed: '当前来源不接受这条下载依据。',
      evidence_route_mismatch: '下载地址与开放获取依据不一致。',
      download_not_allowed: '当前来源不允许自动下载。',
      download_not_pauseable: '当前任务不能暂停。',
      download_not_resumable: '只有已暂停的任务可以继续。',
      attempt_limit: '下载重试次数已达上限。',
      artifact_integrity_failed: '文件校验状态已变化，请重新下载。',
      artifact_path_escape: '文件路径校验失败，已停止导入。',
    };
    return error.code ? translations[error.code] ?? error.message : error.message;
  }
  return fallback;
}

export async function getAcquisitionStatus(projectId?: string | null, limit = 100): Promise<AcquisitionStatus> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) {
    throw new AcquisitionApiError('limit must be between 1 and 500', 400, 'invalid_request');
  }
  try {
    const normalizedProjectId = projectId?.trim() ?? '';
    const { data } = await axios.get<unknown>(`${API_BASE}/api/acquisition/status`, {
      params: { ...(normalizedProjectId ? { project_id: normalizedProjectId } : {}), limit },
    });
    return parseAcquisitionStatus(data);
  } catch (error: unknown) {
    throw asApiError(error, '文献获取状态读取失败。');
  }
}

export async function searchAcquisition(input: AcquisitionSearchInput): Promise<SearchRun> {
  const projectId = normalizedIdentifier(input.projectId, 'projectId');
  const query = input.query.trim();
  const sources = [...new Set(input.sources.map((source) => source.trim()).filter(Boolean))];
  const maxResults = input.maxResults ?? 20;
  if (!query || query.length > 1_000 || sources.length < 1 || sources.length > 8) {
    throw new AcquisitionApiError('search input is invalid', 400, 'invalid_request');
  }
  if (!Number.isInteger(maxResults) || maxResults < 1 || maxResults > 200) {
    throw new AcquisitionApiError('maxResults is invalid', 400, 'invalid_request');
  }
  if (input.yearFrom !== null && input.yearFrom !== undefined && input.yearTo !== null && input.yearTo !== undefined && input.yearTo < input.yearFrom) {
    throw new AcquisitionApiError('year range is invalid', 400, 'invalid_request');
  }
  try {
    const { data } = await axios.post<unknown>(`${API_BASE}/api/acquisition/search`, {
      project_id: projectId,
      query,
      sources,
      max_results: maxResults,
      year_from: input.yearFrom ?? null,
      year_to: input.yearTo ?? null,
    });
    return parseSearchRun(data);
  } catch (error: unknown) {
    throw asApiError(error, '文献检索失败。');
  }
}

export async function queueAcquisitionDownload(
  projectId: string,
  candidateId: string,
  accessEvidenceId: string,
): Promise<DownloadJob> {
  try {
    const { data } = await axios.post<unknown>(`${API_BASE}/api/acquisition/downloads`, {
      project_id: normalizedIdentifier(projectId, 'projectId'),
      candidate_id: normalizedIdentifier(candidateId, 'candidateId'),
      access_evidence_id: normalizedIdentifier(accessEvidenceId, 'accessEvidenceId'),
    });
    return parseDownloadJob(data);
  } catch (error: unknown) {
    throw asApiError(error, '下载任务创建失败。');
  }
}

export async function runAcquisitionDownload(jobId: string): Promise<DownloadJob> {
  try {
    const encoded = encodeURIComponent(normalizedIdentifier(jobId, 'jobId'));
    const { data } = await axios.post<unknown>(`${API_BASE}/api/acquisition/downloads/${encoded}/run`);
    return parseDownloadJob(data);
  } catch (error: unknown) {
    throw asApiError(error, '下载执行失败。');
  }
}

export async function controlAcquisitionDownload(
  jobId: string,
  action: DownloadControlAction,
): Promise<DownloadJob> {
  try {
    const encoded = encodeURIComponent(normalizedIdentifier(jobId, 'jobId'));
    const { data } = await axios.post<unknown>(`${API_BASE}/api/acquisition/downloads/${encoded}/control`, { action });
    return parseDownloadJob(data);
  } catch (error: unknown) {
    throw asApiError(error, '下载任务更新失败。');
  }
}

export async function resolveAcquisitionGate(gateId: string): Promise<{
  gate: HumanAccessGate;
  download_job: DownloadJob | null;
}> {
  try {
    const encoded = encodeURIComponent(normalizedIdentifier(gateId, 'gateId'));
    const { data } = await axios.post<unknown>(`${API_BASE}/api/acquisition/gates/${encoded}/resolve`);
    const record = asRecord(data, 'gate resolution');
    return {
      gate: parseHumanAccessGate(record.gate),
      download_job: record.download_job === null || record.download_job === undefined
        ? null
        : parseDownloadJob(record.download_job),
    };
  } catch (error: unknown) {
    throw asApiError(error, '访问确认失败。');
  }
}

export async function importAcquisitionArtifact(artifactId: string): Promise<ImportReceipt> {
  try {
    const encoded = encodeURIComponent(normalizedIdentifier(artifactId, 'artifactId'));
    const { data } = await axios.post<unknown>(`${API_BASE}/api/acquisition/artifacts/${encoded}/import`);
    return parseImportReceipt(data);
  } catch (error: unknown) {
    throw asApiError(error, '文献导入失败。');
  }
}

export async function getAcquisitionImportReceipt(receiptId: string): Promise<ImportReceipt> {
  try {
    const encoded = encodeURIComponent(normalizedIdentifier(receiptId, 'receiptId'));
    const { data } = await axios.get<unknown>(`${API_BASE}/api/acquisition/receipts/${encoded}`);
    return parseImportReceipt(data);
  } catch (error: unknown) {
    throw asApiError(error, '导入状态读取失败。');
  }
}
