import type {
  DiscussionAgentConfig,
  DiscussionAgentRole,
  DiscussionLLMConfig,
} from './discussionApi';

export type BuiltInDiscussionProfileId = Exclude<DiscussionAgentRole, 'custom'>;
export type DiscussionProfileId = BuiltInDiscussionProfileId | 'custom' | `custom_${string}`;

export type DiscussionApiBindingMode = 'default' | 'credential' | 'inline';

export interface DiscussionAgentProfile {
  id: DiscussionProfileId;
  role: DiscussionAgentRole;
  displayName: string;
  apiMode: DiscussionApiBindingMode;
  credentialId: string;
  provider: string;
  model: string;
  baseUrl: string;
  apiKey: string;
  apiKeyMasked: string;
  protocol: string;
  temperature: number;
  topP: number;
  maxTokens: number;
  strictPin: boolean;
  systemPrompt: string;
  builtIn: boolean;
}

export interface DiscussionProfileStore {
  version: 1;
  defaultJudgeProfileId: DiscussionProfileId;
  profiles: DiscussionAgentProfile[];
}

export interface AgentConfigOverrides {
  agentId: string;
  roleLabel?: string;
  systemPrompt?: string;
}

const STORAGE_KEY = 'scholar-ai-discussion-profiles';
export const DISCUSSION_PROFILE_STORE_CHANGED_EVENT = 'scholar-ai-discussion-profiles-changed';

export const BUILT_IN_DISCUSSION_PROFILE_IDS: readonly BuiltInDiscussionProfileId[] = [
  'proposer',
  'critic',
  'devil_advocate',
  'domain_expert',
  'synthesizer',
];

export const DISCUSSION_PROFILE_IDS: readonly DiscussionProfileId[] = BUILT_IN_DISCUSSION_PROFILE_IDS;

export const DISCUSSION_API_MODES: readonly DiscussionApiBindingMode[] = [
  'default',
  'credential',
  'inline',
];

export const DISCUSSION_API_MODE_LABELS: Record<DiscussionApiBindingMode, string> = {
  default: '使用聊天与生成设置',
  credential: '选择已保存 API',
  inline: '单独填写 API',
};

export const DISCUSSION_ROLE_LABELS: Record<BuiltInDiscussionProfileId | 'custom', string> = {
  proposer: '支持方',
  critic: '批评方',
  devil_advocate: '反方质询',
  domain_expert: '领域专家',
  synthesizer: '综合裁判',
  custom: '自定义',
};

const DEFAULT_SYSTEM_PROMPTS: Record<BuiltInDiscussionProfileId | 'custom', string> = {
  proposer: '围绕研究问题提出可执行的支持论点，并标明需要证据补强的位置。',
  critic: '从方法、证据和推理链路中寻找弱点，优先指出会影响结论可信度的问题。',
  devil_advocate: '主动提出反例、替代解释和潜在混杂因素，避免讨论过早收敛。',
  domain_expert: '结合领域知识判断术语、机制和实验设计是否合理，补充关键背景。',
  synthesizer: '综合各方观点，判断是否已经收敛，并输出可直接进入论文写作的结论。',
  custom: '',
};

const DEFAULT_PROFILE_VALUES = Object.freeze({
  apiMode: 'default' as DiscussionApiBindingMode,
  credentialId: '',
  provider: '',
  model: '',
  baseUrl: '',
  apiKey: '',
  apiKeyMasked: '',
  protocol: 'openai_chat_completions',
  temperature: 0.7,
  topP: 0.9,
  maxTokens: 2048,
  strictPin: false,
});

