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
  cwd?: string | null;
  env: Record<string, string>; // values masked
  env_refs?: Record<string, string>;
  cwd_relative: string | null;
}

export interface McpStreamableHttpConfigPublic {
  url: string;
  headers: Record<string, string>; // values masked
  header_refs?: Record<string, string>;
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
  cwd?: string | null;
  env?: Record<string, string>; // raw secrets; backend stores; UI never re-displays
  env_refs?: Record<string, string>;
  cwd_relative?: string | null;
}

export interface McpStreamableHttpConfigCreate {
  url: string;
  headers?: Record<string, string>;
  header_refs?: Record<string, string>;
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

/**
 * Audit record shape mirroring `mcp_runtime/audit.py` schema. The backend
 * already redacts `preview` via `security_policy.redact_text_for_audit`;
 * the frontend never re-fetches raw env or header values.
 */
export interface McpAuditRecord {
  ts: string;
  tool_call_id: string;
  server_id: string;
  server_slug: string;
  tool_name: string;
  is_error: boolean;
  elapsed_ms: number;
  preview: string;
  truncated: boolean;
  // Optional fields that may appear once the audit schema records
  // capability tag / blocked-by reason. Frontend filter handles absence.
  capability?: McpToolCapability;
  blocked_reason?: string;
}

export interface McpAuditResponse {
  count: number;
  records: McpAuditRecord[];
}

// ---------------------------------------------------------------------------
// Phase 3 pending-call protocol (mirrors mcp_runtime/pending_calls.py +
// routers/mcp_router.py).
// ---------------------------------------------------------------------------

/** Server-shaped pending tool call awaiting operator approval. */
export interface PendingMcpToolCall {
  id: string;
  server_id: string;
  tool_name: string;
  capability: McpToolCapability;
  args_preview: string;
  created_at: string;
}

export type PendingCallDecision = 'approve' | 'reject';

export interface PendingCallDecisionBody {
  decision: PendingCallDecision;
  remember_for_run: boolean;
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

/**
 * Tail the MCP tool-call audit log. Backend records are already redacted.
 * Frontend filters apply on top of the response (per D-MCPUX-7: filtering
 * is frontend-only in v1; backend query API is a Phase 3 follow-up).
 *
 * Default `limit=500` matches the locked v1 contract.
 */
export async function listMcpAuditRecords(opts?: {
  limit?: number;
}): Promise<McpAuditResponse> {
  const limit = opts?.limit ?? 500;
  const resp = await client().get<McpAuditResponse>('/api/mcp/audit', {
    params: { limit },
  });
  return resp.data;
}

// ---------------------------------------------------------------------------
// Phase 3 pending-call endpoints
// ---------------------------------------------------------------------------

const PENDING_PATH = '/api/mcp/pending-calls';

/**
 * Poll-target: return all currently-pending tool calls. Empty array when
 * nothing pending. Frontend polls every ~1s via McpPendingCallPoller.
 */
export async function listPendingMcpCalls(): Promise<PendingMcpToolCall[]> {
  const resp = await client().get<PendingMcpToolCall[]>(PENDING_PATH);
  return resp.data;
}

/**
 * Record an operator decision for a pending call. Returns 204 on success;
 * 404 if id unknown / already decided / timed out; 400 on invalid body.
 */
export async function decidePendingMcpCall(
  callId: string,
  body: PendingCallDecisionBody,
): Promise<void> {
  await client().post(
    `${PENDING_PATH}/${encodeURIComponent(callId)}/decide`,
    body,
  );
}
