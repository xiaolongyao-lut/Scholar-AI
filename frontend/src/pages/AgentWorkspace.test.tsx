import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentWorkspace } from './AgentWorkspace';
import {
  getAgentBridgeStatus,
  getAgentWorkflowHealth,
  getAgentWorkspaceStatus,
  getZoteroAttachmentHealth,
  listRuntimeJobs,
} from '@/services/agentWorkspaceApi';
import { getWikiReview } from '@/services/wikiApi';

vi.mock('@/services/agentWorkspaceApi', () => ({
  getAgentWorkspaceStatus: vi.fn(),
  getAgentBridgeStatus: vi.fn(),
  getAgentWorkflowHealth: vi.fn(),
  getZoteroAttachmentHealth: vi.fn(),
  listRuntimeJobs: vi.fn(),
}));

vi.mock('@/services/wikiApi', () => ({
  getWikiReview: vi.fn(),
}));

const mockedGetAgentWorkspaceStatus = vi.mocked(getAgentWorkspaceStatus);
const mockedGetAgentBridgeStatus = vi.mocked(getAgentBridgeStatus);
const mockedGetAgentWorkflowHealth = vi.mocked(getAgentWorkflowHealth);
const mockedGetZoteroAttachmentHealth = vi.mocked(getZoteroAttachmentHealth);
const mockedListRuntimeJobs = vi.mocked(listRuntimeJobs);
const mockedGetWikiReview = vi.mocked(getWikiReview);

