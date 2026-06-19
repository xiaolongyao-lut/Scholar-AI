import { createDefaultApiClient } from './httpClient.ts';
import { getApiBaseUrl } from './apiBaseUrl.ts';
import type { AxiosInstance } from 'axios';
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

let client: AxiosInstance | null = null;

function getChatClient(): AxiosInstance {
  if (client === null) {
    client = createDefaultApiClient({ baseURL: getApiBaseUrl() });
  }
  return client;
}

const askWithPayload = async (
  body: Record<string, unknown>,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<ChatAskResponse> => {
  const { data } = await getChatClient().post<ChatAskResponse>(
    '/chat/ask',
    body,
    { timeout: timeoutMs, signal },
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
  signal?: AbortSignal;
  fallbackMode?: 'gemini-first' | 'none';
  mcpServerIds?: string[];
  mcpAllowHighRiskTools?: boolean;
  useLocalLiteratureTools?: boolean;
}): Promise<ChatAskResponse> {
  const {
    query,
    context = [],
    history = [],
    llm,
    aiCostProfile,
    timeoutMs = 180000,
    signal,
    mcpServerIds,
    mcpAllowHighRiskTools,
    useLocalLiteratureTools,
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
  if (mcpAllowHighRiskTools !== undefined) {
    body.mcp_allow_high_risk_tools = mcpAllowHighRiskTools;
  }
  if (useLocalLiteratureTools !== undefined) {
    body.use_local_literature_tools = useLocalLiteratureTools;
  }

  return await askWithPayload(body, timeoutMs, signal);
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
    return { ok: false, models: [], error: '请先填写服务地址' };
  }
  try {
    const resp = await getChatClient().post(`/api/${subsystem}/models/discover`, {
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
    const candidate = err as { status?: number; message?: string; details?: unknown };
    if (candidate.status && candidate.message) {
      // ApiClientError from httpClient
      const detailStr = typeof candidate.details === 'string'
        ? candidate.details
        : candidate.details && typeof candidate.details === 'object'
        ? JSON.stringify(candidate.details).slice(0, 400)
        : '';
      const compound = [`HTTP ${candidate.status}`, candidate.message, detailStr].filter(Boolean).join(' · ');
      return { ok: false, models: [], error: compound };
    }
    const msg = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
    return { ok: false, models: [], error: msg };
  }
}

export async function testChatConnectionWithConfig(_llm: LLMConfig): Promise<void> {
  const resp = await getChatClient().post('/api/chat/test', {}, { timeout: 20000 });
  if (!resp.data?.ok) {
    throw new Error(resp.data?.error || `HTTP ${resp.data?.status || 'unknown'}`);
  }
}
