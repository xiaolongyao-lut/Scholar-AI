import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';

export type ContextTier = 'fast' | 'balanced' | 'thorough';

export interface ContextChunk {
  index: number;
  source: string;
  content: string;
  relevance_score?: number;
}

export interface ContextMetadata {
  chunks: ContextChunk[];
  truncated: boolean;
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
  source_paths?: string[];
}

export interface IntelligentChatResponse {
  response: string;
  session_id: string;
  context_chunks_used: number;
  tokens_used: TokenUsage;
  tier_used: ContextTier;
  context_metadata?: ContextMetadata;
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
  const { data } = await axios.post<IntelligentChatResponse>(
    `${getApiBaseUrl()}/api/chat`,
    {
      query: request.query,
      session_id: request.session_id,
      tier: request.tier || 'balanced',
      source_paths: request.source_paths,
    },
    { timeout: timeoutMs }
  );
  return data;
}