export const DEFAULT_DISCUSSION_PROFILE_STORE: DiscussionProfileStore = Object.freeze({
  version: 1,
  defaultJudgeProfileId: 'synthesizer',
  profiles: BUILT_IN_DISCUSSION_PROFILE_IDS.map((id) => ({
    id,
    role: id,
    displayName: DISCUSSION_ROLE_LABELS[id],
    apiMode: DEFAULT_PROFILE_VALUES.apiMode,
    credentialId: DEFAULT_PROFILE_VALUES.credentialId,
    provider: DEFAULT_PROFILE_VALUES.provider,
    model: DEFAULT_PROFILE_VALUES.model,
    baseUrl: DEFAULT_PROFILE_VALUES.baseUrl,
    apiKey: DEFAULT_PROFILE_VALUES.apiKey,
    apiKeyMasked: DEFAULT_PROFILE_VALUES.apiKeyMasked,
    protocol: DEFAULT_PROFILE_VALUES.protocol,
    temperature: DEFAULT_PROFILE_VALUES.temperature,
    topP: DEFAULT_PROFILE_VALUES.topP,
    maxTokens: DEFAULT_PROFILE_VALUES.maxTokens,
    strictPin: DEFAULT_PROFILE_VALUES.strictPin,
    systemPrompt: DEFAULT_SYSTEM_PROMPTS[id],
    builtIn: true,
  })),
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(source: Record<string, unknown>, key: string, fallback: string): string {
  const value = source[key];
  return typeof value === 'string' ? value : fallback;
}

function readBoolean(source: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const value = source[key];
  return typeof value === 'boolean' ? value : fallback;
}

function readNumber(source: Record<string, unknown>, key: string, fallback: number, min: number, max: number): number {
  const value = source[key];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, value));
}

function isBuiltInProfileId(value: unknown): value is BuiltInDiscussionProfileId {
  return typeof value === 'string' && BUILT_IN_DISCUSSION_PROFILE_IDS.includes(value as BuiltInDiscussionProfileId);
}

export function isDiscussionProfileId(value: unknown): value is DiscussionProfileId {
  return typeof value === 'string' && (isBuiltInProfileId(value) || value === 'custom' || value.startsWith('custom_'));
}

export function isBuiltInDiscussionProfile(profile: DiscussionAgentProfile): boolean {
  return profile.builtIn && isBuiltInProfileId(profile.id);
}

function isApiMode(value: unknown): value is DiscussionApiBindingMode {
  return typeof value === 'string' && DISCUSSION_API_MODES.includes(value as DiscussionApiBindingMode);
}

function defaultProfile(id: BuiltInDiscussionProfileId): DiscussionAgentProfile {
  const profile = DEFAULT_DISCUSSION_PROFILE_STORE.profiles.find((item) => item.id === id);
  if (!profile) {
    throw new Error(`Unknown discussion profile id: ${id}`);
  }
  return { ...profile };
}

export function createCustomDiscussionProfile(
  existingProfiles: readonly DiscussionAgentProfile[],
  displayName = '自定义角色',
): DiscussionAgentProfile {
  const used = new Set(existingProfiles.map((profile) => profile.id));
  let index = existingProfiles.filter((profile) => profile.role === 'custom').length + 1;
  let id: DiscussionProfileId = `custom_${index}`;
  while (used.has(id)) {
    index += 1;
    id = `custom_${index}`;
  }
  return {
    id,
    role: 'custom',
    displayName,
    apiMode: 'inline',
    credentialId: DEFAULT_PROFILE_VALUES.credentialId,
    provider: DEFAULT_PROFILE_VALUES.provider,
    model: DEFAULT_PROFILE_VALUES.model,
    baseUrl: DEFAULT_PROFILE_VALUES.baseUrl,
    apiKey: DEFAULT_PROFILE_VALUES.apiKey,
    apiKeyMasked: DEFAULT_PROFILE_VALUES.apiKeyMasked,
    protocol: DEFAULT_PROFILE_VALUES.protocol,
    temperature: DEFAULT_PROFILE_VALUES.temperature,
    topP: DEFAULT_PROFILE_VALUES.topP,
    maxTokens: DEFAULT_PROFILE_VALUES.maxTokens,
    strictPin: DEFAULT_PROFILE_VALUES.strictPin,
    systemPrompt: '',
    builtIn: false,
  };
}

