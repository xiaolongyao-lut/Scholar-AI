import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl.ts';
import { readEnv } from './env.ts';
import type { LLMConfig } from './settingsStore.ts';

export interface ChatAskResponse {
  answer: string;
  model?: string;
  usage?: Record<string, number>;
  fallback?: {
    attemptedProvider: string;
    activeProvider: string;
  };
}

export interface ChatHistoryMessage {
  role: 'user' | 'assistant';
  content: string;
}

const getProviderKey = (provider: string): string => provider.trim().toLowerCase();

const getEnvLLM = (
  current: LLMConfig,
  options: {
    providerKey: keyof ImportMetaEnv;
    baseUrlKey: keyof ImportMetaEnv;
    modelKey: keyof ImportMetaEnv;
    apiKeyKey: keyof ImportMetaEnv;
    defaultProvider: string;
  },
): LLMConfig | null => {
  const provider = readEnv(options.providerKey) || options.defaultProvider;
  const baseUrl = readEnv(options.baseUrlKey);
  const model = readEnv(options.modelKey);
  const apiKey = readEnv(options.apiKeyKey);

  if (!baseUrl || !model || !apiKey) {
    return null;
  }

  return {
    ...current,
    provider: provider || current.provider,
    baseUrl,
    model,
    apiKey,
  };
};

const getGeminiPrimaryLLM = (current: LLMConfig): LLMConfig | null => {
  const envGemini = getEnvLLM(current, {
    providerKey: 'VITE_GEMINI_PROVIDER',
    baseUrlKey: 'VITE_GEMINI_BASE_URL',
    modelKey: 'VITE_GEMINI_MODEL',
    apiKeyKey: 'VITE_GEMINI_API_KEY',
    defaultProvider: 'Gemini',
  });

  if (getProviderKey(current.provider) === 'gemini') {
    return envGemini ?? current;
  }

  return envGemini;
};

const getCopilotFallbackLLM = (current: LLMConfig): LLMConfig | null => {
  const copilotLLM = getEnvLLM(current, {
    providerKey: 'VITE_COPILOT_PROVIDER',
    baseUrlKey: 'VITE_COPILOT_BASE_URL',
    modelKey: 'VITE_COPILOT_MODEL',
    apiKeyKey: 'VITE_COPILOT_API_KEY',
    defaultProvider: 'Copilot',
  });

  const provider = readEnv('VITE_COPILOT_PROVIDER') || 'Copilot';

  // 默认禁用 Copilot 回退：只有显式配置了 baseUrl + model + apiKey 才启用
  if (!copilotLLM) {
    return null;
  }

  return {
    ...copilotLLM,
    provider: provider || copilotLLM.provider,
  };
};

const isConnectivityOrModelError = (error: unknown): boolean => {
  if (!axios.isAxiosError(error)) {
    return false;
  }

  if (!error.response) {
    return true;
  }

  const status = error.response.status;
  if ([408, 429, 500, 502, 503, 504].includes(status)) {
    return true;
  }

  const payload = error.response.data;
  const detail = payload?.error?.message ?? payload?.detail ?? error.message ?? '';
  const lowered = String(detail).toLowerCase();

  return (
    lowered.includes('invalidendpointormodel.notfound')
    || lowered.includes('model or endpoint')
    || lowered.includes('model_not_found')
    || lowered.includes('timeout')
    || lowered.includes('network')
    || lowered.includes('econnrefused')
    || lowered.includes('enotfound')
  );
};

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

const sameLLMTarget = (left: LLMConfig, right: LLMConfig): boolean => (
  getProviderKey(left.provider) === getProviderKey(right.provider)
  && left.baseUrl.trim() === right.baseUrl.trim()
  && left.model.trim() === right.model.trim()
);

export function toBackendLLMConfig(llm: LLMConfig): Record<string, unknown> {
  return {
    provider: llm.provider,
    api_key: llm.apiKey,
    model: llm.model,
    base_url: llm.baseUrl,
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
}): Promise<ChatAskResponse> {
  const {
    query,
    context = [],
    history = [],
    llm,
    aiCostProfile,
    // 第三方 Claude / OpenAI-compatible 代理常在 60-120s 间随机断流；
    // 把默认 ask 超时拉到 180s 与后端 LLM_HTTP_TIMEOUT 对齐，避免前端先于后端超时。
    timeoutMs = 180000,
    fallbackMode = 'gemini-first',
  } = params;
  const primaryLLM = fallbackMode === 'gemini-first'
    ? getGeminiPrimaryLLM(llm) ?? llm
    : llm;

  const primaryBody = {
    query,
    context,
    history,
    llm: toBackendLLMConfig(primaryLLM),
    ai_cost_profile: aiCostProfile,
  };

  try {
    return await askWithPayload(primaryBody, timeoutMs);
  } catch (primaryError) {
    const shouldTryCopilotFallback = fallbackMode === 'gemini-first'
      && (
        getProviderKey(primaryLLM.provider) === 'gemini'
        || isConnectivityOrModelError(primaryError)
      );

    if (!shouldTryCopilotFallback) {
      throw primaryError;
    }

    const copilotLLM = getCopilotFallbackLLM(primaryLLM);
    if (copilotLLM) {
      if (!sameLLMTarget(copilotLLM, primaryLLM)) {
        try {
          const copilotBody = {
            query,
            context,
            history,
            llm: toBackendLLMConfig(copilotLLM),
            ai_cost_profile: aiCostProfile,
          };
          const data = await askWithPayload(copilotBody, timeoutMs);
          return {
            ...data,
            model: data.model ?? copilotLLM.model,
            fallback: {
              attemptedProvider: primaryLLM.provider,
              activeProvider: copilotLLM.provider,
            },
          };
        } catch {
          // ignore and continue to backend default fallback
        }
      }
    }

    // 最后保底：回退到“当前后端路数”（不带 llm 覆盖）
    const backendDefaultBody = {
      query,
      context,
      history,
      ai_cost_profile: aiCostProfile,
    };
    return await askWithPayload(backendDefaultBody, timeoutMs);
  }
}

export async function testChatConnectionWithConfig(llm: LLMConfig): Promise<void> {
  await askChatWithConfig({
    query: 'ping',
    context: [],
    llm: {
      ...llm,
      maxTokens: Math.min(llm.maxTokens, 64),
    },
    timeoutMs: 20000,
    fallbackMode: 'none',
  });
}
