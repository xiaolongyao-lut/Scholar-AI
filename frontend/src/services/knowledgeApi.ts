import axios from 'axios';

import { getApiBaseUrl } from './apiBaseUrl';

const API_BASE = getApiBaseUrl();

export type KnowledgePackageKind =
  | 'wiki'
  | 'source_vault'
  | 'academic_english'
  | 'bridge_lexicon'
  | 'skill_package'
  | 'config'
  | 'product_docs';
export type KnowledgePackageStatus = 'loaded' | 'missing' | 'disabled' | 'stale' | 'unknown';
export type KnowledgeConformanceStatus = 'proved' | 'pending' | 'blocked' | 'not_applicable';
export type KnowledgeConformanceEvidenceLevel =
  | 'runtime_projection'
  | 'contract_evidence'
  | 'focused_test_evidence'
  | 'not_applicable';

export interface KnowledgePackageProjection {
  package_id: string;
  kind: KnowledgePackageKind;
  title: string;
  source_label: string;
  status: KnowledgePackageStatus;
  available: boolean;
  loaded: boolean;
  manifest_loaded: boolean;
  source_path: string;
  source_hash: string;
  content_hash: string;
  updated_at: string;
  read_endpoint: string;
  search_endpoint: string | null;
  notes: string[];
  manifest: Record<string, unknown>;
}

export interface KnowledgePackagesResponse {
  schema_version: string;
  packages: KnowledgePackageProjection[];
}

export interface KnowledgeRuntimeConformanceItem {
  requirement: string;
  status: KnowledgeConformanceStatus;
  evidence_level: KnowledgeConformanceEvidenceLevel;
  evidence_scope: string[];
  evidence: string[];
  missing: string[];
}

export interface KnowledgeRuntimeTestEvidence {
  focused_test_exists: boolean;
  source_edit_hash_test: boolean;
  context_receipt_test: boolean;
  evidence_pack_test: boolean;
  agent_resource_read_test: boolean;
  mcp_tool_test: boolean;
  test_nodes: string[];
}

export interface KnowledgeRuntimeActualLoadingGate {
  status: KnowledgeConformanceStatus;
  evidence_level: KnowledgeConformanceEvidenceLevel;
  artifact_path: string;
  artifact_ref: string;
  artifact_contract: string;
  artifact_exists: boolean;
  artifact_schema_valid: boolean;
  artifact_contract_valid: boolean;
  artifact_checked_at: string;
  verdict: string;
  evidence_scope: string[];
  evidence: string[];
  missing: string[];
  validation_errors: string[];
  required_checks: string[];
  claim_boundary: string;
  provider_preflight: KnowledgeRuntimeProviderPreflight;
  recovery: KnowledgeRuntimeActualLoadingRecovery;
}

export interface KnowledgeRuntimeRecoveryRef {
  ref_type: string;
  ref: string;
  status: string;
  required_before_completion: boolean;
  requires_authorization: boolean;
}

export interface KnowledgeRuntimeActualLoadingRecovery {
  schema_version: string;
  read_only: boolean;
  state: string;
  blocked_by: string[];
  recovery_refs: KnowledgeRuntimeRecoveryRef[];
  provider_ready_for_authorized_live_smoke: boolean;
  completion_requires_authorized_live_smoke: boolean;
}

export interface KnowledgeRuntimeProviderPreflightRecord {
  fingerprint: string;
  provider: string;
  base_url_host: string;
  model: string;
  status: string;
  ordinary_chat_ok: boolean;
  forced_tool_choice_ok: boolean;
  last_probe_at: string;
  failure_class: string;
  masked_error: string;
}

export interface KnowledgeRuntimeProviderPreflight {
  status: KnowledgeConformanceStatus;
  evidence_level: KnowledgeConformanceEvidenceLevel;
  artifact_path: string;
  artifact_ref: string;
  artifact_exists: boolean;
  artifact_schema_valid: boolean;
  checked_at: string;
  record_count: number;
  latest_status: string;
  records: KnowledgeRuntimeProviderPreflightRecord[];
  evidence_scope: string[];
  evidence: string[];
  missing: string[];
  validation_errors: string[];
  claim_boundary: string;
}

