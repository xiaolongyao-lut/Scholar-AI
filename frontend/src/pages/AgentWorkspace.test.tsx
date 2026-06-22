import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentWorkspace } from './AgentWorkspace';
import {
  getAgentBridgeStatus,
  getAgentHandoffCard,
  getAgentWorkflowHealth,
  getAgentWorkspaceRequirement,
  getAgentWorkspaceStatus,
  getBehaviorEvalPack,
  getEvidenceIntegrityGate,
  getResearchActionLifecycle,
  getWorkflowPassport,
  getWorkflowReplayIndex,
  getWorkflowReplayLineage,
  getZoteroAttachmentHealth,
  listRuntimeJobs,
  type BlockingActionBoundaryProjection,
  type WorkflowActionPreflightProjection,
} from '@/services/agentWorkspaceApi';
import { getWikiReview } from '@/services/wikiApi';

vi.mock('@/services/agentWorkspaceApi', () => ({
  getAgentWorkspaceStatus: vi.fn(),
  getAgentWorkspaceRequirement: vi.fn(),
  getAgentBridgeStatus: vi.fn(),
  getAgentHandoffCard: vi.fn(),
  getAgentWorkflowHealth: vi.fn(),
  getBehaviorEvalPack: vi.fn(),
  getEvidenceIntegrityGate: vi.fn(),
  getResearchActionLifecycle: vi.fn(),
  getWorkflowPassport: vi.fn(),
  getWorkflowReplayIndex: vi.fn(),
  getWorkflowReplayLineage: vi.fn(),
  getZoteroAttachmentHealth: vi.fn(),
  listRuntimeJobs: vi.fn(),
}));

vi.mock('@/services/wikiApi', () => ({
  getWikiReview: vi.fn(),
}));

const mockedGetAgentWorkspaceStatus = vi.mocked(getAgentWorkspaceStatus);
const mockedGetAgentWorkspaceRequirement = vi.mocked(getAgentWorkspaceRequirement);
const mockedGetAgentBridgeStatus = vi.mocked(getAgentBridgeStatus);
const mockedGetAgentHandoffCard = vi.mocked(getAgentHandoffCard);
const mockedGetAgentWorkflowHealth = vi.mocked(getAgentWorkflowHealth);
const mockedGetBehaviorEvalPack = vi.mocked(getBehaviorEvalPack);
const mockedGetEvidenceIntegrityGate = vi.mocked(getEvidenceIntegrityGate);
const mockedGetResearchActionLifecycle = vi.mocked(getResearchActionLifecycle);
const mockedGetWorkflowPassport = vi.mocked(getWorkflowPassport);
const mockedGetWorkflowReplayIndex = vi.mocked(getWorkflowReplayIndex);
const mockedGetWorkflowReplayLineage = vi.mocked(getWorkflowReplayLineage);
const mockedGetZoteroAttachmentHealth = vi.mocked(getZoteroAttachmentHealth);
const mockedListRuntimeJobs = vi.mocked(listRuntimeJobs);
const mockedGetWikiReview = vi.mocked(getWikiReview);
const emptyWorkflowStageRuntimeFacts = {
  diagnostics: {},
  reproducibility: {},
};

function workspaceStateFixture(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 'scholar_ai_agent_workspace_state_v1' as const,
    generated_at: '2026-06-21T01:00:00Z',
    workspace_ready: true,
    read_only: true,
    artifact_root: {
      label: 'agent_mcp_workflows',
      path: 'workspace_artifacts/agent_mcp_workflows',
      exists: true,
      file_count: 0,
      total_bytes: 0,
      truncated: false,
    },
    runtime_state_root: {
      label: 'runtime_state',
      path: 'workspace_artifacts/runtime_state',
      exists: true,
      file_count: 2,
      total_bytes: 128,
      truncated: false,
    },
    output_root: {
      label: 'generated_output',
      path: 'workspace_artifacts/generated/output',
      exists: true,
      file_count: 0,
      total_bytes: 0,
      truncated: false,
    },
    git: {
      available: true,
      branch: 'main',
      ahead: 33,
      behind: 0,
      changed_count: 0,
      staged_count: 0,
      unstaged_count: 0,
      untracked_count: 0,
      conflicted_count: 0,
      dirty_paths: [],
      error: null,
    },
    goal_state: {
      available: true,
      path: 'docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json',
      updated_at: '2026-06-22T21:50:27+08:00',
      checkpoint_id: '20260622-214730-n41-goal-state-record-update',
      requirement_count: 49,
      proved_count: 47,
      incomplete_count: 1,
      out_of_scope_count: 1,
      latest_requirement_id: 'N41-goal-state-workspace-visibility',
      requirement_status: {
        total: 49,
        proved: 47,
        incomplete: 1,
        out_of_scope: 1,
        latest_id: 'N41-goal-state-workspace-visibility',
      },
      open_requirements: [
        {
          id: 'B01-computer-use-accessibility-tree',
          status: 'incomplete',
          requirement: 'Computer Use accessibility-tree acceptance is blocked by sandboxPolicy.',
          residual_risk: 'Retry only after the external tool error is fixed.',
        },
      ],
      completion_claim: {
        this_slice: 'N41 made goal-state recovery visible.',
        full_goal: 'The full Scholar AI workflow spine remains active, not complete.',
      },
      next_authorized_local_actions: [
        'Create a rollback checkpoint and search mature references before nontrivial edits.',
      ],
      stop_boundaries: ['No push, tag, release, deploy, or external upload.'],
      error: null,
    },
    recovery_probes: [
      {
        label: 'Workflow Passport',
        route: '/runtime/workflow-passport',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover stage, gate, reproducibility, and provenance context before resuming workflow work.',
        mcp_tool: 'literature.workflow_passport',
      },
      {
        label: 'Evidence Integrity Gate',
        route: '/runtime/evidence-integrity-gate',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover blockers, unresolved evidence, and integrity signals before trusting claims.',
        mcp_tool: 'literature.evidence_integrity_gate',
      },
      {
        label: 'Research Action Lifecycle',
        route: '/runtime/research-action-lifecycle',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover action, approval, preflight, effect, and forbidden-action state before mutation.',
        mcp_tool: 'literature.research_action_lifecycle',
      },
      {
        label: 'Agent Handoff Card',
        route: '/runtime/job/{job_id}/agent-handoff-card',
        read_only: true,
        requires_identifier: true,
        identifier_hint: 'job_id',
        purpose: 'Recover resumable handoff instructions, resource refs, replay recovery, and boundaries for one job.',
        mcp_tool: 'literature.agent_handoff_card',
      },
      {
        label: 'Agent Workspace Status',
        route: '/api/agent-workspace/status',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover local artifact, audit, git, root, and recovery-probe state.',
        mcp_tool: 'literature.agent_workspace_status',
      },
    ],
    boundaries: [
      'Do not execute approvals, import-to-wiki writes, external uploads, push, tag, release, publish, or deploy from this status surface.',
      'Create a rollback checkpoint and re-check official or mature references before nontrivial edits.',
    ],
    next_safe_local_actions: [
      'Read Workflow Passport, Evidence Integrity Gate, Research Action Lifecycle, and Agent Handoff Cards before resuming mutating work.',
      'Inspect git dirty paths and preserve unrelated local work before staging or committing.',
    ],
    ...overrides,
  };
}

interface IntegrityDrilldownFixtureRef {
  ref_type: string;
  ref_id: string;
}

interface IntegrityDrilldownFixtureOptions {
  status?: 'pass' | 'warn' | 'unresolved' | 'block';
  evidenceCount?: number;
  replayCount?: number;
  evidenceRefs?: IntegrityDrilldownFixtureRef[];
  replayRefs?: IntegrityDrilldownFixtureRef[];
}

function integrityDrilldownFixture(
  sourceKind: string,
  checkedFacts: Record<string, unknown>,
  options: IntegrityDrilldownFixtureOptions = {},
): Record<string, unknown> {
  const status = options.status ?? 'unresolved';
  return {
    schema_version: 'scholar_ai_integrity_signal_drilldown_v1',
    status,
    source_ref: {
      source_id: `${sourceKind}:fixture`,
      source_kind: sourceKind,
      source_digest: `sha256:${sourceKind}`,
      raw_path_exposed: false,
    },
    checked_facts: checkedFacts,
    evidence_refs: options.evidenceRefs ?? Array.from({ length: options.evidenceCount ?? 1 }, (_, index) => ({
      ref_type: sourceKind,
      ref_id: `${sourceKind}:${index + 1}`,
    })),
    replay_refs: options.replayRefs ?? Array.from({ length: options.replayCount ?? 0 }, (_, index) => ({
      ref_type: 'workflow_replay_probe',
      ref_id: `${sourceKind}:replay:${index + 1}`,
    })),
    requires_human_review: status === 'unresolved',
    blocks_claims: status === 'block',
  };
}

