import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import {
  isPdfBboxUnit,
  readPdfBbox,
  type PdfBbox,
  type PdfBboxUnit,
  type PdfContentSelection,
} from '@/lib/pdfAnchor';
import {
  sanitizeResearchSelections,
  type ResearchSelection,
} from '@/types/researchSelection';
import {
  sanitizeVisualObservationReferences,
  type VisualObservationReference,
} from '@/types/visualObservation';
import type { AnalysisChainPayload } from './discussionApi';

export type ContextTier = 'fast' | 'balanced' | 'thorough';
export type ChatMode = 'direct' | 'literature_qa' | 'inspiration';
export type GeneratedIn = 'smart_read' | 'mcp_sidebar';
export type EvidenceRole = 'selected_content' | 'current_material' | 'cited_project_material' | 'project_context';

export interface ContextChunk {
  index: number;
  source: string;
  content: string;
  relevance_score?: number;
  chunk_id?: string | null;
  material_id?: string | null;
  evidence_role?: EvidenceRole;
  title?: string | null;
  section_title?: string | null;
  page?: number | string | null;
  source_labels?: string[];
  source_hint?: string | null;
  bbox?: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
  figure_candidate?: string | null;
  figure_candidate_detail?: Record<string, unknown> | null;
  image_paths?: string[];
}

export interface ContextMetadata {
  chunks: ContextChunk[];
  truncated: boolean;
}

export interface EvidenceReference {
  chunk_id: string;
  material_id?: string | null;
  evidence_role?: EvidenceRole;
  source: string;
  text: string;
  quote: string;
  anchor_kind?: 'text' | 'visual' | null;
  content_hash?: string | null;
  locator_hash?: string | null;
  chunk_hash?: string | null;
  embedding_input_hash?: string | null;
  hash_version?: string | null;
  label?: string;
  score?: number | null;
  source_labels?: string[];
  page?: number | string | null;
  bbox?: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
  source_hint?: string | null;
  query_overlap_tokens?: string[];
  source_kind?: 'local' | 'web' | 'mcp';
  source_type?: 'project' | 'wiki';
  source_title?: string | null;
  source_path?: string | null;
  joint_score?: number | null;
  figure_candidate?: string | null;
  figure_candidate_detail?: Record<string, unknown> | null;
  image_paths?: string[];
}

export interface CurrentPdfContext {
  material_id: string;
  page?: number | null;
  page_label?: string | null;
  chunk_id?: string | null;
  bbox?: PdfBbox | null;
  bbox_unit?: PdfBboxUnit | null;
  selected_text?: string | null;
  selection?: PdfContentSelection | null;
  /** Canonical bounded list for mixed text/figure/table/formula selections. */
  selections?: PdfContentSelection[];
  context_kind?: 'reader_page' | 'selection' | 'deep_link';
  source_labels?: string[];
}

export interface InspirationContext {
  spark_id: string;
  content: string;
  causal_chain_summary?: string;
  evidence_texts?: string[];
  evidence_refs?: EvidenceReference[];
  suggested_angles?: string[];
}

export interface ImageAttachment {
  mime: string;
  data_b64: string;
  size: number;
  name?: string;
}

export interface SessionModeConflictError {
  ok: false;
  error: 'session_mode_conflict';
  current_mode: ChatMode;
  requested_mode: ChatMode;
}

// Keep chat/stream requests serial so one browser session does not
// emit overlapping upstream calls through the shared smart-read endpoint.
let smartReadRequestQueue: Promise<void> = Promise.resolve();

