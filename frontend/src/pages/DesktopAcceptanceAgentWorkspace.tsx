import { TerminalSquare } from 'lucide-react';

import { PageHeader } from '@/components/common/PageHeader';
import { ReadinessPanel, ResearchWorkflowSpine, WorkspaceStatePanel } from './AgentWorkspace';
import type {
  AgentHandoffCardProjection,
  AgentBridgeStatus,
  AgentWorkflowHealthCheck,
  AgentWorkspaceStatus,
  BehaviorEvalPackProjection,
  BlockingActionBoundaryProjection,
  EvidenceIntegrityGateProjection,
  ResearchActionLifecycleProjection,
  RuntimeJobsStatus,
  WorkflowActionPreflightProjection,
  WorkflowPassportProjection,
  ZoteroAttachmentHealth,
} from '@/services/agentWorkspaceApi';
import type { WikiReviewListModel } from '@/types/wiki';
import type { WritingJob } from '@/types/runtime';

const EMPTY_WORKFLOW_STAGE_RUNTIME_FACTS = {
  diagnostics: {},
  reproducibility: {},
};

function integrityDrilldownFixture(
  sourceKind: string,
  checkedFacts: Record<string, unknown>,
  status: 'unresolved' | 'block',
): Record<string, unknown> {
  return {
    schema_version: 'scholar_ai_integrity_signal_drilldown_v1',
    status,
    source_ref: {
      source_id: `${sourceKind}:desktop-acceptance`,
      source_kind: sourceKind,
      source_digest: `sha256:${sourceKind}`,
      raw_path_exposed: false,
    },
    checked_facts: checkedFacts,
    evidence_refs: [{ ref_type: sourceKind, ref_id: `${sourceKind}:desktop-acceptance` }],
    replay_refs: [],
    requires_human_review: status === 'unresolved',
    blocks_claims: status === 'block',
  };
}

