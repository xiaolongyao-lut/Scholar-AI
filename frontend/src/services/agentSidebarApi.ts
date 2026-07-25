import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import type { EvidenceRefLike } from '@/components/evidence/EvidencePill';
import { isPdfBboxUnit, readPdfBbox, type PdfBboxUnit } from '@/lib/pdfAnchor';
import {
  sanitizeVisualObservationReferences,
  type VisualObservationReference,
} from '@/types/visualObservation';

export type AgentSidebarQrelsState = 'missing' | 'candidate' | 'reviewed' | 'canonical' | 'unknown';

export interface AgentSidebarHealth {
  status: 'ok' | 'degraded' | 'offline' | 'unknown';
  version?: string | null;
  raw: Record<string, unknown>;
}

export interface AgentSidebarQrelsStatus {
  schema_version?: 'retrieval-qrels-status/v1';
  status: AgentSidebarQrelsState;
  candidate_qrels_count?: number;
  reviewed_qrels_count?: number;
  canonical_qrels_count?: number;
  semantic_quality_claim_allowed?: boolean;
  quality_claim?: string;
  qrels_content_hash?: string | null;
  notes?: string[];
}

export interface AgentSidebarGateStatus {
  status: string;
  reason?: string | null;
  message?: string | null;
  quality?: string | null;
  gate_config_hash?: string | null;
  summary?: Record<string, unknown>;
}

export interface AgentSidebarRetrievalDiagnostics {
  retrieval_method?: string | null;
  retrieval_provider?: string | null;
  embedding_status?: string | null;
  rerank_status?: string | null;
  fallback_reason?: string | null;
  fallback_reasons?: string[];
  lexical_only?: boolean;
  qrels_status?: AgentSidebarQrelsStatus | null;
}

export interface AgentSidebarEvidenceRef {
  ref_id?: string | null;
  read_endpoint?: string | null;
  chunk_id?: string | null;
  material_id?: string | null;
  page?: number | string | null;
  bbox?: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
  source?: string | null;
  source_title?: string | null;
  title?: string | null;
  summary?: string | null;
  text?: string | null;
  quote?: string | null;
  anchor_kind?: 'text' | 'visual' | null;
  source_kind?: 'local' | 'web' | 'mcp' | null;
  source_type?: 'project' | 'wiki' | null;
  source_labels?: string[] | null;
  joint_score?: number | null;
  chunk_hash?: string | null;
  content_hash?: string | null;
  locator_hash?: string | null;
  embedding_input_hash?: string | null;
  hash_version?: string | null;
}

export interface AgentSidebarKnowledgeConsumerRef {
  ref_type?: string | null;
  ref_id?: string | null;
  read_endpoint?: string | null;
  page_endpoint?: string | null;
  page_path?: string | null;
  slug?: string | null;
  status?: string | null;
  endpoint?: string | null;
  item_id?: string | null;
  wiki_slug?: string | null;
  graph_patch_ref_count?: number;
  read_only?: boolean;
}

export interface AgentSidebarKnowledgeConsumerRefs {
  read_only?: boolean;
  agent_request_id?: string | null;
  runtime_job_id?: string | null;
  runtime_session_id?: string | null;
  project_id?: string | null;
  wiki_candidate_ref?: AgentSidebarKnowledgeConsumerRef | null;
  wiki_review_item_ref?: AgentSidebarKnowledgeConsumerRef | null;
  graph_candidate_ref?: AgentSidebarKnowledgeConsumerRef | null;
  evolution_capture_ref?: AgentSidebarKnowledgeConsumerRef | null;
}

export interface AgentSidebarAnswerReceipt {
  receipt_schema_version?: string;
  project_id?: string | null;
  question?: string | null;
  answer_origin?: string | null;
  answer_model?: string | null;
  answer_model_origin?: string | null;
  generated_in?: string | null;
  evidence_origin?: string | null;
  evidence_pack_ref?: string | null;
  lifecycle_state?: string;
  staleness_status?: string;
  output_language?: string | null;
  qrels_status?: AgentSidebarQrelsStatus | null;
  evidence_gate_status?: AgentSidebarGateStatus | null;
  retrieval_diagnostics?: AgentSidebarRetrievalDiagnostics | null;
  top_evidence_refs: AgentSidebarEvidenceRef[];
  visual_observation_refs?: VisualObservationReference[];
  knowledge_consumer_refs?: AgentSidebarKnowledgeConsumerRefs | null;
}

