import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';

export type ContextTier = 'fast' | 'balanced' | 'thorough';
export type ChatMode = 'direct' | 'literature_qa' | 'inspiration';

export interface ContextChunk {
  index: number;
  source: string;
  content: string;
  relevance_score?: number;
  chunk_id?: string | null;
  material_id?: string | null;
  title?: string | null;
  section_title?: string | null;
  page?: number | string | null;
  source_labels?: string[];
  source_hint?: string | null;
}

export interface ContextMetadata {
  chunks: ContextChunk[];
  truncated: boolean;
}

export interface EvidenceReference {
  chunk_id: string;
  material_id?: string | null;
  source: string;
  text: string;
  quote: string;
  label?: string;
  score?: number | null;
  source_labels?: string[];
  page?: number | string | null;
  source_hint?: string | null;
  query_overlap_tokens?: string[];
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

export interface TokenUsage {
  prompt: number;
  completion: number;
  total: number;
}

export interface IntelligentChatRequest {
  query: string;
  session_id?: string;
  tier?: ContextTier;
  project_id?: string;
  source_paths?: string[];
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
  evidence_refs?: EvidenceReference[];
  actual_sampling_params?: {
    temperature: number;
    top_p: number;
    top_k: number;
    max_tokens: number;
  };
}

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
  total_turns: number;
  total_tokens: number;
  created_at?: string | null;
  updated_at?: string | null;
  preview: string;
  mode?: ChatMode;
  legacy_mode_inferred?: boolean;
}

export interface ChatSessionListResponse {
  sessions: ChatSessionSummary[];
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
  tier_used?: ContextTier | null;
  context_metadata?: ContextMetadata | null;
  tokens_used?: TokenUsage | null;
  evidence_refs?: EvidenceReference[];
  inspiration_context?: InspirationContext | null;
}

export interface ChatResumeResponse {
  session_id: string;
  messages: ChatResumeMessage[];
}

export async function getBudgetStatus(): Promise<BudgetStatus> {
  const { data } = await axios.get<BudgetStatus>(`${getApiBaseUrl()}/api/budget/status`);
  return data;
}

export async function listChatSessions(timeoutMs: number = 15000): Promise<ChatSessionSummary[]> {
  const { data } = await axios.get<ChatSessionListResponse>(
    `${getApiBaseUrl()}/api/chat/sessions`,
    { timeout: timeoutMs }
  );
  return Array.isArray(data.sessions) ? data.sessions : [];
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
  return data;
}

export async function sendIntelligentChatMessage(
  request: IntelligentChatRequest,
  timeoutMs: number = 60000
): Promise<IntelligentChatResponse> {
  const payload: Record<string, unknown> = {
    query: request.query,
    session_id: request.session_id,
    tier: request.tier || 'balanced',
    project_id: request.project_id,
    source_paths: request.source_paths,
    direct_mode: request.direct_mode ?? false,
  };
  if (request.mode !== undefined) payload.mode = request.mode;
  if (request.inspiration_context !== undefined) payload.inspiration_context = request.inspiration_context;
  if (request.images && request.images.length > 0) payload.images = request.images;
  const { data } = await axios.post<IntelligentChatResponse>(
    `${getApiBaseUrl()}/api/chat`,
    payload,
    { timeout: timeoutMs }
  );
  return data;
}

export function isSessionModeConflictError(error: unknown): SessionModeConflictError | null {
  if (!axios.isAxiosError(error) || !error.response) return null;
  if (error.response.status !== 409) return null;
  const body = error.response.data;
  if (body && typeof body === 'object' && body.error === 'session_mode_conflict') {
    return body as SessionModeConflictError;
  }
  return null;
}