const ACCEPTANCE_WORKSPACE_STATE = {
  schema_version: 'scholar_ai_agent_workspace_state_v1',
  generated_at: '2026-06-21T04:00:00.000Z',
  workspace_ready: true,
  read_only: true,
  artifact_root: {
    label: 'agent_mcp_workflows',
    path: 'workspace_artifacts/agent_mcp_workflows',
    exists: true,
    file_count: 2,
    total_bytes: 4096,
    truncated: false,
  },
  runtime_state_root: {
    label: 'runtime_state',
    path: 'workspace_artifacts/runtime_state',
    exists: true,
    file_count: 3,
    total_bytes: 2048,
    truncated: false,
  },
  output_root: {
    label: 'generated_output',
    path: 'workspace_artifacts/generated/output',
    exists: true,
    file_count: 1,
    total_bytes: 1024,
    truncated: false,
  },
  git: {
    available: true,
    branch: 'main',
    ahead: 41,
    behind: 0,
    changed_count: 3,
    staged_count: 0,
    unstaged_count: 2,
    untracked_count: 1,
    conflicted_count: 0,
    dirty_paths: [
      'frontend/src/pages/DesktopAcceptanceAgentWorkspace.tsx',
      'frontend/src/pages/DesktopAcceptanceAgentWorkspace.test.tsx',
      'docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json',
    ],
    error: null,
  },
  goal_state: {
    available: true,
    path: 'docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json',
    updated_at: '2026-06-22T23:56:58+08:00',
    checkpoint_id: '20260622-235229-n48-requirement-evidence-closeout',
    requirement_count: 56,
    proved_count: 54,
    incomplete_count: 1,
    out_of_scope_count: 1,
    latest_requirement_id: 'N48-post-n47-requirement-evidence-closeout',
    completion_claim: {
      this_slice: 'N49 aligned the source desktop Agent Workspace acceptance fixture with N48 recovery state.',
      full_goal: 'The full Scholar AI research workflow spine goal remains active, not complete.',
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
    'Do not mutate Zotero databases or github/ reference repositories from Agent Workspace state.',
    'Create a rollback checkpoint and re-check official or mature references before nontrivial edits.',
  ],
  next_safe_local_actions: [
    'Read Workflow Passport, Evidence Integrity Gate, Research Action Lifecycle, and Agent Handoff Cards before resuming mutating work.',
    'Inspect git dirty paths and preserve unrelated local work before staging or committing.',
    'Use workspace artifacts and audit records as recovery evidence; treat missing evidence as unresolved.',
  ],
} satisfies AgentWorkspaceStatus['workspace_state'];

const ACCEPTANCE_WORKSPACE_STATUS: AgentWorkspaceStatus = {
  artifact_root: 'workspace_artifacts/agent_mcp_workflows',
  artifact_count: 2,
  audit_count: 1,
  total_artifact_bytes: 4096,
  latest_activity_at: '2026-06-21T04:00:00.000Z',
  workspace_state: ACCEPTANCE_WORKSPACE_STATE,
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

const ACCEPTANCE_BLOCKING_BOUNDARY: BlockingActionBoundaryProjection = {
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
      signal_id: 'citation_verification:unsupported:acceptance',
      category: 'citation_verification',
      status: 'block',
      severity: 'block',
      message: 'Unsupported citation anchors block export readiness.',
      blocks_claims: true,
    },
  ],
  unresolved_signal_refs: [
    {
      signal_id: 'retrieval_quality:missing_qrels_status:acceptance',
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
      signal_id: 'citation_verification:unsupported:acceptance',
      category: 'citation_verification',
      status: 'block',
      severity: 'block',
      message: 'Unsupported citation anchors block export readiness.',
      linked_stage_id: 'citation_review',
      source_ref: {
        source_id: 'citation_verification:desktop-acceptance',
        source_kind: 'citation_verification',
        source_digest: 'sha256:citation-verification-desktop-acceptance',
        raw_path_exposed: false,
      },
      checked_facts: {
        citation_id: 'cite:acceptance',
        verification_status: 'unsupported',
        stage_id: 'citation_review',
      },
      evidence_refs: [
        { ref_type: 'citation_verification', ref_id: 'cite:acceptance' },
        { ref_type: 'runtime_job', ref_id: 'job_export_acceptance' },
      ],
      replay_refs: [
        { ref_type: 'preflight_refresh_receipt', ref_id: 'preflight_refresh:desktop-acceptance' },
      ],
      recovery_refs: [
        { ref_type: 'workflow_passport_stage', ref_id: 'citation_review' },
        { ref_type: 'evidence_integrity_signal', ref_id: 'citation_verification:unsupported:acceptance' },
        { ref_type: 'runtime_job', ref_id: 'job_export_acceptance' },
      ],
      local_read_only_probes: [
        { label: 'Read Evidence Integrity Gate', read_only: true },
        { label: 'Read research action lifecycle', endpoint: '/runtime/research-action-lifecycle', read_only: true },
      ],
      next_safe_local_actions: ['Run citation verification and attach locator evidence.'],
      requires_human_review: false,
      blocks_claims: true,
      read_only: true,
      raw_path_exposed: false,
    },
  ],
  evidence_refs: [{ ref_type: 'evidence_integrity_signal', ref_id: 'citation_verification:unsupported:acceptance' }],
  local_read_only_probes: [
    { label: 'Read Workflow Passport', read_only: true },
    { label: 'Read Evidence Integrity Gate', read_only: true },
    { label: 'Read research action lifecycle', endpoint: '/runtime/research-action-lifecycle', read_only: true },
  ],
  next_safe_local_actions: ['Resolve unsupported citation anchors before export.'],
  forbidden_actions: [
    'Do not execute export overwrite while integrity checks are blocked.',
    'Do not mutate C:\\Users\\Alice\\private\\desktop-acceptance.pdf from a boundary.',
  ],
  provenance: {
    derived_from: ['runtime.evidence_integrity_gate', 'runtime.research_action_lifecycle_refs'],
    read_only: true,
  },
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
  blocking_action_boundary: ACCEPTANCE_BLOCKING_BOUNDARY,
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
      diagnostics: {},
      reproducibility: {
        research_action_refs: [
          {
            ref_type: 'research_action_lifecycle',
            ref_id: 'export_overwrite:job_export_acceptance',
            action_id: 'writing.export_project',
            action_type: 'export_overwrite',
            status: 'blocked',
            stage_id: 'citation_review',
            job_id: 'job_export_acceptance',
            session_id: 'session_export_acceptance',
            project_id: 'desktop-acceptance',
            requires_user_confirmation: true,
            preflight_present: true,
            latest_receipt_id: 'preflight_refresh:desktop-acceptance',
            probe_endpoint: '/runtime/research-action-lifecycle',
            read_only: true,
          },
        ],
      },
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
      ...EMPTY_WORKFLOW_STAGE_RUNTIME_FACTS,
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
      ...EMPTY_WORKFLOW_STAGE_RUNTIME_FACTS,
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
      drilldown: integrityDrilldownFixture(
        'citation_verification',
        { unsupported_count: 1, citation_id: 'cite:acceptance' },
        'block',
      ),
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
      drilldown: integrityDrilldownFixture(
        'qrels_status',
        { evidence_ref_count: 2, qrels_status: 'missing' },
        'unresolved',
      ),
    },
  ],
  summary: {
    signal_count: 2,
    status_counts: { block: 1, unresolved: 1 },
    severity_counts: { block: 1, note: 1 },
    unresolved_is_pass: false,
    research_action_count: 1,
    research_action_refs: [
      {
        ref_type: 'research_action_lifecycle',
        ref_id: 'export_overwrite:job_export_acceptance',
        action_id: 'writing.export_project',
        action_type: 'export_overwrite',
        status: 'blocked',
        stage_id: 'citation_review',
        job_id: 'job_export_acceptance',
        session_id: 'session_export_acceptance',
        project_id: 'desktop-acceptance',
        requires_user_confirmation: true,
        preflight_present: true,
        latest_receipt_id: 'preflight_refresh:desktop-acceptance',
        probe_endpoint: '/runtime/research-action-lifecycle',
        read_only: true,
      },
    ],
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
      blocking_action_boundary_status: 'blocked',
    },
    blocking_action_boundary: ACCEPTANCE_BLOCKING_BOUNDARY,
    provenance: { derived_from: ['runtime.evidence_integrity_gate'] },
  },
  blocking_action_boundary: ACCEPTANCE_BLOCKING_BOUNDARY,
  provenance: { derived_from: ['runtime.workflow_passport', 'runtime.jobs', 'runtime.research_action_lifecycle_refs'] },
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
  action_lifecycle_recovery: {
    schema_version: 'scholar_ai_handoff_action_lifecycle_recovery_v1',
    read_only: true,
    action_ref_count: 1,
    scoped_action_ref_count: 1,
    blocked_action_count: 1,
    pending_confirmation_count: 1,
    missing_preflight_count: 0,
    action_refs: [
      {
        ref_type: 'research_action_lifecycle',
        ref_id: 'export_overwrite:job_export_acceptance',
        action_id: 'writing.export_project',
        action_type: 'export_overwrite',
        status: 'blocked',
        stage_id: 'citation_review',
        job_id: 'job_export_acceptance',
        session_id: 'session_export_acceptance',
        project_id: 'desktop-acceptance',
        requires_user_confirmation: true,
        preflight_present: true,
        latest_receipt_id: 'preflight_refresh:desktop-acceptance',
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
      'Do not mutate C:\\Users\\Alice\\private\\desktop-acceptance.pdf from this read-only projection.',
    ],
    provenance: {
      derived_from: ['runtime.research_action_lifecycle_refs'],
      research_action_lifecycle_schema_version: 'scholar_ai_research_action_lifecycle_v1',
    },
  },
  resource_refs: [{ ref_id: 'material:acceptance', kind: 'material' }],
  artifacts: [],
  resume_probes: [{ label: 'Read workflow passport' }, { label: 'Read evidence integrity gate' }],
  forbidden_actions: ['Do not treat unresolved integrity checks as passed or verified.'],
  resume_prompt: 'Read current state before mutating local files.',
  provenance: { derived_from: ['runtime.job', 'runtime.workflow_passport'] },
};