function runSmartReadRequestSerially<T>(task: () => Promise<T>): Promise<T> {
  const run = smartReadRequestQueue.then(task, task);
  smartReadRequestQueue = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

export interface TokenUsage {
  prompt: number;
  completion: number;
  total: number;
}

export type AnswerOrigin = 'internal_smartread' | 'external_agent';
export type AnswerModelOrigin = 'scholar_ai_configured_chat' | 'external_agent';

export interface IntelligentChatRequest {
  query: string;
  /** Stable client turn id used to keep retries and durable selections aligned. */
  turn_id?: string;
  session_id?: string;
  tier?: ContextTier;
  project_id?: string;
  project_reasoning_bias_enabled?: boolean;
  answer_origin?: AnswerOrigin;
  material_id?: string;
  current_pdf_context?: CurrentPdfContext;
  /** Durable input locators. Never include image indexes or encoded pixels. */
  research_selections?: ResearchSelection[];
  source_paths?: string[];
  mcpServerIds?: string[];
  mcpAllowHighRiskTools?: boolean;
  useLocalLiteratureTools?: boolean;
  generated_in?: GeneratedIn;
  evidence_pack_ref?: string;
  /** @deprecated Legacy compatibility only. Unified smart-read callers should omit this. */
  direct_mode?: boolean;
  mode?: ChatMode;
  inspiration_context?: InspirationContext;
  images?: ImageAttachment[];
}

export interface IntelligentChatResponse {
  response: string;
  session_id: string;
  context_chunks_used: number;
  tokens_used: TokenUsage;
  tier_used: ContextTier;
  context_metadata?: ContextMetadata;
  retrieval_diagnostics?: SmartReadRetrievalDiagnostics | null;
  evidence_refs?: EvidenceReference[];
  visual_evidence_refs?: EvidenceReference[];
  visual_observation_refs?: VisualObservationReference[];
  answer_origin?: AnswerOrigin;
  answer_model_origin?: AnswerModelOrigin;
  retrieval_provider?: 'scholar_ai';
  generated_in?: GeneratedIn;
  evidence_pack_ref?: string | null;
  actual_sampling_params?: {
    temperature: number;
    top_p: number;
    top_k: number;
    max_tokens: number;
  };
  analysis_chain?: AnalysisChainPayload | null;
  mcp_run?: Record<string, unknown> | null;
}

export interface SmartReadGatewayDiagnostics {
  dense_hit_count?: number;
  lexical_hit_count?: number;
  visual_hit_count?: number;
  candidate_count?: number;
  dense_enabled?: boolean;
  material_balancing_enabled?: boolean;
  chroma_status?: string;
  fts_status?: string;
  fallback_reasons?: string[];
  gate_status_counts?: Record<string, number>;
}

export interface SmartReadTolfDiagnostics {
  status?: string;
  candidate_count?: number;
  input_count?: number;
  graph_node_count?: number;
  graph_edge_count?: number;
  gate_after_count?: number;
  activation_min?: number | null;
  activation_max?: number | null;
  activation_mean?: number | null;
  top_final_rank_score?: number | null;
  rank_contribution_keys?: string[];
  fallback_reason?: string | null;
}

export interface SmartReadRetrievalDiagnostics {
  retrieval_method?: string;
  embedding_status?: string | null;
  rerank_status?: string | null;
  lexical_only?: boolean;
  fallback_reasons?: string[];
  gateway?: SmartReadGatewayDiagnostics | null;
  tolf?: SmartReadTolfDiagnostics | null;
  qrels_status?: {
    schema_version?: 'retrieval-qrels-status/v1';
    status?: 'missing' | 'candidate' | 'reviewed' | 'canonical';
    candidate_qrels_count?: number;
    reviewed_qrels_count?: number;
    canonical_qrels_count?: number;
    semantic_quality_claim_allowed?: boolean;
    quality_claim?:
      | 'no_qrels_available'
      | 'candidate_qrels_review_required'
      | 'reviewed_qrels_promotion_required'
      | 'canonical_qrels_available';
    notes?: string[];
  } | null;
}

export type IntelligentChatStreamEvent =
  | {
      event: 'metadata';
      session_id: string;
      context_chunks_used: number;
      tier_used: ContextTier;
      context_metadata?: ContextMetadata | null;
      evidence_refs?: EvidenceReference[];
      visual_evidence_refs?: EvidenceReference[];
      actual_sampling_params?: IntelligentChatResponse['actual_sampling_params'] | null;
      retrieval_diagnostics?: SmartReadRetrievalDiagnostics | null;
      answer_origin?: AnswerOrigin;
      answer_model_origin?: AnswerModelOrigin;
      retrieval_provider?: 'scholar_ai';
      generated_in?: GeneratedIn;
      evidence_pack_ref?: string | null;
    }
  | {
      event: 'text_delta';
      delta: string;
    }
  | {
      event: 'usage';
      usage?: {
        prompt_tokens?: number;
        completion_tokens?: number;
        total_tokens?: number;
        prompt?: number;
        completion?: number;
        total?: number;
      };
      model?: string;
    }
  | {
      event: 'analysis_chain_done';
      session_id?: string;
      analysis_chain: AnalysisChainPayload;
    }
  | {
      event: 'done';
      response?: string;
      session_id?: string;
      tokens_used?: TokenUsage;
      visual_evidence_refs?: EvidenceReference[];
      visual_observation_refs?: VisualObservationReference[];
      answer_origin?: AnswerOrigin;
      answer_model_origin?: AnswerModelOrigin;
      generated_in?: GeneratedIn;
      evidence_pack_ref?: string | null;
    }
  | {
      event: 'error';
      error: string;
      status_code?: number;
    };

export interface BudgetStatus {
  call_count: number;
  call_cap: number;
  cost_usd: number;
  budget_usd: number;
  percent_calls: number;
  percent_usd: number;
}

export interface ChatSessionSummary {
  session_id: string;
  project_id?: string | null;
  title?: string | null;
  total_turns: number;
  total_tokens: number;
  created_at?: string | null;
  updated_at?: string | null;
  preview: string;
  mode?: ChatMode;
  legacy_mode_inferred?: boolean;
  source?: string | null;
  agent_count?: number | null;
  synthesis_preview?: string | null;
  archived?: boolean;
  archived_at?: string | null;
  fork?: {
    source_session_id: string;
    base_node_id: string;
    branch_id: string;
    created_at?: string;
  } | null;
}

export interface ChatSessionListResponse {
  sessions: ChatSessionSummary[];
}

export interface ChatSessionArchiveResponse {
  session_id: string;
  archived: boolean;
  archived_at?: string | null;
}

export interface ChatHistorySearchResult {
  conversation_id: string;
  node_id: string;
  role: string;
  node_type: string;
  snippet: string;
}

export interface ChatHistorySearchResponse {
  query: string;
  results: ChatHistorySearchResult[];
}

export interface ChatHistoryForkResponse {
  conversation_id: string;
  branch_id: string;
  base_node_id: string;
  fork_session_id: string;
}

export interface ChatHistoryImportResponse {
  imported_conversations: number;
  imported_messages: number;
  imported_compression_snapshots: number;
}

export interface ChatAgent {
  agent_id: string;
  conversation_id: string;
  agent_role: string;
  display_name: string;
  provider?: string | null;
  model?: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface ChatAgentsResponse {
  conversation_id: string;
  agents: ChatAgent[];
}

export interface ChatResumeRequest {
  session_id: string;
  limit?: number;
}

export interface ChatResumeMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  turn_id?: string | null;
  research_selections?: ResearchSelection[];
  tier_used?: ContextTier | null;
  context_metadata?: ContextMetadata | null;
  tokens_used?: TokenUsage | null;
  evidence_refs?: EvidenceReference[];
  visual_evidence_refs?: EvidenceReference[];
  visual_observation_refs?: VisualObservationReference[];
  answer_origin?: AnswerOrigin | null;
  answer_model_origin?: AnswerModelOrigin | null;
  retrieval_provider?: 'scholar_ai' | null;
  generated_in?: GeneratedIn | null;
  evidence_pack_ref?: string | null;
  retrieval_diagnostics?: SmartReadRetrievalDiagnostics | null;
  analysis_chain?: AnalysisChainPayload | null;
  inspiration_context?: InspirationContext | null;
}

export interface ChatResumeResponse {
  session_id: string;
  project_id?: string | null;
  messages: ChatResumeMessage[];
}

export class IntelligentChatHttpError extends Error {
  readonly status: number;
  readonly statusText: string;
  readonly bodyText: string;
  readonly body: unknown;

  constructor(status: number, statusText: string, bodyText: string, body: unknown) {
    const detail = extractErrorDetail(body);
    const statusLabel = `${status} ${statusText}`.trim();
    super(detail ? `${statusLabel}: ${detail}` : statusLabel);
    this.name = 'IntelligentChatHttpError';
    this.status = status;
    this.statusText = statusText;
    this.bodyText = bodyText;
    this.body = body;
  }
}

function extractErrorDetail(body: unknown): string | null {
  if (!isRecord(body)) return null;
  const detail = body.detail;
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (isRecord(detail)) return JSON.stringify(detail);
  const error = body.error;
  if (isRecord(error) && typeof error.message === 'string' && error.message.trim()) {
    return error.message.trim();
  }
  if (typeof error === 'string' && error.trim()) return error.trim();
  return null;
}

function parseResponseBody(text: string): unknown {
  if (!text.trim()) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export async function getBudgetStatus(): Promise<BudgetStatus> {
  const { data } = await axios.get<BudgetStatus>(`${getApiBaseUrl()}/api/budget/status`);
  return data;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readOptionalString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed || null;
}

function readOptionalPage(value: unknown): number | string | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return readOptionalString(value);
}

function readOptionalStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const values = value.flatMap((item): string[] => {
    const text = readOptionalString(item);
    return text ? [text] : [];
  });
  return values.length > 0 ? values : undefined;
}

