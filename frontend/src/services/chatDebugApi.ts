import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import type { ContextTier } from './intelligentChatApi';

export interface DebugChunk {
  chunk_id?: string | null;
  material_id?: string | null;
  content_preview: string;
  relevance_score?: number | null;
  source: string;
  page?: number | string | null;
  section?: string | null;
  source_labels?: string[];
}

export interface RejectedChunk {
  chunk_id: string;
  reason: 'rank' | 'budget' | 'filter';
}

export interface DebugMetrics {
  query_rewrite_time_ms?: number | null;
  retrieval_time_ms: number;
  rerank_time_ms?: number | null;
  prompt_build_time_ms: number;
  generation_time_ms?: number | null;
  total_time_ms: number;
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
}

export interface ChatDebugRequest {
  query: string;
  project_id?: string;
  source_paths?: string[];
  tier?: ContextTier;
  top_k?: number;
  include_generation?: boolean;
  include_full_prompt?: boolean;
  persist_trace?: boolean;
}

export interface ChatDebugResponse {
  trace_id: string;
  query: string;
  rewritten_query?: string | null;
  retrieval_results: DebugChunk[];
  selected_chunks: DebugChunk[];
  rejected_chunks: RejectedChunk[];
  prompt_preview: string;
  prompt_template?: string | null;
  answer?: string | null;
  confidence_score?: number | null;
  confidence_label?: 'high' | 'medium' | 'low' | 'very_low' | null;
  metrics: DebugMetrics;
}

export async function sendChatDebug(
  request: ChatDebugRequest,
  timeoutMs: number = 30000,
): Promise<ChatDebugResponse> {
  const { data } = await axios.post<ChatDebugResponse>(
    `${getApiBaseUrl()}/api/chat/debug`,
    {
      query: request.query,
      project_id: request.project_id,
      source_paths: request.source_paths,
      tier: request.tier ?? 'balanced',
      top_k: request.top_k ?? 20,
      include_generation: request.include_generation ?? false,
      include_full_prompt: request.include_full_prompt ?? false,
      persist_trace: request.persist_trace ?? false,
    },
    { timeout: timeoutMs },
  );
  return data;
}
