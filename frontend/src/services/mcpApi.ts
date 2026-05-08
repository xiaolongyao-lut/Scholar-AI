import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl.ts';

// ---------------------------------------------------------------------------
// Backend types — mirror models/mcp.py + routers/mcp_router.py.
// Kept in sync manually until OpenAPI regen.
// ---------------------------------------------------------------------------

export type McpTransport = 'stdio' | 'streamable_http';

export type McpProvenance =
  | 'official_provider'
  | 'runtime_user_confirmed'
  | 'runtime_untrusted_custom';

export type McpApprovalState =
  | 'registered'
  | 'catalog_reviewed'
  | 'enabled_for_session';

export type McpToolCapability =
  | 'read'
  | 'write'
  | 'network'
  | 'filesystem'
  | 'destructive'
  | 'unknown';

export interface McpStdioConfigPublic {
  command: string;
  args: string[];
  env: Record<string, string>; // values masked
  cwd_relative: string | null;
}

export interface McpStreamableHttpConfigPublic {
  url: string;
  headers: Record<string, string>; // values masked
  timeout_seconds: number;
}

export interface McpServerConfigPublic {
  server_id: string;
  name: string;
  server_slug: string;
  transport: McpTransport;
  stdio: McpStdioConfigPublic | null;
  http: McpStreamableHttpConfigPublic | null;
  provenance: McpProvenance;
  tags: string[];
  notes: string;
  approval_state: McpApprovalState;
  fingerprint: string;
  fingerprint_version: string;
  created_at: string;
  updated_at: string;
}

export interface McpStdioConfigCreate {
  command: string;
  args?: string[];
  env?: Record<string, string>; // raw secrets; backend stores; UI never re-displays
  cwd_relative?: string | null;
}

export interface McpStreamableHttpConfigCreate {
  url: string;
  headers?: Record<string, string>;
  timeout_seconds?: number;
}

export interface McpServerConfigCreate {
  name: string;
  server_slug: string;
  transport: McpTransport;
  stdio?: McpStdioConfigCreate | null;
  http?: McpStreamableHttpConfigCreate | null;
  provenance?: McpProvenance;
  tags?: string[];
  notes?: string;
}

export interface McpServerConfigUpdate {
  name?: string;
  notes?: string;
  tags?: string[];
  approval_state?: McpApprovalState;
  stdio?: McpStdioConfigCreate | null;
  http?: McpStreamableHttpConfigCreate | null;
}

export interface McpToolDescriptor {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  capability: McpToolCapability;
}

export interface McpTestResponse {
  server_id: string;
  status: 'ok' | 'skipped' | 'probe_failed';
  reason?: string;
  tool_count?: number;
  tools?: McpToolDescriptor[];
  fingerprint?: string;
  probed: boolean;
}

// ---------------------------------------------------------------------------
// HTTP client
// ---------------------------------------------------------------------------

const PATH = '/api/mcp/servers';

const client = () => axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 30_000,
});

export async function listMcpServers(opts?: {
  approvalState?: McpApprovalState;
}): Promise<McpServerConfigPublic[]> {
  const params: Record<string, string> = {};
  if (opts?.approvalState) params.approval_state = opts.approvalState;
  const resp = await client().get<McpServerConfigPublic[]>(PATH, { params });
  return resp.data;
}

export async function createMcpServer(
  body: McpServerConfigCreate,
): Promise<McpServerConfigPublic> {
  const resp = await client().post<McpServerConfigPublic>(PATH, body);
  return resp.data;
}

export async function getMcpServer(serverId: string): Promise<McpServerConfigPublic> {
  const resp = await client().get<McpServerConfigPublic>(
    `${PATH}/${encodeURIComponent(serverId)}`,
  );
  return resp.data;
}

export async function updateMcpServer(
  serverId: string,
  body: McpServerConfigUpdate,
): Promise<McpServerConfigPublic> {
  const resp = await client().put<McpServerConfigPublic>(
    `${PATH}/${encodeURIComponent(serverId)}`,
    body,
  );
  return resp.data;
}

export async function deleteMcpServer(serverId: string): Promise<void> {
  await client().delete(`${PATH}/${encodeURIComponent(serverId)}`);
}

export async function testMcpServer(serverId: string): Promise<McpTestResponse> {
  const resp = await client().post<McpTestResponse>(
    `${PATH}/${encodeURIComponent(serverId)}/test`,
  );
  return resp.data;
}

export async function listMcpServerTools(serverId: string): Promise<McpToolDescriptor[]> {
  const resp = await client().get<McpToolDescriptor[]>(
    `${PATH}/${encodeURIComponent(serverId)}/tools`,
  );
  return resp.data;
}
