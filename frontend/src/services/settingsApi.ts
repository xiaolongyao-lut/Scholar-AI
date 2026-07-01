import axios from 'axios';

import { getApiBaseUrl } from '@/services/apiBaseUrl';

export interface SettingsApiConfig {
  provider: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  api_key_masked: string;
  updated_at: string;
}

export interface SettingsCredentialsSummary {
  total: number;
  enabled: number;
  generation: number;
  embedding: number;
  rerank: number;
  ocr: number;
}

export interface SettingsFeatureFlag {
  name: string;
  label: string;
  current: boolean;
  source: string;
}

export interface UnifiedSettings {
  api: {
    chat: SettingsApiConfig;
    embedding: SettingsApiConfig;
    rerank: SettingsApiConfig;
  };
  credentials: SettingsCredentialsSummary;
  feature_flags: SettingsFeatureFlag[];
}

/**
 * Load the unified Settings document.
 *
 * Response shape is mask-safe: credential material never leaves the backend.
 */
export async function getUnifiedSettings(): Promise<UnifiedSettings> {
  const response = await axios.get<UnifiedSettings>(`${getApiBaseUrl()}/api/settings`);
  return response.data;
}