describe('AgentWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetAgentWorkspaceStatus.mockResolvedValue({
      artifact_root: 'workspace_artifacts/agent_mcp_workflows',
      artifact_count: 0,
      audit_count: 0,
      total_artifact_bytes: 0,
      latest_activity_at: null,
      artifacts: [],
      audit_records: [],
    });
    mockedGetAgentBridgeStatus.mockResolvedValue({
      enabled: true,
      pending_count: 0,
      running_count: 0,
      recent: [],
    });
    mockedGetAgentWorkflowHealth.mockResolvedValue({
      schema_version: 'scholar-ai-health-check/v1',
      status: 'ok',
      generated_at: '2026-06-21T01:00:00Z',
      include_live: false,
      checks: [],
      recommendations: [],
      outcome: {
        schema_version: 'scholar-ai-tool-outcome/v1',
        status: 'success',
        quality: 'full',
        reason: 'Scholar AI workflow readiness checks passed.',
        next_action: { kind: 'none', message: '' },
        attempts: [],
      },
    });
    mockedGetZoteroAttachmentHealth.mockResolvedValue({
      schema_version: 'scholar-ai-zotero-attachment-health/v1',
      status: 'blocked',
      generated_at: '2026-06-21T01:00:00Z',
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
    });
    mockedGetWikiReview.mockResolvedValue({
      enabled: true,
      items: [],
    });
    mockedListRuntimeJobs.mockResolvedValue({ recent: [] });
  });

  it('renders writing export runtime jobs with workflow summary badges', async () => {
    mockedListRuntimeJobs.mockResolvedValue({
      recent: [
        {
          job_id: 'job_export_state_1',
          session_id: 'session_export_state_1',
          kind: 'artifact_export',
          status: 'completed',
          input_text: 'Export writing project project-1 as json',
          created_at: '2026-06-20T01:00:00.000Z',
          started_at: '2026-06-20T01:00:01.000Z',
          completed_at: '2026-06-20T01:00:02.000Z',
          action_id: 'api.writing.export',
          skill_id: null,
          tags: ['writing_export', 'json'],
          metadata: { project_id: 'project-1' },
          writing_workflow_state_summary: {
            phase: 'export_ready',
            readiness: { has_export_manifest: true },
            export_format: 'json',
            export_filename: 'paper.json',
          },
        },
      ],
    });

    render(<AgentWorkspace />);

    expect(await screen.findAllByText('Export writing project project-1 as json')).toHaveLength(2);
    expect(screen.getByText('写作导出')).toBeInTheDocument();
    expect(screen.getByText('export_ready')).toBeInTheDocument();
    expect(screen.getByText('paper.json')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('Runtime Jobs')).toBeInTheDocument();
    });
  });

  it('renders local readiness guidance from health, Zotero, review, runtime, and audit signals', async () => {
    mockedGetAgentWorkspaceStatus.mockResolvedValue({
      artifact_root: 'workspace_artifacts/agent_mcp_workflows',
      artifact_count: 1,
      audit_count: 1,
      total_artifact_bytes: 512,
      latest_activity_at: '2026-06-21T02:00:00.000Z',
      artifacts: [],
      audit_records: [
        {
          timestamp: '2026-06-21T02:00:00.000Z',
          tool_name: 'literature.agent_result',
          args_summary: {},
          touched_paths: [],
          allow_block_reason: 'safe',
          result_preview: 'failed export readiness',
          duration_ms: 12,
          error_code: 'export_failed',
        },
      ],
    });
    mockedGetAgentBridgeStatus.mockResolvedValue({
      enabled: true,
      pending_count: 1,
      running_count: 1,
      recent: [],
    });
    mockedGetAgentWorkflowHealth.mockResolvedValue({
      schema_version: 'scholar-ai-health-check/v1',
      status: 'degraded',
      generated_at: '2026-06-21T02:00:00Z',
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
    });
    mockedGetZoteroAttachmentHealth.mockResolvedValue({
      schema_version: 'scholar-ai-zotero-attachment-health/v1',
      status: 'blocked',
      generated_at: '2026-06-21T02:00:00Z',
      zotero_data_dir: 'C:/private/Zotero',
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
    });
    mockedGetWikiReview.mockResolvedValue({
      enabled: true,
      items: [
        {
          item_id: 'review-1',
          kind: 'claim',
          title: '待审 Claim',
          page_path: 'claims/a.md',
          summary: '需要补证据。',
          status: 'pending',
          created_at: '2026-06-21T02:00:00Z',
          source: 'agent_result',
          metadata: {},
          decision: null,
        },
      ],
    });
    mockedListRuntimeJobs.mockResolvedValue({
      recent: [
        {
          job_id: 'job_single_1',
          session_id: 'session_single_1',
          kind: 'agent_request',
          status: 'in_progress',
          input_text: '单篇精读 Paper A',
          created_at: '2026-06-21T02:00:00.000Z',
          started_at: '2026-06-21T02:00:01.000Z',
          completed_at: null,
          action_id: null,
          skill_id: null,
          tags: [],
          metadata: { intent: 'single_paper_deep_read' },
          writing_workflow_state_summary: { phase: 'reading' },
        },
        {
          job_id: 'job_export_1',
          session_id: 'session_export_1',
          kind: 'artifact_export',
          status: 'failed',
          input_text: 'Export project',
          created_at: '2026-06-21T02:00:00.000Z',
          started_at: '2026-06-21T02:00:01.000Z',
          completed_at: '2026-06-21T02:00:02.000Z',
          action_id: 'api.writing.export',
          skill_id: null,
          tags: ['writing_export'],
          metadata: { project_id: 'project-1' },
          writing_workflow_state_summary: { phase: 'export_failed' },
        },
      ],
    });

    render(<AgentWorkspace />);

    expect(await screen.findByRole('heading', { name: '本地就绪' })).toBeInTheDocument();
    expect(screen.getByText('工作流检查')).toBeInTheDocument();
    expect(screen.getByText('Zotero 附件')).toBeInTheDocument();
    expect(screen.getByText('单篇精读')).toBeInTheDocument();
    expect(screen.getByText('Review Queue')).toBeInTheDocument();
    expect(screen.getByText('导出与审计')).toBeInTheDocument();
    expect(screen.getAllByText('Scan the project source folder so retrieval and evidence packs can read chunks.')).toHaveLength(1);
    expect(screen.getByText('Provide a Zotero data directory containing zotero.sqlite, then rerun the health check.')).toBeInTheDocument();
    expect(screen.getByText('进入 Wiki 工作台复核待审页面。')).toBeInTheDocument();
    expect(screen.getByText('打开任务详情检查待补充哨兵和 evidence refs。')).toBeInTheDocument();
    expect(screen.queryByText('C:/private/Zotero')).not.toBeInTheDocument();
  });
});
