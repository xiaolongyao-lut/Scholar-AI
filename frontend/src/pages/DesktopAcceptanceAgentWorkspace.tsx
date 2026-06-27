import { TerminalSquare } from 'lucide-react';

import { PageHeader } from '@/components/common/PageHeader';
import { ReadinessPanel, ResearchWorkflowSpine, WikiImportRecoveryPanel, WorkspaceStatePanel } from './AgentWorkspace';
import type {
  AgentHandoffCardProjection,
  AgentBridgeStatus,
  AgentWorkflowHealthCheck,
  AgentWorkspaceGoalRequirementDrilldown,
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
import type { KnowledgeRuntimeConformanceResponse } from '@/services/knowledgeApi';
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
    ahead: 56,
    behind: 0,
    changed_count: 14,
    staged_count: 0,
    unstaged_count: 14,
    untracked_count: 3,
    conflicted_count: 0,
    dirty_paths: [
      'frontend/src/pages/DesktopAcceptanceAgentWorkspace.tsx',
      'frontend/src/pages/DesktopAcceptanceAgentWorkspace.test.tsx',
      'docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json',
      'frontend/src/pages/AgentWorkspace.tsx',
      'frontend/src/pages/AgentWorkspace.test.tsx',
      'agent_mcp_server/src/lit_assistant_mcp/server.py',
      'agent_mcp_server/src/lit_assistant_mcp/tools/runtime.py',
      '.gitignore',
    ],
    error: null,
  },
  goal_state: {
    available: true,
    path: 'docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json',
    updated_at: '2026-06-23T19:49:30+08:00',
    checkpoint_id: '20260623-194244-n74-main-wiki-import-desktop-acceptance',
    requirement_count: 82,
    proved_count: 82,
    incomplete_count: 0,
    out_of_scope_count: 0,
    latest_requirement_id: 'N74-wiki-import-desktop-acceptance',
    requirement_status: {
      total: 82,
      proved: 82,
      incomplete: 0,
      out_of_scope: 0,
      latest_id: 'N74-wiki-import-desktop-acceptance',
    },
    open_requirements: [],
    completion_claim: {
      this_slice: 'N74 completed desktop Wiki Import Recovery acceptance with screenshot and UIA host-tree evidence.',
      full_goal: 'The long-running Scholar AI research workflow spine remains active, not complete.',
    },
    next_authorized_local_actions: [
      'Create a rollback checkpoint and search mature references before nontrivial edits.',
      'If continuing Computer Use repair, compare Windows UIA host-tree capture with any available deeper accessibility-tree API.',
    ],
    stop_boundaries: ['No push, tag, release, deploy, or external upload.'],
    error: null,
  },
  desktop_smoke: {
    schema_version: 'scholar_ai_desktop_smoke_state_v1',
    available: true,
    read_only: true,
    run_id: 'n74-wiki-import-recovery-desktop-aligned',
    status: 'passed',
    initial_path: '/__desktop_acceptance/agent-workspace',
    expected_initial_path: '/__desktop_acceptance/agent-workspace',
    candidate_count: 2,
    ignored_count: 1,
    summary_path: 'workspace_artifacts/generated/desktop_smoke/n74-wiki-import-recovery-desktop-aligned/summary.json',
    screenshot_path: 'workspace_artifacts/generated/desktop_smoke/n74-wiki-import-recovery-desktop-aligned/window.png',
    accessibility_tree_path: 'workspace_artifacts/generated/desktop_smoke/n74-wiki-import-recovery-desktop-aligned/accessibility-tree.json',
    screenshot_nonblank: true,
    accessibility_tree_available: true,
    accessibility_tree_root_name: '文献助手',
    accessibility_tree_root_control_type: '窗口',
    accessibility_tree_node_count: 20,
    accessibility_tree_named_node_count: 9,
    warnings: [],
    errors: [],
    error: null,
  },
  ocr_runtime: {
    schema_version: 'scholar_ai_ocr_runtime_state_v1',
    available: true,
    read_only: true,
    policy: 'auto',
    configured_engine: null,
    selected_engine: 'mock_local',
    language: 'en',
    source: 'default',
    engine_config: {},
    engine_count: 2,
    ready_engine_count: 1,
    engines: [
      {
        name: 'mock_local',
        display_name: 'Mock Local OCR',
        engine_type: 'local',
        available: true,
        requires_network: false,
        readiness_status: 'ready',
        readiness_blockers: [],
        next_safe_local_actions: ['Run literature.ocr_execution_probe with confirm_execution=true on a small local image.'],
        unavailable_reason: null,
      },
      {
        name: 'remote_api',
        display_name: 'Remote OCR API',
        engine_type: 'remote',
        available: false,
        requires_network: true,
        readiness_status: 'configuration_required',
        readiness_blockers: ['api_key is required'],
        next_safe_local_actions: ['Configure remote_api only with local credential references and explicit upload consent.'],
        unavailable_reason: 'api_key is required',
      },
    ],
    readiness_blockers: ['remote_api: api_key is required'],
    warning: null,
    next_safe_local_actions: ['Inspect literature.ocr_health before claiming OCR execution readiness.'],
    error: null,
  },
  wiki_doctor: {
    schema_version: 'scholar_ai_wiki_doctor_state_v1',
    available: true,
    read_only: true,
    status: 'warning',
    registry_db_path: 'workspace_artifacts/runtime_state/wiki.db',
    source_count: 1,
    chunk_count: 1,
    pending_source_count: 1,
    pending_chunk_count: 1,
    needs_replay: true,
    source_status_counts: { not_mirrored: 1 },
    chunk_status_counts: { not_mirrored: 1 },
    sample_count: 2,
    samples: [
      {
        record_type: 'source',
        record_id: 'markdown-source-backlog',
        source_id: 'markdown-source-backlog',
        status: 'not_mirrored',
        error: null,
      },
      {
        record_type: 'chunk',
        record_id: 'markdown-source-backlog:0',
        source_id: 'markdown-source-backlog',
        status: 'not_mirrored',
        error: null,
      },
    ],
    action_count: 1,
    next_safe_local_actions: [
      'Read /api/wiki/doctor, then run an explicit local maintenance slice before WikiRegistry.replay_source_vault_mirror().',
    ],
    warning: 'Source Vault mirror backlog has 1 source rows and 1 chunk rows pending replay.',
    error: null,
  },
  recovery_probes: [
    {
      label: 'Desktop Smoke Evidence',
      route: '/api/agent-workspace/status',
      read_only: true,
      requires_identifier: false,
      identifier_hint: null,
      purpose: 'Recover latest source desktop screenshot and accessibility-tree artifact labels before claiming UI acceptance.',
      mcp_tool: 'literature.agent_workspace_status',
    },
    {
      label: 'Wiki Doctor',
      route: '/api/wiki/doctor',
      read_only: true,
      requires_identifier: false,
      identifier_hint: null,
      purpose: 'Recover WikiRegistry Source Vault mirror backlog before replaying or claiming KRT recovery closure.',
      mcp_tool: 'literature.wiki_doctor',
    },
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
    {
      label: 'Goal Requirement Drilldown',
      route: '/api/agent-workspace/goal-requirements/{requirement_id}',
      read_only: true,
      requires_identifier: true,
      identifier_hint: 'requirement_id',
      purpose: 'Recover one requirement-to-evidence row by id before claiming closure.',
      mcp_tool: 'literature.agent_workspace_requirement',
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

const ACCEPTANCE_REQUIREMENT_DRILLDOWN = {
  schema_version: 'scholar_ai_goal_requirement_drilldown_v1',
  available: true,
  read_only: true,
  path: 'docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json',
  updated_at: '2026-06-23T19:49:30+08:00',
  checkpoint_id: '20260623-194244-n74-main-wiki-import-desktop-acceptance',
  id: 'N74-wiki-import-desktop-acceptance',
  status: 'proved',
  requirement: 'Extend the source desktop Agent Workspace acceptance route so the N73 Wiki Import Recovery panel is visible in the real 文献助手 pywebview desktop surface.',
  residual_risk: 'Windows UIA currently exposes the pywebview/Chrome host tree, while focused DOM tests and screenshot prove inner React panel visibility.',
  evidence: [
    {
      label: 'frontend/src/pages/DesktopAcceptanceAgentWorkspace.tsx',
      text: 'Desktop acceptance fixture renders WikiImportRecoveryPanel with local Markdown import runtime recovery metadata.',
    },
    {
      label: 'frontend/src/pages/DesktopAcceptanceAgentWorkspace.test.tsx',
      text: 'Role-scoped test proves Wiki import recovery visibility, review-gated metadata, and no raw route or local path leakage.',
    },
    {
      label: 'workspace_artifacts/generated/desktop_smoke/n74-wiki-import-recovery-desktop/window.png',
      text: 'Source desktop screenshot visibly shows Wiki Import Recovery in the 文献助手 window.',
    },
    {
      label: 'workspace_artifacts/generated/desktop_smoke/n74-wiki-import-recovery-desktop/accessibility-tree.json',
      text: 'Native UIA host-tree artifact reports root 文献助手 with non-empty named nodes.',
    },
  ],
  evidence_count: 4,
  truncated: false,
  next_safe_local_actions: [
    'Create a rollback checkpoint and search mature references before continuing desktop or Computer Use work.',
  ],
  stop_boundaries: ['No push, tag, release, deploy, external upload, approval execution, or Zotero DB mutation.'],
  error: null,
} satisfies AgentWorkspaceGoalRequirementDrilldown;

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
    {
      item_id: 'desktop-import-runtime-note',
      kind: 'draft',
      title: 'Runtime Import Note',
      page_path: 'private/imports/runtime-note.md',
      summary: 'Local Markdown import candidate stays in review queue recovery.',
      status: 'pending',
      created_at: '2026-06-23T10:00:00.000Z',
      source: 'local_markdown_import',
      metadata: {
        manual_wiki_import: true,
        requested_status: 'final',
        source_path: 'C:\\Users\\Alice\\My Documents\\runtime note.md',
        runtime_session_id: 'session_wiki_import_acceptance',
        runtime_job_id: 'job_wiki_import_acceptance',
        runtime_approval_id: 'approval_wiki_import_acceptance',
        evidence_integrity_gate: {
          status: 'block',
          signal_id: 'wiki_import:manual_local_markdown:acceptance',
          blocks_claims: true,
        },
        runtime_recovery: {
          agent_handoff_card: '/runtime/job/job_wiki_import_acceptance/agent-handoff-card',
        },
        agent_handoff_recovery: {
          review_queue_probe: '/api/wiki/review?status=pending&kind=draft',
          forbidden_actions: [
            'direct_zotero_db_write',
            'external_upload',
            'auto_approve_import',
          ],
        },
      },
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
            endpoint: '/runtime/job/{job_id}/preflight-refresh-receipt',
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

const ACCEPTANCE_KNOWLEDGE_RUNTIME: KnowledgeRuntimeConformanceResponse = {
  schema_version: 'scholar_ai_knowledge_runtime_conformance_v1',
  generated_at: '2026-06-25T10:00:00.000Z',
  pipeline: [
    'authoritative source',
    'builder/loader/chunker',
    'runtime artifact',
    'manifest/provenance/hash',
    'searchable ref/resource',
    'bounded context',
    'QA/agent actual loading',
    'audit/test proof',
  ],
  summary: {
    proved: 1,
    pending: 0,
    blocked: 1,
    not_applicable: 0,
  },
  actual_loading_gate: {
    status: 'blocked',
    evidence_level: 'contract_evidence',
    artifact_path: 'workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json',
    artifact_ref: 'workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json',
    artifact_contract: 'scholar-ai-live-context-receipt-smoke/v1',
    artifact_exists: false,
    artifact_schema_valid: false,
    artifact_contract_valid: false,
    artifact_checked_at: '2026-06-26T03:39:00Z',
    verdict: 'missing_artifact',
    evidence_scope: [
      '/api/chat',
      'literature.agent_resource_read',
      'literature.knowledge_context_receipt',
      'assembled_context_hash_backflow',
    ],
    evidence: [],
    missing: [
      'authorized live provider smoke artifact with verdict=ok',
      'LITASSIST_RUN_LIVE_CONTEXT_RECEIPT_SMOKE or --allow-live-provider-call',
    ],
    validation_errors: [],
    required_checks: [
      'artifact.schema.valid',
      'artifact.generated_at.utc_aware',
      'artifact.verdict.ok',
      'artifact.status_code.200',
      'artifact.required_tools.used',
      'artifact.required_tools.names',
      'artifact.receipt_hash.preview',
      'artifact.receipt_hash.final_answer',
      'artifact.receipt_hash.query_matches_direct',
      'artifact.direct_receipt.assembled_context_hash',
    ],
    next_safe_local_actions: [
      'Require provider_preflight.status=proved before running live context-receipt smoke.',
      'Run tests/live_api_chat_knowledge_context_receipt_smoke.py only with explicit live-provider authorization.',
    ],
    claim_boundary: 'Package conformance proves deterministic source-to-context receipts only; no live QA/model actual-loading artifact is present.',
    provider_preflight: {
      status: 'blocked',
      evidence_level: 'contract_evidence',
      artifact_path: 'workspace_artifacts/runtime_state/provider-capabilities.json',
      artifact_ref: 'workspace_artifacts/runtime_state/provider-capabilities.json',
      artifact_exists: true,
      artifact_schema_valid: true,
      checked_at: '2026-06-26T03:40:00Z',
      record_count: 1,
      latest_status: 'auth_required',
      status_counts: { auth_required: 1 },
      auth_required_count: 1,
      tool_call_ok_count: 0,
      provider_ready_for_authorized_live_smoke: false,
      records: [
        {
          fingerprint: 'a'.repeat(64),
          provider: 'hhl',
          base_url_host: 'free.hanhanapi.top',
          model: 'gpt-5.5',
          status: 'auth_required',
          ordinary_chat_ok: false,
          forced_tool_choice_ok: false,
          last_probe_at: '2026-06-25T20:13:21Z',
          failure_class: 'models',
          masked_error: 'HTTP 401: Invalid token (request id: [REDACTED])',
        },
      ],
      evidence_scope: ['/api/chat/tool-capability/test'],
      evidence: ['workspace_artifacts/runtime_state/provider-capabilities.json'],
      missing: ['provider_tool_call_status=tool_call_ok'],
      validation_errors: [],
      next_safe_local_actions: [
        'Stop live actual-loading smoke while latest provider status is auth_required.',
        'After the user corrects provider credentials/config, rerun provider tool-capability preflight.',
      ],
      claim_boundary: 'Provider preflight has not proven forced tool calls.',
    },
    recovery: {
      schema_version: 'scholar-ai-knowledge-runtime-recovery/v1',
      read_only: true,
      state: 'blocked_provider_preflight_and_missing_live_smoke',
      blocked_by: ['provider_preflight:blocked:auth_required', 'live_smoke:missing_artifact'],
      recovery_refs: [
        {
          ref_type: 'conformance_endpoint',
          ref: '/api/knowledge/runtime-conformance',
          status: 'blocked',
          method: 'GET',
          access_mode: 'read_only',
          required_before_completion: true,
          requires_authorization: false,
        },
        {
          ref_type: 'provider_preflight_artifact',
          ref: 'workspace_artifacts/runtime_state/provider-capabilities.json',
          status: 'blocked',
          method: 'READ',
          access_mode: 'local_artifact',
          required_before_completion: true,
          requires_authorization: false,
        },
        {
          ref_type: 'provider_preflight_endpoint',
          ref: '/api/chat/tool-capability/test',
          status: 'requires_configured_credentials',
          method: 'POST',
          access_mode: 'authorized_provider_preflight',
          required_before_completion: true,
          requires_authorization: true,
        },
        {
          ref_type: 'live_smoke_harness',
          ref: 'workspace_tests/evaluation_scripts/live_api_chat_knowledge_context_receipt_smoke.py',
          status: 'authorization_required',
          method: 'RUN',
          access_mode: 'explicit_live_provider_smoke',
          required_before_completion: true,
          requires_authorization: true,
        },
      ],
      provider_ready_for_authorized_live_smoke: false,
      completion_requires_authorized_live_smoke: true,
    },
  },
  packages: [
    {
      package_id: 'source_vault',
      kind: 'source_vault',
      title: 'Source Vault',
      overall_status: 'blocked',
      loaded: false,
      source_path: 'workspace_artifacts/source_vault',
      source_hash: 'missing',
      content_hash: 'missing',
      read_endpoint: '/api/knowledge/source-vault/{ref_id}',
      search_endpoint: '/api/knowledge/source-vault/search',
      manifest: { empty_runtime: true },
      runtime_consumers: [{ surface: 'MCP', tool: 'literature.source_vault_read' }],
      mcp_tools: ['literature.source_vault_search', 'literature.source_vault_read'],
      test_evidence: {
        focused_test_exists: true,
        source_edit_hash_test: true,
        context_receipt_test: false,
        evidence_pack_test: false,
        agent_resource_read_test: true,
        mcp_tool_test: true,
        test_nodes: ['tests/test_knowledge_router.py::test_knowledge_runtime_conformance_blocks_endpoint_only_claims'],
      },
      conformance: [
        {
          requirement: 'Loaded refs must exist before claiming bounded context.',
          status: 'blocked',
          evidence_level: 'runtime_projection',
          evidence_scope: ['default_runtime'],
          evidence: [],
          missing: ['loaded_ref'],
        },
      ],
    },
    {
      package_id: 'wiki',
      kind: 'wiki',
      title: 'Private Wiki',
      overall_status: 'proved',
      loaded: true,
      source_path: 'workspace_artifacts/wiki',
      source_hash: 'sha256:wiki-source-hash',
      content_hash: 'sha256:wiki-content-hash',
      read_endpoint: '/api/wiki/resource/{ref_id}',
      search_endpoint: '/api/wiki/search',
      manifest: { loaded: true },
      runtime_consumers: [{ surface: 'Agent', caller: 'resource_read' }],
      mcp_tools: ['literature.wiki_search', 'literature.wiki_resource_read'],
      test_evidence: {
        focused_test_exists: true,
        source_edit_hash_test: true,
        context_receipt_test: true,
        evidence_pack_test: true,
        agent_resource_read_test: true,
        mcp_tool_test: true,
        test_nodes: ['tests/wiki/test_wiki_router.py::test_wiki_source_rebuild_search_resource_and_context_receipt_chain'],
      },
      conformance: [
        {
          requirement: 'Wiki refs can be loaded into bounded context.',
          status: 'proved',
          evidence_level: 'focused_test_evidence',
          evidence_scope: ['wiki'],
          evidence: ['context receipt test passed'],
          missing: [],
        },
      ],
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
        <WikiImportRecoveryPanel wikiReview={ACCEPTANCE_REVIEW} />
        <WorkspaceStatePanel
          workspaceStatus={ACCEPTANCE_WORKSPACE_STATUS}
          knowledgeRuntime={ACCEPTANCE_KNOWLEDGE_RUNTIME}
          requirementDrilldown={ACCEPTANCE_REQUIREMENT_DRILLDOWN}
          selectedRequirementId="N74-wiki-import-desktop-acceptance"
          requirementQuery=""
          onRequirementQueryChange={() => undefined}
          onSelectRequirement={() => undefined}
        />
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
