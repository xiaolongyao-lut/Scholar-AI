/**
 * Cross-subsystem migration helper for legacy localStorage credentials.
 *
 * After Settings S5 the chat / embedding sections are backend-driven via
 * `/api/{subsystem}/config`. Legacy installs may still hold provider /
 * apiKey / baseUrl / model in localStorage under `scholar-ai-settings`.
 *
 * `migrateLegacyCredentials` pushes those into the backend runtime override
 * (PUT) the first time a Settings section observes both:
 *   - backend config is empty, AND
 *   - localStorage carries non-empty legacy credentials.
 *
 * On success it returns the migrated public config so the caller can update
 * its local form state, plus a flag telling the caller to clear the legacy
 * localStorage fields. On failure it returns null and leaves localStorage
 * untouched so the user can retry by saving manually.
 */
import axios, { AxiosError } from 'axios';

export interface SubsystemPublicConfig {
  provider: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  api_key_masked: string;
  updated_at: string;
}

export interface LegacySubsystemCredentials {
  provider?: string;
  apiKey?: string;
  baseUrl?: string;
  model?: string;
}

export interface MigrationResult {
  migratedConfig: SubsystemPublicConfig;
  shouldClearLocalStorage: boolean;
}

const isEmptyBackendConfig = (cfg: SubsystemPublicConfig): boolean =>
  !cfg.has_api_key && !cfg.provider && !cfg.base_url && !cfg.model;

const hasLegacyCredentials = (legacy: LegacySubsystemCredentials | null | undefined): boolean => {
  if (!legacy) return false;
  return !!(legacy.apiKey || legacy.baseUrl || legacy.model || legacy.provider);
};

/**
 * Decide whether a migration PUT should run, and execute it.
 *
 * Returns `null` when there is nothing to migrate, when the migration PUT
 * fails for any reason, or when the inputs are invalid. Errors are not
 * thrown; callers treat null as "leave localStorage as-is, surface no UI
 * error" since the user can still save manually.
 *
 * Inputs:
 * - backendBaseUrl: result of `getApiBaseUrl()` (may be empty string).
 * - subsystemPath: the path under `/api/`, e.g. `chat` or `embedding`.
 * - currentBackendConfig: the GET response, used to detect "empty backend".
 * - legacy: the localStorage-derived credentials struct, may be null.
 *
 * Output:
 * - MigrationResult on success.
 * - null when migration was not needed or failed safely.
 */
export async function migrateLegacyCredentials(
  backendBaseUrl: string,
  subsystemPath: 'chat' | 'embedding',
  currentBackendConfig: SubsystemPublicConfig,
  legacy: LegacySubsystemCredentials | null | undefined,
): Promise<MigrationResult | null> {
  if (!isEmptyBackendConfig(currentBackendConfig)) return null;
  if (!hasLegacyCredentials(legacy)) return null;

  const payload: Record<string, string | null> = {
    provider: legacy!.provider || '',
    base_url: legacy!.baseUrl || '',
    api_key: legacy!.apiKey || null,
    model: legacy!.model || '',
  };

  try {
    const response = await axios.put<SubsystemPublicConfig>(
      `${backendBaseUrl}/api/${subsystemPath}/config`,
      payload,
    );
    return {
      migratedConfig: response.data,
      shouldClearLocalStorage: true,
    };
  } catch (err: unknown) {
    // Never let migration failures leak credentials to the console; the
    // caller will surface a generic UI hint via the Save flow if the user
    // tries again.
    if (err instanceof AxiosError) {
      // Intentionally swallow.
    }
    return null;
  }
}
