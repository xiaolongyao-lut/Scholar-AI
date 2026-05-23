/**
 * Feature flags API client.
 *
 * Backend contract: literature_assistant/core/routers/feature_flags_router.py
 *   GET  /api/feature-flags          → { flags: FeatureFlagEntry[] }
 *   POST /api/feature-flags/{name}   body { enabled: bool } → FeatureFlagEntry
 */

import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';

export interface FeatureFlagEntry {
  name: string;
  label: string;
  description: string;
  default: boolean;
  env_var: string | null;
  current: boolean;
  source: 'override' | 'env' | 'default';
}

interface FeatureFlagListResponse {
  flags: FeatureFlagEntry[];
}

export async function listFeatureFlags(): Promise<FeatureFlagEntry[]> {
  const { data } = await axios.get<FeatureFlagListResponse>(
    `${getApiBaseUrl()}/api/feature-flags`,
    { timeout: 5000 },
  );
  return data.flags;
}

export async function setFeatureFlag(
  name: string,
  enabled: boolean,
): Promise<FeatureFlagEntry> {
  const { data } = await axios.post<FeatureFlagEntry>(
    `${getApiBaseUrl()}/api/feature-flags/${encodeURIComponent(name)}`,
    { enabled },
    { timeout: 5000 },
  );
  return data;
}