function normalizeProfile(value: unknown, fallback: DiscussionAgentProfile): DiscussionAgentProfile {
  if (!isRecord(value)) {
    return { ...fallback };
  }

  const id = isDiscussionProfileId(value.id) ? value.id : fallback.id;
  const role = isBuiltInProfileId(value.role) ? value.role : id === 'custom' || id.startsWith('custom_') ? 'custom' : fallback.role;
  const apiMode = isApiMode(value.apiMode) ? value.apiMode : fallback.apiMode;
  const builtIn = isBuiltInProfileId(id);

  return {
    id,
    role,
    displayName: readString(value, 'displayName', fallback.displayName).trim() || fallback.displayName,
    apiMode,
    credentialId: readString(value, 'credentialId', fallback.credentialId).trim(),
    provider: readString(value, 'provider', fallback.provider).trim(),
    model: readString(value, 'model', fallback.model).trim(),
    baseUrl: readString(value, 'baseUrl', fallback.baseUrl).trim(),
    apiKey: readString(value, 'apiKey', fallback.apiKey),
    apiKeyMasked: readString(value, 'apiKeyMasked', fallback.apiKeyMasked).trim(),
    protocol: readString(value, 'protocol', fallback.protocol).trim() || fallback.protocol,
    temperature: readNumber(value, 'temperature', fallback.temperature, 0, 2),
    topP: readNumber(value, 'topP', fallback.topP, 0, 1),
    maxTokens: Math.round(readNumber(value, 'maxTokens', fallback.maxTokens, 64, 32_000)),
    strictPin: readBoolean(value, 'strictPin', fallback.strictPin),
    systemPrompt: readString(value, 'systemPrompt', fallback.systemPrompt),
    builtIn,
  };
}

/**
 * Normalize persisted discussion profile data from localStorage.
 *
 * Input:
 * - value: unknown JSON payload, possibly malformed or from an older schema.
 *
 * Output:
 * - Complete DiscussionProfileStore with built-in profiles plus valid custom roles.
 */
export function normalizeDiscussionProfileStore(value: unknown): DiscussionProfileStore {
  if (!isRecord(value)) {
    return {
      ...DEFAULT_DISCUSSION_PROFILE_STORE,
      profiles: DEFAULT_DISCUSSION_PROFILE_STORE.profiles.map((profile) => ({ ...profile })),
    };
  }

  const rawProfiles = Array.isArray(value.profiles) ? value.profiles : [];
  const normalizedProfiles = BUILT_IN_DISCUSSION_PROFILE_IDS.map((id) => {
    const fallback = defaultProfile(id);
    const candidate = rawProfiles.find((item) => isRecord(item) && item.id === id);
    return normalizeProfile(candidate, fallback);
  });
  const seen = new Set<DiscussionProfileId>(normalizedProfiles.map((profile) => profile.id));
  for (const raw of rawProfiles) {
    if (!isRecord(raw) || !isDiscussionProfileId(raw.id) || isBuiltInProfileId(raw.id)) {
      continue;
    }
    if (seen.has(raw.id)) {
      continue;
    }
    const fallback = createCustomDiscussionProfile(normalizedProfiles, DISCUSSION_ROLE_LABELS.custom);
    const custom = normalizeProfile(raw, { ...fallback, id: raw.id, role: 'custom', builtIn: false });
    normalizedProfiles.push({ ...custom, role: 'custom', builtIn: false });
    seen.add(custom.id);
  }

  const defaultJudge = isDiscussionProfileId(value.defaultJudgeProfileId) && seen.has(value.defaultJudgeProfileId)
    ? value.defaultJudgeProfileId
    : DEFAULT_DISCUSSION_PROFILE_STORE.defaultJudgeProfileId;
  return {
    version: 1,
    defaultJudgeProfileId: defaultJudge,
    profiles: normalizedProfiles,
  };
}

/**
 * Load discussion role presets from browser storage.
 *
 * Output:
 * - Defensive default store when storage is unavailable or corrupt.
 */
export function loadDiscussionProfileStore(): DiscussionProfileStore {
  if (typeof window === 'undefined') {
    return normalizeDiscussionProfileStore(null);
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return normalizeDiscussionProfileStore(raw ? JSON.parse(raw) : null);
  } catch {
    return normalizeDiscussionProfileStore(null);
  }
}

/**
 * Persist discussion role presets to browser storage.
 *
 * Input:
 * - store: complete or partial profile store; invalid values are normalized
 *   before writing so readers always receive a full schema.
 */
