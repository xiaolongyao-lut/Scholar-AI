/**
 * Settings persistence layer using localStorage.
 * Stores LLM/Embedding configuration for use by query services.
 */

export interface LLMConfig {
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  temperature: number;
  topP: number;
  maxTokens: number;
  systemPrompt: string;
}

export interface EmbeddingConfig {
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  dimension: number;
}

export interface WorkspaceConfig {
  localStoragePath: string;
  autoIndex: boolean;
}

export interface AppSettings {
  llm: LLMConfig;
  embedding: EmbeddingConfig;
  workspace: WorkspaceConfig;
}

const STORAGE_KEY = 'scholar-ai-settings';

const DEFAULT_SETTINGS: AppSettings = {
  llm: {
    provider: 'DeepSeek',
    apiKey: '',
    model: 'deepseek-chat',
    baseUrl: 'https://api.deepseek.com',
    temperature: 0.7,
    topP: 0.9,
    maxTokens: 4096,
    systemPrompt: '',
  },
  embedding: {
    provider: 'OpenAI',
    apiKey: '',
    model: 'text-embedding-3-small',
    baseUrl: 'https://api.openai.com/v1',
    dimension: 1536,
  },
  workspace: {
    localStoragePath: './output',
    autoIndex: true,
  },
};

export function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { ...DEFAULT_SETTINGS, ...parsed, llm: { ...DEFAULT_SETTINGS.llm, ...parsed.llm }, embedding: { ...DEFAULT_SETTINGS.embedding, ...parsed.embedding }, workspace: { ...DEFAULT_SETTINGS.workspace, ...parsed.workspace } };
    }
  } catch { /* ignore */ }
  return { ...DEFAULT_SETTINGS };
}

export function saveSettings(settings: AppSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export function getLLMConfig(): LLMConfig {
  return loadSettings().llm;
}