export interface KnowledgeRuntimeConformancePackage {
  package_id: string;
  kind: KnowledgePackageKind;
  title: string;
  overall_status: KnowledgeConformanceStatus;
  loaded: boolean;
  source_path: string;
  source_hash: string;
  content_hash: string;
  read_endpoint: string;
  search_endpoint: string | null;
  manifest: Record<string, unknown>;
  runtime_consumers: Record<string, string>[];
  mcp_tools: string[];
  test_evidence: KnowledgeRuntimeTestEvidence;
  conformance: KnowledgeRuntimeConformanceItem[];
}

export interface KnowledgeRuntimeConformanceResponse {
  schema_version: string;
  generated_at: string;
  pipeline: string[];
  summary: Record<KnowledgeConformanceStatus, number>;
  actual_loading_gate: KnowledgeRuntimeActualLoadingGate;
  packages: KnowledgeRuntimeConformancePackage[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`Invalid Knowledge Packages response: ${field} must be a non-empty string`);
  }
  return value;
}

function readPossiblyEmptyString(value: unknown, field: string): string {
  if (typeof value !== 'string') {
    throw new Error(`Invalid Knowledge Packages response: ${field} must be a string`);
  }
  return value;
}

function readBoolean(value: unknown, field: string): boolean {
  if (typeof value !== 'boolean') {
    throw new Error(`Invalid Knowledge Packages response: ${field} must be a boolean`);
  }
  return value;
}

function readOptionalBoolean(value: unknown, field: string, fallback: boolean): boolean {
  if (value === undefined || value === null) {
    return fallback;
  }
  return readBoolean(value, field);
}

function readNullableString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  return readString(value, field);
}

function readStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new Error(`Invalid Knowledge Packages response: ${field} must be a string array`);
  }
  return [...value];
}

function readOptionalStringArray(value: unknown, field: string): string[] {
  if (value === undefined || value === null) {
    return [];
  }
  return readStringArray(value, field);
}

function readStatus(value: unknown): KnowledgePackageStatus {
  if (
    value === 'loaded' ||
    value === 'missing' ||
    value === 'disabled' ||
    value === 'stale' ||
    value === 'unknown'
  ) {
    return value;
  }
  throw new Error('Invalid Knowledge Packages response: status is unknown');
}

function readKind(value: unknown): KnowledgePackageKind {
  if (
    value === 'wiki' ||
    value === 'source_vault' ||
    value === 'academic_english' ||
    value === 'bridge_lexicon' ||
    value === 'skill_package' ||
    value === 'config' ||
    value === 'product_docs'
  ) {
    return value;
  }
  throw new Error('Invalid Knowledge Packages response: kind is unknown');
}

