/**
 * Settings persistence layer using localStorage.
 *
 * Post-S5 (commit `d39f89a5`) chat / embedding credentials are owned by the
 * backend runtime override stores at `/api/{chat,embedding}/config`. This
 * module no longer types provider / apiKey / baseUrl / model into LLMConfig
 * or EmbeddingConfig.
 *
 * Settings cleanup (2026-05-16, plan
 * `docs/plans/active/2026-05-16-settings-cleanup-plan.md`) deleted the
 * deprecated credential-shaped fields. Existing localStorage payloads from
 * pre-cleanup users may still carry those keys; they are read back through
 * `readLegacyCredentialBlob()` for one-shot migration and erased by
 * `clearLegacyCredentialBlob()`.
 */

export interface LLMConfig {
  temperature: number;
  topP: number;
  maxTokens: number;
  systemPrompt: string;
}

export interface EmbeddingConfig {
  dimension: number;
}

export interface WorkspaceConfig {
  localStoragePath: string;
  autoIndex: boolean;
  retrievalTopK: number;
  aiCostProfile?: 'balanced' | 'aggressive' | 'quality';
  /** Workbench(知识库智能研读)入库模式 — none / query / full。
   *  Persisted so reopening the page keeps the user's last choice. */
  ingestMode?: 'none' | 'query' | 'full';
  /** Workbench 选中的 MCP server ids,跨刷新保留(plan §五 设置持久化)。 */
  mcpServerIds?: string[];
}

export interface AppSettings {
  llm: LLMConfig;
  embedding: EmbeddingConfig;
  workspace: WorkspaceConfig;
}

/**
 * Raw blob shape for the legacy credential keys that may still exist in
 * pre-cleanup localStorage payloads. Decoupled from AppSettings so that
 * `LLMConfig` / `EmbeddingConfig` can shed these fields without breaking
 * first-mount migration.
 */
export interface LegacyCredentialBlob {
  provider?: string;
  apiKey?: string;
  baseUrl?: string;
  model?: string;
}

const STORAGE_KEY = 'scholar-ai-settings';

const DEFAULT_SETTINGS: AppSettings = {
  llm: {
    temperature: 0.7,
    topP: 0.9,
    maxTokens: 4096,
    systemPrompt: '',
  },
  embedding: {
    dimension: 1536,
  },
  workspace: {
    localStoragePath: './output',
    autoIndex: true,
    retrievalTopK: 6,
  },
};

export function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        ...DEFAULT_SETTINGS,
        ...parsed,
        llm: { ...DEFAULT_SETTINGS.llm, ...parsed.llm },
        embedding: { ...DEFAULT_SETTINGS.embedding, ...parsed.embedding },
        workspace: { ...DEFAULT_SETTINGS.workspace, ...parsed.workspace },
      };
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

/**
 * Read raw legacy credential keys directly from the persisted localStorage
 * blob, bypassing the typed AppSettings shape. Used by Settings sections to
 * feed `migrateLegacyCredentials` without depending on `LLMConfig` /
 * `EmbeddingConfig` carrying the deprecated fields.
 *
 * Returns an empty blob if the storage key is absent, the JSON is corrupt,
 * or the requested subsystem block does not exist.
 */
export function readLegacyCredentialBlob(
  subsystem: 'llm' | 'embedding',
): LegacyCredentialBlob {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as
      | { llm?: Record<string, unknown>; embedding?: Record<string, unknown> }
      | null;
    const block = parsed?.[subsystem] ?? {};
    return {
      provider: typeof block.provider === 'string' ? block.provider : undefined,
      apiKey: typeof block.apiKey === 'string' ? block.apiKey : undefined,
      baseUrl: typeof block.baseUrl === 'string' ? block.baseUrl : undefined,
      model: typeof block.model === 'string' ? block.model : undefined,
    };
  } catch {
    return {};
  }
}

/**
 * Erase legacy credential keys from the persisted localStorage blob without
 * touching the typed AppSettings fields. Called after a successful first-mount
 * migration so the next `loadSettings` round does not re-discover the same
 * legacy values.
 */
export function clearLegacyCredentialBlob(
  subsystem: 'llm' | 'embedding',
): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as Record<string, unknown> | null;
    if (!parsed || typeof parsed !== 'object') return;
    const block = parsed[subsystem];
    if (!block || typeof block !== 'object') return;
    const blockObj = block as Record<string, unknown>;
    delete blockObj.provider;
    delete blockObj.apiKey;
    delete blockObj.baseUrl;
    delete blockObj.model;
    parsed[subsystem] = blockObj;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
  } catch {
    /* ignore */
  }
}
