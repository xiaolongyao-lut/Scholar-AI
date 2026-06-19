import { createDefaultApiClient } from './httpClient';
import type { WritingJob } from '@/types/runtime';

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