describe('AgentWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetAgentWorkspaceStatus.mockResolvedValue({
      artifact_root: 'workspace_artifacts/agent_mcp_workflows',
      artifact_count: 0,
      audit_count: 0,
      total_artifact_bytes: 0,
      latest_activity_at: null,
      workspace_state: workspaceStateFixture(),
      artifacts: [],
      audit_records: [],
    });
    mockedGetAgentWorkspaceRequirement.mockResolvedValue({
      schema_version: 'scholar_ai_goal_requirement_drilldown_v1',
      available: true,
      read_only: true,
      path: 'docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json',
      updated_at: '2026-06-22T21:50:27+08:00',
      checkpoint_id: '20260622-214730-n41-goal-state-record-update',
      id: 'B01-computer-use-accessibility-tree',
      status: 'incomplete',
      requirement: 'Computer Use accessibility-tree acceptance is blocked by sandboxPolicy.',
      residual_risk: 'Retry only after the external tool error is fixed.',
      evidence: [
        {
          label: 'tests/test_agent_workspace_router.py',
          text: 'router contract covers redacted requirement drilldown',
        },
      ],
      evidence_count: 1,
      truncated: false,
      next_safe_local_actions: [
        'Create a rollback checkpoint and search mature references before edits.',
      ],
      stop_boundaries: ['No push, tag, release, deploy, or external upload.'],
      error: null,
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
    mockedGetWorkflowPassport.mockResolvedValue({
      schema_version: 'scholar_ai_workflow_passport_v1',
      generated_at: '2026-06-21T01:00:00Z',
      scope: {},
      current_stage_id: 'material_ingest',
      gate_summary: {
        gate_counts: { pass: 0, unresolved: 1, block: 0 },
        severity_counts: { warn: 1 },
      },
      provenance: {},
      stages: [
        {
          stage_id: 'material_ingest',
          label: 'Material ingest',
          status: 'in_progress',
          required_artifacts: ['material_processing_task'],
          present_artifacts: [],
          object_ids: [],
          event_types: [],
          ...emptyWorkflowStageRuntimeFacts,
          next_actions: ['Create or complete a material-processing task for source materials.'],
          updated_at: null,
          gate: {
            gate_id: 'material_ingest.gate',
            status: 'unresolved',
            severity: 'warn',
            reason: 'Stage is in progress and still needs completion evidence.',
            evidence: [],
            blockers: [],
            unresolved: ['Stage is in progress and still needs completion evidence.'],
            requires_user_confirmation: false,
          },
        },
      ],
    });
    mockedGetEvidenceIntegrityGate.mockResolvedValue({
      schema_version: 'scholar_ai_evidence_integrity_gate_v1',
      generated_at: '2026-06-21T01:00:00Z',
      scope: {},
      status: 'unresolved',
      signals: [
        {
          signal_id: 'workflow_stage:material_ingest',
          category: 'workflow_stage',
          status: 'unresolved',
          severity: 'note',
          message: 'Stage is in progress and still needs completion evidence.',
          evidence: [],
          next_actions: ['Complete material ingest evidence.'],
          metadata: {},
          drilldown: integrityDrilldownFixture(
            'workflow_passport_stage',
            { stage_id: 'material_ingest', gate_status: 'unresolved' },
            { status: 'unresolved', evidenceCount: 0 },
          ),
        },
      ],
      summary: {
        signal_count: 1,
        status_counts: { unresolved: 1 },
        severity_counts: { note: 1 },
        unresolved_is_pass: false,
      },
      blockers: [],
      unresolved: ['Stage is in progress and still needs completion evidence.'],
      provenance: {},
    });
    mockedGetResearchActionLifecycle.mockResolvedValue({
      schema_version: 'scholar_ai_research_action_lifecycle_v1',
      generated_at: '2026-06-21T01:00:01Z',
      scope: {},
      actions: [],
      summary: {
        action_count: 0,
        matching_action_count: 0,
        matching_job_count: 0,
        status_counts: {},
        action_type_counts: {},
        requires_user_confirmation: false,
        read_only: true,
        external_mutation: false,
        source_material_mutation: false,
      },
      blockers: [],
      unresolved: [],
      resume_probes: [],
      provenance: { derived_from: ['runtime.jobs'] },
    });
    mockedGetBehaviorEvalPack.mockResolvedValue({
      schema_version: 'scholar_ai_behavior_eval_pack_v1',
      generated_at: '2026-06-21T01:00:01Z',
      mode: 'canary',
      summary: {
        case_count: 8,
        observation_count: 8,
        red_flag_count: 8,
        block_count: 7,
        warn_count: 1,
        unresolved_count: 0,
        structural_status: 'pass',
        behavior_status: 'block',
        structural_note: 'Canary mode passes when every unsafe canary is detected.',
      },
      results: [],
      blockers: ['Output claims verification while nested diagnostics remain offline, needs-review, or unresolved.'],
      warnings: ['Observation forwards full raw source content or exceeds declared resource bounds.'],
      next_actions: ['Keep unresolved checks visibly unresolved; rerun source verification before claiming verified.'],
      provenance: {
        source: 'runtime_router.behavior_eval_pack',
        read_only: true,
        record_written: false,
      },
      cases: [],
      run_record: {},
    });
    mockedGetWorkflowReplayIndex.mockResolvedValue({
      schema_version: 'scholar_ai_workflow_replay_index_v1',
      generated_at: '2026-06-21T01:00:01Z',
      scope: {},
      total_jobs_scanned: 0,
      total_receipts_seen: 0,
      matching_job_count: 0,
      returned_count: 0,
      items: [],
      blockers: [],
      unresolved: [],
      resume_probes: [],
      summary: {
        has_replay_evidence: false,
        index_is_read_only: true,
        requires_exact_job_id: false,
      },
      provenance: {},
    });
    mockedGetAgentHandoffCard.mockRejectedValue(new Error('handoff not found'));
    mockedGetWorkflowReplayLineage.mockRejectedValue(new Error('lineage not found'));
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
      workspace_state: workspaceStateFixture({
        artifact_root: {
          label: 'agent_mcp_workflows',
          path: 'workspace_artifacts/agent_mcp_workflows',
          exists: true,
          file_count: 1,
          total_bytes: 512,
          truncated: false,
        },
        output_root: {
          label: 'generated_output',
          path: 'workspace_artifacts/generated/output',
          exists: true,
          file_count: 3,
          total_bytes: 2048,
          truncated: true,
        },
        git: {
          available: true,
          branch: 'main',
          ahead: 33,
          behind: 0,
          changed_count: 2,
          staged_count: 0,
          unstaged_count: 1,
          untracked_count: 1,
          conflicted_count: 0,
          dirty_paths: ['literature_assistant/core/routers/agent_workspace_router.py', 'docs/plans/local-goal-state.json'],
          error: null,
        },
      }),
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

  it('filters open requirements before truncation and selects a matching drilldown', async () => {
    const openRequirements = [
      'N56-alpha-ready',
      'N56-beta-ready',
      'N56-gamma-ready',
      'N56-delta-ready',
      'N56-epsilon-ready',
      'N56-zeta-risk-filter-target',
    ].map((id, index) => ({
      id,
      status: index === 5 ? 'incomplete' : 'proved',
      requirement: index === 5
        ? 'Filterable requirement remains selectable after the visible list is narrowed.'
        : `Stable requirement row ${index + 1}`,
      residual_risk: index === 5 ? 'zeta evidence must remain reachable after filtering.' : null,
    }));

    mockedGetAgentWorkspaceStatus.mockResolvedValue({
      artifact_root: 'workspace_artifacts/agent_mcp_workflows',
      artifact_count: 0,
      audit_count: 0,
      total_artifact_bytes: 0,
      latest_activity_at: null,
      workspace_state: workspaceStateFixture({
        goal_state: {
          ...workspaceStateFixture().goal_state,
          requirement_count: 54,
          proved_count: 52,
          incomplete_count: 1,
          out_of_scope_count: 1,
          latest_requirement_id: 'N56-open-requirement-filtering',
          requirement_status: {
            total: 54,
            proved: 52,
            incomplete: 1,
            out_of_scope: 1,
            latest_id: 'N56-open-requirement-filtering',
          },
          open_requirements: openRequirements,
        },
      }),
      artifacts: [],
      audit_records: [],
    });
    mockedGetAgentWorkspaceRequirement.mockImplementation(async (requirementId: string) => ({
      schema_version: 'scholar_ai_goal_requirement_drilldown_v1',
      available: true,
      read_only: true,
      path: 'docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json',
      updated_at: '2026-06-23T02:20:00+08:00',
      checkpoint_id: '20260623-020320-n56-agent-workspace-open-requirement-filtering-p',
      id: requirementId,
      status: requirementId.includes('zeta') ? 'incomplete' : 'proved',
      requirement: requirementId.includes('zeta')
        ? 'Filterable requirement remains selectable after the visible list is narrowed.'
        : 'Stable requirement row',
      residual_risk: requirementId.includes('zeta') ? 'zeta evidence must remain reachable after filtering.' : null,
      evidence: [
        {
          label: 'frontend/src/pages/AgentWorkspace.test.tsx',
          text: `drilldown loaded for ${requirementId}`,
        },
      ],
      evidence_count: 1,
      truncated: false,
      next_safe_local_actions: ['Keep requirement recovery read-only.'],
      stop_boundaries: ['No external mutation.'],
      error: null,
    }));

    render(<AgentWorkspace />);

    const workspaceStateRegion = await screen.findByRole('region', { name: 'Workspace state visibility' });
    expect(within(workspaceStateRegion).getByText('open requirements 6')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('requirements shown 5 / total 6')).toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByRole('button', {
      name: /N56-zeta-risk-filter-target/,
    })).not.toBeInTheDocument();

    fireEvent.change(within(workspaceStateRegion).getByLabelText('Filter open requirements'), {
      target: { value: 'zeta' },
    });

    expect(within(workspaceStateRegion).getByText('requirement matches 1 / total 6')).toBeInTheDocument();
    const filteredRequirement = within(workspaceStateRegion).getByRole('button', {
      name: /N56-zeta-risk-filter-target/,
    });
    expect(filteredRequirement).toBeInTheDocument();
    expect(filteredRequirement).not.toHaveAttribute('aria-current');

    fireEvent.click(filteredRequirement);

    await waitFor(() => {
      expect(mockedGetAgentWorkspaceRequirement).toHaveBeenLastCalledWith('N56-zeta-risk-filter-target');
    });
    expect(filteredRequirement).toHaveAttribute('aria-current', 'true');
    const requirementDrilldownRegion = within(workspaceStateRegion).getByRole('region', { name: 'Requirement evidence drilldown' });
    expect(within(requirementDrilldownRegion).getByText('N56-zeta-risk-filter-target · incomplete')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('frontend/src/pages/AgentWorkspace.test.tsx · drilldown loaded for N56-zeta-risk-filter-target')).toBeInTheDocument();
  });

  it('renders workflow passport, integrity gate, handoff card, and behavior eval visibility', async () => {
    const blockingBoundary: BlockingActionBoundaryProjection = {
      schema_version: 'scholar_ai_blocking_action_boundary_v1',
      action_id: 'writing.export_project',
      required_claim_id: 'export_readiness',
      status: 'blocked',
      can_proceed: false,
      require_ready: true,
      refresh_required: false,
      blocked_claims: [
        {
          claim_id: 'export_readiness',
          label: 'Export readiness',
          status: 'blocked',
          reason: 'Unsupported citation anchors block export readiness.',
          blocker_count: 1,
          unresolved_count: 1,
        },
      ],
      blockers: ['Unsupported citation anchors block export readiness.'],
      unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
      blocked_signal_refs: [
        {
          signal_id: 'citation_verification:unsupported:1',
          category: 'citation_verification',
          status: 'block',
          severity: 'block',
          message: 'Unsupported citation anchors block export readiness.',
          blocks_claims: true,
        },
        {
          signal_id: 'behavior_eval:unsafe-handoff-claim',
          category: 'behavior_eval',
          status: 'block',
          severity: 'block',
          message: 'Behavior Eval Pack found blocking MCP/agent workflow red flags.',
          blocks_claims: true,
          replay_ref_count: 1,
        },
      ],
      unresolved_signal_refs: [
        {
          signal_id: 'retrieval_quality:missing_qrels_status:1',
          category: 'retrieval_quality',
          status: 'unresolved',
          severity: 'note',
          message: 'Evidence refs exist, but retrieval qrels status is not recorded.',
          blocks_claims: false,
          replay_ref_count: 1,
        },
      ],
      recovery_drilldowns: [
        {
          signal_id: 'citation_verification:unsupported:1',
          category: 'citation_verification',
          status: 'block',
          severity: 'block',
          message: 'Unsupported citation anchors block export readiness.',
          linked_stage_id: 'citation_review',
          source_ref: {
            source_id: 'C:\\Users\\Alice\\private\\paper.pdf',
            source_kind: 'citation_verification',
            source_digest: 'sha256:citation-fixture',
            raw_path_exposed: false,
          },
          checked_facts: {
            citation_id: 'cite:unsupported',
            verification_status: 'unsupported',
            stage_id: 'citation_review',
          },
          evidence_refs: [
            { ref_type: 'citation_verification', ref_id: 'cite:unsupported' },
            { ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1' },
          ],
          replay_refs: [
            { ref_type: 'preflight_refresh_receipt', ref_id: 'preflight_refresh:test123' },
          ],
          recovery_refs: [
            { ref_type: 'workflow_passport_stage', ref_id: 'citation_review' },
            { ref_type: 'evidence_integrity_signal', ref_id: 'citation_verification:unsupported:1' },
            { ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1' },
          ],
          local_read_only_probes: [
            { label: 'Read Evidence Integrity Gate', read_only: true },
            { label: 'Read workflow replay lineage', read_only: true },
          ],
          next_safe_local_actions: ['Run citation source verification before retrying export.'],
          requires_human_review: false,
          blocks_claims: true,
          read_only: true,
          raw_path_exposed: false,
        },
        {
          signal_id: 'retrieval_quality:missing_qrels_status:1',
          category: 'retrieval_quality',
          status: 'unresolved',
          severity: 'note',
          message: 'Evidence refs exist, but retrieval qrels status is not recorded.',
          linked_stage_id: 'evidence_pack',
          source_ref: {
            source_id: 'qrels_status:fixture',
            source_kind: 'qrels_status',
            source_digest: 'sha256:qrels-fixture',
            raw_path_exposed: false,
          },
          checked_facts: {
            evidence_ref_count: 2,
            qrels_status: 'missing',
            stage_id: 'evidence_pack',
          },
          evidence_refs: [{ ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1' }],
          replay_refs: [{ ref_type: 'workflow_replay_probe', ref_id: 'qrels_status:replay:1' }],
          recovery_refs: [
            { ref_type: 'workflow_passport_stage', ref_id: 'evidence_pack' },
            { ref_type: 'evidence_integrity_signal', ref_id: 'retrieval_quality:missing_qrels_status:1' },
          ],
          local_read_only_probes: [{ label: 'Refresh boundary signal drilldown', read_only: true }],
          next_safe_local_actions: ['Record qrels_status before retrying export.'],
          requires_human_review: true,
          blocks_claims: false,
          read_only: true,
          raw_path_exposed: false,
        },
        {
          signal_id: 'behavior_eval:unsafe-handoff-claim',
          category: 'behavior_eval',
          status: 'block',
          severity: 'block',
          message: 'Behavior Eval Pack found blocking MCP/agent workflow red flags.',
          linked_stage_id: 'agent_handoff',
          source_ref: {
            source_id: 'behavior_eval_runs\\observation-red-flags.json',
            source_kind: 'behavior_eval_pack',
            source_digest: 'sha256:behavior-eval-fixture',
            raw_path_exposed: false,
          },
          checked_facts: {
            mode: 'observations',
            behavior_status: 'block',
            red_flag_count: 1,
            block_count: 1,
            stage_id: 'agent_handoff',
          },
          evidence_refs: [
            { ref_type: 'behavior_eval_pack', ref_id: 'behavior_eval_runs/observation-red-flags.json' },
            { ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1' },
          ],
          replay_refs: [
            { ref_type: 'behavior_eval_pack', ref_id: 'behavior_eval_runs/observation-red-flags.json' },
          ],
          recovery_refs: [
            { ref_type: 'workflow_passport_stage', ref_id: 'agent_handoff' },
            { ref_type: 'evidence_integrity_signal', ref_id: 'behavior_eval:unsafe-handoff-claim' },
          ],
          local_read_only_probes: [
            { label: 'Read behavior eval run record', read_only: true },
            { label: 'Read Evidence Integrity Gate', read_only: true },
          ],
          next_safe_local_actions: ['Review behavior-eval findings before making export, handoff, or external-action claims.'],
          requires_human_review: false,
          blocks_claims: true,
          read_only: true,
          raw_path_exposed: false,
        },
      ],
      evidence_refs: [{ ref_type: 'evidence_integrity_signal', ref_id: 'citation_verification:unsupported:1' }],
      local_read_only_probes: [
        {
          label: 'Read Workflow Passport',
          url: '/runtime/workflow-passport',
          method: 'GET',
          read_only: true,
        },
        {
          label: 'Read Evidence Integrity Gate',
          url: '/runtime/evidence-integrity-gate',
          method: 'GET',
          read_only: true,
        },
        {
          label: 'Read runtime job action preflight metadata',
          url: '/runtime/job/job_agent_handoff_1',
          method: 'GET',
          read_only: true,
        },
        {
          label: 'Read research action lifecycle',
          endpoint: '/runtime/research-action-lifecycle',
          method: 'GET',
          read_only: true,
        },
      ],
      next_safe_local_actions: ['Resolve blocker: Unsupported citation anchors block export readiness.'],
      forbidden_actions: [
        'Do not execute the blocked action until the required readiness claim is ready and fresh.',
        'Do not treat unresolved integrity checks as passed or verified.',
        'Do not mutate C:\\Users\\Alice\\private\\paper.pdf from a boundary.',
      ],
      provenance: { derived_from: ['runtime.evidence_integrity_gate', 'runtime.action_preflight'] },
    };
    const blockedActionPreflight: WorkflowActionPreflightProjection = {
      schema_version: 'scholar_ai_action_preflight_v1',
      generated_at: '2026-06-21T03:00:00Z',
      action_id: 'writing.export_project',
      required_claim_id: 'export_readiness',
      require_ready: true,
      status: 'blocked',
      can_proceed: false,
      claim_status: 'blocked',
      gate_status: 'block',
      current_stage_id: 'citation_review',
      freshness: {
        schema_version: 'scholar_ai_action_preflight_freshness_v1',
        status: 'fresh',
        refresh_required: false,
        max_age_seconds: 900,
        age_seconds: 0,
        oldest_evidence_at: '2026-06-21T03:00:00Z',
        newest_evidence_at: '2026-06-21T03:00:00Z',
        expires_at: '2026-06-21T03:15:00Z',
        checked_at: '2026-06-21T03:00:00Z',
        reasons: ['Action preflight evidence is within the freshness window.'],
        refresh_actions: [],
        sources: [],
      },
      refresh_required: false,
      refresh_receipt_id: 'preflight_refresh:test123',
      refresh_receipt: {
        schema_version: 'scholar_ai_preflight_refresh_receipt_v1',
        receipt_id: 'preflight_refresh:test123',
        generated_at: '2026-06-21T03:00:01Z',
        action_id: 'writing.export_project',
        required_claim_id: 'export_readiness',
        scope: { project_id: 'project-1', job_id: 'job_agent_handoff_1' },
        status: 'blocked',
        can_proceed: false,
        refresh_required: false,
        projection_digests: {
          workflow_passport: 'sha256:passport',
          evidence_integrity_gate: 'sha256:gate',
          workflow_readiness_claims: 'sha256:claims',
          action_preflight: 'sha256:preflight',
        },
        projection_refs: [{ ref_type: 'workflow_passport' }, { ref_type: 'evidence_integrity_gate' }],
        freshness: { status: 'fresh' },
        validation: { gate_status: 'block', claim_status: 'blocked', blocker_count: 1, unresolved_count: 1 },
        replay: { external_mutation: false, source_material_mutation: false },
        provenance: { derived_from: ['runtime.action_preflight'] },
      },
      blockers: ['Unsupported citation anchors block export readiness.'],
      unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
      evidence: [{ ref_type: 'evidence_integrity_signal', ref_id: 'citation_verification:unsupported:1' }],
      blocking_action_boundary: blockingBoundary,
      summary: {
        hard_blocked: true,
        unresolved_is_ready: false,
        readiness_ok: false,
        workflow_state_phase: 'export_failed',
      },
      provenance: {
        derived_from: [
          'runtime.workflow_passport',
          'runtime.evidence_integrity_gate',
          'runtime.workflow_readiness_claims',
        ],
      },
    };
    mockedGetAgentWorkspaceStatus.mockResolvedValue({
      artifact_root: 'workspace_artifacts/agent_mcp_workflows',
      artifact_count: 1,
      audit_count: 0,
      total_artifact_bytes: 256,
      latest_activity_at: '2026-06-21T03:00:00.000Z',
      workspace_state: workspaceStateFixture({
        artifact_root: {
          label: 'agent_mcp_workflows',
          path: 'workspace_artifacts/agent_mcp_workflows',
          exists: true,
          file_count: 1,
          total_bytes: 256,
          truncated: false,
        },
        git: {
          available: true,
          branch: 'main',
          ahead: 33,
          behind: 0,
          changed_count: 2,
          staged_count: 0,
          unstaged_count: 1,
          untracked_count: 1,
          conflicted_count: 0,
          dirty_paths: ['literature_assistant/core/routers/agent_workspace_router.py', 'docs/plans/local-goal-state.json'],
          error: null,
        },
      }),
      artifacts: [
        {
          path: 'behavior_eval_runs/behavior-eval-20260621.json',
          name: 'behavior-eval-20260621.json',
          kind: 'json',
          size_bytes: 256,
          modified_at: '2026-06-21T03:00:00.000Z',
          preview: '{"schema_version":"scholar_ai_behavior_eval_pack_v1"}',
          truncated: false,
        },
      ],
      audit_records: [],
    });
    mockedListRuntimeJobs.mockResolvedValue({
      recent: [
        {
          job_id: 'job_agent_handoff_1',
          session_id: 'session_agent_handoff_1',
          kind: 'agent_request',
          status: 'in_progress',
          input_text: '单篇精读：证据链检查',
          created_at: '2026-06-21T03:00:00.000Z',
          started_at: '2026-06-21T03:00:01.000Z',
          completed_at: null,
          action_id: null,
          skill_id: null,
          tags: [],
          metadata: { intent: 'single_paper_deep_read', agent_host: 'codex', action_preflight: blockedActionPreflight },
          writing_workflow_state_summary: { phase: 'evidence_pack' },
        },
      ],
    });
    mockedGetWorkflowPassport.mockResolvedValue({
      schema_version: 'scholar_ai_workflow_passport_v1',
      generated_at: '2026-06-21T03:00:00Z',
      scope: { project_id: 'project-1' },
      current_stage_id: 'evidence_pack',
      gate_summary: {
        gate_counts: { pass: 1, unresolved: 1, block: 1 },
        severity_counts: { none: 1, warn: 1, block: 1 },
        blocking_stage_ids: ['citation_review'],
        unresolved_stage_ids: ['evidence_pack'],
        requires_user_confirmation: true,
      },
      provenance: { derived_from: ['runtime.research_projection'] },
      stages: [
        {
          stage_id: 'material_ingest',
          label: 'Material ingest',
          status: 'complete',
          required_artifacts: ['material_processing_task'],
          present_artifacts: [{ kind: 'material_processing_task' }],
          object_ids: ['research_material:1'],
          event_types: ['material.ingest.completed'],
          diagnostics: {},
          reproducibility: {
            cache_decision_record_count: 1,
            research_action_refs: [
              {
                ref_type: 'research_action_lifecycle',
                ref_id: 'wiki_candidate:job_agent_handoff_1',
                action_id: 'agent.wiki_candidate',
                action_type: 'wiki_candidate',
                status: 'pending_approval',
                stage_id: 'agent_handoff',
                job_id: 'job_agent_handoff_1',
                session_id: 'session_agent_handoff_1',
                project_id: 'project-1',
                requires_user_confirmation: true,
                preflight_present: true,
                latest_receipt_id: 'preflight_refresh:test123',
                probe_endpoint: '/runtime/research-action-lifecycle',
                read_only: true,
              },
            ],
            cache_decision_refs: [
              {
                ref_type: 'material_processing_cache_decision',
                ref_id: 'material-cache-decision:fixture-hit',
                decision: 'hit',
                policy: 'use',
                replayable: true,
                reason: 'Existing artifacts matched C:\\Users\\Alice\\private\\paper.pdf cache.',
                artifact_family_digest: 'sha256:artifact-family-fixture',
                has_all_requested_outputs: true,
              },
            ],
          },
          next_actions: [],
          updated_at: '2026-06-21T03:00:00Z',
          gate: {
            gate_id: 'material_ingest.gate',
            status: 'pass',
            severity: 'none',
            reason: 'Required runtime evidence is present for this stage.',
            evidence: [{ ref_type: 'research_object', ref_id: 'research_material:1' }],
            blockers: [],
            unresolved: [],
            requires_user_confirmation: false,
          },
        },
        {
          stage_id: 'evidence_pack',
          label: 'Evidence pack',
          status: 'in_progress',
          required_artifacts: ['evidence_pack', 'qrels_status'],
          present_artifacts: [{ kind: 'evidence_pack' }],
          object_ids: ['evidence_pack:1'],
          event_types: ['evidence.pack.created'],
          ...emptyWorkflowStageRuntimeFacts,
          next_actions: ['Record qrels_status before making retrieval-quality claims.'],
          updated_at: '2026-06-21T03:01:00Z',
          gate: {
            gate_id: 'evidence_pack.gate',
            status: 'unresolved',
            severity: 'warn',
            reason: 'Stage is in progress and still needs completion evidence.',
            evidence: [{ ref_type: 'research_object', ref_id: 'evidence_pack:1' }],
            blockers: [],
            unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
            requires_user_confirmation: false,
          },
        },
        {
          stage_id: 'citation_review',
          label: 'Citation review',
          status: 'blocked',
          required_artifacts: ['citation_bank'],
          present_artifacts: [],
          object_ids: [],
          event_types: ['approval.required'],
          ...emptyWorkflowStageRuntimeFacts,
          next_actions: ['Resolve unsupported citation anchors before export.'],
          updated_at: '2026-06-21T03:02:00Z',
          gate: {
            gate_id: 'citation_review.gate',
            status: 'block',
            severity: 'block',
            reason: 'Unsupported citation anchors block export readiness.',
            evidence: [{ ref_type: 'research_event_type', ref_id: 'approval.required' }],
            blockers: ['Unsupported citation anchors block export readiness.'],
            unresolved: [],
            requires_user_confirmation: true,
          },
        },
        {
          stage_id: 'agent_handoff',
          label: 'Agent handoff',
          status: 'blocked',
          required_artifacts: ['agent_handoff_card'],
          present_artifacts: [],
          object_ids: [],
          event_types: ['agent.handoff.blocked'],
          ...emptyWorkflowStageRuntimeFacts,
          next_actions: ['Review behavior-eval findings before handoff.'],
          updated_at: '2026-06-21T03:03:00Z',
          gate: {
            gate_id: 'agent_handoff.gate',
            status: 'block',
            severity: 'block',
            reason: 'Behavior Eval Pack found blocking MCP/agent workflow red flags.',
            evidence: [{ ref_type: 'evidence_integrity_signal', ref_id: 'behavior_eval:unsafe-handoff-claim' }],
            blockers: ['Behavior Eval Pack found blocking MCP/agent workflow red flags.'],
            unresolved: [],
            requires_user_confirmation: false,
          },
        },
      ],
    });
    mockedGetEvidenceIntegrityGate.mockResolvedValue({
      schema_version: 'scholar_ai_evidence_integrity_gate_v1',
      generated_at: '2026-06-21T03:00:00Z',
      scope: { project_id: 'project-1' },
      status: 'block',
      signals: [
        {
          signal_id: 'workflow_stage:citation_review',
          category: 'workflow_stage',
          status: 'block',
          severity: 'block',
          message: 'Citation review stage is blocked by unsupported anchors.',
          evidence: [{ ref_type: 'workflow_passport_stage', ref_id: 'citation_review' }],
          next_actions: ['Open the linked integrity signal before export.'],
          metadata: { stage_id: 'citation_review' },
          drilldown: integrityDrilldownFixture(
            'workflow_passport_stage',
            { stage_id: 'citation_review', gate_status: 'block', requires_user_confirmation: true },
            {
              status: 'block',
              evidenceRefs: [{ ref_type: 'workflow_passport_stage', ref_id: 'citation_review' }],
              replayCount: 1,
            },
          ),
        },
        {
          signal_id: 'citation_verification:unsupported:1',
          category: 'citation_verification',
          status: 'block',
          severity: 'block',
          message: 'Unsupported citation anchors block export readiness.',
          evidence: [{ ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1' }],
          next_actions: ['Run citation verification and attach locator evidence.'],
          metadata: { unsupported_count: 1 },
          drilldown: integrityDrilldownFixture(
            'citation_verification',
            { unsupported_count: 1, citation_id: 'cite:unsupported' },
            { status: 'block' },
          ),
        },
        {
          signal_id: 'retrieval_quality:missing_qrels_status:1',
          category: 'retrieval_quality',
          status: 'unresolved',
          severity: 'note',
          message: 'Evidence refs exist, but retrieval qrels status is not recorded.',
          evidence: [{ ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1' }],
          next_actions: ['Record qrels_status before making retrieval-quality claims.'],
          metadata: { evidence_ref_count: 2 },
          drilldown: integrityDrilldownFixture(
            'qrels_status',
            { evidence_ref_count: 2, qrels_status: 'missing' },
            { status: 'unresolved', replayCount: 1 },
          ),
        },
        {
          signal_id: 'locator:runtime_payload:invalid-bbox',
          category: 'locator',
          status: 'warn',
          severity: 'warn',
          message: 'Evidence refs include invalid bbox locators and need repair before strong claims.',
          evidence: [{ ref_type: 'locator_coverage', ref_id: 'runtime_payload:invalid-bbox' }],
          next_actions: ['Repair invalid bbox locators before relying on layout-specific evidence claims.'],
          metadata: {
            coverage_state: 'page_located',
            risk_level: 'warn',
            total_refs: 1,
            project_ref_count: 1,
            bbox_locator_count: 0,
            invalid_bbox_count: 1,
            sample_invalid_bbox_ref_ids: ['chunk:invalid-bbox'],
            bbox: [-25, 0, 10, 10],
            source_path: 'C:\\Users\\Alice\\private\\paper.pdf',
          },
          drilldown: integrityDrilldownFixture(
            'locator_coverage',
            {
              schema_version: 'scholar-ai-evidence-locator-coverage/v1',
              coverage_state: 'page_located',
              risk_level: 'warn',
              total_refs: 1,
              project_ref_count: 1,
              page_locator_count: 1,
              bbox_locator_count: 0,
              invalid_bbox_count: 1,
              sample_invalid_bbox_ref_ids: ['chunk:invalid-bbox'],
              bbox: [-25, 0, 10, 10],
              source_path: 'C:\\Users\\Alice\\private\\paper.pdf',
            },
            {
              status: 'unresolved',
              evidenceRefs: [{ ref_type: 'locator_coverage', ref_id: 'runtime_payload:invalid-bbox' }],
            },
          ),
        },
        {
          signal_id: 'behavior_eval:unsafe-handoff-claim',
          category: 'behavior_eval',
          status: 'block',
          severity: 'block',
          message: 'Behavior Eval Pack found blocking MCP/agent workflow red flags.',
          evidence: [
            { ref_type: 'behavior_eval_pack', ref_id: 'behavior_eval_runs/observation-red-flags.json' },
            { ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1' },
          ],
          next_actions: ['Review behavior-eval findings before making export, handoff, or external-action claims.'],
          metadata: {
            mode: 'observations',
            behavior_status: 'block',
            red_flag_count: 1,
          },
          drilldown: integrityDrilldownFixture(
            'behavior_eval_pack',
            {
              mode: 'observations',
              behavior_status: 'block',
              red_flag_count: 1,
              block_count: 1,
              stage_id: 'agent_handoff',
            },
            {
              status: 'block',
              evidenceRefs: [
                { ref_type: 'behavior_eval_pack', ref_id: 'behavior_eval_runs/observation-red-flags.json' },
                { ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1' },
              ],
              replayRefs: [
                { ref_type: 'behavior_eval_pack', ref_id: 'behavior_eval_runs/observation-red-flags.json' },
              ],
            },
          ),
        },
      ],
      summary: {
        signal_count: 5,
        status_counts: { block: 3, unresolved: 1 },
        severity_counts: { block: 3, warn: 1, note: 1 },
        unresolved_is_pass: false,
        research_action_count: 2,
        research_action_refs: [
          {
            ref_type: 'research_action_lifecycle',
            ref_id: 'agent_handoff:job_agent_handoff_1',
            action_id: 'agent.handoff_card',
            action_type: 'agent_handoff',
            status: 'blocked',
            stage_id: 'agent_handoff',
            job_id: 'job_agent_handoff_1',
            session_id: 'session_agent_handoff_1',
            project_id: 'project-1',
            requires_user_confirmation: false,
            preflight_present: true,
            latest_receipt_id: 'preflight_refresh:test123',
            probe_endpoint: '/runtime/research-action-lifecycle',
            read_only: true,
          },
        ],
      },
      blockers: [
        'Unsupported citation anchors block export readiness.',
        'Behavior Eval Pack found blocking MCP/agent workflow red flags.',
      ],
      unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
      enforcement: {
        schema_version: 'scholar_ai_workflow_enforcement_v1',
        status: 'blocked',
        claims: [
          {
            claim_id: 'export_readiness',
            label: 'Export readiness',
            status: 'blocked',
            reason: 'Unsupported citation anchors block export readiness.',
            required_readiness: ['has_export_manifest'],
            missing_readiness: [],
            source_gate_status: 'block',
            blockers: ['Unsupported citation anchors block export readiness.'],
            unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
            evidence: [{ ref_type: 'evidence_integrity_signal', ref_id: 'citation_verification:unsupported:1' }],
          },
          {
            claim_id: 'handoff_readiness',
            label: 'Agent handoff readiness',
            status: 'unresolved',
            reason: 'Evidence refs exist, but retrieval qrels status is not recorded.',
            required_readiness: [],
            missing_readiness: [],
            source_gate_status: 'block',
            blockers: [],
            unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
            evidence: [{ ref_type: 'evidence_integrity_signal', ref_id: 'retrieval_quality:missing_qrels_status:1' }],
          },
        ],
        summary: {
          ready: 0,
          warning: 0,
          unresolved: 1,
          blocked: 1,
          unresolved_is_ready: false,
          blocking_action_boundary_status: 'blocked',
        },
        blocking_action_boundary: blockingBoundary,
        provenance: { derived_from: ['runtime.evidence_integrity_gate'] },
      },
      blocking_action_boundary: blockingBoundary,
      provenance: {
        derived_from: ['runtime.workflow_passport', 'runtime.research_action_lifecycle_refs'],
        research_action_lifecycle_schema_version: 'scholar_ai_research_action_lifecycle_v1',
      },
    });
    mockedGetResearchActionLifecycle.mockResolvedValue({
      schema_version: 'scholar_ai_research_action_lifecycle_v1',
      generated_at: '2026-06-21T03:00:04Z',
      scope: { project_id: 'project-1', limit: 50 },
      actions: [
        {
          action_uid: 'wiki_candidate:job_agent_handoff_1',
          action_id: 'agent.wiki_candidate',
          action_type: 'wiki_candidate',
          status: 'pending_approval',
          project_id: 'project-1',
          session_id: 'session_agent_handoff_1',
          job_id: 'job_agent_handoff_1',
          object_refs: [
            { ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1', object_type: 'agent_request' },
            { ref_type: 'research_object', ref_id: 'research_agent_request:job_agent_handoff_1' },
          ],
          approval: {
            requires_user_confirmation: true,
            status_counts: { pending: 1 },
            approval_refs: [
              {
                approval_id: 'approval:wiki-graph',
                status: 'pending',
                reason: 'Confirm wiki and graph candidates before any write.',
              },
            ],
          },
          preflight: {
            present: true,
            action_id: 'agent.wiki_candidate',
            required_claim_id: 'handoff_readiness',
            status: 'blocked',
            can_proceed: false,
            refresh_required: false,
            receipt_refs: [
              {
                ref_type: 'preflight_refresh_receipt',
                ref_id: 'preflight_refresh:test123',
                job_id: 'job_agent_handoff_1',
                status: 'blocked',
                can_proceed: false,
              },
            ],
          },
          gate_refs: [
            {
              ref_type: 'workflow_passport',
              schema_version: 'scholar_ai_workflow_passport_v1',
              current_stage_id: 'evidence_pack',
            },
            {
              ref_type: 'evidence_integrity_gate',
              schema_version: 'scholar_ai_evidence_integrity_gate_v1',
              status: 'block',
            },
          ],
          effect_summary: {
            proposed_effect_count: 2,
            actual_effect_count: 0,
            external_mutation: false,
            source_material_mutation: false,
            requires_user_confirmation: true,
          },
          effect_refs: [
            { ref_type: 'wiki_ref', ref_id: 'wiki:candidate/action-life', title: 'Candidate Wiki' },
            { ref_type: 'runtime_artifact', ref_id: 'artifact:agent-result' },
          ],
          recovery: {
            read_only: true,
            resume_probes: [
              {
                label: 'Read research action lifecycle',
                endpoint: '/runtime/research-action-lifecycle',
                read_only: true,
              },
              {
                label: 'Read workflow passport',
                endpoint: '/runtime/workflow-passport',
                read_only: true,
              },
            ],
            next_safe_local_actions: ['Resolve blocker: Pending user confirmation is required.'],
          },
          forbidden_actions: [
            'Do not execute approvals or write wiki/graph changes from the lifecycle projection.',
            'Do not mutate C:\\Users\\Alice\\private\\paper.pdf from a lifecycle projection.',
          ],
          provenance: {
            derived_from: ['runtime.jobs', 'runtime.approval_requests'],
            read_only: true,
          },
        },
        {
          action_uid: 'approval_gate:approval:wiki-graph',
          action_id: 'agent.approval_gate',
          action_type: 'approval_gate',
          status: 'pending_approval',
          project_id: 'project-1',
          session_id: 'session_agent_handoff_1',
          job_id: 'job_agent_handoff_1',
          object_refs: [{ ref_type: 'research_object', ref_id: 'approval_gate:approval:wiki-graph' }],
          approval: {
            requires_user_confirmation: true,
            status_counts: { pending: 1 },
            approval_refs: [{ approval_id: 'approval:wiki-graph', status: 'pending' }],
          },
          preflight: {
            present: false,
            status: 'not_applicable',
            can_proceed: false,
            refresh_required: false,
            receipt_refs: [],
          },
          gate_refs: [],
          effect_summary: {
            responded: false,
            requires_user_confirmation: true,
            external_mutation: false,
            source_material_mutation: false,
          },
          effect_refs: [],
          recovery: {
            read_only: true,
            resume_probes: [
              {
                label: 'Read runtime snapshot',
                endpoint: '/runtime/job/job_agent_handoff_1/snapshot',
                read_only: true,
              },
            ],
            next_safe_local_actions: ['Resolve blocker: Pending user confirmation is required.'],
          },
          forbidden_actions: [
            'Do not execute approvals or write wiki/graph changes from the lifecycle projection.',
          ],
          provenance: { derived_from: ['runtime.approval_requests'], read_only: true },
        },
      ],
      summary: {
        action_count: 2,
        matching_action_count: 2,
        matching_job_count: 1,
        status_counts: { pending_approval: 2, blocked: 0, unresolved: 0, completed: 0 },
        action_type_counts: { wiki_candidate: 1, approval_gate: 1 },
        requires_user_confirmation: true,
        read_only: true,
        external_mutation: false,
        source_material_mutation: false,
      },
      blockers: ['Pending user confirmation is required.'],
      unresolved: [],
      resume_probes: [
        {
          label: 'Read research action lifecycle',
          endpoint: '/runtime/research-action-lifecycle',
          read_only: true,
        },
        {
          label: 'Read evidence integrity gate',
          endpoint: '/runtime/evidence-integrity-gate',
          read_only: true,
        },
      ],
      provenance: { derived_from: ['runtime.jobs'], read_only: true },
    });
    mockedGetAgentHandoffCard.mockResolvedValue({
      schema_version: 'scholar_ai_agent_handoff_card_v1',
      generated_at: '2026-06-21T03:00:00Z',
      request_id: 'agent_request_1',
      job_id: 'job_agent_handoff_1',
      session_id: 'session_agent_handoff_1',
      project_id: 'project-1',
      status: 'in_progress',
      agent_host: 'codex',
      intent: 'single_paper_deep_read',
      current_stage_id: 'evidence_pack',
      completed_evidence: [{ ref_type: 'runtime_job', ref_id: 'job_agent_handoff_1' }],
      blockers: [],
      unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
      action_preflight: blockedActionPreflight,
      readiness_claims: {
        schema_version: 'scholar_ai_workflow_enforcement_v1',
        status: 'unresolved',
        claims: [
          {
            claim_id: 'handoff_readiness',
            label: 'Agent handoff readiness',
            status: 'unresolved',
            reason: 'Evidence refs exist, but retrieval qrels status is not recorded.',
            required_readiness: [],
            missing_readiness: [],
            source_gate_status: 'unresolved',
            blockers: [],
            unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
            evidence: [{ ref_type: 'evidence_integrity_signal', ref_id: 'retrieval_quality:missing_qrels_status:1' }],
          },
        ],
        summary: {
          ready: 0,
          warning: 0,
          unresolved: 1,
          blocked: 0,
          unresolved_is_ready: false,
        },
        provenance: { derived_from: ['runtime.agent_handoff_card'] },
      },
      replay_recovery: {
        schema_version: 'scholar_ai_agent_handoff_replay_recovery_v1',
        current_receipt: {
          receipt_id: 'preflight_refresh:test123',
          status: 'blocked',
          can_proceed: false,
          refresh_required: false,
        },
        lineage: {
          schema_version: 'scholar_ai_workflow_replay_lineage_v1',
          receipt_count: 2,
          latest_receipt_id: 'preflight_refresh:test123',
          latest_status: 'blocked',
          latest_blocker_count: 1,
          latest_unresolved_count: 1,
          lineage_is_read_only: true,
        },
        index: {
          schema_version: 'scholar_ai_workflow_replay_index_v1',
          matching_job_count: 2,
          returned_count: 2,
          blocked_job_count: 1,
          unresolved_job_count: 1,
          stale_job_count: 0,
          index_is_read_only: true,
          requires_exact_job_id: false,
        },
        highest_priority_attempt: {
          job_id: 'job_agent_handoff_1',
          latest_status: 'blocked',
          latest_required_claim_id: 'handoff_readiness',
          latest_receipt_id: 'preflight_refresh:test123',
          recovery_priority: 160,
          read_only: true,
        },
        resume_probes: [{ label: 'Read workflow replay lineage', read_only: true }],
        recovery_required: true,
        read_only: true,
        source_material_mutation: false,
        external_mutation: false,
      },
      action_lifecycle_recovery: {
        schema_version: 'scholar_ai_handoff_action_lifecycle_recovery_v1',
        read_only: true,
        action_ref_count: 1,
        scoped_action_ref_count: 2,
        blocked_action_count: 1,
        pending_confirmation_count: 1,
        missing_preflight_count: 0,
        action_refs: [
          {
            ref_type: 'research_action_lifecycle',
            ref_id: 'agent_handoff:job_agent_handoff_1',
            action_id: 'agent.handoff_card',
            action_type: 'agent_handoff',
            status: 'blocked',
            stage_id: 'agent_handoff',
            job_id: 'job_agent_handoff_1',
            session_id: 'session_agent_handoff_1',
            project_id: 'project-1',
            requires_user_confirmation: true,
            preflight_present: true,
            latest_receipt_id: 'preflight_refresh:test123',
            probe_endpoint: '/runtime/research-action-lifecycle',
            read_only: true,
          },
        ],
        resume_probes: [
          {
            label: 'Read research action lifecycle',
            endpoint: '/runtime/research-action-lifecycle',
            read_only: true,
          },
        ],
        forbidden_actions: [
          'Do not execute approvals from the handoff action-lifecycle recovery bundle.',
          'Do not import wiki candidates, upload externally, or mutate C:\\Users\\Alice\\private\\paper.pdf from this read-only projection.',
        ],
        provenance: {
          derived_from: ['runtime.research_action_lifecycle_refs'],
          research_action_lifecycle_schema_version: 'scholar_ai_research_action_lifecycle_v1',
        },
      },
      resource_refs: [
        { ref_id: 'material:1', kind: 'material' },
        { ref_id: 'C:\\Users\\Alice\\private\\paper.pdf', kind: 'source_path' },
      ],
      artifacts: [],
      resume_probes: [
        { label: 'Read workflow passport' },
        { label: 'Read evidence integrity gate' },
        { label: 'Inspect local file C:\\Users\\Alice\\private\\paper.pdf before mutation' },
      ],
      forbidden_actions: [
        'Do not treat unresolved integrity checks as passed or verified.',
        'Do not mutate C:\\Users\\Alice\\private\\paper.pdf from a handoff card.',
      ],
      resume_prompt: 'Read /runtime/workflow-passport before mutating local files.',
      provenance: { derived_from: ['runtime.job'] },
    });
    mockedGetWorkflowReplayLineage.mockResolvedValue({
      schema_version: 'scholar_ai_workflow_replay_lineage_v1',
      generated_at: '2026-06-21T03:00:02Z',
      job_id: 'job_agent_handoff_1',
      session_id: 'session_agent_handoff_1',
      project_id: 'project-1',
      scope: { project_id: 'project-1', job_id: 'job_agent_handoff_1' },
      receipt_count: 2,
      returned_count: 2,
      latest_receipt_id: 'preflight_refresh:test123',
      latest: {
        receipt_id: 'preflight_refresh:test123',
        status: 'blocked',
        blocker_count: 1,
        unresolved_count: 1,
      },
      previous: {
        receipt_id: 'preflight_refresh:older',
        status: 'unresolved',
        blocker_count: 0,
        unresolved_count: 1,
      },
      items: [
        {
          ordinal: 1,
          receipt_id: 'preflight_refresh:older',
          generated_at: '2026-06-21T02:55:00Z',
          action_id: 'writing.export_project',
          required_claim_id: 'export_readiness',
          status: 'unresolved',
          can_proceed: false,
          refresh_required: false,
          blocker_count: 0,
          unresolved_count: 1,
          digest_keys: ['workflow_passport'],
          projection_digests: { workflow_passport: 'sha256:old-passport' },
          external_mutation: false,
          source_material_mutation: false,
        },
        {
          ordinal: 2,
          receipt_id: 'preflight_refresh:test123',
          generated_at: '2026-06-21T03:00:01Z',
          action_id: 'writing.export_project',
          required_claim_id: 'export_readiness',
          status: 'blocked',
          can_proceed: false,
          refresh_required: false,
          blocker_count: 1,
          unresolved_count: 1,
          digest_keys: ['workflow_passport', 'evidence_integrity_gate'],
          projection_digests: {
            workflow_passport: 'sha256:passport',
            evidence_integrity_gate: 'sha256:gate',
          },
          external_mutation: false,
          source_material_mutation: false,
        },
      ],
      comparison: {
        status_changed: true,
        blocker_count_delta: 1,
        unresolved_count_delta: 0,
        changed_digest_keys: ['evidence_integrity_gate'],
      },
      blockers: ['Latest replay receipt reports 1 blocking checks.'],
      unresolved: ['Latest replay receipt reports 1 unresolved checks.'],
      resume_probes: [{ label: 'Read workflow replay lineage' }],
      summary: {
        has_receipts: true,
        latest_status: 'blocked',
        latest_blocker_count: 1,
        latest_unresolved_count: 1,
        lineage_is_read_only: true,
      },
      provenance: { derived_from: ['runtime.artifacts.preflight_refresh_receipt'] },
    });
    mockedGetWorkflowReplayIndex.mockResolvedValue({
      schema_version: 'scholar_ai_workflow_replay_index_v1',
      generated_at: '2026-06-21T03:00:03Z',
      scope: { limit: 25 },
      total_jobs_scanned: 2,
      total_receipts_seen: 3,
      matching_job_count: 2,
      returned_count: 2,
      items: [
        {
          ordinal: 1,
          job_id: 'job_agent_handoff_1',
          session_id: 'session_agent_handoff_1',
          project_id: 'project-1',
          job_kind: 'agent_request',
          job_status: 'in_progress',
          session_title: 'Agent handoff',
          receipt_count: 2,
          latest_receipt_id: 'preflight_refresh:test123',
          latest_generated_at: '2026-06-21T03:00:01Z',
          latest_status: 'blocked',
          latest_action_id: 'writing.export_project',
          latest_required_claim_id: 'export_readiness',
          latest_can_proceed: false,
          latest_refresh_required: false,
          latest_blocker_count: 1,
          latest_unresolved_count: 1,
          changed_digest_keys: ['evidence_integrity_gate'],
          comparison: { blocker_count_delta: 1 },
          recovery_priority: 160,
          metadata_receipt_count: 2,
          artifact_receipt_count: 2,
          resume_probes: [{ label: 'Read workflow replay lineage' }],
          read_only: true,
        },
      ],
      blockers: ['Job job_agent_handoff_1 latest replay receipt reports 1 blocking checks.'],
      unresolved: ['Job job_agent_handoff_1 latest replay receipt reports 1 unresolved checks.'],
      resume_probes: [{ label: 'List workflow replay index' }],
      summary: {
        has_replay_evidence: true,
        blocked_job_count: 1,
        unresolved_job_count: 1,
        stale_job_count: 0,
        ready_job_count: 0,
        index_is_read_only: true,
        requires_exact_job_id: false,
      },
      provenance: { derived_from: ['runtime.jobs'] },
    });

    render(<AgentWorkspace />);

    expect(await screen.findByRole('region', { name: '研究流程主干' })).toBeInTheDocument();
    expect(await screen.findByText('Material Cache Decisions')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '研究流程' })).toBeInTheDocument();
    expect(screen.getByText('Workflow Passport')).toBeInTheDocument();
    expect(screen.getByText('Evidence Integrity Gate')).toBeInTheDocument();
    expect(screen.getByText('Readiness Claims')).toBeInTheDocument();
    expect(screen.getByText('Command Preflight')).toBeInTheDocument();
    expect(screen.getByText('Research Action Lifecycle')).toBeInTheDocument();
    expect(screen.getByText('Replay Lineage')).toBeInTheDocument();
    expect(screen.getByText('Replay Index')).toBeInTheDocument();
    expect(screen.getByText('Behavior Eval Pack')).toBeInTheDocument();
    expect(screen.getAllByText('Agent Handoff').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Evidence pack').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Export readiness').length).toBeGreaterThan(0);
    expect(screen.getByText('Agent handoff readiness')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Material cache decision records' })).toBeInTheDocument();
    expect(screen.getByText('cache decisions 1')).toBeInTheDocument();
    expect(screen.getByText('material-cache-decision:fixture-hit')).toBeInTheDocument();
    expect(screen.getByText('hit · use · replayable true · outputs true')).toBeInTheDocument();
    expect(screen.getByText('sha256:artifact-family-fixture')).toBeInTheDocument();
    expect(screen.getByText('Existing artifacts matched [redacted-local-path] cache.')).toBeInTheDocument();
    expect(screen.getAllByText('can proceed false').length).toBeGreaterThan(0);
    expect(screen.getAllByText('require ready true').length).toBeGreaterThan(0);
    expect(screen.getAllByText('writing.export_project').length).toBeGreaterThan(0);
    expect(screen.getAllByText('receipt preflight_refresh:test123').length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(mockedGetAgentHandoffCard).toHaveBeenCalledWith('job_agent_handoff_1');
      expect(mockedGetWorkflowReplayLineage).toHaveBeenCalledWith('job_agent_handoff_1', { limit: 12 });
    });
    const crosslinkRegion = screen.getByRole('region', { name: 'Research action crosslinks' });
    expect(within(crosslinkRegion).getByText('Research Action Crosslinks')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('crosslinks 4')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('lifecycle read-only true')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('passport refs 1')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('gate refs 1')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('handoff refs 1')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('boundary probes 1')).toBeInTheDocument();
    expect(within(crosslinkRegion).getAllByText('runtime.research_action_lifecycle_refs').length).toBeGreaterThan(0);
    expect(within(crosslinkRegion).getByText('wiki_candidate:job_agent_handoff_1 · wiki_candidate · pending_approval · agent_handoff · read-only true')).toBeInTheDocument();
    expect(within(crosslinkRegion).getAllByText('agent_handoff:job_agent_handoff_1 · agent_handoff · blocked · agent_handoff · read-only true').length).toBeGreaterThan(1);
    expect(within(crosslinkRegion).getByText('Read research action lifecycle · read-only true')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('handoff action refs 1')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('scoped action refs 2')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('blocked actions 1')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('pending confirmations 1')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('missing preflight 0')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('Do not execute approvals from the handoff action-lifecycle recovery bundle.')).toBeInTheDocument();
    expect(within(crosslinkRegion).getByText('Do not import wiki candidates, upload externally, or mutate [redacted-local-path] from this read-only projection.')).toBeInTheDocument();
    const lifecycleRegion = screen.getByRole('region', { name: 'Research action lifecycle' });
    expect(within(lifecycleRegion).getByText('Research Action Lifecycle')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('2 actions · pending 2 · block 0 · unresolved 0 · completed 0')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('pending approval 2')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('blocked actions 0')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('confirmation true')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('read-only true')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('agent.wiki_candidate')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('wiki_candidate:job_agent_handoff_1')).toBeInTheDocument();
    expect(within(lifecycleRegion).getAllByText('pending_approval').length).toBeGreaterThan(0);
    expect(within(lifecycleRegion).getAllByText('confirmation true · pending 1 · approved 0 · rejected 0').length).toBeGreaterThan(0);
    expect(within(lifecycleRegion).getByText('blocked · can proceed false · refresh false · receipts 1')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('external mutation false · source mutation false · proposed 2')).toBeInTheDocument();
    expect(within(lifecycleRegion).getAllByText('recovery read-only true').length).toBeGreaterThan(0);
    expect(within(lifecycleRegion).getByText('forbidden 2')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('runtime_job:job_agent_handoff_1')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('wiki_ref:wiki:candidate/action-life')).toBeInTheDocument();
    expect(within(lifecycleRegion).getByText('Read research action lifecycle · read-only true')).toBeInTheDocument();
    expect(within(lifecycleRegion).getAllByText('Resolve blocker: Pending user confirmation is required.').length).toBeGreaterThan(0);
    expect(within(lifecycleRegion).getAllByText('Do not execute approvals or write wiki/graph changes from the lifecycle projection.').length).toBeGreaterThan(0);
    expect(within(lifecycleRegion).getByText('Do not mutate [redacted-local-path] from a lifecycle projection.')).toBeInTheDocument();
    expect(screen.getByText('preflight_refresh:test123 · digests 4 · block 1 · unresolved 1')).toBeInTheDocument();
    expect(await screen.findByText('2 receipts · latest blocked · block 1 · unresolved 1')).toBeInTheDocument();
    expect(screen.getByText('Latest replay receipt reports 1 blocking checks.')).toBeInTheDocument();
    expect(screen.getByText('2 jobs · block 1 · unresolved 1 · stale 0')).toBeInTheDocument();
    expect(screen.getByText('Job job_agent_handoff_1 latest replay receipt reports 1 blocking checks.')).toBeInTheDocument();
    expect(screen.getAllByText('preflight_refresh:test123').length).toBeGreaterThan(0);
    expect(screen.getAllByText('preflight blocked').length).toBeGreaterThan(0);
    expect(screen.getAllByText('fresh 0s').length).toBeGreaterThan(0);
    const boundaryRegion = screen.getByRole('region', { name: 'Blocking action boundary' });
    expect(within(boundaryRegion).getByText('Blocking Action Boundary')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('boundary can proceed false')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('boundary require ready true')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('boundary refresh false')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('blocked signals 2')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('unresolved signals 1')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('recovery drilldowns 3')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('claim export_readiness')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('citation_verification:unsupported:1 · block')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('behavior_eval:unsafe-handoff-claim · block')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('retrieval_quality:missing_qrels_status:1 · unresolved')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Recovery Drilldowns')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('citation_verification:unsupported:1')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Citation review · citation_verification')).toBeInTheDocument();
    expect(within(boundaryRegion).getAllByText('facts 3').length).toBeGreaterThan(0);
    expect(within(boundaryRegion).getAllByText('evidence 2').length).toBeGreaterThan(0);
    expect(within(boundaryRegion).getAllByText('replay 1').length).toBeGreaterThan(0);
    expect(within(boundaryRegion).getAllByText('safe probes 2').length).toBeGreaterThan(1);
    expect(within(boundaryRegion).getAllByText('blocks claims true').length).toBeGreaterThan(1);
    expect(within(boundaryRegion).getAllByText('human review false').length).toBeGreaterThan(1);
    expect(within(boundaryRegion).getAllByText('read-only true').length).toBeGreaterThan(0);
    expect(within(boundaryRegion).getByText('Run citation source verification before retrying export.')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Evidence pack · qrels_status')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Record qrels_status before retrying export.')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Agent handoff · behavior_eval_pack')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Review behavior-eval findings before making export, handoff, or external-action claims.')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Read Workflow Passport · read-only true')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Read Evidence Integrity Gate · read-only true')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Read runtime job action preflight metadata · read-only true')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Do not execute the blocked action until the required readiness claim is ready and fresh.')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Do not mutate [redacted-local-path] from a boundary.')).toBeInTheDocument();
    expect(screen.queryByText('C:\\Users\\Alice\\private\\paper.pdf')).not.toBeInTheDocument();
    expect(screen.getAllByText('Unsupported citation anchors block export readiness.').length).toBeGreaterThan(0);
    expect(screen.getAllByText('unresolved 1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('blocked').length).toBeGreaterThan(0);
    expect(screen.getAllByText('behavior eval canary ok').length).toBeGreaterThan(0);
    expect(screen.getByText('behavior gate 1')).toBeInTheDocument();
    const behaviorGateRegion = screen.getByRole('region', { name: 'Behavior eval gate signals' });
    expect(within(behaviorGateRegion).getByText('Behavior Gate Signals')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('blocking')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('1 behavior_eval signals · block 1 · unresolved 0 · recovery 1')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('behavior block 1')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('behavior unresolved 0')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('behavior recovery 1')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('observation-mode gate')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('pack mode canary')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('behavior_eval:unsafe-handoff-claim')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('evidence type behavior_eval_pack')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('severity block')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('evidence 2')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('next actions 1')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('Behavior Recovery Drilldowns')).toBeInTheDocument();
    expect(within(behaviorGateRegion).getByText('behavior_eval:unsafe-handoff-claim · Agent handoff · safe probes 2')).toBeInTheDocument();
    expect(screen.getByText('Canary mode passes when every unsafe canary is detected.')).toBeInTheDocument();
    expect(screen.getByText('canary · cases 8 · flags 8 · block 7 · warn 1')).toBeInTheDocument();
    expect(screen.getAllByText('Integrity Drilldown Inspector').length).toBeGreaterThan(0);
    expect(screen.getAllByText('integrity links 1').length).toBeGreaterThan(0);
    expect(screen.getByText('linked stage Citation review')).toBeInTheDocument();
    expect(screen.getByText('raw path redacted')).toBeInTheDocument();
    expect(screen.getAllByText('workflow_stage:citation_review').length).toBeGreaterThan(1);
    expect(screen.getByText('workflow_passport_stage:citation_review')).toBeInTheDocument();
    expect(screen.getByText('workflow_replay_probe:workflow_passport_stage:replay:1')).toBeInTheDocument();
    expect(screen.getByText('Open the linked integrity signal before export.')).toBeInTheDocument();
    const locatorQualityRegion = screen.getByRole('region', { name: 'Locator quality repair signals' });
    expect(within(locatorQualityRegion).getByText('Locator Quality Repair')).toBeInTheDocument();
    expect(within(locatorQualityRegion).getByText('locator risks 1')).toBeInTheDocument();
    expect(within(locatorQualityRegion).getByText('invalid bbox 1')).toBeInTheDocument();
    expect(within(locatorQualityRegion).getByText('bbox locators 0')).toBeInTheDocument();
    expect(within(locatorQualityRegion).getByText('coverage page_located')).toBeInTheDocument();
    expect(within(locatorQualityRegion).getByText('chunk:invalid-bbox')).toBeInTheDocument();
    expect(within(locatorQualityRegion).getByText('Repair invalid bbox locators before relying on layout-specific evidence claims.')).toBeInTheDocument();
    fireEvent.click(within(locatorQualityRegion).getByRole('button', { name: 'Inspect locator signal locator:runtime_payload:invalid-bbox' }));
    expect(screen.getByText('locator:runtime_payload:invalid-bbox')).toBeInTheDocument();
    expect(screen.getByText('locator_coverage')).toBeInTheDocument();
    expect(screen.queryByText('[-25,0,10,10]')).not.toBeInTheDocument();
    expect(screen.queryByText('[-25, 0, 10, 10]')).not.toBeInTheDocument();
    expect(screen.queryByText('C:\\Users\\Alice\\private\\paper.pdf')).not.toBeInTheDocument();
    expect(screen.getByText('structural pass')).toBeInTheDocument();
    expect(screen.getByText('read-only true · record not written')).toBeInTheDocument();
    expect(screen.getAllByText('artifacts 1').length).toBeGreaterThan(0);
    expect(screen.getByText('behavior-eval-20260621.json')).toBeInTheDocument();
    const workspaceStateRegion = screen.getByRole('region', { name: 'Workspace state visibility' });
    expect(within(workspaceStateRegion).getByText('Workspace State')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('workspace ready')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getAllByText('read-only true').length).toBeGreaterThan(1);
    expect(within(workspaceStateRegion).getByText('main · changed 2 · staged 0 · unstaged 1 · untracked 1')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('ahead 33')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('artifacts ready · files 1 · 256 B')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('runtime ready · files 2 · 128 B')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal-state 49 rows · proved 47 · incomplete 1 · out-of-scope 1 · latest N41-goal-state-workspace-visibility')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal-state visible')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('requirement status visible')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('open requirements 1')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Open Requirements')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('B01-computer-use-accessibility-tree · incomplete · Computer Use accessibility-tree acceptance is blocked by sandboxPolicy. · risk Retry only after the external tool error is fixed.')).toBeInTheDocument();
    const requirementDrilldownRegion = within(workspaceStateRegion).getByRole('region', { name: 'Requirement evidence drilldown' });
    expect(within(requirementDrilldownRegion).getByText('Requirement Evidence')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('drilldown visible')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('read-only true')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('evidence 1')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('B01-computer-use-accessibility-tree · incomplete')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('requirement Computer Use accessibility-tree acceptance is blocked by sandboxPolicy.')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('risk Retry only after the external tool error is fixed.')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('tests/test_agent_workspace_router.py · router contract covers redacted requirement drilldown')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('next Create a rollback checkpoint and search mature references before edits.')).toBeInTheDocument();
    expect(within(requirementDrilldownRegion).getByText('boundary No push, tag, release, deploy, or external upload.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('full goal status visible')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('slice completion N41 made goal-state recovery visible.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('full goal The full Scholar AI workflow spine remains active, not complete.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('checkpoint 20260622-214730-n41-goal-state-record-update')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json')).toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText(/C:\\Users\\/)).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText(/restore_command/)).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('literature_assistant/core/routers/agent_workspace_router.py')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('docs/plans/local-goal-state.json')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Workflow Passport · read-only true · literature.workflow_passport')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Research Action Lifecycle · read-only true · literature.research_action_lifecycle')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Agent Handoff Card · read-only true · needs job_id · literature.agent_handoff_card')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Create a rollback checkpoint and re-check official or mature references before nontrivial edits.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText('/runtime/workflow-passport')).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText('/runtime/job/{job_id}/agent-handoff-card')).not.toBeInTheDocument();
    expect(mockedGetAgentWorkspaceRequirement).toHaveBeenCalledWith('B01-computer-use-accessibility-tree');
    expect(mockedGetBehaviorEvalPack).toHaveBeenCalledWith({ includeCases: true });
    expect(mockedGetResearchActionLifecycle).toHaveBeenCalledWith({ limit: 50 });
    expect(await screen.findByText('in_progress · refs 2 · probes 3 · replay 2')).toBeInTheDocument();
    expect(screen.getByText('preflight_refresh:test123 · job_agent_handoff_1 blocked · index 2 · read-only true')).toBeInTheDocument();
    const handoffRecoveryRegion = screen.getByRole('region', { name: 'Agent handoff recovery bundle' });
    expect(handoffRecoveryRegion).toBeInTheDocument();
    expect(within(handoffRecoveryRegion).getByText('Agent Handoff Recovery Bundle')).toBeInTheDocument();
    expect(screen.getByText('recovery required')).toBeInTheDocument();
    expect(screen.getAllByText('read-only true').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Evidence pack').length).toBeGreaterThan(0);
    expect(screen.getAllByText('receipt preflight_refresh:test123').length).toBeGreaterThan(0);
    expect(screen.getByText('claim handoff_readiness')).toBeInTheDocument();
    expect(screen.getByText('priority 160')).toBeInTheDocument();
    expect(screen.getByText('job_agent_handoff_1 · blocked')).toBeInTheDocument();
    expect(screen.getByText('material:1')).toBeInTheDocument();
    expect(screen.getByText('source_path:[redacted-local-path]')).toBeInTheDocument();
    expect(screen.getByText('source mutation false · external mutation false')).toBeInTheDocument();
    expect(screen.getByText('safe probes 3')).toBeInTheDocument();
    expect(screen.getByText('replay probes 1')).toBeInTheDocument();
    expect(screen.getByText('Read workflow passport')).toBeInTheDocument();
    expect(screen.getByText('Read evidence integrity gate')).toBeInTheDocument();
    expect(screen.getByText('Read workflow replay lineage')).toBeInTheDocument();
    expect(screen.getByText('Inspect local file [redacted-local-path] before mutation')).toBeInTheDocument();
    expect(within(handoffRecoveryRegion).getByText('Do not treat unresolved integrity checks as passed or verified.')).toBeInTheDocument();
    expect(within(handoffRecoveryRegion).getByText('Do not mutate [redacted-local-path] from a handoff card.')).toBeInTheDocument();
    expect(screen.queryByText(/C:\\Users\\Alice\\private\\paper\.pdf/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/runtime\/workflow-passport/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^integrity 通过$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Export readiness ready$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^preflight ready$/)).not.toBeInTheDocument();
  });

  it('renders stale action preflight as refresh-required command guardrail', async () => {
    const staleActionPreflight: WorkflowActionPreflightProjection = {
      schema_version: 'scholar_ai_action_preflight_v1',
      generated_at: '2026-06-21T03:30:01Z',
      action_id: 'writing.export_project',
      required_claim_id: 'export_readiness',
      require_ready: true,
      status: 'stale',
      can_proceed: false,
      claim_status: 'ready',
      gate_status: 'pass',
      current_stage_id: 'export',
      freshness: {
        schema_version: 'scholar_ai_action_preflight_freshness_v1',
        status: 'stale',
        refresh_required: true,
        max_age_seconds: 900,
        age_seconds: 1801,
        oldest_evidence_at: '2026-06-21T03:00:00Z',
        newest_evidence_at: '2026-06-21T03:00:00Z',
        expires_at: '2026-06-21T03:15:00Z',
        checked_at: '2026-06-21T03:30:01Z',
        reasons: ['Oldest preflight evidence is 1801 seconds old, exceeding 900 seconds.'],
        refresh_actions: ['Rebuild the Workflow Passport and Evidence Integrity Gate before executing this command.'],
        sources: [{ label: 'workflow_passport.generated_at', timestamp: '2026-06-21T03:00:00Z' }],
      },
      refresh_required: true,
      blockers: [],
      unresolved: ['Oldest preflight evidence is 1801 seconds old, exceeding 900 seconds.'],
      evidence: [{ ref_type: 'workflow_passport', current_stage_id: 'export' }],
      summary: {
        hard_blocked: true,
        unresolved_is_ready: false,
        readiness_ok: true,
        refresh_required: true,
        freshness_status: 'stale',
        workflow_state_phase: 'export_ready',
      },
      provenance: { derived_from: ['runtime.action_preflight'] },
    };
    mockedGetAgentWorkspaceStatus.mockResolvedValue({
      artifact_root: 'workspace_artifacts/agent_mcp_workflows',
      artifact_count: 0,
      audit_count: 0,
      total_artifact_bytes: 0,
      latest_activity_at: null,
      workspace_state: workspaceStateFixture(),
      artifacts: [],
      audit_records: [],
    });
    mockedListRuntimeJobs.mockResolvedValue({
      recent: [
        {
          job_id: 'job_stale_preflight',
          session_id: 'session_stale_preflight',
          kind: 'artifact_export',
          status: 'completed',
          input_text: 'export with stale preflight',
          created_at: '2026-06-21T03:00:00.000Z',
          started_at: '2026-06-21T03:00:01.000Z',
          completed_at: '2026-06-21T03:00:02.000Z',
          action_id: 'api.writing.export',
          skill_id: null,
          tags: ['writing_export'],
          metadata: { project_id: 'project-stale-preflight', action_preflight: staleActionPreflight },
          writing_workflow_state_summary: { phase: 'export_ready', action_preflight: staleActionPreflight },
        },
      ],
    });
    mockedGetWorkflowPassport.mockResolvedValue(null as unknown as Awaited<ReturnType<typeof getWorkflowPassport>>);
    mockedGetEvidenceIntegrityGate.mockResolvedValue(null as unknown as Awaited<ReturnType<typeof getEvidenceIntegrityGate>>);
    mockedGetWorkflowReplayIndex.mockResolvedValue(null as unknown as Awaited<ReturnType<typeof getWorkflowReplayIndex>>);
    mockedGetAgentHandoffCard.mockRejectedValue(new Error('handoff not found'));

    render(<AgentWorkspace />);

    expect(await screen.findByRole('region', { name: '研究流程主干' })).toBeInTheDocument();
    expect(screen.getAllByText('preflight stale').length).toBeGreaterThan(0);
    expect(screen.getAllByText('refresh required').length).toBeGreaterThan(0);
    expect(screen.getAllByText('stale 1801s').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Oldest preflight evidence is 1801 seconds old, exceeding 900 seconds.').length).toBeGreaterThan(0);
    expect(screen.queryByText(/^preflight ready$/)).not.toBeInTheDocument();
  });
});
