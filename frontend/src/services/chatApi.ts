import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl.ts';
import type { LLMConfig } from './settingsStore.ts';

export interface ChatAskResponse {
  answer: string;
  model?: string;
  usage?: Record<string, number>;
}

export interface ChatHistoryMessage {
  role: 'user' | 'assistant';
  content: string;
}

const askWithPayload = async (
  body: Record<string, unknown>,
  timeoutMs: number,
): Promise<ChatAskResponse> => {
  const { data } = await axios.post<ChatAskResponse>(
    `${getApiBaseUrl()}/chat/ask`,
    body,
    { timeout: timeoutMs },
  );
  return data;
};

export function toBackendLLMConfig(llm: LLMConfig): Record<string, unknown> {
  return {
    temperature: llm.temperature,
    top_p: llm.topP,
    max_tokens: llm.maxTokens,
    system_prompt: llm.systemPrompt,
  };
}

export async function askChatWithConfig(params: {
  query: string;
  context?: string[];
  history?: ChatHistoryMessage[];
  llm: LLMConfig;
  aiCostProfile?: 'balanced' | 'aggressive' | 'quality';
  timeoutMs?: number;
  fallbackMode?: 'gemini-first' | 'none';
  mcpServerIds?: string[];
}): Promise<ChatAskResponse> {
  const {
    query,
    context = [],
    history = [],
    llm,
    aiCostProfile,
    timeoutMs = 180000,
    mcpServerIds,
  } = params;

  const body: Record<string, unknown> = {
    query,
    context,
    history,
    llm: toBackendLLMConfig(llm),
    ai_cost_profile: aiCostProfile,
  };
  if (mcpServerIds !== undefined) {
    body.mcp_server_ids = mcpServerIds;
  }

  return await askWithPayload(body, timeoutMs);
}

export interface DiscoveredModel {
  id: string;
  name: string;
  description?: string;
}

export interface DiscoverModelsResult {
  ok: boolean;
  models: DiscoveredModel[];
  endpoint?: string;
  error?: string;
}

export async function discoverModels(baseUrl: string, apiKey: string, subsystem: 'chat' | 'embedding' | 'rerank' = 'chat'): Promise<DiscoverModelsResult> {
  if (!baseUrl.trim()) {
    return { ok: false, models: [], error: 'Base URL is empty' };
  }
  try {
    const resp = await axios.post(`${getApiBaseUrl()}/api/${subsystem}/models/discover`, {
      base_url: baseUrl,
      api_key: apiKey,
    }, { timeout: 15000 });
    return {
      ok: !!resp.data?.ok,
      models: Array.isArray(resp.data?.models) ? resp.data.models : [],
      endpoint: resp.data?.endpoint,
      error: resp.data?.error,
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return { ok: false, models: [], error: msg };
  }
}

export async function testChatConnectionWithConfig(_llm: LLMConfig): Promise<void> {
  const resp = await axios.post(`${getApiBaseUrl()}/api/chat/test`, {}, { timeout: 20000 });
  if (!resp.data?.ok) {
    throw new Error(resp.data?.error || `HTTP ${resp.data?.status || 'unknown'}`);
  }
}