/**
 * Normalize evidence at the HTTP boundary without collapsing quote/text or
 * guessing a coordinate unit. A bbox is usable only when its explicit unit is
 * known; otherwise the page/chunk identity remains while geometry is dropped.
 */
function sanitizeEvidenceReference(value: unknown): EvidenceReference | null {
  if (!isRecord(value)) return null;
  const chunkId = readOptionalString(value.chunk_id) ?? readOptionalString(value.ref_id);
  if (!chunkId) return null;

  const bboxUnit = isPdfBboxUnit(value.bbox_unit) ? value.bbox_unit : null;
  const bbox = bboxUnit ? readPdfBbox(value.bbox) : null;
  const sourceTitle = readOptionalString(value.source_title);
  const source = readOptionalString(value.source) ?? sourceTitle ?? '';
  const anchorKind = value.anchor_kind === 'text' || value.anchor_kind === 'visual'
    ? value.anchor_kind
    : null;
  const evidenceRole = value.evidence_role === 'selected_content'
    || value.evidence_role === 'current_material'
    || value.evidence_role === 'cited_project_material'
    || value.evidence_role === 'project_context'
    ? value.evidence_role
    : undefined;
  const sourceKind = value.source_kind === 'local' || value.source_kind === 'web' || value.source_kind === 'mcp'
    ? value.source_kind
    : undefined;
  const sourceType = value.source_type === 'project' || value.source_type === 'wiki'
    ? value.source_type
    : undefined;
  const sanitized: EvidenceReference = {
    chunk_id: chunkId,
    material_id: readOptionalString(value.material_id),
    ...(evidenceRole ? { evidence_role: evidenceRole } : {}),
    source,
    // Keep these fields independent. An absent text must not be replaced by quote,
    // and an absent quote must not be synthesized from a summary.
    text: readOptionalString(value.text) ?? '',
    quote: readOptionalString(value.quote) ?? '',
    ...(anchorKind ? { anchor_kind: anchorKind } : { anchor_kind: null }),
    ...(bbox ? { bbox: [...bbox], bbox_unit: bboxUnit } : { bbox: null, bbox_unit: null }),
    ...(readOptionalString(value.label) ? { label: readOptionalString(value.label) ?? undefined } : {}),
    ...(typeof value.score === 'number' && Number.isFinite(value.score) ? { score: value.score } : {}),
    ...(readOptionalPage(value.page) !== null ? { page: readOptionalPage(value.page) } : {}),
    ...(readOptionalStringArray(value.source_labels) ? { source_labels: readOptionalStringArray(value.source_labels) } : {}),
    ...(readOptionalString(value.source_hint) ? { source_hint: readOptionalString(value.source_hint) ?? undefined } : {}),
    ...(sourceKind ? { source_kind: sourceKind } : {}),
    ...(sourceType ? { source_type: sourceType } : {}),
    ...(sourceTitle ? { source_title: sourceTitle } : {}),
    ...(readOptionalString(value.source_path) ? { source_path: readOptionalString(value.source_path) ?? undefined } : {}),
    ...(typeof value.joint_score === 'number' && Number.isFinite(value.joint_score) ? { joint_score: value.joint_score } : {}),
    ...(readOptionalString(value.figure_candidate) ? { figure_candidate: readOptionalString(value.figure_candidate) ?? undefined } : {}),
    ...(isRecord(value.figure_candidate_detail) ? { figure_candidate_detail: value.figure_candidate_detail } : {}),
    ...(readOptionalStringArray(value.image_paths) ? { image_paths: readOptionalStringArray(value.image_paths) } : {}),
  };
  for (const key of ['content_hash', 'locator_hash', 'chunk_hash', 'embedding_input_hash', 'hash_version'] as const) {
    const hash = readOptionalString(value[key]);
    if (hash) sanitized[key] = hash;
  }
  return sanitized;
}