const ACCEPTANCE_ACTION_LIFECYCLE: ResearchActionLifecycleProjection = {
  schema_version: 'scholar_ai_research_action_lifecycle_v1',
  generated_at: '2026-06-21T04:01:05.000Z',
  scope: { project_id: 'desktop-acceptance', limit: 50 },
  actions: [
    {
      action_uid: 'export_overwrite:job_export_acceptance',
      action_id: 'writing.export_project',
      action_type: 'export_overwrite',
      status: 'blocked',
      project_id: 'desktop-acceptance',
      session_id: 'session_export_acceptance',
      job_id: 'job_export_acceptance',
      object_refs: [
        { ref_type: 'runtime_job', ref_id: 'job_export_acceptance', object_type: 'artifact_export' },
        { ref_type: 'research_object', ref_id: 'research_export:job_export_acceptance' },
      ],
      approval: {
        requires_user_confirmation: true,
        status_counts: { pending: 1 },
        approval_refs: [{ approval_id: 'approval:desktop-export', status: 'pending' }],
      },
      preflight: { ...ACCEPTANCE_EXPORT_PREFLIGHT },
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
        proposed_effect_count: 1,
        actual_effect_count: 0,
        external_mutation: false,
        source_material_mutation: false,
        requires_user_confirmation: true,
      },
      effect_refs: [{ ref_type: 'runtime_artifact', ref_id: 'artifact:desktop-export-draft' }],
      recovery: {
        read_only: true,
        resume_probes: [
          {
            label: 'Read research action lifecycle',
            endpoint: '/runtime/research-action-lifecycle',
            read_only: true,
          },
          {
            label: 'Read action preflight',
            endpoint: '/runtime/workflow-action-preflight',
            read_only: true,
          },
        ],
        next_safe_local_actions: ['Resolve unsupported citation anchors before export.'],
      },
      forbidden_actions: ['Do not approve export overwrite while integrity checks are blocked.'],
      provenance: { derived_from: ['runtime.jobs', 'runtime.action_preflight'], read_only: true },
    },
  ],
  summary: {
    action_count: 1,
    matching_action_count: 1,
    matching_job_count: 1,
    status_counts: { blocked: 1, pending_approval: 0, unresolved: 0, completed: 0 },
    action_type_counts: { export_overwrite: 1 },
    requires_user_confirmation: true,
    read_only: true,
    external_mutation: false,
    source_material_mutation: false,
  },
  blockers: ['Unsupported citation anchors block export readiness.'],
  unresolved: [],
  resume_probes: [
    {
      label: 'Read research action lifecycle',
      endpoint: '/runtime/research-action-lifecycle',
      read_only: true,
    },
  ],
  provenance: { derived_from: ['runtime.jobs'], read_only: true },
};

const ACCEPTANCE_BEHAVIOR_EVAL_PACK: BehaviorEvalPackProjection = {
  schema_version: 'scholar_ai_behavior_eval_pack_v1',
  generated_at: '2026-06-21T04:00:00.000Z',
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
        <WorkspaceStatePanel workspaceStatus={ACCEPTANCE_WORKSPACE_STATUS} />
        <ResearchWorkflowSpine
          loading={false}
          passport={ACCEPTANCE_WORKFLOW_PASSPORT}
          integrityGate={ACCEPTANCE_INTEGRITY_GATE}
          actionLifecycle={ACCEPTANCE_ACTION_LIFECYCLE}
          handoffCard={ACCEPTANCE_HANDOFF_CARD}
          actionPreflight={ACCEPTANCE_EXPORT_PREFLIGHT}
          workflowReplayIndex={null}
          workflowReplayLineage={null}
          behaviorEvalPack={ACCEPTANCE_BEHAVIOR_EVAL_PACK}
          behaviorEvalArtifacts={[]}
          density="desktop-acceptance"
        />
      </div>
    </div>
  );
}

export default DesktopAcceptanceAgentWorkspace;
