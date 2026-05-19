/**
 * MCP local installer API client (S4 / plan 2026-05-20 §A4).
 *
 * Mirrors the backend's mcp_installer_router.py endpoints. Lives separate
 * from the existing mcpApi.ts (which handles registry CRUD + audit +
 * pending-calls) so the installer flow can be reasoned about in isolation.
 */
import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';

// ---------------------------------------------------------------------------
// Backend models — mirror models/mcp_installation.py.
// Kept in sync manually until OpenAPI regen.
// ---------------------------------------------------------------------------

export type McpScanConfidence = 'high' | 'medium' | 'low' | 'none';
export type McpScanWarningLevel = 'info' | 'warn' | 'block';

export interface McpScanWarning {
  level: McpScanWarningLevel;
  code: string;
  message: string;
  field: string | null;
}

export interface McpLaunchCandidate {
  command: string;
  args: string[];
  cwd: string;
  confidence: McpScanConfidence;
  source: string;
  sha: string;
}

export interface McpInstallConfigField {
  id: string;
  label: string;
  env: string;
  type: 'text' | 'select';
  required: boolean;
  default: string | null;
  options: Array<{ value: string; label: string }> | null;
  description: string;
}

export interface McpRequiredCredential {
  id: string;
  label: string;
  env: string;
  kind: 'api_key';
  provider_hints: string[];
  required: boolean;
  description: string;
}

export interface McpPackageScanRequest {
  source_path: string;
  template_hint?: string;
}

export interface McpPackageScanResult {
  scan_id: string;
  source_path: string;
  package_id: string;
  display_name: string;
  description: string;
  version: string;
  confidence: McpScanConfidence;
  transport: string;
  launch_candidates: McpLaunchCandidate[];
  config_fields: McpInstallConfigField[];
  required_credentials: McpRequiredCredential[];
  expected_tools: string[];
  capabilities: string[];
  warnings: McpScanWarning[];
  needs_manual_launch: boolean;
  expires_at: string;
}

export interface McpInstallationPreviewRequest {
  scan_id: string;
  launch_candidate_sha: string;
}

export interface McpInstallationPreviewResponse {
  scan_id: string;
  source_path: string;
  package_id: string;
  display_name: string;
  description: string;
  version: string;
  transport: string;
  candidate: McpLaunchCandidate;
  config_fields: McpInstallConfigField[];
  required_credentials: McpRequiredCredential[];
  expected_tools: string[];
  warnings: McpScanWarning[];
  expires_at: string;
}

export interface McpInstallationInstallRequest {
  scan_id: string;
  launch_candidate_sha: string;
  server_slug: string;
  display_name: string;
  config_values: Record<string, string>;
  credential_bindings: Record<string, string>;
  /**
   * Locked Revisions M7: only `true` triggers a probe that spawns the
   * server process. UI MUST surface this as an explicit checkbox with
   * copy that mentions the risk of starting the package's process.
   */
  trust_to_probe: boolean;
  enable_for_session?: boolean;
  notes?: string;
}

export interface McpInstallationInstallResponse {
  install_id: string;
  server_id: string;
  server: Record<string, unknown>;
  install_dir: string;
  absolute_cwd: string;
  approval_state: string;
  probe: {
    status: 'ok' | 'skipped_untrusted' | 'probe_failed';
    tool_count: number;
    tools: Array<Record<string, unknown>>;
    reason: string;
  };
}

/**
 * Error code returned in `detail.code` when a 4xx/410 install error occurs.
 * Frontend switches on this rather than parsing the localized message.
 */
export type McpInstallErrorCode =
  | 'scan_rejected'
  | 'scan_not_found'
  | 'scan_expired'
  | 'candidate_mismatch'
  | 'credential_not_found'
  | 'credential_disabled'
  | 'transport_unsupported'
  | 'server_slug_conflict'
  | 'install_error';

export interface McpInstallErrorDetail {
  code: McpInstallErrorCode;
  message: string;
}

export class McpInstallApiError extends Error {
  readonly status: number;
  readonly code: McpInstallErrorCode;

  constructor(status: number, code: McpInstallErrorCode, message: string) {
    super(message);
    this.name = 'McpInstallApiError';
    this.status = status;
    this.code = code;
  }
}

// ---------------------------------------------------------------------------
// HTTP client
// ---------------------------------------------------------------------------

const BASE = '/api/mcp/installations';

const client = () => axios.create({
  baseURL: getApiBaseUrl(),
  timeout: 60_000,
});

function rethrowAsInstallError(exc: unknown): never {
  if (axios.isAxiosError(exc) && exc.response) {
    const status = exc.response.status;
    const raw = (exc.response.data ?? {}) as { detail?: McpInstallErrorDetail | string };
    if (raw.detail && typeof raw.detail === 'object' && 'code' in raw.detail) {
      throw new McpInstallApiError(status, raw.detail.code, raw.detail.message);
    }
    if (typeof raw.detail === 'string') {
      throw new McpInstallApiError(status, 'install_error', raw.detail);
    }
    throw new McpInstallApiError(status, 'install_error', `HTTP ${status}`);
  }
  if (exc instanceof Error) throw exc;
  throw new Error(String(exc));
}

export async function scanLocalMcpPackage(
  body: McpPackageScanRequest,
): Promise<McpPackageScanResult> {
  try {
    const resp = await client().post<McpPackageScanResult>(`${BASE}/scan`, body);
    return resp.data;
  } catch (exc) {
    rethrowAsInstallError(exc);
  }
}

export async function previewInstall(
  body: McpInstallationPreviewRequest,
): Promise<McpInstallationPreviewResponse> {
  try {
    const resp = await client().post<McpInstallationPreviewResponse>(
      `${BASE}/preview`,
      body,
    );
    return resp.data;
  } catch (exc) {
    rethrowAsInstallError(exc);
  }
}

export async function installMcpPackage(
  body: McpInstallationInstallRequest,
): Promise<McpInstallationInstallResponse> {
  try {
    const resp = await client().post<McpInstallationInstallResponse>(
      `${BASE}/install`,
      body,
    );
    return resp.data;
  } catch (exc) {
    rethrowAsInstallError(exc);
  }
}
