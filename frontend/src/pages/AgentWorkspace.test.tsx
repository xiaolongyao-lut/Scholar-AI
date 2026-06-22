import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentWorkspace } from './AgentWorkspace';
import {
  getAgentBridgeStatus,
  getAgentHandoffCard,
  getAgentWorkflowHealth,
  getAgentWorkspaceStatus,
  getBehaviorEvalPack,
  getEvidenceIntegrityGate,
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
  getAgentBridgeStatus: vi.fn(),
  getAgentHandoffCard: vi.fn(),
  getAgentWorkflowHealth: vi.fn(),
  getBehaviorEvalPack: vi.fn(),
  getEvidenceIntegrityGate: vi.fn(),
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
const mockedGetAgentBridgeStatus = vi.mocked(getAgentBridgeStatus);
const mockedGetAgentHandoffCard = vi.mocked(getAgentHandoffCard);
const mockedGetAgentWorkflowHealth = vi.mocked(getAgentWorkflowHealth);
const mockedGetBehaviorEvalPack = vi.mocked(getBehaviorEvalPack);
const mockedGetEvidenceIntegrityGate = vi.mocked(getEvidenceIntegrityGate);
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
      ],
      summary: {
        signal_count: 3,
        status_counts: { block: 2, unresolved: 1 },
        severity_counts: { block: 2, note: 1 },
        unresolved_is_pass: false,
      },
      blockers: ['Unsupported citation anchors block export readiness.'],
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
      provenance: { derived_from: ['runtime.workflow_passport'] },
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
    expect(screen.getByRole('heading', { name: '研究流程' })).toBeInTheDocument();
    expect(screen.getByText('Workflow Passport')).toBeInTheDocument();
    expect(screen.getByText('Evidence Integrity Gate')).toBeInTheDocument();
    expect(screen.getByText('Readiness Claims')).toBeInTheDocument();
    expect(screen.getByText('Command Preflight')).toBeInTheDocument();
    expect(screen.getByText('Replay Lineage')).toBeInTheDocument();
    expect(screen.getByText('Replay Index')).toBeInTheDocument();
    expect(screen.getByText('Behavior Eval Pack')).toBeInTheDocument();
    expect(screen.getByText('Agent Handoff')).toBeInTheDocument();
    expect(screen.getAllByText('Evidence pack').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Export readiness').length).toBeGreaterThan(0);
    expect(screen.getByText('Agent handoff readiness')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Material cache decision records' })).toBeInTheDocument();
    expect(screen.getByText('Material Cache Decisions')).toBeInTheDocument();
    expect(screen.getByText('cache decisions 1')).toBeInTheDocument();
    expect(screen.getByText('material-cache-decision:fixture-hit')).toBeInTheDocument();
    expect(screen.getByText('hit · use · replayable true · outputs true')).toBeInTheDocument();
    expect(screen.getByText('sha256:artifact-family-fixture')).toBeInTheDocument();
    expect(screen.getByText('Existing artifacts matched [redacted-local-path] cache.')).toBeInTheDocument();
    expect(screen.getAllByText('can proceed false').length).toBeGreaterThan(0);
    expect(screen.getAllByText('require ready true').length).toBeGreaterThan(0);
    expect(screen.getAllByText('writing.export_project').length).toBeGreaterThan(0);
    expect(screen.getAllByText('receipt preflight_refresh:test123').length).toBeGreaterThan(0);
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
    expect(within(boundaryRegion).getByText('blocked signals 1')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('unresolved signals 1')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('recovery drilldowns 2')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('claim export_readiness')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('citation_verification:unsupported:1 · block')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('retrieval_quality:missing_qrels_status:1 · unresolved')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Recovery Drilldowns')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('citation_verification:unsupported:1')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Citation review · citation_verification')).toBeInTheDocument();
    expect(within(boundaryRegion).getAllByText('facts 3').length).toBeGreaterThan(0);
    expect(within(boundaryRegion).getAllByText('evidence 2').length).toBeGreaterThan(0);
    expect(within(boundaryRegion).getAllByText('replay 1').length).toBeGreaterThan(0);
    expect(within(boundaryRegion).getByText('safe probes 2')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('blocks claims true')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('human review false')).toBeInTheDocument();
    expect(within(boundaryRegion).getAllByText('read-only true').length).toBeGreaterThan(0);
    expect(within(boundaryRegion).getByText('Run citation source verification before retrying export.')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Evidence pack · qrels_status')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Record qrels_status before retrying export.')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Read Workflow Passport · read-only true')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Read Evidence Integrity Gate · read-only true')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Read runtime job action preflight metadata · read-only true')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Do not execute the blocked action until the required readiness claim is ready and fresh.')).toBeInTheDocument();
    expect(within(boundaryRegion).getByText('Do not mutate [redacted-local-path] from a boundary.')).toBeInTheDocument();
    expect(screen.queryByText('C:\\Users\\Alice\\private\\paper.pdf')).not.toBeInTheDocument();
    expect(screen.getAllByText('Unsupported citation anchors block export readiness.').length).toBeGreaterThan(0);
    expect(screen.getAllByText('unresolved 1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('blocked').length).toBeGreaterThan(0);
    expect(screen.getAllByText('behavior eval 阻断').length).toBeGreaterThan(0);
    expect(screen.getByText('canary · cases 8 · flags 8 · block 7 · warn 1')).toBeInTheDocument();
    expect(screen.getAllByText('Integrity Drilldown Inspector').length).toBeGreaterThan(0);
    expect(screen.getByText('integrity links 1')).toBeInTheDocument();
    expect(screen.getByText('linked stage Citation review')).toBeInTheDocument();
    expect(screen.getByText('raw path redacted')).toBeInTheDocument();
    expect(screen.getAllByText('workflow_stage:citation_review').length).toBeGreaterThan(1);
    expect(screen.getByText('workflow_passport_stage:citation_review')).toBeInTheDocument();
    expect(screen.getByText('workflow_replay_probe:workflow_passport_stage:replay:1')).toBeInTheDocument();
    expect(screen.getByText('Open the linked integrity signal before export.')).toBeInTheDocument();
    expect(screen.getByText('structural pass')).toBeInTheDocument();
    expect(screen.getByText('read-only true · record not written')).toBeInTheDocument();
    expect(screen.getAllByText('artifacts 1').length).toBeGreaterThan(0);
    expect(screen.getByText('behavior-eval-20260621.json')).toBeInTheDocument();
    await waitFor(() => {
      expect(mockedGetAgentHandoffCard).toHaveBeenCalledWith('job_agent_handoff_1');
      expect(mockedGetWorkflowReplayLineage).toHaveBeenCalledWith('job_agent_handoff_1', { limit: 12 });
    });
    expect(mockedGetBehaviorEvalPack).toHaveBeenCalledWith({ includeCases: true });
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