export interface AgentSidebarReceiptSummary {
  conversation_id: string;
  project_id?: string | null;
  title: string;
  mode: string;
  created_at: string;
  updated_at: string;
  lifecycle_state: string;
  staleness_status: string;
  receipt: AgentSidebarAnswerReceipt;
}

export interface AgentSidebarReceiptListResponse {
  project_id: string;
  receipts: AgentSidebarReceiptSummary[];
}

export interface AgentSidebarStaleness {
  status: string;
  checked: string[];
  warnings: string[];
  mismatches: string[];
}

export interface AgentSidebarReceiptReadResponse {
  conversation_id: string;
  project_id?: string | null;
  answer: string;
  receipt: AgentSidebarAnswerReceipt;
  staleness: AgentSidebarStaleness;
}

export interface AgentSidebarRevalidateResponse {
  conversation_id: string;
  project_id: string;
  applied: boolean;
  apply_allowed: boolean;
  status: string;
  previous_staleness: AgentSidebarStaleness;
  revalidated_staleness: AgentSidebarStaleness;
  top_ref_delta: Record<string, unknown>;
  receipt: AgentSidebarAnswerReceipt;
  evidence_pack: Record<string, unknown>;
  gate: AgentSidebarGateStatus;
}

export interface AgentSidebarResourceRef {
  ref_id: string;
  kind: string;
  project_id?: string | null;
  title?: string | null;
  summary?: string | null;
  read_endpoint?: string | null;
  metadata: Record<string, unknown>;
}

export interface AgentSidebarAgentRequestJob {
  job_id: string;
  status: string;
  metadata: Record<string, unknown>;
}

export interface AgentSidebarAnswerRequestResponse {
  request_id: string;
  job: AgentSidebarAgentRequestJob;
  poll: Record<string, string>;
  envelope: {
    intent?: string;
    project_id?: string | null;
    user_text?: string;
    resource_refs?: AgentSidebarResourceRef[];
  };
}

export interface AgentSidebarAnswerRequestOptions {
  projectId?: string | null;
  agentHost?: string;
  source?: string;
  route?: string;
  generatedIn?: string;
  maxChars?: number;
  maxChunks?: number;
}

export interface AgentSidebarDesktopOpenResponse {
  schema_version?: string;
  status: 'running' | 'starting';
  started: boolean;
  product_name: string;
  window_title: string;
  base_url?: string | null;
  pid?: number | null;
  focused: boolean;
  message: string;
}

