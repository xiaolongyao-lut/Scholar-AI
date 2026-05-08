import axios from 'axios';
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
  | 'default'
  | 'cheap'
  | 'fast'
  | 'quality'
  | 'discussion'
  | 'embedding'
  | 'rerank';

export type CredentialTrustSource =
  | 'official_provider'
  | 'env_configured_gateway'
  | 'runtime_user_confirmed'
  | 'runtime_untrusted_custom';

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

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

const PATH = '/api/credentials';

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

export async function deleteCredential(credentialId: string): Promise<void> {
  await client().delete(`${PATH}/${encodeURIComponent(credentialId)}`);
}

export async function testCredential(
  credentialId: string,
  opts?: { trustSourceOverride?: CredentialTrustSource },
): Promise<CredentialTestResponse> {
  const body: Record<string, string> = {};
  if (opts?.trustSourceOverride) body.trust_source_override = opts.trustSourceOverride;
  const resp = await client().post<CredentialTestResponse>(
    `${PATH}/${encodeURIComponent(credentialId)}/test`,
    body,
  );
  return resp.data;
}
