/**
 * Legacy env migration API client + modal (S6 frontend / plan 2026-05-20 §6).
 *
 * Detects raw secret-shaped env / header entries on an existing MCP
 * server and offers a guided migration to env_refs / header_refs via
 * the shared CredentialPicker.
 *
 * Backend contract:
 *   GET  /api/mcp/servers/{id}/legacy-env       → masked detection list
 *   POST /api/mcp/servers/{id}/migrate-env-to-refs
 *        body: { mapping: {env_key: credential_id}, confirm_remove_raw: true }
 *        → moves raw values into refs, removes raw entries, rebuilds binding index
 */
import axios from 'axios';
import { getApiBaseUrl } from '@/services/apiBaseUrl';

export interface LegacyEnvEntry {
  target_env: string;
  value_masked: string;
  transport_field: 'stdio.env' | 'http.headers';
}

export interface LegacyEnvResponse {
  server_id: string;
  count: number;
  entries: LegacyEnvEntry[];
}

export interface MigrateEnvRefsRequest {
  mapping: Record<string, string>;
  confirm_remove_raw: true;
}

export interface MigrateEnvRefsResponse {
  server_id: string;
  migrated_stdio_env_keys: string[];
  migrated_http_header_keys: string[];
  server: Record<string, unknown>;
}

const client = () => axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 30_000,
});

export async function fetchLegacyEnv(serverId: string): Promise<LegacyEnvResponse> {
  const resp = await client().get<LegacyEnvResponse>(
    `/api/mcp/servers/${encodeURIComponent(serverId)}/legacy-env`,
  );
  return resp.data;
}

export async function migrateEnvToRefs(
  serverId: string,
  body: MigrateEnvRefsRequest,
): Promise<MigrateEnvRefsResponse> {
  const resp = await client().post<MigrateEnvRefsResponse>(
    `/api/mcp/servers/${encodeURIComponent(serverId)}/migrate-env-to-refs`,
    body,
  );
  return resp.data;
}
