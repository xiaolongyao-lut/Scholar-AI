/**
 * Legacy env migration API client + modal.
 *
 * Detects legacy secret-shaped entries on an existing MCP server and
 * offers a guided migration through the shared CredentialPicker.
 *
 * Backend contract is intentionally kept in typed functions below so UI copy
 * never needs to render machine field names.
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
