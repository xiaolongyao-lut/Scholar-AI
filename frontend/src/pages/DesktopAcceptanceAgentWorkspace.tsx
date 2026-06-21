import { TerminalSquare } from 'lucide-react';

import { PageHeader } from '@/components/common/PageHeader';
import { ReadinessPanel, ResearchWorkflowSpine } from './AgentWorkspace';
import type {
  AgentHandoffCardProjection,
  AgentBridgeStatus,
  AgentWorkflowHealthCheck,
  AgentWorkspaceAuditRecord,
  AgentWorkspaceStatus,
  EvidenceIntegrityGateProjection,
  RuntimeJobsStatus,
  WorkflowActionPreflightProjection,
  WorkflowPassportProjection,
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

const ACCEPTANCE_EXPORT_PREFLIGHT: WorkflowActionPreflightProjection = {
  schema_version: 'scholar_ai_action_preflight_v1',
  generated_at: '2026-06-21T04:01:05.000Z',
  action_id: 'writing.export_project',
  required_claim_id: 'export_readiness',
  require_ready: true,
  status: 'blocked',
  can_proceed: false,
  claim_status: 'blocked',
  gate_status: 'block',
  current_stage_id: 'citation_review',
  blockers: ['Unsupported citation anchors block export readiness.'],
  unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
  evidence: [{ ref_type: 'evidence_integrity_signal', ref_id: 'citation_verification:unsupported:acceptance' }],
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
    metadata: { project_id: 'desktop-acceptance', action_preflight: ACCEPTANCE_EXPORT_PREFLIGHT },
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

const ACCEPTANCE_WORKFLOW_PASSPORT: WorkflowPassportProjection = {
  schema_version: 'scholar_ai_workflow_passport_v1',
  generated_at: '2026-06-21T04:00:00.000Z',
  scope: { project_id: 'desktop-acceptance' },
  current_stage_id: 'evidence_pack',
  gate_summary: {
    gate_counts: { pass: 1, unresolved: 2, block: 1 },
    severity_counts: { none: 1, warn: 2, block: 1 },
    blocking_stage_ids: ['citation_review'],
    unresolved_stage_ids: ['evidence_pack', 'draft'],
    requires_user_confirmation: true,
  },
  provenance: { derived_from: ['runtime.research_projection', 'runtime.jobs'] },
  stages: [
    {
      stage_id: 'material_ingest',
      label: 'Material ingest',
      status: 'complete',
      required_artifacts: ['material_processing_task', 'chunks', 'locators'],
      present_artifacts: [{ kind: 'material_processing_task' }],
      object_ids: ['research_material:acceptance'],
      event_types: ['material.ingest.completed'],
      next_actions: [],
      updated_at: '2026-06-21T04:00:00.000Z',
      gate: {
        gate_id: 'material_ingest.gate',
        status: 'pass',
        severity: 'none',
        reason: 'Required runtime evidence is present for this stage.',
        evidence: [{ ref_type: 'research_object', ref_id: 'research_material:acceptance' }],
        blockers: [],
        unresolved: [],
        requires_user_confirmation: false,
      },
    },
    {
      stage_id: 'evidence_pack',
      label: 'Evidence pack',
      status: 'in_progress',
      required_artifacts: ['evidence_pack', 'locator_coverage', 'qrels_status'],
      present_artifacts: [{ kind: 'evidence_pack' }],
      object_ids: ['evidence_pack:acceptance'],
      event_types: ['evidence.pack.created'],
      next_actions: ['Record qrels_status before making retrieval-quality claims.'],
      updated_at: '2026-06-21T04:01:00.000Z',
      gate: {
        gate_id: 'evidence_pack.gate',
        status: 'unresolved',
        severity: 'warn',
        reason: 'Stage is in progress and still needs completion evidence.',
        evidence: [{ ref_type: 'research_object', ref_id: 'evidence_pack:acceptance' }],
        blockers: [],
        unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
        requires_user_confirmation: false,
      },
    },
    {
      stage_id: 'citation_review',
      label: 'Citation review',
      status: 'blocked',
      required_artifacts: ['citation_bank', 'lint_report', 'integrity_gate'],
      present_artifacts: [],
      object_ids: [],
      event_types: ['approval.required'],
      next_actions: ['Resolve unsupported citation anchors before export.'],
      updated_at: '2026-06-21T04:02:00.000Z',
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
};

const ACCEPTANCE_INTEGRITY_GATE: EvidenceIntegrityGateProjection = {
  schema_version: 'scholar_ai_evidence_integrity_gate_v1',
  generated_at: '2026-06-21T04:00:00.000Z',
  scope: { project_id: 'desktop-acceptance' },
  status: 'block',
  signals: [
    {
      signal_id: 'citation_verification:unsupported:acceptance',
      category: 'citation_verification',
      status: 'block',
      severity: 'block',
      message: 'Unsupported citation anchors block export readiness.',
      evidence: [{ ref_type: 'runtime_job', ref_id: 'job_export_acceptance' }],
      next_actions: ['Run citation verification and attach locator evidence.'],
      metadata: { unsupported_count: 1 },
    },
    {
      signal_id: 'retrieval_quality:missing_qrels_status:acceptance',
      category: 'retrieval_quality',
      status: 'unresolved',
      severity: 'note',
      message: 'Evidence refs exist, but retrieval qrels status is not recorded.',
      evidence: [{ ref_type: 'runtime_job', ref_id: 'job_single_paper_acceptance' }],
      next_actions: ['Record qrels_status before making retrieval-quality claims.'],
      metadata: { evidence_ref_count: 2 },
    },
  ],
  summary: {
    signal_count: 2,
    status_counts: { block: 1, unresolved: 1 },
    severity_counts: { block: 1, note: 1 },
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
        evidence: [{ ref_type: 'evidence_integrity_signal', ref_id: 'citation_verification:unsupported:acceptance' }],
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
        evidence: [{ ref_type: 'evidence_integrity_signal', ref_id: 'retrieval_quality:missing_qrels_status:acceptance' }],
      },
    ],
    summary: {
      ready: 0,
      warning: 0,
      unresolved: 1,
      blocked: 1,
      unresolved_is_ready: false,
    },
    provenance: { derived_from: ['runtime.evidence_integrity_gate'] },
  },
  provenance: { derived_from: ['runtime.workflow_passport', 'runtime.jobs'] },
};

const ACCEPTANCE_HANDOFF_CARD: AgentHandoffCardProjection = {
  schema_version: 'scholar_ai_agent_handoff_card_v1',
  generated_at: '2026-06-21T04:00:00.000Z',
  request_id: 'agent_request_acceptance',
  job_id: 'job_single_paper_acceptance',
  session_id: 'session_single_paper_acceptance',
  project_id: 'desktop-acceptance',
  status: 'in_progress',
  agent_host: 'codex',
  intent: 'single_paper_deep_read',
  current_stage_id: 'evidence_pack',
  completed_evidence: [{ ref_type: 'runtime_job', ref_id: 'job_single_paper_acceptance' }],
  blockers: [],
  unresolved: ['Evidence refs exist, but retrieval qrels status is not recorded.'],
  action_preflight: ACCEPTANCE_EXPORT_PREFLIGHT,
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
        evidence: [{ ref_type: 'evidence_integrity_signal', ref_id: 'retrieval_quality:missing_qrels_status:acceptance' }],
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
  resource_refs: [{ ref_id: 'material:acceptance', kind: 'material' }],
  artifacts: [],
  resume_probes: [{ label: 'Read workflow passport' }, { label: 'Read evidence integrity gate' }],
  forbidden_actions: ['Do not treat unresolved integrity checks as passed or verified.'],
  resume_prompt: 'Read current state before mutating local files.',
  provenance: { derived_from: ['runtime.job', 'runtime.workflow_passport'] },
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
        <ResearchWorkflowSpine
          loading={false}
          passport={ACCEPTANCE_WORKFLOW_PASSPORT}
          integrityGate={ACCEPTANCE_INTEGRITY_GATE}
          handoffCard={ACCEPTANCE_HANDOFF_CARD}
          actionPreflight={ACCEPTANCE_EXPORT_PREFLIGHT}
          workflowReplayIndex={null}
          workflowReplayLineage={null}
          behaviorEvalArtifacts={[]}
          density="desktop-acceptance"
        />
      </div>
    </div>
  );
}

export default DesktopAcceptanceAgentWorkspace;