function apiUrl(path: string): string {
  return `${getApiBaseUrl()}${path}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed || undefined;
}

function readContentString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function readBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function readNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function readPage(value: unknown): number | string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value;
  if (typeof value === 'string' && value.trim()) return value.trim();
  return null;
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): string[] => {
    const text = readString(item);
    return text ? [text] : [];
  });
}

function readRecord(value: unknown): Record<string, unknown> | undefined {
  return isRecord(value) ? value : undefined;
}

function readStringRecord(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, item]): Array<[string, string]> => {
      const text = readString(item);
      return text ? [[key, text]] : [];
    }),
  );
}

function readEvidenceKind(value: unknown): 'local' | 'web' | 'mcp' | null {
  return value === 'local' || value === 'web' || value === 'mcp' ? value : null;
}

function readEvidenceType(value: unknown): 'project' | 'wiki' | null {
  return value === 'project' || value === 'wiki' ? value : null;
}

function readBboxUnit(value: unknown): PdfBboxUnit | null {
  return isPdfBboxUnit(value) ? value : null;
}

function parseQrelsStatus(value: unknown): AgentSidebarQrelsStatus | null {
  if (!isRecord(value)) return null;
  const rawStatus = readString(value.status);
  const status: AgentSidebarQrelsState =
    rawStatus === 'missing' || rawStatus === 'candidate' || rawStatus === 'reviewed' || rawStatus === 'canonical'
      ? rawStatus
      : 'unknown';
  const semanticQualityClaimAllowed = status === 'canonical' && readBoolean(value.semantic_quality_claim_allowed) === true;
  return {
    schema_version: value.schema_version === 'retrieval-qrels-status/v1' ? value.schema_version : undefined,
    status,
    candidate_qrels_count: readNumber(value.candidate_qrels_count),
    reviewed_qrels_count: readNumber(value.reviewed_qrels_count),
    canonical_qrels_count: readNumber(value.canonical_qrels_count),
    semantic_quality_claim_allowed: semanticQualityClaimAllowed,
    quality_claim: semanticQualityClaimAllowed ? readString(value.quality_claim) : undefined,
    qrels_content_hash: readString(value.qrels_content_hash) ?? null,
    notes: readStringArray(value.notes),
  };
}

function parseGateStatus(value: unknown): AgentSidebarGateStatus | null {
  if (!isRecord(value)) return null;
  return {
    status: readString(value.status) ?? 'unknown',
    reason: readString(value.reason) ?? null,
    message: readString(value.message) ?? null,
    quality: readString(value.quality) ?? null,
    gate_config_hash: readString(value.gate_config_hash) ?? null,
    summary: readRecord(value.summary),
  };
}

function parseRetrievalDiagnostics(value: unknown): AgentSidebarRetrievalDiagnostics | null {
  if (!isRecord(value)) return null;
  return {
    retrieval_method: readString(value.retrieval_method) ?? null,
    retrieval_provider: readString(value.retrieval_provider) ?? null,
    embedding_status: readString(value.embedding_status) ?? null,
    rerank_status: readString(value.rerank_status) ?? null,
    fallback_reason: readString(value.fallback_reason) ?? null,
    fallback_reasons: readStringArray(value.fallback_reasons),
    lexical_only: readBoolean(value.lexical_only),
    qrels_status: parseQrelsStatus(value.qrels_status),
  };
}

function parseEvidenceRef(value: unknown): AgentSidebarEvidenceRef | null {
  if (!isRecord(value)) return null;
  const bboxUnit = readBboxUnit(value.bbox_unit);
  const bbox = bboxUnit ? readPdfBbox(value.bbox) : null;
  return {
    ref_id: readString(value.ref_id) ?? null,
    read_endpoint: readString(value.read_endpoint) ?? null,
    chunk_id: readString(value.chunk_id) ?? null,
    material_id: readString(value.material_id) ?? null,
    page: readPage(value.page),
    bbox: bbox ? [...bbox] : null,
    bbox_unit: bbox ? bboxUnit : null,
    source: readString(value.source) ?? null,
    source_title: readString(value.source_title) ?? null,
    title: readString(value.title) ?? null,
    summary: readString(value.summary) ?? null,
    text: readString(value.text) ?? null,
    quote: readString(value.quote) ?? null,
    anchor_kind: value.anchor_kind === 'text' || value.anchor_kind === 'visual'
      ? value.anchor_kind
      : null,
    source_kind: readEvidenceKind(value.source_kind),
    source_type: readEvidenceType(value.source_type),
    source_labels: readStringArray(value.source_labels),
    joint_score: readNumber(value.joint_score) ?? null,
    chunk_hash: readString(value.chunk_hash) ?? null,
    content_hash: readString(value.content_hash) ?? null,
    locator_hash: readString(value.locator_hash) ?? null,
    embedding_input_hash: readString(value.embedding_input_hash) ?? null,
    hash_version: readString(value.hash_version) ?? null,
  };
}

function parseEvidenceRefs(value: unknown): AgentSidebarEvidenceRef[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): AgentSidebarEvidenceRef[] => {
    const parsed = parseEvidenceRef(item);
    return parsed ? [parsed] : [];
  });
}

function parseKnowledgeConsumerRef(value: unknown): AgentSidebarKnowledgeConsumerRef | null {
  if (!isRecord(value)) return null;
  return {
    ref_type: readString(value.ref_type) ?? null,
    ref_id: readString(value.ref_id) ?? null,
    read_endpoint: readString(value.read_endpoint) ?? null,
    page_endpoint: readString(value.page_endpoint) ?? null,
    page_path: readString(value.page_path) ?? null,
    slug: readString(value.slug) ?? null,
    status: readString(value.status) ?? null,
    endpoint: readString(value.endpoint) ?? null,
    item_id: readString(value.item_id) ?? null,
    wiki_slug: readString(value.wiki_slug) ?? null,
    graph_patch_ref_count: readNumber(value.graph_patch_ref_count),
    read_only: readBoolean(value.read_only),
  };
}

function parseKnowledgeConsumerRefs(value: unknown): AgentSidebarKnowledgeConsumerRefs | null {
  if (!isRecord(value)) return null;
  return {
    read_only: readBoolean(value.read_only),
    agent_request_id: readString(value.agent_request_id) ?? null,
    runtime_job_id: readString(value.runtime_job_id) ?? null,
    runtime_session_id: readString(value.runtime_session_id) ?? null,
    project_id: readString(value.project_id) ?? null,
    wiki_candidate_ref: parseKnowledgeConsumerRef(value.wiki_candidate_ref),
    wiki_review_item_ref: parseKnowledgeConsumerRef(value.wiki_review_item_ref),
    graph_candidate_ref: parseKnowledgeConsumerRef(value.graph_candidate_ref),
    evolution_capture_ref: parseKnowledgeConsumerRef(value.evolution_capture_ref),
  };
}

export function parseAnswerReceipt(value: unknown): AgentSidebarAnswerReceipt {
  if (!isRecord(value)) {
    return { top_evidence_refs: [], visual_observation_refs: [] };
  }
  const diagnostics = parseRetrievalDiagnostics(value.retrieval_diagnostics);
  const directQrels = parseQrelsStatus(value.qrels_status);
  return {
    receipt_schema_version: readString(value.receipt_schema_version),
    project_id: readString(value.project_id) ?? null,
    question: readString(value.question) ?? null,
    answer_origin: readString(value.answer_origin) ?? null,
    answer_model: readString(value.answer_model) ?? null,
    answer_model_origin: readString(value.answer_model_origin) ?? null,
    generated_in: readString(value.generated_in) ?? null,
    evidence_origin: readString(value.evidence_origin) ?? null,
    evidence_pack_ref: readString(value.evidence_pack_ref) ?? null,
    lifecycle_state: readString(value.lifecycle_state) ?? 'saved',
    staleness_status: readString(value.staleness_status) ?? 'unchecked',
    output_language: readString(value.output_language) ?? null,
    qrels_status: directQrels ?? diagnostics?.qrels_status ?? null,
    evidence_gate_status: parseGateStatus(value.evidence_gate_status),
    retrieval_diagnostics: diagnostics,
    top_evidence_refs: parseEvidenceRefs(value.top_evidence_refs),
    visual_observation_refs: sanitizeVisualObservationReferences(value.visual_observation_refs),
    knowledge_consumer_refs: parseKnowledgeConsumerRefs(value.knowledge_consumer_refs),
  };
}

export function parseStaleness(value: unknown): AgentSidebarStaleness {
  if (!isRecord(value)) {
    return { status: 'unchecked', checked: [], warnings: [], mismatches: [] };
  }
  return {
    status: readString(value.status) ?? 'unchecked',
    checked: readStringArray(value.checked),
    warnings: readStringArray(value.warnings),
    mismatches: readStringArray(value.mismatches),
  };
}

export function parseReceiptSummary(value: unknown): AgentSidebarReceiptSummary {
  if (!isRecord(value)) {
    throw new Error('Invalid answer receipt summary: expected object');
  }
  const conversationId = readString(value.conversation_id);
  if (!conversationId) {
    throw new Error('Invalid answer receipt summary: conversation_id is required');
  }
  return {
    conversation_id: conversationId,
    project_id: readString(value.project_id) ?? null,
    title: readContentString(value.title),
    mode: readString(value.mode) ?? 'literature_qa',
    created_at: readContentString(value.created_at),
    updated_at: readContentString(value.updated_at),
    lifecycle_state: readString(value.lifecycle_state) ?? 'saved',
    staleness_status: readString(value.staleness_status) ?? 'unchecked',
    receipt: parseAnswerReceipt(value.receipt),
  };
}

export function parseReceiptListResponse(value: unknown): AgentSidebarReceiptListResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid answer receipt list response: expected object');
  }
  const projectId = readString(value.project_id);
  if (!projectId) {
    throw new Error('Invalid answer receipt list response: project_id is required');
  }
  if (!Array.isArray(value.receipts)) {
    throw new Error('Invalid answer receipt list response: receipts must be an array');
  }
  return {
    project_id: projectId,
    receipts: value.receipts.map(parseReceiptSummary),
  };
}

export function parseReceiptReadResponse(value: unknown): AgentSidebarReceiptReadResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid answer receipt read response: expected object');
  }
  const conversationId = readString(value.conversation_id);
  if (!conversationId) {
    throw new Error('Invalid answer receipt read response: conversation_id is required');
  }
  return {
    conversation_id: conversationId,
    project_id: readString(value.project_id) ?? null,
    answer: readContentString(value.answer),
    receipt: parseAnswerReceipt(value.receipt),
    staleness: parseStaleness(value.staleness),
  };
}

export function parseRevalidateResponse(value: unknown): AgentSidebarRevalidateResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid receipt revalidate response: expected object');
  }
  const conversationId = readString(value.conversation_id);
  const projectId = readString(value.project_id);
  if (!conversationId || !projectId) {
    throw new Error('Invalid receipt revalidate response: conversation_id and project_id are required');
  }
  return {
    conversation_id: conversationId,
    project_id: projectId,
    applied: readBoolean(value.applied) ?? false,
    apply_allowed: readBoolean(value.apply_allowed) ?? false,
    status: readString(value.status) ?? 'unknown',
    previous_staleness: parseStaleness(value.previous_staleness),
    revalidated_staleness: parseStaleness(value.revalidated_staleness),
    top_ref_delta: readRecord(value.top_ref_delta) ?? {},
    receipt: parseAnswerReceipt(value.receipt),
    evidence_pack: readRecord(value.evidence_pack) ?? {},
    gate: parseGateStatus(value.gate) ?? { status: 'unknown' },
  };
}

function parseResourceRef(value: unknown): AgentSidebarResourceRef | null {
  if (!isRecord(value)) return null;
  const refId = readString(value.ref_id);
  const kind = readString(value.kind);
  if (!refId || !kind) return null;
  return {
    ref_id: refId,
    kind,
    project_id: readString(value.project_id) ?? null,
    title: readString(value.title) ?? null,
    summary: readString(value.summary) ?? null,
    read_endpoint: readString(value.read_endpoint) ?? null,
    metadata: readRecord(value.metadata) ?? {},
  };
}

function parseRequestJob(value: unknown): AgentSidebarAgentRequestJob {
  if (!isRecord(value)) {
    throw new Error('Invalid agent request response: job must be an object');
  }
  const jobId = readString(value.job_id);
  if (!jobId) {
    throw new Error('Invalid agent request response: job_id is required');
  }
  return {
    job_id: jobId,
    status: readString(value.status) ?? 'unknown',
    metadata: readRecord(value.metadata) ?? {},
  };
}

export function parseAnswerRequestResponse(value: unknown): AgentSidebarAnswerRequestResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid agent request response: expected object');
  }
  const requestId = readString(value.request_id);
  if (!requestId) {
    throw new Error('Invalid agent request response: request_id is required');
  }
  const envelope = readRecord(value.envelope) ?? {};
  const resourceRefs = Array.isArray(envelope.resource_refs)
    ? envelope.resource_refs.flatMap((item): AgentSidebarResourceRef[] => {
        const parsed = parseResourceRef(item);
        return parsed ? [parsed] : [];
      })
    : undefined;
  return {
    request_id: requestId,
    job: parseRequestJob(value.job),
    poll: readStringRecord(value.poll),
    envelope: {
      intent: readString(envelope.intent),
      project_id: readString(envelope.project_id) ?? null,
      user_text: readString(envelope.user_text),
      resource_refs: resourceRefs,
    },
  };
}

export function parseDesktopOpenResponse(value: unknown): AgentSidebarDesktopOpenResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid desktop open response: expected object');
  }
  const rawStatus = readString(value.status);
  const status = rawStatus === 'starting' ? 'starting' : 'running';
  return {
    schema_version: readString(value.schema_version),
    status,
    started: readBoolean(value.started) ?? false,
    product_name: readString(value.product_name) ?? 'Scholar AI',
    window_title: readString(value.window_title) ?? '文献助手',
    base_url: readString(value.base_url) ?? null,
    pid: readNumber(value.pid) ?? null,
    focused: readBoolean(value.focused) ?? false,
    message: readString(value.message) ?? (status === 'running' ? '文献助手桌面端已在运行。' : '正在启动文献助手桌面端。'),
  };
}

function isAxiosErrorLike(error: unknown): error is { response?: { data?: unknown }; code?: string } {
  const axiosWithChecker = axios as { isAxiosError?: (value: unknown) => boolean };
  if (typeof axiosWithChecker.isAxiosError === 'function' && axiosWithChecker.isAxiosError(error)) {
    return true;
  }
  return isRecord(error) && error.isAxiosError === true;
}

function describeDesktopOpenError(error: unknown): string | undefined {
  if (!isAxiosErrorLike(error)) return undefined;
  const responseData = error.response?.data;
  const detail = isRecord(responseData) ? readString(responseData.detail) : undefined;
  if (detail) return `打开文献助手失败：${detail}`;
  if (error.code === 'ECONNABORTED') {
    return '文献助手响应超时。请确认桌面端正在启动，然后稍后重试。';
  }
  if (!error.response) {
    return '文献助手后端已断开。请先启动文献助手桌面端，然后在侧栏重试。';
  }
  return undefined;
}

export function parseHealth(value: unknown): AgentSidebarHealth {
  const raw = isRecord(value) ? value : {};
  const statusText = readString(raw.status) ?? readString(raw.health) ?? 'unknown';
  const status = statusText === 'ok'
    ? 'ok'
    : statusText === 'degraded'
      ? 'degraded'
      : statusText === 'offline'
        ? 'offline'
        : 'unknown';
  return {
    status,
    version: readString(raw.version) ?? null,
    raw,
  };
}

export async function openAgentSidebarDesktop(timeoutMs: number = 15000): Promise<AgentSidebarDesktopOpenResponse> {
  try {
    const { data } = await axios.post<unknown>(
      apiUrl('/api/agent-bridge/desktop/open'),
      {},
      { timeout: timeoutMs },
    );
    return parseDesktopOpenResponse(data);
  } catch (error) {
    const message = describeDesktopOpenError(error);
    if (message) {
      throw new Error(message);
    }
    throw error;
  }
}

export async function getAgentSidebarHealth(timeoutMs: number = 8000): Promise<AgentSidebarHealth> {
  const { data } = await axios.get<unknown>(apiUrl('/health'), { timeout: timeoutMs });
  return parseHealth(data);
}

export async function listAgentSidebarReceipts(
  projectId: string,
  limit: number = 20,
  timeoutMs: number = 15000,
): Promise<AgentSidebarReceiptListResponse> {
  const normalizedProjectId = projectId.trim();
  if (!normalizedProjectId) {
    throw new Error('project_id must not be empty');
  }
  const boundedLimit = Math.max(1, Math.min(100, Math.trunc(limit)));
  const { data } = await axios.get<unknown>(
    apiUrl('/api/chat/answer-receipts'),
    {
      params: { project_id: normalizedProjectId, limit: boundedLimit },
      timeout: timeoutMs,
    },
  );
  return parseReceiptListResponse(data);
}

export async function readAgentSidebarReceipt(
  conversationId: string,
  timeoutMs: number = 15000,
): Promise<AgentSidebarReceiptReadResponse> {
  const normalizedConversationId = conversationId.trim();
  if (!normalizedConversationId) {
    throw new Error('conversation_id must not be empty');
  }
  const { data } = await axios.get<unknown>(
    apiUrl(`/api/chat/answer-receipts/${encodeURIComponent(normalizedConversationId)}`),
    { timeout: timeoutMs },
  );
  return parseReceiptReadResponse(data);
}

export async function revalidateAgentSidebarReceipt(
  conversationId: string,
  options: { apply?: boolean; topK?: number } = {},
  timeoutMs: number = 60000,
): Promise<AgentSidebarRevalidateResponse> {
  const normalizedConversationId = conversationId.trim();
  if (!normalizedConversationId) {
    throw new Error('conversation_id must not be empty');
  }
  const topK = Math.max(1, Math.min(50, Math.trunc(options.topK ?? 10)));
  const { data } = await axios.post<unknown>(
    apiUrl(`/api/chat/answer-receipts/${encodeURIComponent(normalizedConversationId)}/revalidate`),
    { apply: options.apply === true, top_k: topK },
    { timeout: timeoutMs },
  );
  return parseRevalidateResponse(data);
}

function resourceKind(refId: string, ref: AgentSidebarEvidenceRef): string {
  const prefix = refId.split(':', 1)[0]?.trim();
  if (prefix) return prefix.slice(0, 80);
  return (ref.source_type || ref.source_kind || 'evidence').slice(0, 80);
}

function boundedRequestText(value: string | undefined, fallback: string, limit: number): string {
  const text = (value ?? '').trim() || fallback;
  return text.slice(0, limit);
}

function receiptResourceRefs(read: AgentSidebarReceiptReadResponse, projectId: string): AgentSidebarResourceRef[] {
  return read.receipt.top_evidence_refs.slice(0, 12).flatMap((ref): AgentSidebarResourceRef[] => {
    const refId = (ref.ref_id || ref.chunk_id || '').trim();
    if (!refId) return [];
    return [{
      ref_id: refId,
      kind: resourceKind(refId, ref),
      project_id: projectId,
      title: ref.source_title ?? ref.title ?? ref.source ?? null,
      summary: ref.summary ?? ref.text ?? ref.quote ?? null,
      read_endpoint: ref.read_endpoint ?? null,
      metadata: {
        evidence_pack_ref: read.receipt.evidence_pack_ref,
        material_id: ref.material_id,
        chunk_id: ref.chunk_id,
        page: ref.page,
        source_type: ref.source_type,
        source_kind: ref.source_kind,
        source_labels: ref.source_labels,
      },
    }];
  });
}

export async function createAgentSidebarAnswerRequest(
  read: AgentSidebarReceiptReadResponse,
  options: AgentSidebarAnswerRequestOptions = {},
  timeoutMs: number = 15000,
): Promise<AgentSidebarAnswerRequestResponse> {
  const projectId = (options.projectId ?? read.project_id ?? read.receipt.project_id ?? '').trim();
  if (!projectId) {
    throw new Error('project_id must not be empty');
  }
  const question = (read.receipt.question ?? '').trim();
  if (!question) {
    throw new Error('saved receipt question is required for host-agent handoff');
  }
  const maxChars = Math.max(100, Math.min(40000, Math.trunc(options.maxChars ?? 12000)));
  const maxChunks = Math.max(1, Math.min(50, Math.trunc(options.maxChunks ?? 12)));
  const source = boundedRequestText(options.source, 'agent_sidebar', 80);
  const agentHost = boundedRequestText(options.agentHost, 'codex', 80);
  const route = boundedRequestText(options.route, '/agent-sidebar', 300);
  const generatedIn = boundedRequestText(options.generatedIn, 'mcp_sidebar', 80);
  const payload = {
    source,
    agent_host: agentHost,
    intent: 'sidebar_answer',
    user_text: question,
    project_id: projectId,
    route,
    resource_refs: receiptResourceRefs(read, projectId),
    context_budget: {
      max_chars: maxChars,
      max_chunks: maxChunks,
      include_full_text: false,
    },
    output_targets: {
      runtime_job: true,
      smart_read_conversation: true,
      agent_workspace: true,
      wiki_candidate: false,
      graph_candidate: false,
      evolution_capture: false,
    },
    metadata: {
      source_conversation_id: read.conversation_id,
      receipt_schema_version: read.receipt.receipt_schema_version,
      evidence_pack_ref: read.receipt.evidence_pack_ref,
      generated_in: generatedIn,
      evidence_origin: read.receipt.evidence_origin ?? 'scholar_ai_mcp',
      qrels_status: read.receipt.qrels_status,
      evidence_gate_status: read.receipt.evidence_gate_status,
      retrieval_diagnostics: read.receipt.retrieval_diagnostics,
      output_language: read.receipt.output_language,
    },
  };
  const { data } = await axios.post<unknown>(
    apiUrl('/api/agent-bridge/request'),
    payload,
    { timeout: timeoutMs },
  );
  return parseAnswerRequestResponse(data);
}

export function agentSidebarEvidenceToPill(ref: AgentSidebarEvidenceRef): EvidenceRefLike {
  const page = typeof ref.page === 'number' && Number.isFinite(ref.page)
    ? ref.page
    : typeof ref.page === 'string' && /^\d{1,5}$/.test(ref.page)
      ? Number.parseInt(ref.page, 10)
      : null;
  const bboxUnit = isPdfBboxUnit(ref.bbox_unit) ? ref.bbox_unit : null;
  const bbox = bboxUnit ? readPdfBbox(ref.bbox) : null;
  return {
    evidence_id: ref.ref_id ?? ref.chunk_id ?? null,
    chunk_id: ref.chunk_id ?? null,
    material_id: ref.material_id ?? null,
    page,
    bbox: bbox ? [...bbox] : null,
    bbox_unit: bbox ? bboxUnit : null,
    text: ref.text ?? ref.quote ?? ref.summary ?? null,
    quote: ref.quote ?? null,
    anchor_kind: ref.anchor_kind ?? null,
    content_hash: ref.content_hash ?? null,
    locator_hash: ref.locator_hash ?? null,
    chunk_hash: ref.chunk_hash ?? null,
    embedding_input_hash: ref.embedding_input_hash ?? null,
    hash_version: ref.hash_version ?? null,
    source: ref.source ?? ref.source_title ?? ref.title ?? null,
    source_title: ref.source_title ?? ref.title ?? null,
    source_kind: ref.source_kind ?? 'local',
    source_type: ref.source_type ?? 'project',
    source_labels: ref.source_labels ?? null,
    joint_score: ref.joint_score ?? null,
  };
}

function inline(value: unknown, fallback: string = 'unknown', maxChars: number = 160): string {
  const raw = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value).trim()
    : '';
  const text = raw || fallback;
  return text.length > maxChars ? `${text.slice(0, maxChars - 1)}…` : text;
}

function evidenceLine(ref: AgentSidebarEvidenceRef, index: number): string {
  const title = inline(ref.source_title ?? ref.title ?? ref.source ?? '未命名来源', '未命名来源', 120);
  const locatorParts = [
    ref.page !== null && ref.page !== undefined ? `第 ${inline(ref.page, '', 24)} 页` : '',
    ref.ref_id ? inline(ref.ref_id, '', 100) : '',
  ].filter(Boolean);
  const locator = locatorParts.length > 0 ? locatorParts.join('，') : '无定位';
  return `- [E${index}] ${title}, ${locator}`;
}

export function buildAgentSidebarReceiptMarkdown(read: AgentSidebarReceiptReadResponse): string {
  const receipt = read.receipt;
  const qrels = receipt.qrels_status;
  const gate = receipt.evidence_gate_status;
  const retrieval = receipt.retrieval_diagnostics;
  const evidenceLines = receipt.top_evidence_refs.slice(0, 10).map((ref, index) => evidenceLine(ref, index + 1));
  const nextActions = [
    '- 复核这条回答。',
    receipt.top_evidence_refs.length > 0 ? '- 引用更多原文前，先读取 E1。' : '',
    receipt.evidence_pack_ref ? '- 基于该证据包生成候选 qrels 审核包。' : '',
    '- 把这份限定 receipt 摘要复制为主栏指令。',
  ].filter(Boolean);
  return [
    '### 回答',
    read.answer || '保存的回答没有返回正文。',
    '',
    '### 证据状态',
    `- receipt: ${read.conversation_id} (${inline(receipt.receipt_schema_version, 'unknown', 80)})`,
    `- evidence_pack_ref: ${inline(receipt.evidence_pack_ref, 'none', 160)}`,
    `- 门禁: ${inline(gate?.status, 'unknown', 80)}${gate?.reason ? ` - ${inline(gate.reason, '', 160)}` : ''}`,
    `- qrels: ${inline(qrels?.status, 'unknown', 80)}；允许质量声明: ${qrels?.semantic_quality_claim_allowed === true ? '是' : '否'}`,
    `- 检索: method=${inline(retrieval?.retrieval_method, 'unknown', 80)}；provider=${inline(retrieval?.retrieval_provider, 'unknown', 80)}；rerank=${inline(retrieval?.rerank_status, 'unknown', 80)}`,
    `- 时效: ${inline(read.staleness.status || receipt.staleness_status, 'unknown', 80)}`,
    '',
    '### 证据',
    ...(evidenceLines.length > 0 ? evidenceLines : ['- 这条 receipt 没有返回限定证据引用。']),
    '',
    '### 后续动作',
    ...nextActions,
  ].join('\n');
}
