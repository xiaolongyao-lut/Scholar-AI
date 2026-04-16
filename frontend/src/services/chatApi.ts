import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import type { LLMConfig } from './settingsStore';

export interface ChatAskResponse {
  answer: string;
  model?: string;
  usage?: Record<string, number>;
}

export interface ChatHistoryMessage {
  role: 'user' | 'assistant';
  content: string;
}

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
  timeoutMs?: number;
}): Promise<ChatAskResponse> {
  const { query, context = [], history = [], llm, timeoutMs = 120000 } = params;
  const { data } = await axios.post<ChatAskResponse>(
    `${getApiBaseUrl()}/chat/ask`,
    {
      query,
      context,
      history,
      llm: toBackendLLMConfig(llm),
    },
    { timeout: timeoutMs },
  );
  return data;
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
  });
}
