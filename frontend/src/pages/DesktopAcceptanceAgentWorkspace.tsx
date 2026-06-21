import { TerminalSquare } from 'lucide-react';

import { PageHeader } from '@/components/common/PageHeader';
import { ReadinessPanel } from './AgentWorkspace';
import type {
  AgentBridgeStatus,
  AgentWorkflowHealthCheck,
  AgentWorkspaceAuditRecord,
  AgentWorkspaceStatus,
  RuntimeJobsStatus,
  ZoteroAttachmentHealth,
} from '@/services/agentWorkspaceApi';
import type { WikiReviewListModel } from '@/types/wiki';
import type { WritingJob } from '@/types/runtime';

const ACCEPTANCE_WORKSPACE_STATUS: AgentWorkspaceStatus = {
  artifact_root: 'workspace_artifacts/agent_mcp_workflows',
  artifact_count: 2,
  audit_count: 1,
  total_artifact_bytes: 4096,
  latest_activity_at: '2026-06-21T04:00:00.000Z',
  artifacts: [],
  audit_records: [
    {
      timestamp: '2026-06-21T04:00:00.000Z',
      tool_name: 'literature.agent_result',
      args_summary: { intent: 'single_paper_deep_read' },
      touched_paths: [],
      allow_block_reason: 'safe',
      result_preview: '待补充 sentinel remained in the draft.',
      duration_ms: 18,
      error_code: 'needs_completion',
    },
  ],
};

const ACCEPTANCE_BRIDGE_STATUS: AgentBridgeStatus = {
  enabled: true,
  pending_count: 1,
  running_count: 1,
  recent: [],
};

const ACCEPTANCE_AGENT_JOBS: WritingJob[] = [
  {
    job_id: 'job_single_paper_acceptance',
    session_id: 'session_single_paper_acceptance',
    kind: 'agent_request',
    status: 'in_progress',
    input_text: '单篇精读：方法与证据链检查',
    created_at: '2026-06-21T04:00:00.000Z',
    started_at: '2026-06-21T04:00:01.000Z',
    completed_at: null,
    action_id: null,
    skill_id: null,
    tags: [],
    metadata: {
      intent: 'single_paper_deep_read',
      progress_message: '正在检查待补充哨兵和 evidence refs。',
    },
    writing_workflow_state_summary: { phase: 'reading' },
  },
  {
    job_id: 'job_export_acceptance',
    session_id: 'session_export_acceptance',
    kind: 'artifact_export',
    status: 'failed',
    input_text: 'Export project draft',
    created_at: '2026-06-21T04:01:00.000Z',
    started_at: '2026-06-21T04:01:01.000Z',
    completed_at: '2026-06-21T04:01:05.000Z',
    action_id: 'api.writing.export',
    skill_id: null,
    tags: ['writing_export'],
    metadata: { project_id: 'desktop-acceptance' },
    writing_workflow_state_summary: { phase: 'export_failed', export_format: 'docx' },
  },
];

const ACCEPTANCE_RUNTIME_JOBS: RuntimeJobsStatus = {
  recent: ACCEPTANCE_AGENT_JOBS,
};

const ACCEPTANCE_HEALTH: AgentWorkflowHealthCheck = {
  schema_version: 'scholar-ai-health-check/v1',
  status: 'degraded',
  generated_at: '2026-06-21T04:00:00.000Z',
  include_live: false,
  checks: [
    {
      name: 'project_index',
      status: 'degraded',
      reason: 'Materials exist, but no indexed chunks were found.',
      details: { material_count: 2, chunk_count: 0 },
      next_action: {
        kind: 'scan_folder',
        message: 'Scan the project source folder so retrieval and evidence packs can read chunks.',
      },
    },
  ],
  recommendations: [
    {
      kind: 'scan_folder',
      message: 'Scan the project source folder so retrieval and evidence packs can read chunks.',
    },
  ],
  outcome: {
    schema_version: 'scholar-ai-tool-outcome/v1',
    status: 'degraded',
    quality: 'partial',
    reason: 'Scholar AI workflow readiness is degraded or blocked; inspect recommendations.',
    next_action: {
      kind: 'scan_folder',
      message: 'Scan the project source folder so retrieval and evidence packs can read chunks.',
    },
    attempts: [],
  },
};

const ACCEPTANCE_ZOTERO: ZoteroAttachmentHealth = {
  schema_version: 'scholar-ai-zotero-attachment-health/v1',
  status: 'blocked',
  generated_at: '2026-06-21T04:00:00.000Z',
  zotero_data_dir: '',
  snapshot_used: false,
  summary: { status_counts: {}, returned_item_count: 0 },
  items: [],
  reports: {},
  outcome: {
    schema_version: 'scholar-ai-tool-outcome/v1',
    status: 'config_needed',
    quality: 'none',
    reason: 'zotero_data_dir is required',
    next_action: {
      kind: 'open_settings',
      message: 'Provide a Zotero data directory containing zotero.sqlite, then rerun the health check.',
    },
    attempts: [],
  },
};

const ACCEPTANCE_REVIEW: WikiReviewListModel = {
  enabled: true,
  items: [
    {
      item_id: 'review-acceptance-1',
      kind: 'claim',
      title: '待审 Claim',
      page_path: 'claims/acceptance.md',
      summary: '需要补充证据锚点。',
      status: 'pending',
      created_at: '2026-06-21T04:00:00.000Z',
      source: 'agent_result',
      metadata: {},
      decision: null,
    },
  ],
};

export function DesktopAcceptanceAgentWorkspace() {
  return (
    <div
      className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background px-5 py-4"
      data-testid="desktop-acceptance-agent-workspace"
    >
      <PageHeader
        icon={<TerminalSquare size={18} />}
        title="Agent Workspace"
        subtitle="本地就绪"
        className="mb-3 shrink-0"
      />
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden">
        <ReadinessPanel
          loading={false}
          error={null}
          workspaceStatus={ACCEPTANCE_WORKSPACE_STATUS}
          bridgeStatus={ACCEPTANCE_BRIDGE_STATUS}
          runtimeJobsStatus={ACCEPTANCE_RUNTIME_JOBS}
          healthCheck={ACCEPTANCE_HEALTH}
          zoteroHealth={ACCEPTANCE_ZOTERO}
          wikiReview={ACCEPTANCE_REVIEW}
          agentJobs={ACCEPTANCE_AGENT_JOBS}
          auditRecords={ACCEPTANCE_WORKSPACE_STATUS.audit_records}
          density="desktop-acceptance"
        />
      </div>
    </div>
  );
}

export default DesktopAcceptanceAgentWorkspace;