export function sanitizeEvidenceReferences(value: unknown): EvidenceReference[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): EvidenceReference[] => {
    const reference = sanitizeEvidenceReference(item);
    return reference ? [reference] : [];
  });
}

function isChatSessionListResponse(data: unknown): data is ChatSessionListResponse {
  if (!isRecord(data)) return false;
  return Array.isArray(data.sessions);
}

function isChatHistorySearchResponse(data: unknown): data is ChatHistorySearchResponse {
  if (!isRecord(data)) return false;
  return Array.isArray(data.results);
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 智能 chat agents 响应守卫, 当前路径用结构性宽容解析, 保留供后续 strict-mode 切换
function isChatSessionAgentsResponse(data: unknown): data is ChatAgentsResponse {
  if (!isRecord(data)) return false;
  return Array.isArray(data.agents);
}

export async function listChatSessions(
  timeoutMs: number = 15000,
  options: { includeArchived?: boolean; archivedOnly?: boolean } = {},
): Promise<ChatSessionSummary[]> {
  const { data } = await axios.get<unknown>(
    `${getApiBaseUrl()}/api/chat/sessions`,
    {
      params: {
        include_archived: options.includeArchived || undefined,
        archived_only: options.archivedOnly || undefined,
      },
      timeout: timeoutMs,
    }
  );
  if (!isChatSessionListResponse(data)) {
    throw new Error('Invalid response shape from /api/chat/sessions');
  }
  return data.sessions;
}

export async function archiveChatSession(
  sessionId: string,
  timeoutMs: number = 15000,
): Promise<ChatSessionArchiveResponse> {
  const normalized = sessionId.trim();
  if (!normalized) {
    throw new Error('session_id must not be empty');
  }
  const { data } = await axios.put<ChatSessionArchiveResponse>(
    `${getApiBaseUrl()}/api/chat/sessions/${encodeURIComponent(normalized)}/archive`,
    {},
    { timeout: timeoutMs },
  );
  return data;
}

export async function restoreChatSession(
  sessionId: string,
  timeoutMs: number = 15000,
): Promise<ChatSessionArchiveResponse> {
  const normalized = sessionId.trim();
  if (!normalized) {
    throw new Error('session_id must not be empty');
  }
  const { data } = await axios.put<ChatSessionArchiveResponse>(
    `${getApiBaseUrl()}/api/chat/sessions/${encodeURIComponent(normalized)}/restore`,
    {},
    { timeout: timeoutMs },
  );
  return data;
}

export async function deleteChatSession(
  sessionId: string,
  timeoutMs: number = 15000
): Promise<void> {
  const normalized = sessionId.trim();
  if (!normalized) {
    throw new Error('session_id must not be empty');
  }
  await axios.delete(
    `${getApiBaseUrl()}/api/chat/sessions/${encodeURIComponent(normalized)}`,
    { timeout: timeoutMs }
  );
}

export interface ChatSessionBulkDeleteResult {
  deleted: string[];
  missing: string[];
  deleted_count: number;
}

export async function bulkDeleteChatSessions(
  sessionIds: string[],
  timeoutMs: number = 30000,
): Promise<ChatSessionBulkDeleteResult> {
  const normalized = Array.from(
    new Set(sessionIds.map((id) => id.trim()).filter(Boolean)),
  );
  if (normalized.length === 0) {
    throw new Error('session_ids must not be empty');
  }
  const { data } = await axios.post<ChatSessionBulkDeleteResult>(
    `${getApiBaseUrl()}/api/chat/sessions/bulk-delete`,
    { session_ids: normalized },
    { timeout: timeoutMs },
  );
  return data;
}

export async function importChatHistory(timeoutMs: number = 15000): Promise<ChatHistoryImportResponse> {
  const { data } = await axios.post<ChatHistoryImportResponse>(
    `${getApiBaseUrl()}/api/chat/history/import`,
    {},
    { timeout: timeoutMs },
  );
  return data;
}

export async function searchChatHistory(
  query: string,
  limit: number = 20,
  timeoutMs: number = 15000,
): Promise<ChatHistorySearchResult[]> {
  const normalized = query.trim();
  if (!normalized) {
    return [];
  }
  const { data } = await axios.get<unknown>(
    `${getApiBaseUrl()}/api/chat/history/search`,
    {
      params: { q: normalized, limit },
      timeout: timeoutMs,
    },
  );
  if (!isChatHistorySearchResponse(data)) {
    throw new Error('Invalid response shape from /api/chat/history/search');
  }
  return data.results;
}

export async function forkChatHistoryConversation(
  conversationId: string,
  baseNodeId: string,
  timeoutMs: number = 15000,
): Promise<ChatHistoryForkResponse> {
  const normalizedConversationId = conversationId.trim();
  const normalizedBaseNodeId = baseNodeId.trim();
  if (!normalizedConversationId) {
    throw new Error('conversation_id must not be empty');
  }
  if (!normalizedBaseNodeId) {
    throw new Error('base_node_id must not be empty');
  }
  const { data } = await axios.post<ChatHistoryForkResponse>(
    `${getApiBaseUrl()}/api/chat/history/conversations/${encodeURIComponent(normalizedConversationId)}/fork`,
    { base_node_id: normalizedBaseNodeId },
    { timeout: timeoutMs },
  );
  return data;
}

export async function listChatHistoryAgents(
  conversationId: string,
  timeoutMs: number = 15000,
): Promise<ChatAgent[]> {
  const normalizedConversationId = conversationId.trim();
  if (!normalizedConversationId) {
    return [];
  }
  const { data } = await axios.get<ChatAgentsResponse>(
    `${getApiBaseUrl()}/api/chat/history/conversations/${encodeURIComponent(normalizedConversationId)}/agents`,
    { timeout: timeoutMs },
  );
  return Array.isArray(data.agents) ? data.agents : [];
}

export async function resumeChatSession(
  request: ChatResumeRequest,
  timeoutMs: number = 15000
): Promise<ChatResumeResponse> {
  if (!request.session_id.trim()) {
    throw new Error('session_id must not be empty');
  }
  const { data } = await axios.post<ChatResumeResponse>(
    `${getApiBaseUrl()}/api/chat/resume`,
    {
      session_id: request.session_id,
      limit: request.limit ?? 100,
    },
    { timeout: timeoutMs }
  );
  return {
    ...data,
    messages: Array.isArray(data.messages)
      ? data.messages.map((message) => {
          const { visual_observation_refs: rawReferences, ...rest } = message;
          const references = sanitizeVisualObservationReferences(rawReferences);
          const evidenceReferences = sanitizeEvidenceReferences(message.evidence_refs);
          const visualEvidenceReferences = sanitizeEvidenceReferences(message.visual_evidence_refs);
          return {
            ...rest,
            ...(message.evidence_refs !== undefined ? { evidence_refs: evidenceReferences } : {}),
            ...(message.visual_evidence_refs !== undefined
              ? { visual_evidence_refs: visualEvidenceReferences }
              : {}),
            ...(references.length > 0 ? { visual_observation_refs: references } : {}),
          };
        })
      : [],
  };
}

export async function sendIntelligentChatMessage(
  request: IntelligentChatRequest,
  timeoutMs: number = 60000
): Promise<IntelligentChatResponse> {
  return runSmartReadRequestSerially(async () => {
    const payload: Record<string, unknown> = {
      query: request.query,
      turn_id: request.turn_id,
      session_id: request.session_id,
      tier: request.tier || 'balanced',
      project_id: request.project_id,
      project_reasoning_bias_enabled: request.project_reasoning_bias_enabled,
      answer_origin: request.answer_origin,
      generated_in: request.generated_in,
      evidence_pack_ref: request.evidence_pack_ref,
      material_id: request.material_id,
      current_pdf_context: request.current_pdf_context,
      research_selections: request.research_selections
        ? sanitizeResearchSelections(request.research_selections)
        : undefined,
      source_paths: request.source_paths,
    };
    if (request.direct_mode !== undefined) payload.direct_mode = request.direct_mode;
    if (request.mode !== undefined) payload.mode = request.mode;
    if (request.mcpServerIds !== undefined) payload.mcp_server_ids = request.mcpServerIds;
    if (request.mcpAllowHighRiskTools !== undefined) {
      payload.mcp_allow_high_risk_tools = request.mcpAllowHighRiskTools;
    }
    if (request.useLocalLiteratureTools !== undefined) {
      payload.use_local_literature_tools = request.useLocalLiteratureTools;
    }
    if (request.inspiration_context !== undefined) payload.inspiration_context = request.inspiration_context;
    if (request.images && request.images.length > 0) payload.images = request.images;
    const { data } = await axios.post<IntelligentChatResponse>(
      `${getApiBaseUrl()}/api/chat`,
      payload,
      { timeout: timeoutMs }
    );
    const {
      visual_observation_refs: rawReferences,
      evidence_refs: rawEvidenceReferences,
      visual_evidence_refs: rawVisualEvidenceReferences,
      ...rest
    } = data;
    const references = sanitizeVisualObservationReferences(rawReferences);
    return {
      ...rest,
      ...(rawEvidenceReferences !== undefined
        ? { evidence_refs: sanitizeEvidenceReferences(rawEvidenceReferences) }
        : {}),
      ...(rawVisualEvidenceReferences !== undefined
        ? { visual_evidence_refs: sanitizeEvidenceReferences(rawVisualEvidenceReferences) }
        : {}),
      ...(references.length > 0 ? { visual_observation_refs: references } : {}),
    };
  });
}

export async function streamIntelligentChatMessage(
  request: IntelligentChatRequest,
  opts: {
    onEvent: (event: IntelligentChatStreamEvent) => void;
    signal?: AbortSignal;
  },
): Promise<void> {
  await runSmartReadRequestSerially(async () => {
    const payload: Record<string, unknown> = {
      query: request.query,
      turn_id: request.turn_id,
      session_id: request.session_id,
      tier: request.tier || 'balanced',
      project_id: request.project_id,
      project_reasoning_bias_enabled: request.project_reasoning_bias_enabled,
      answer_origin: request.answer_origin,
      generated_in: request.generated_in,
      evidence_pack_ref: request.evidence_pack_ref,
      material_id: request.material_id,
      current_pdf_context: request.current_pdf_context,
      research_selections: request.research_selections
        ? sanitizeResearchSelections(request.research_selections)
        : undefined,
      source_paths: request.source_paths,
    };
    if (request.direct_mode !== undefined) payload.direct_mode = request.direct_mode;
    if (request.mode !== undefined) payload.mode = request.mode;
    if (request.mcpServerIds !== undefined) payload.mcp_server_ids = request.mcpServerIds;
    if (request.mcpAllowHighRiskTools !== undefined) {
      payload.mcp_allow_high_risk_tools = request.mcpAllowHighRiskTools;
    }
    if (request.useLocalLiteratureTools !== undefined) {
      payload.use_local_literature_tools = request.useLocalLiteratureTools;
    }
    if (request.inspiration_context !== undefined) payload.inspiration_context = request.inspiration_context;
    if (request.images && request.images.length > 0) payload.images = request.images;

    const response = await fetch(`${getApiBaseUrl()}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: opts.signal,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => '');
      throw new IntelligentChatHttpError(
        response.status,
        response.statusText,
        text,
        parseResponseBody(text),
      );
    }
    if (!response.body) {
      throw new Error('stream response has no body');
    }

    if (opts.signal?.aborted) {
      throw new DOMException('The operation was aborted.', 'AbortError');
    }

    const reader = response.body.getReader();
    const abortReader = () => {
      void reader.cancel().catch(() => undefined);
    };
    opts.signal?.addEventListener('abort', abortReader, { once: true });
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    try {
      while (true) {
        if (opts.signal?.aborted) {
          throw new DOMException('The operation was aborted.', 'AbortError');
        }
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        while (true) {
          const sep = buffer.indexOf('\n\n');
          if (sep < 0) break;
          const chunk = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          for (const line of chunk.split('\n')) {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data:')) continue;
            const rawPayload = trimmed.slice(5).trim();
            if (!rawPayload) continue;
            let event: IntelligentChatStreamEvent | null = null;
            try {
              const parsed: unknown = JSON.parse(rawPayload);
              event = coerceIntelligentChatStreamEvent(parsed);
            } catch {
              // Ignore malformed provider/proxy fragments; the backend emits a
              // terminal error event for actionable failures.
            }
            if (event) {
              opts.onEvent(event);
            }
          }
        }
      }
      if (opts.signal?.aborted) {
        throw new DOMException('The operation was aborted.', 'AbortError');
      }
    } finally {
      opts.signal?.removeEventListener('abort', abortReader);
      try {
        reader.releaseLock();
      } catch {
        // Already released on abort.
      }
    }
  });
}

function coerceStringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const items = value.filter((item): item is string => typeof item === 'string');
  return items.length > 0 ? items : undefined;
}

function coerceAnalysisChainPayload(value: unknown): AnalysisChainPayload | null {
  if (!isRecord(value)) return null;
  const chain: AnalysisChainPayload = {};
  if (typeof value.observation === 'string') chain.observation = value.observation;
  if (typeof value.mechanism === 'string') chain.mechanism = value.mechanism;
  const evidence = coerceStringList(value.evidence);
  if (evidence) chain.evidence = evidence;
  if (typeof value.boundary === 'string') chain.boundary = value.boundary;
  const counterEvidence = coerceStringList(value.counter_evidence);
  if (counterEvidence) chain.counter_evidence = counterEvidence;
  if (typeof value.next_action === 'string') chain.next_action = value.next_action;
  return Object.keys(chain).length > 0 ? chain : null;
}

function coerceIntelligentChatStreamEvent(value: unknown): IntelligentChatStreamEvent | null {
  if (!isRecord(value) || typeof value.event !== 'string') return null;
  switch (value.event) {
    case 'metadata':
      if (typeof value.session_id !== 'string') return null;
      if (typeof value.context_chunks_used !== 'number') return null;
      if (value.tier_used !== 'fast' && value.tier_used !== 'balanced' && value.tier_used !== 'thorough') {
        return null;
      }
      return {
        ...(value as Extract<IntelligentChatStreamEvent, { event: 'metadata' }>),
        ...(value.evidence_refs !== undefined
          ? { evidence_refs: sanitizeEvidenceReferences(value.evidence_refs) }
          : {}),
        ...(value.visual_evidence_refs !== undefined
          ? { visual_evidence_refs: sanitizeEvidenceReferences(value.visual_evidence_refs) }
          : {}),
      };
    case 'text_delta':
      return typeof value.delta === 'string' ? value as IntelligentChatStreamEvent : null;
    case 'usage':
      return value as IntelligentChatStreamEvent;
    case 'analysis_chain_done': {
      const chain = coerceAnalysisChainPayload(value.analysis_chain);
      if (!chain) return null;
      return {
        event: 'analysis_chain_done',
        session_id: typeof value.session_id === 'string' ? value.session_id : undefined,
        analysis_chain: chain,
      };
    }
    case 'done': {
      const references = sanitizeVisualObservationReferences(value.visual_observation_refs);
      const {
        visual_observation_refs: _rawReferences,
        visual_evidence_refs: rawVisualEvidenceReferences,
        ...rest
      } = value;
      return {
        ...(rest as Extract<IntelligentChatStreamEvent, { event: 'done' }>),
        ...(rawVisualEvidenceReferences !== undefined
          ? { visual_evidence_refs: sanitizeEvidenceReferences(rawVisualEvidenceReferences) }
          : {}),
        ...(references.length > 0 ? { visual_observation_refs: references } : {}),
      };
    }
    case 'error':
      return typeof value.error === 'string' ? value as IntelligentChatStreamEvent : null;
    default:
      return null;
  }
}

function coerceSessionModeConflictError(value: unknown): SessionModeConflictError | null {
  if (!isRecord(value)) return null;
  if (value.ok !== false) return null;
  if (value.error !== 'session_mode_conflict') return null;
  if (
    value.current_mode !== 'direct'
    && value.current_mode !== 'literature_qa'
    && value.current_mode !== 'inspiration'
  ) {
    return null;
  }
  if (
    value.requested_mode !== 'direct'
    && value.requested_mode !== 'literature_qa'
    && value.requested_mode !== 'inspiration'
  ) {
    return null;
  }
  return {
    ok: false,
    error: 'session_mode_conflict',
    current_mode: value.current_mode,
    requested_mode: value.requested_mode,
  };
}

export function isSessionModeConflictError(error: unknown): SessionModeConflictError | null {
  let status: number | null = null;
  let body: unknown = null;
  if (axios.isAxiosError(error) && error.response) {
    status = error.response.status;
    body = error.response.data;
  } else if (error instanceof IntelligentChatHttpError) {
    status = error.status;
    body = error.body;
  }
  if (status !== 409) return null;
  return coerceSessionModeConflictError(body);
}