function readManifest(value: unknown, field: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid Knowledge Packages response: ${field} must be an object`);
  }
  return { ...value };
}

function readRecordArray(value: unknown, field: string): Record<string, string>[] {
  if (!Array.isArray(value)) {
    throw new Error(`Invalid Knowledge Runtime response: ${field} must be an array`);
  }
  return value.map((entry, index) => {
    if (!isRecord(entry)) {
      throw new Error(`Invalid Knowledge Runtime response: ${field}[${index}] must be an object`);
    }
    const normalized: Record<string, string> = {};
    Object.entries(entry).forEach(([key, rawValue]) => {
      if (typeof rawValue !== 'string') {
        throw new Error(`Invalid Knowledge Runtime response: ${field}[${index}].${key} must be a string`);
      }
      normalized[key] = rawValue;
    });
    return normalized;
  });
}

function readNumberRecord(value: unknown, field: string): Record<KnowledgeConformanceStatus, number> {
  if (!isRecord(value)) {
    throw new Error(`Invalid Knowledge Runtime response: ${field} must be an object`);
  }
  const summary: Record<KnowledgeConformanceStatus, number> = {
    proved: 0,
    pending: 0,
    blocked: 0,
    not_applicable: 0,
  };
  Object.entries(value).forEach(([key, rawValue]) => {
    if (key !== 'proved' && key !== 'pending' && key !== 'blocked' && key !== 'not_applicable') {
      return;
    }
    if (typeof rawValue !== 'number' || !Number.isFinite(rawValue)) {
      throw new Error(`Invalid Knowledge Runtime response: ${field}.${key} must be a finite number`);
    }
    summary[key] = rawValue;
  });
  return summary;
}

function readConformanceStatus(value: unknown): KnowledgeConformanceStatus {
  if (value === 'proved' || value === 'pending' || value === 'blocked' || value === 'not_applicable') {
    return value;
  }
  throw new Error('Invalid Knowledge Runtime response: conformance status is unknown');
}

function readConformanceEvidenceLevel(value: unknown): KnowledgeConformanceEvidenceLevel {
  if (
    value === 'runtime_projection' ||
    value === 'contract_evidence' ||
    value === 'focused_test_evidence' ||
    value === 'not_applicable'
  ) {
    return value;
  }
  throw new Error('Invalid Knowledge Runtime response: evidence_level is unknown');
}

export function parseKnowledgePackageProjection(value: unknown): KnowledgePackageProjection {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Packages response: package must be an object');
  }
  return {
    package_id: readString(value.package_id, 'package_id'),
    kind: readKind(value.kind),
    title: readString(value.title, 'title'),
    source_label: readString(value.source_label, 'source_label'),
    status: readStatus(value.status),
    available: readBoolean(value.available, 'available'),
    loaded: readBoolean(value.loaded, 'loaded'),
    manifest_loaded: readBoolean(value.manifest_loaded, 'manifest_loaded'),
    source_path: readString(value.source_path, 'source_path'),
    source_hash: readString(value.source_hash, 'source_hash'),
    content_hash: readString(value.content_hash, 'content_hash'),
    updated_at: readString(value.updated_at, 'updated_at'),
    read_endpoint: readString(value.read_endpoint, 'read_endpoint'),
    search_endpoint: readNullableString(value.search_endpoint, 'search_endpoint'),
    notes: readStringArray(value.notes, 'notes'),
    manifest: readManifest(value.manifest, 'manifest'),
  } satisfies KnowledgePackageProjection;
}

export function parseKnowledgePackagesResponse(value: unknown): KnowledgePackagesResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Packages response: payload must be an object');
  }
  if (!Array.isArray(value.packages)) {
    throw new Error('Invalid Knowledge Packages response: packages must be an array');
  }
  return {
    schema_version: readString(value.schema_version, 'schema_version'),
    packages: value.packages.map(parseKnowledgePackageProjection),
  } satisfies KnowledgePackagesResponse;
}

export function parseKnowledgeRuntimeConformanceItem(value: unknown): KnowledgeRuntimeConformanceItem {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Runtime response: conformance item must be an object');
  }
  return {
    requirement: readString(value.requirement, 'requirement'),
    status: readConformanceStatus(value.status),
    evidence_level: readConformanceEvidenceLevel(value.evidence_level),
    evidence_scope: readStringArray(value.evidence_scope, 'evidence_scope'),
    evidence: readStringArray(value.evidence, 'evidence'),
    missing: readStringArray(value.missing, 'missing'),
  } satisfies KnowledgeRuntimeConformanceItem;
}

export function parseKnowledgeRuntimeTestEvidence(value: unknown): KnowledgeRuntimeTestEvidence {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Runtime response: test_evidence must be an object');
  }
  return {
    focused_test_exists: readBoolean(value.focused_test_exists, 'focused_test_exists'),
    source_edit_hash_test: readBoolean(value.source_edit_hash_test, 'source_edit_hash_test'),
    context_receipt_test: readBoolean(value.context_receipt_test, 'context_receipt_test'),
    evidence_pack_test: readBoolean(value.evidence_pack_test, 'evidence_pack_test'),
    agent_resource_read_test: readBoolean(value.agent_resource_read_test, 'agent_resource_read_test'),
    mcp_tool_test: readBoolean(value.mcp_tool_test, 'mcp_tool_test'),
    test_nodes: readStringArray(value.test_nodes, 'test_nodes'),
  } satisfies KnowledgeRuntimeTestEvidence;
}

export function parseKnowledgeRuntimeActualLoadingGate(value: unknown): KnowledgeRuntimeActualLoadingGate {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Runtime response: actual_loading_gate must be an object');
  }
  const artifactPath = readString(value.artifact_path, 'actual_loading_gate.artifact_path');
  return {
    status: readConformanceStatus(value.status),
    evidence_level: readConformanceEvidenceLevel(value.evidence_level),
    artifact_path: artifactPath,
    artifact_ref:
      typeof value.artifact_ref === 'string' && value.artifact_ref.length > 0
        ? value.artifact_ref
        : artifactPath,
    artifact_contract: readString(value.artifact_contract, 'actual_loading_gate.artifact_contract'),
    artifact_exists: readOptionalBoolean(value.artifact_exists, 'actual_loading_gate.artifact_exists', false),
    artifact_schema_valid: readOptionalBoolean(
      value.artifact_schema_valid,
      'actual_loading_gate.artifact_schema_valid',
      false,
    ),
    artifact_contract_valid: readOptionalBoolean(
      value.artifact_contract_valid,
      'actual_loading_gate.artifact_contract_valid',
      false,
    ),
    artifact_checked_at:
      typeof value.artifact_checked_at === 'string' && value.artifact_checked_at.length > 0
        ? value.artifact_checked_at
        : 'unknown',
    verdict: readString(value.verdict, 'actual_loading_gate.verdict'),
    evidence_scope: readStringArray(value.evidence_scope, 'actual_loading_gate.evidence_scope'),
    evidence: readStringArray(value.evidence, 'actual_loading_gate.evidence'),
    missing: readStringArray(value.missing, 'actual_loading_gate.missing'),
    validation_errors: readStringArray(value.validation_errors, 'actual_loading_gate.validation_errors'),
    required_checks: readStringArray(value.required_checks, 'actual_loading_gate.required_checks'),
    claim_boundary: readPossiblyEmptyString(value.claim_boundary, 'actual_loading_gate.claim_boundary'),
    provider_preflight: parseKnowledgeRuntimeProviderPreflight(value.provider_preflight),
    recovery: parseKnowledgeRuntimeActualLoadingRecovery(value.recovery),
  } satisfies KnowledgeRuntimeActualLoadingGate;
}

export function parseKnowledgeRuntimeRecoveryRef(value: unknown): KnowledgeRuntimeRecoveryRef {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Runtime response: actual_loading_gate.recovery.recovery_refs[] must be an object');
  }
  return {
    ref_type: readString(value.ref_type, 'actual_loading_gate.recovery.recovery_refs[].ref_type'),
    ref: readString(value.ref, 'actual_loading_gate.recovery.recovery_refs[].ref'),
    status: readPossiblyEmptyString(value.status, 'actual_loading_gate.recovery.recovery_refs[].status'),
    required_before_completion: readOptionalBoolean(
      value.required_before_completion,
      'actual_loading_gate.recovery.recovery_refs[].required_before_completion',
      true,
    ),
    requires_authorization: readOptionalBoolean(
      value.requires_authorization,
      'actual_loading_gate.recovery.recovery_refs[].requires_authorization',
      false,
    ),
  } satisfies KnowledgeRuntimeRecoveryRef;
}

export function parseKnowledgeRuntimeActualLoadingRecovery(
  value: unknown,
): KnowledgeRuntimeActualLoadingRecovery {
  if (value === undefined || value === null) {
    return {
      schema_version: 'scholar-ai-knowledge-runtime-recovery/v1',
      read_only: true,
      state: 'unavailable',
      blocked_by: [],
      recovery_refs: [],
      provider_ready_for_authorized_live_smoke: false,
      completion_requires_authorized_live_smoke: true,
    } satisfies KnowledgeRuntimeActualLoadingRecovery;
  }
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Runtime response: actual_loading_gate.recovery must be an object');
  }
  if (!Array.isArray(value.recovery_refs)) {
    throw new Error('Invalid Knowledge Runtime response: actual_loading_gate.recovery.recovery_refs must be an array');
  }
  return {
    schema_version: readString(value.schema_version, 'actual_loading_gate.recovery.schema_version'),
    read_only: readBoolean(value.read_only, 'actual_loading_gate.recovery.read_only'),
    state: readString(value.state, 'actual_loading_gate.recovery.state'),
    blocked_by: readOptionalStringArray(value.blocked_by, 'actual_loading_gate.recovery.blocked_by'),
    recovery_refs: value.recovery_refs.map(parseKnowledgeRuntimeRecoveryRef),
    provider_ready_for_authorized_live_smoke: readBoolean(
      value.provider_ready_for_authorized_live_smoke,
      'actual_loading_gate.recovery.provider_ready_for_authorized_live_smoke',
    ),
    completion_requires_authorized_live_smoke: readBoolean(
      value.completion_requires_authorized_live_smoke,
      'actual_loading_gate.recovery.completion_requires_authorized_live_smoke',
    ),
  } satisfies KnowledgeRuntimeActualLoadingRecovery;
}

export function parseKnowledgeRuntimeProviderPreflightRecord(
  value: unknown,
): KnowledgeRuntimeProviderPreflightRecord {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Runtime response: provider_preflight.records[] must be an object');
  }
  return {
    fingerprint: readString(value.fingerprint, 'actual_loading_gate.provider_preflight.records[].fingerprint'),
    provider: readPossiblyEmptyString(value.provider, 'actual_loading_gate.provider_preflight.records[].provider'),
    base_url_host: readPossiblyEmptyString(
      value.base_url_host,
      'actual_loading_gate.provider_preflight.records[].base_url_host',
    ),
    model: readPossiblyEmptyString(value.model, 'actual_loading_gate.provider_preflight.records[].model'),
    status: readPossiblyEmptyString(value.status, 'actual_loading_gate.provider_preflight.records[].status'),
    ordinary_chat_ok: readBoolean(
      value.ordinary_chat_ok,
      'actual_loading_gate.provider_preflight.records[].ordinary_chat_ok',
    ),
    forced_tool_choice_ok: readBoolean(
      value.forced_tool_choice_ok,
      'actual_loading_gate.provider_preflight.records[].forced_tool_choice_ok',
    ),
    last_probe_at: readPossiblyEmptyString(
      value.last_probe_at,
      'actual_loading_gate.provider_preflight.records[].last_probe_at',
    ),
    failure_class: readPossiblyEmptyString(
      value.failure_class,
      'actual_loading_gate.provider_preflight.records[].failure_class',
    ),
    masked_error: readPossiblyEmptyString(
      value.masked_error,
      'actual_loading_gate.provider_preflight.records[].masked_error',
    ),
  } satisfies KnowledgeRuntimeProviderPreflightRecord;
}

export function parseKnowledgeRuntimeProviderPreflight(value: unknown): KnowledgeRuntimeProviderPreflight {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Runtime response: provider_preflight must be an object');
  }
  if (!Array.isArray(value.records)) {
    throw new Error('Invalid Knowledge Runtime response: provider_preflight.records must be an array');
  }
  const recordCount = value.record_count;
  if (typeof recordCount !== 'number' || !Number.isFinite(recordCount) || recordCount < 0) {
    throw new Error('Invalid Knowledge Runtime response: provider_preflight.record_count must be a finite number');
  }
  return {
    status: readConformanceStatus(value.status),
    evidence_level: readConformanceEvidenceLevel(value.evidence_level),
    artifact_path: readString(value.artifact_path, 'actual_loading_gate.provider_preflight.artifact_path'),
    artifact_ref: readString(value.artifact_ref, 'actual_loading_gate.provider_preflight.artifact_ref'),
    artifact_exists: readBoolean(value.artifact_exists, 'actual_loading_gate.provider_preflight.artifact_exists'),
    artifact_schema_valid: readBoolean(
      value.artifact_schema_valid,
      'actual_loading_gate.provider_preflight.artifact_schema_valid',
    ),
    checked_at: readString(value.checked_at, 'actual_loading_gate.provider_preflight.checked_at'),
    record_count: recordCount,
    latest_status: readPossiblyEmptyString(
      value.latest_status,
      'actual_loading_gate.provider_preflight.latest_status',
    ),
    records: value.records.map(parseKnowledgeRuntimeProviderPreflightRecord),
    evidence_scope: readStringArray(value.evidence_scope, 'actual_loading_gate.provider_preflight.evidence_scope'),
    evidence: readStringArray(value.evidence, 'actual_loading_gate.provider_preflight.evidence'),
    missing: readStringArray(value.missing, 'actual_loading_gate.provider_preflight.missing'),
    validation_errors: readStringArray(
      value.validation_errors,
      'actual_loading_gate.provider_preflight.validation_errors',
    ),
    claim_boundary: readPossiblyEmptyString(
      value.claim_boundary,
      'actual_loading_gate.provider_preflight.claim_boundary',
    ),
  } satisfies KnowledgeRuntimeProviderPreflight;
}

export function parseKnowledgeRuntimeConformancePackage(value: unknown): KnowledgeRuntimeConformancePackage {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Runtime response: package must be an object');
  }
  if (!Array.isArray(value.conformance)) {
    throw new Error('Invalid Knowledge Runtime response: conformance must be an array');
  }
  return {
    package_id: readString(value.package_id, 'package_id'),
    kind: readKind(value.kind),
    title: readString(value.title, 'title'),
    overall_status: readConformanceStatus(value.overall_status),
    loaded: readBoolean(value.loaded, 'loaded'),
    source_path: readString(value.source_path, 'source_path'),
    source_hash: readString(value.source_hash, 'source_hash'),
    content_hash: readString(value.content_hash, 'content_hash'),
    read_endpoint: readString(value.read_endpoint, 'read_endpoint'),
    search_endpoint: readNullableString(value.search_endpoint, 'search_endpoint'),
    manifest: readManifest(value.manifest, 'manifest'),
    runtime_consumers: readRecordArray(value.runtime_consumers, 'runtime_consumers'),
    mcp_tools: readStringArray(value.mcp_tools, 'mcp_tools'),
    test_evidence: parseKnowledgeRuntimeTestEvidence(value.test_evidence),
    conformance: value.conformance.map(parseKnowledgeRuntimeConformanceItem),
  } satisfies KnowledgeRuntimeConformancePackage;
}

export function parseKnowledgeRuntimeConformanceResponse(value: unknown): KnowledgeRuntimeConformanceResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid Knowledge Runtime response: payload must be an object');
  }
  if (!Array.isArray(value.pipeline)) {
    throw new Error('Invalid Knowledge Runtime response: pipeline must be an array');
  }
  if (!Array.isArray(value.packages)) {
    throw new Error('Invalid Knowledge Runtime response: packages must be an array');
  }
  return {
    schema_version: readString(value.schema_version, 'schema_version'),
    generated_at: readString(value.generated_at, 'generated_at'),
    pipeline: readStringArray(value.pipeline, 'pipeline'),
    summary: readNumberRecord(value.summary, 'summary'),
    actual_loading_gate: parseKnowledgeRuntimeActualLoadingGate(value.actual_loading_gate),
    packages: value.packages.map(parseKnowledgeRuntimeConformancePackage),
  } satisfies KnowledgeRuntimeConformanceResponse;
}

export async function getKnowledgePackages(): Promise<KnowledgePackagesResponse> {
  const { data } = await axios.get<unknown>(`${API_BASE}/api/knowledge/packages`);
  return parseKnowledgePackagesResponse(data);
}

export async function getKnowledgeRuntimeConformance(): Promise<KnowledgeRuntimeConformanceResponse> {
  const { data } = await axios.get<unknown>(`${API_BASE}/api/knowledge/runtime-conformance`);
  return parseKnowledgeRuntimeConformanceResponse(data);
}
