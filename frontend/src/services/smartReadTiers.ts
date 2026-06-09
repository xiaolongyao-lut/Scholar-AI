import type { ContextTier } from '@/services/intelligentChatApi';

export type SmartReadCostTier = 'low' | 'medium' | 'high' | 'xhigh' | 'max';
export type WorkspaceAiCostProfile = 'aggressive' | 'balanced' | 'quality';

export interface SmartReadTierConfig {
  label: string;
  shortLabel: string;
  tooltip: string;
  backendTier: ContextTier;
  workspaceCostProfile: WorkspaceAiCostProfile;
  retrievalTopK: number;
}

const STORAGE_KEY = 'smart-read-cost-tier-v1';

export const SMART_READ_TIERS: readonly SmartReadCostTier[] = [
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
];

export const SMART_READ_TIER_CONFIG: Record<SmartReadCostTier, SmartReadTierConfig> = {
  low: {
    label: '低',
    shortLabel: '低',
    tooltip: '更快、更省调用；适合事实确认和短问题。',
    backendTier: 'fast',
    workspaceCostProfile: 'aggressive',
    retrievalTopK: 4,
  },
  medium: {
    label: '中',
    shortLabel: '中',
    tooltip: '默认平衡档；适合多数文献问答。',
    backendTier: 'balanced',
    workspaceCostProfile: 'balanced',
    retrievalTopK: 8,
  },
  high: {
    label: '高',
    shortLabel: '高',
    tooltip: '增加上下文覆盖；适合复杂机制、方法和对比问题。',
    backendTier: 'thorough',
    workspaceCostProfile: 'quality',
    retrievalTopK: 12,
  },
  xhigh: {
    label: 'XHigh',
    shortLabel: 'xhigh',
    tooltip: '进一步扩大检索范围；Codex 系列最高建议用 XHigh。',
    backendTier: 'thorough',
    workspaceCostProfile: 'quality',
    retrievalTopK: 16,
  },
  max: {
    label: 'Max',
    shortLabel: 'max',
    tooltip: '最大本地上下文预算；Claude 系列最高建议用 Max。',
    backendTier: 'thorough',
    workspaceCostProfile: 'quality',
    retrievalTopK: 20,
  },
};

export function isSmartReadCostTier(value: unknown): value is SmartReadCostTier {
  return typeof value === 'string' && SMART_READ_TIERS.includes(value as SmartReadCostTier);
}

export function backendTierForCostTier(tier: SmartReadCostTier): ContextTier {
  return SMART_READ_TIER_CONFIG[tier].backendTier;
}

export function workspaceCostProfileForTier(tier: SmartReadCostTier): WorkspaceAiCostProfile {
  return SMART_READ_TIER_CONFIG[tier].workspaceCostProfile;
}

export function retrievalTopKForTier(tier: SmartReadCostTier): number {
  return SMART_READ_TIER_CONFIG[tier].retrievalTopK;
}

export function costTierFromBackendTier(tier: ContextTier | null | undefined): SmartReadCostTier {
  if (tier === 'fast') return 'low';
  if (tier === 'thorough') return 'high';
  return 'medium';
}

export function costTierFromWorkspaceProfile(
  profile: WorkspaceAiCostProfile | null | undefined,
): SmartReadCostTier {
  if (profile === 'aggressive') return 'low';
  if (profile === 'quality') return 'high';
  return 'medium';
}

export function loadSmartReadCostTier(fallback: SmartReadCostTier = 'medium'): SmartReadCostTier {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return isSmartReadCostTier(raw) ? raw : fallback;
  } catch {
    return fallback;
  }
}

export function saveSmartReadCostTier(tier: SmartReadCostTier): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, tier);
    window.dispatchEvent(new CustomEvent('smart-read-cost-tier-change', { detail: { tier } }));
  } catch {
    /* storage disabled */
  }
}

export function subscribeSmartReadCostTier(listener: (tier: SmartReadCostTier) => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const handleCustom = (event: Event) => {
    const detail = event instanceof CustomEvent ? event.detail : null;
    const tier = detail && typeof detail === 'object' ? (detail as { tier?: unknown }).tier : null;
    if (isSmartReadCostTier(tier)) listener(tier);
  };
  const handleStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY && isSmartReadCostTier(event.newValue)) {
      listener(event.newValue);
    }
  };
  window.addEventListener('smart-read-cost-tier-change', handleCustom);
  window.addEventListener('storage', handleStorage);
  return () => {
    window.removeEventListener('smart-read-cost-tier-change', handleCustom);
    window.removeEventListener('storage', handleStorage);
  };
}
