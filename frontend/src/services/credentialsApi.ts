import axios from 'axios';
import type { AxiosError } from 'axios';
import { getApiBaseUrl } from './apiBaseUrl.ts';

// ---------------------------------------------------------------------------
// Backend types (mirror models/credentials.py — kept in sync manually until
// we generate from OpenAPI).
// ---------------------------------------------------------------------------

export type CredentialCategory = 'generation' | 'embedding' | 'rerank';

export type CredentialProtocol =
  | 'openai_chat_completions'
  | 'openai_responses'
  | 'anthropic_messages'
  | 'embeddings'
  | 'rerank';

export type CredentialStrategyHint =
  | 'low'
  | 'medium'
  | 'high'
  | 'default'
  | 'cheap'
  | 'fast'
  | 'quality'
  | 'xhigh'
  | 'max'
  | 'discussion'
  | 'embedding'
  | 'rerank';

export type CredentialTrustSource =
  | 'official_provider'
  | 'env_configured_gateway'
  | 'runtime_user_confirmed'
  | 'runtime_untrusted_custom';

export interface CredentialSamplingOverride {
  temperature?: number | null;
  top_p?: number | null;
  max_tokens?: number | null;
  system_prompt?: string | null;
}

export interface RuntimeCredentialPublic {
  credential_id: string;
  category: CredentialCategory;
  provider: string;
  model: string;
  base_url: string;
  protocol: CredentialProtocol;
  enabled: boolean;
  priority: number;
  tags: string[];
  strategy_hint: CredentialStrategyHint;
  trust_source: CredentialTrustSource;
  notes: string;
  sampling_override: CredentialSamplingOverride | null;
  api_key_masked: string;
  has_api_key: boolean;
  fingerprint: string;
  fingerprint_version: string;
  created_at: string;
  updated_at: string;
}

export interface RuntimeCredentialCreate {
  category: CredentialCategory;
  provider: string;
  model: string;
  base_url: string;
  protocol: CredentialProtocol;
  api_key: string;
  enabled?: boolean;
  priority?: number;
  tags?: string[];
  strategy_hint?: CredentialStrategyHint;
  trust_source?: CredentialTrustSource;
  notes?: string;
  sampling_override?: CredentialSamplingOverride | null;
}

export interface RuntimeCredentialUpdate {
  provider?: string;
  model?: string;
  base_url?: string;
  protocol?: CredentialProtocol;
  enabled?: boolean;
  priority?: number;
  tags?: string[];
  strategy_hint?: CredentialStrategyHint;
  trust_source?: CredentialTrustSource;
  notes?: string;
  sampling_override?: CredentialSamplingOverride | null;
  api_key?: string;
}

export interface CredentialPolicyDecision {
  allowed: boolean;
  reason: string;
  trust_source: string;
  scheme: string;
  host: string;
  port: number | null;
  path: string;
  resolved_ips: string[];
  rejected_ips: string[];
  skipped_network: boolean;
}

export interface CredentialProbeResult {
  probed: boolean;
  url_used: string;
  method: string;
  status_code?: number;
  status_class?: string;
  ok?: boolean;
  reachable?: boolean;
  error?: string;
}

export interface CredentialTestResponse {
  credential_id: string;
  status: 'ok' | 'skipped' | 'rejected' | 'probe_failed';
  reason?: string;
  decision: CredentialPolicyDecision;
  probe?: CredentialProbeResult;
  probed: boolean;
}

export interface AppliedCredentialConfig {
  provider: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  api_key_masked: string;
  updated_at: string;
}

interface ApiErrorBody {
  detail?: unknown;
  error?: {
    message?: unknown;
  };
  message?: unknown;
}

interface ApiErrorDetail {
  code?: unknown;
  message?: unknown;
}

function isApiErrorDetail(value: unknown): value is ApiErrorDetail {
  return typeof value === 'object' && value !== null;
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

const PATH = '/api/credentials';
const CREDENTIAL_TEST_TIMEOUT_MS = 60_000;

const client = () => axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 15_000,
});

export async function listCredentials(opts?: {
  category?: CredentialCategory;
  enabledOnly?: boolean;
}): Promise<RuntimeCredentialPublic[]> {
  const params: Record<string, string | boolean> = {};
  if (opts?.category) params.category = opts.category;
  if (opts?.enabledOnly) params.enabled_only = true;
  const resp = await client().get<RuntimeCredentialPublic[]>(PATH, { params });
  return resp.data;
}

export async function createCredential(
  body: RuntimeCredentialCreate,
): Promise<RuntimeCredentialPublic> {
  const resp = await client().post<RuntimeCredentialPublic>(PATH, body);
  return resp.data;
}

export async function getCredential(
  credentialId: string,
): Promise<RuntimeCredentialPublic> {
  const resp = await client().get<RuntimeCredentialPublic>(
    `${PATH}/${encodeURIComponent(credentialId)}`,
  );
  return resp.data;
}

export async function updateCredential(
  credentialId: string,
  body: RuntimeCredentialUpdate,
): Promise<RuntimeCredentialPublic> {
  const resp = await client().put<RuntimeCredentialPublic>(
    `${PATH}/${encodeURIComponent(credentialId)}`,
    body,
  );
  return resp.data;
}

/**
 * Returns true when a credential write failed because the selected id is gone.
 *
 * The credentials UI uses this to clear stale edit state after another tab or
 * component deleted the same credential.
 */
export function isCredentialNotFoundError(error: unknown): boolean {
  if (!axios.isAxiosError<ApiErrorBody>(error)) {
    return false;
  }
  if (error.response?.status !== 404) {
    return false;
  }
  const detail = error.response.data?.detail;
  if (isApiErrorDetail(detail) && detail.code === 'credential_not_found') {
    return true;
  }
  return getApiErrorMessage(error).includes('凭证不存在');
}

function getApiErrorMessage(error: AxiosError<ApiErrorBody>): string {
  const data = error.response?.data;
  const detail = data?.detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (isApiErrorDetail(detail) && typeof detail.message === 'string') {
    return detail.message;
  }
  const errorMessage = data?.error?.message;
  if (typeof errorMessage === 'string') {
    return errorMessage;
  }
  const message = data?.message;
  if (typeof message === 'string') {
    return message;
  }
  return error.message;
}

export async function deleteCredential(credentialId: string): Promise<void> {
  await client().delete(`${PATH}/${encodeURIComponent(credentialId)}`);
}

export async function testCredential(
  credentialId: string,
  opts?: { trustSourceOverride?: CredentialTrustSource; timeoutMs?: number },
): Promise<CredentialTestResponse> {
  const body: Record<string, string> = {};
  if (opts?.trustSourceOverride) body.trust_source_override = opts.trustSourceOverride;
  const resp = await client().post<CredentialTestResponse>(
    `${PATH}/${encodeURIComponent(credentialId)}/test`,
    body,
    { timeout: opts?.timeoutMs ?? CREDENTIAL_TEST_TIMEOUT_MS },
  );
  return resp.data;
}

export async function applyCredentialToSubsystem(
  subsystem: CredentialCategory,
  credentialId: string,
): Promise<AppliedCredentialConfig> {
  const pathSubsystem = subsystem === 'generation' ? 'chat' : subsystem;
  const resp = await client().post<AppliedCredentialConfig>(
    `/api/${pathSubsystem}/config/apply-credential`,
    { credential_id: credentialId },
  );
  return resp.data;
}
