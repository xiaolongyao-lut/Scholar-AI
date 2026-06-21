import { createDefaultApiClient } from './httpClient';
import type { components } from '@/generated/openapi';
import type { WritingJob } from '@/types/runtime';

export type AgentWorkflowHealthCheck = components['schemas']['HealthCheckResponse'];
export type ZoteroAttachmentHealth = components['schemas']['ZoteroAttachmentHealthResponse'];

export interface AgentWorkspaceArtifact {
  path: string;
  name: string;
  kind: string;
  size_bytes: number;
  modified_at: string;
  preview: string;
  truncated: boolean;
}

export interface AgentWorkspaceAuditRecord {
  timestamp: string;
  tool_name: string;
  args_summary: Record<string, unknown>;
  touched_paths: string[];
  allow_block_reason: string;
  result_preview: string;
  duration_ms: number;
  error_code: string | null;
}

export interface AgentWorkspaceStatus {
  artifact_root: string;
  artifact_count: number;
  audit_count: number;
  total_artifact_bytes: number;
  latest_activity_at: string | null;
  artifacts: AgentWorkspaceArtifact[];
  audit_records: AgentWorkspaceAuditRecord[];
}

export interface AgentBridgeStatus {
  enabled: boolean;
  pending_count: number;
  running_count: number;
  recent: WritingJob[];
}

export interface RuntimeJobsStatus {
  recent: WritingJob[];
}

const client = createDefaultApiClient({ timeoutMs: 20_000 });

export async function getAgentWorkspaceStatus(opts?: {
  artifactLimit?: number;
  auditLimit?: number;
  previewChars?: number;
}): Promise<AgentWorkspaceStatus> {
  const response = await client.get<AgentWorkspaceStatus>('/api/agent-workspace/status', {
    params: {
      artifact_limit: opts?.artifactLimit ?? 200,
      audit_limit: opts?.auditLimit ?? 300,
      preview_chars: opts?.previewChars ?? 4000,
    },
  });
  return response.data;
}

export async function getAgentBridgeStatus(opts?: {
  limit?: number;
}): Promise<AgentBridgeStatus> {
  const response = await client.get<AgentBridgeStatus>('/api/agent-bridge/status', {
    params: {
      limit: opts?.limit ?? 20,
    },
  });
  return response.data;
}

export async function listRuntimeJobs(opts?: {
  limit?: number;
}): Promise<RuntimeJobsStatus> {
  const response = await client.get<WritingJob[]>('/runtime/jobs', {
    params: {
      limit: opts?.limit ?? 100,
    },
  });
  return { recent: response.data };
}

/**
 * Return passive local workflow readiness without spending provider quota.
 *
 * Args:
 *   opts: Whether to ask the backend to record explicit live-probe intent.
 *
 * Returns:
 *   Versioned readiness checks and ToolOutcome next-action guidance.
 */
export async function getAgentWorkflowHealth(opts?: {
  includeLive?: boolean;
}): Promise<AgentWorkflowHealthCheck> {
  const response = await client.get<AgentWorkflowHealthCheck>('/api/health/check', {
    params: {
      include_live: opts?.includeLive ?? false,
    },
  });
  return response.data;
}

/**
 * Return read-only Zotero attachment diagnostics for UI guidance.
 *
 * Args:
 *   opts: Optional local Zotero path controls and report-writing policy.
 *
 * Returns:
 *   Versioned Zotero health report. The backend reads a snapshot only and never
 *   writes Zotero repair state.
 */
export async function getZoteroAttachmentHealth(opts?: {
  zoteroDataDir?: string | null;
  allowedRoot?: string | null;
  minTextChars?: number;
  maxItems?: number;
  writeReports?: boolean;
}): Promise<ZoteroAttachmentHealth> {
  const response = await client.get<ZoteroAttachmentHealth>('/api/zotero/attachment-health', {
    params: {
      zotero_data_dir: opts?.zoteroDataDir ?? undefined,
      allowed_root: opts?.allowedRoot ?? undefined,
      min_text_chars: opts?.minTextChars ?? undefined,
      max_items: opts?.maxItems ?? 20,
      write_reports: opts?.writeReports ?? false,
    },
  });
  return response.data;
}
