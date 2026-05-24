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
    // 2026-05-24: peel out backend `detail` / response body when the
    // request itself failed (4xx/5xx from our backend, not from upstream).
    // The user reported "连接失败" with no reason, which made debugging
    // third-party gateways painful.
    if (axios.isAxiosError(err) && err.response) {
      const status = err.response.status;
      const statusText = err.response.statusText || '';
      const data = err.response.data;
      let detail = '';
      if (typeof data === 'string') {
        detail = data;
      } else if (data && typeof data === 'object') {
        const rec = data as Record<string, unknown>;
        const candidate = rec.error ?? rec.detail ?? rec.message;
        if (typeof candidate === 'string') {
          detail = candidate;
        } else if (candidate && typeof candidate === 'object') {
          try { detail = JSON.stringify(candidate); } catch { detail = String(candidate); }
        } else {
          try { detail = JSON.stringify(data).slice(0, 400); } catch { detail = ''; }
        }
      }
      const compound = [`HTTP ${status}`, statusText, detail].filter(Boolean).join(' · ');
      return { ok: false, models: [], error: compound };
    }
    const msg = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
    return { ok: false, models: [], error: msg };
  }
}

export async function testChatConnectionWithConfig(_llm: LLMConfig): Promise<void> {
  const resp = await axios.post(`${getApiBaseUrl()}/api/chat/test`, {}, { timeout: 20000 });
  if (!resp.data?.ok) {
    throw new Error(resp.data?.error || `HTTP ${resp.data?.status || 'unknown'}`);
  }
}