export function saveDiscussionProfileStore(store: DiscussionProfileStore): void {
  if (typeof window === 'undefined') {
    return;
  }
  const normalized = normalizeDiscussionProfileStore(store);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  window.dispatchEvent(new Event(DISCUSSION_PROFILE_STORE_CHANGED_EVENT));
}

/**
 * Resolve one role profile from a normalized store.
 *
 * Inputs:
 * - store: normalized or user-edited store.
 * - id: supported role profile id.
 *
 * Output:
 * - Matching profile, or the built-in default for that role.
 */
export function getDiscussionProfile(
  store: DiscussionProfileStore,
  id: DiscussionProfileId,
): DiscussionAgentProfile {
  const normalized = normalizeDiscussionProfileStore(store);
  const found = normalized.profiles.find((profile) => profile.id === id);
  if (found) return found;
  return isBuiltInProfileId(id) ? defaultProfile(id) : createCustomDiscussionProfile(normalized.profiles);
}

/**
 * Convert a role profile into the backend `DiscussionAgentConfig` shape.
 *
 * Inputs:
 * - profile: role defaults and optional API binding.
 * - overrides: per-run label and prompt overrides from the discussion page.
 *
 * Output:
 * - Secret-bearing `llm` is included only when the inline API profile is
 *   complete; otherwise the backend default or credential id path is used.
 */
export function buildAgentConfigFromProfile(
  profile: DiscussionAgentProfile,
  overrides: AgentConfigOverrides,
): DiscussionAgentConfig {
  const agentId = overrides.agentId.trim();
  if (!agentId) {
    throw new Error('Agent id is required.');
  }
  if (!isDiscussionProfileId(profile.id) || !profile.role) {
    throw new Error('Unsupported discussion profile.');
  }

  const roleLabel = overrides.roleLabel?.trim() || profile.displayName;
  const systemPrompt = overrides.systemPrompt?.trim() || profile.systemPrompt.trim();
  const config: DiscussionAgentConfig = {
    agent_id: agentId,
    role: profile.role,
    role_label: roleLabel,
    system_prompt: systemPrompt || undefined,
    strict_pin: profile.strictPin,
    priority: 100,
    metadata: {
      profile_id: profile.id,
      api_mode: profile.apiMode,
      temperature: profile.temperature,
      top_p: profile.topP,
      max_tokens: profile.maxTokens,
    },
  };

  if (profile.apiMode === 'credential' && profile.credentialId.trim()) {
    config.credential_id = profile.credentialId.trim();
    return config;
  }

  if (profile.apiMode === 'inline' && profile.credentialId.trim() && !profile.apiKey.trim()) {
    config.credential_id = profile.credentialId.trim();
    config.metadata = {
      ...config.metadata,
      credential_source: 'role_api',
    };
    return config;
  }

  const inlineLlm = buildInlineLlm(profile);
  if (inlineLlm) {
    config.llm = inlineLlm;
  }
  return config;
}

/**
 * Summarize the current API binding without exposing secrets.
 *
 * Output:
 * - Short Chinese label suitable for compact role rows and cards.
 */
export function describeApiBinding(profile: DiscussionAgentProfile): string {
  if (profile.apiMode === 'credential') {
    return profile.credentialId.trim() ? '已保存 API' : '未选择 API';
  }
  if (profile.apiMode === 'inline') {
    return profile.model.trim() ? `角色 API · ${profile.model.trim()}` : '角色 API 未完成';
  }
  return DISCUSSION_API_MODE_LABELS.default;
}

function buildInlineLlm(profile: DiscussionAgentProfile): DiscussionLLMConfig | null {
  if (profile.apiMode !== 'inline') {
    return null;
  }

  const provider = profile.provider.trim();
  const model = profile.model.trim();
  const baseUrl = profile.baseUrl.trim();
  const apiKey = profile.apiKey.trim();
  if (!provider || !model || !baseUrl || !apiKey) {
    return null;
  }

  return {
    provider,
    model,
    base_url: baseUrl,
    api_key: apiKey,
    protocol: profile.protocol.trim() || DEFAULT_PROFILE_VALUES.protocol,
    temperature: profile.temperature,
    top_p: profile.topP,
    max_tokens: profile.maxTokens,
  };
}
