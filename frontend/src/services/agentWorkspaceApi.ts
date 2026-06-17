import { createDefaultApiClient } from './httpClient';

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
