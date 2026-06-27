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
import {
  getKnowledgeRuntimeConformance,
  type KnowledgeRuntimeConformanceResponse,
} from '@/services/knowledgeApi';
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

vi.mock('@/services/knowledgeApi', () => ({
  getKnowledgeRuntimeConformance: vi.fn(),
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
const mockedGetKnowledgeRuntimeConformance = vi.mocked(getKnowledgeRuntimeConformance);
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
      updated_at: '2026-06-24T17:55:00+08:00',
      checkpoint_id: '20260624-173328-n112-sandboxpolicy-knowledge-runtime-continuatio',
      rollback_caveat: 'Restore only with explicit user intent after checking dirty worktree ownership.',
      requirement_count: 125,
      proved_count: 125,
      incomplete_count: 0,
      out_of_scope_count: 0,
      latest_requirement_id: 'N112-sandboxpolicy-current-state-alignment',
      requirement_status: {
        total: 125,
        proved: 125,
        incomplete: 0,
        out_of_scope: 0,
        latest_id: 'N112-sandboxpolicy-current-state-alignment',
      },
      open_requirements: [],
      completion_claim: {
        this_slice: 'N112 aligned current recovery state with local UIA accessibility-tree evidence.',
        full_goal: 'The full Scholar AI workflow spine remains active, not complete.',
        can_mark_goal_complete: false,
        why_not_complete: 'Live provider/model actual-loading is still blocked.',
      },
      lifecycle_rollup: {
        schema_version: 'scholar_ai_goal_lifecycle_rollup_v1',
        updated_at: '2026-06-25T23:59:30+08:00',
        status: 'active_requirements_proved_pending_authorized_gates',
        is_goal_complete: false,
        can_mark_goal_complete: false,
        requirements_all_proved: true,
        requirements_all_proved_or_out_of_scope: true,
        latest_requirement_id: 'N173-goal-lifecycle-rollup',
        latest_slice_id: 'N173-goal-lifecycle-rollup',
        completion_blockers: [
          {
            id: 'actual_loading_gate_live_model_proof',
            status: 'blocked_pending_explicit_authorization',
            requirement_surface: 'Knowledge Runtime Pipeline QA/agent actual model-context loading',
            missing_evidence: 'Authorized live provider/model smoke artifact with verdict=ok.',
            current_boundary: 'Deterministic contract and harness tests are proved.',
          },
        ],
        machine_readable_completion_rule: 'Goal may be marked complete only after blockers clear.',
        why_not_complete: [
          'All requirement rows are proved, but goal-level proof gates remain.',
        ],
      },
      next_authorized_local_actions: [
        'Create a rollback checkpoint and search mature references before nontrivial edits.',
        'Continue deterministic local recovery and proof hardening.',
        'Keep live provider/model actual-loading blocked until preflight is proved.',
      ],
      stop_boundaries: [
        'Do not call the long-run goal complete while can_mark_goal_complete is false.',
        'No push, tag, release, deploy, or external upload.',
        'Do not run live provider/model or remote OCR upload without explicit authorization.',
        'Do not reset squad state, mutate Zotero DB, modify github/ references, or add Feishu/Lark integration without explicit authorization.',
      ],
      authoritative_records: [
        'AI_WORKSPACE_GUIDE.md',
        'AGENTS.md',
        'docs/plans/autonomous-execution-framework.md',
        'docs/plans/autonomous-execution-planning-playbook.md',
      ],
      mature_references_checked: [
        {
          topic: 'N112 recovery state response model at C:\\Users\\Alice\\private\\goal.json',
          source: 'FastAPI response-model documentation',
          url: 'https://fastapi.tiangolo.com/tutorial/response-model/',
          status: 'HEAD checked 200',
          checked_at: '2026-06-24T17:55:00+08:00',
          use_in_slice: 'Keep recovery state on the typed status response.',
        },
      ],
      error: null,
    },
    desktop_smoke: {
      schema_version: 'scholar_ai_desktop_smoke_state_v1' as const,
      available: true,
      read_only: true,
      run_id: 'n75-desktop-smoke',
      status: 'passed',
      initial_path: '/__desktop_acceptance/agent-workspace',
      expected_initial_path: '/__desktop_acceptance/agent-workspace',
      candidate_count: 2,
      ignored_count: 1,
      summary_path: 'workspace_artifacts/generated/desktop_smoke/n75-desktop-smoke/summary.json',
      screenshot_path: 'workspace_artifacts/generated/desktop_smoke/n75-desktop-smoke/window.png',
      accessibility_tree_path: 'workspace_artifacts/generated/desktop_smoke/n75-desktop-smoke/accessibility-tree.json',
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
      schema_version: 'scholar_ai_ocr_runtime_state_v1' as const,
      available: true,
      read_only: true,
      policy: 'engine',
      configured_engine: 'remote_api',
      selected_engine: null,
      language: 'en',
      source: 'config',
      engine_config: {
        api_key: '***',
        base_url: 'https://ocr.example.test',
      },
      engine_count: 2,
      ready_engine_count: 1,
      engines: [
        {
          name: 'remote_api',
          display_name: 'Remote OCR API',
          engine_type: 'remote',
          available: false,
          requires_network: true,
          readiness_status: 'configuration_required',
          readiness_blockers: ['allow_remote_upload must be true'],
          next_safe_local_actions: ['Set allow_remote_upload only after explicit consent.'],
          unavailable_reason: 'remote upload consent is not enabled',
        },
        {
          name: 'mock_local',
          display_name: 'Mock Local OCR',
          engine_type: 'local',
          available: true,
          requires_network: false,
          readiness_status: 'ready',
          readiness_blockers: [],
          next_safe_local_actions: ['Run literature.ocr_execution_probe with confirm_execution=true.'],
          unavailable_reason: null,
        },
      ],
      readiness_blockers: [
        'OCR policy is engine but remote_api is not ready',
        'remote_api: allow_remote_upload must be true',
      ],
      warning: 'OCR policy is engine but remote_api is not ready',
      next_safe_local_actions: ['Inspect literature.ocr_engines before running OCR.'],
      error: null,
    },
    wiki_doctor: {
      schema_version: 'scholar_ai_wiki_doctor_state_v1' as const,
      available: true,
      read_only: true,
      status: 'warning',
      registry_db_path: 'workspace_artifacts/runtime_state/wiki.db',
      source_count: 3,
      chunk_count: 7,
      pending_source_count: 1,
      pending_chunk_count: 2,
      needs_replay: true,
      source_status_counts: { mirrored: 2, not_mirrored: 1 },
      chunk_status_counts: { mirrored: 5, not_mirrored: 2 },
      sample_count: 3,
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
          status: 'blocked',
          error: 'Source Vault write requires explicit replay authority.',
        },
      ],
      action_count: 1,
      next_safe_local_actions: [
        'Read /api/wiki/doctor, then run an explicit local maintenance slice before WikiRegistry.replay_source_vault_mirror().',
      ],
      warning: 'Source Vault mirror backlog has 1 source rows and 2 chunk rows pending replay.',
      error: null,
    },
    knowledge_actual_loading_gate: {
      schema_version: 'scholar_ai_krt_actual_loading_gate_state_v1' as const,
      available: true,
      read_only: true,
      status: 'blocked',
      verdict: 'missing_artifact',
      artifact_ref: 'workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json',
      artifact_path: 'workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json',
      artifact_exists: false,
      artifact_schema_valid: false,
      artifact_contract_valid: false,
      provider_preflight_status: 'blocked',
      provider_latest_status: 'auth_required',
      provider_record_count: 1,
      auth_required_count: 1,
      tool_call_ok_count: 0,
      provider_ready_for_authorized_live_smoke: false,
      recovery_state: 'blocked_provider_preflight_and_missing_live_smoke',
      recovery_blocked_by: ['provider_preflight:blocked:auth_required', 'live_smoke_artifact:missing'],
      recovery_ref_count: 5,
      authorization_required_ref_count: 2,
      completion_requires_authorized_live_smoke: true,
      missing: [
        'authorized live provider smoke artifact with verdict=ok',
        'provider_preflight.status=proved',
      ],
      next_safe_local_actions: [
        'Require provider_preflight.status=proved before running live context-receipt smoke.',
      ],
      claim_boundary: 'Deterministic context receipts are proved, but live QA/model loading is not.',
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
        label: 'OCR Runtime Status',
        route: '/api/pdf-backend/ocr-status',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover OCR policy, selected engine, readiness blockers, and redacted runtime config before claiming local processing capability.',
        mcp_tool: 'literature.ocr_status',
      },
      {
        label: 'Wiki Doctor',
        route: '/api/wiki/doctor',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover wiki integrity diagnostics and Source Vault mirror backlog before claiming Knowledge Runtime Pipeline closure.',
        mcp_tool: 'literature.wiki_doctor',
      },
      {
        label: 'Knowledge Runtime Conformance',
        route: '/api/knowledge/runtime-conformance',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover package conformance, actual-loading gate state, and blocked evidence before claiming model-context readiness.',
        mcp_tool: 'literature.knowledge_runtime_conformance',
      },
      {
        label: 'Knowledge Packages',
        route: '/api/knowledge/packages',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover package source paths, hashes, runtime consumers, and load status before selecting refs for bounded context.',
        mcp_tool: 'literature.knowledge_packages',
      },
      {
        label: 'Wiki Search',
        route: '/api/wiki/search',
        read_only: true,
        requires_identifier: true,
        identifier_hint: 'query',
        purpose: 'Recover wiki refs before bounded resource reads or context receipts.',
        mcp_tool: 'literature.wiki_search',
      },
      {
        label: 'Academic English Search',
        route: '/api/knowledge/academic-english/search?q={query}',
        read_only: true,
        requires_identifier: true,
        identifier_hint: 'query',
        purpose: 'Recover academic-English refs before bounded resource reads or context receipts.',
        mcp_tool: 'literature.academic_english_search',
      },
      {
        label: 'Product Docs Search',
        route: '/api/knowledge/product-docs/search?q={query}',
        read_only: true,
        requires_identifier: true,
        identifier_hint: 'query',
        purpose: 'Recover product-doc refs before bounded resource reads or context receipts.',
        mcp_tool: 'literature.product_docs_search',
      },
      {
        label: 'Source Vault Status',
        route: '/api/knowledge/source-vault',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover Source Vault manifest, source counts, refs, and empty-runtime blockers before claiming source-to-context proof.',
        mcp_tool: 'literature.source_vault_status',
      },
      {
        label: 'Source Vault Search',
        route: '/api/knowledge/source-vault/search?q={query}',
        read_only: true,
        requires_identifier: true,
        identifier_hint: 'query',
        purpose: 'Recover Source Vault search refs before reading bounded resources or assembling context receipts.',
        mcp_tool: 'literature.source_vault_search',
      },
      {
        label: 'Source Vault Resource Read',
        route: '/api/agent-bridge/resource/{ref_id}',
        read_only: true,
        requires_identifier: true,
        identifier_hint: 'ref_id',
        purpose: 'Recover bounded Source Vault resource text, cursor, hash, and provenance before using refs as context.',
        mcp_tool: 'literature.source_vault_read',
      },
      {
        label: 'Knowledge Context Receipt',
        route: '/api/knowledge/context-receipt',
        read_only: true,
        requires_identifier: true,
        identifier_hint: 'ref_id',
        purpose: 'Recover bounded context receipt proof for selected refs before claiming prompt/context loading.',
        mcp_tool: 'literature.knowledge_context_receipt',
      },
      {
        label: 'MCP Result Envelope',
        route: '/api/agent-workspace/status',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover safe_result envelope fields, recursive redaction, structured truncation metadata, and serialization_failed boundaries from the source-readable MCP capability map before interpreting large tool outputs.',
        mcp_tool: 'source.read_file',
      },
      {
        label: 'Goal Lifecycle Completion Gate',
        route: '/api/agent-workspace/status',
        read_only: true,
        requires_identifier: false,
        identifier_hint: null,
        purpose: 'Recover can_mark_goal_complete, completion_blockers, completion_claim, and why_not_complete before treating all-proved requirements as long-goal closure.',
        mcp_tool: 'literature.agent_workspace_status',
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
      'Create a rollback checkpoint and re-check official or mature references before nontrivial edits.',
    ],
    next_safe_local_actions: [
      'Read Wiki Doctor, Knowledge Runtime Conformance, Source Vault Status/Search/Read, Knowledge Context Receipt, MCP Result Envelope, Workflow Passport, Evidence Integrity Gate, Research Action Lifecycle, Agent Handoff Cards, and Goal Requirement Drilldowns before resuming mutating work or claiming closure.',
      'Inspect git dirty paths and preserve unrelated local work before staging or committing.',
    ],
    ...overrides,
  };
}

function knowledgeRuntimeFixture(): KnowledgeRuntimeConformanceResponse {
  return {
    schema_version: 'scholar_ai_knowledge_runtime_conformance_v1',
    generated_at: '2026-06-25T10:00:00Z',
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
            requirement: 'Loaded searchable refs exist before claiming bounded context.',
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
        runtime_consumers: [
          { surface: 'QA', caller: 'evidence_pack' },
          { surface: 'Agent', caller: 'resource_read' },
        ],
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
      updated_at: '2026-06-24T17:55:00+08:00',
      checkpoint_id: '20260624-173328-n112-sandboxpolicy-knowledge-runtime-continuatio',
      id: 'B01-computer-use-accessibility-tree',
      status: 'proved',
      requirement: 'Local UIA accessibility-tree acceptance is restored for the source desktop app.',
      residual_risk: 'External Computer Use package exports issue remains a residual risk.',
      evidence: [
        {
          label: 'workspace_artifacts/generated/desktop_smoke/sandboxpolicy-diagnosis-20260623/summary.json',
          text: 'status passed with root 文献助手 and non-empty UIA tree',
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
    mockedGetKnowledgeRuntimeConformance.mockResolvedValue(knowledgeRuntimeFixture());
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

  it('renders local Markdown wiki import recovery metadata without exposing internal routes', async () => {
    mockedGetWikiReview.mockResolvedValue({
      enabled: true,
      items: [
        {
          item_id: 'import-synthesis-runtime-note',
          kind: 'draft',
          title: 'Runtime Import Note',
          page_path: 'private/imports/runtime-note.md',
          summary: 'Local Markdown import candidate.',
          status: 'pending',
          created_at: '2026-06-23T10:00:00Z',
          source: 'local_markdown_import',
          metadata: {
            manual_wiki_import: true,
            requested_status: 'final',
            source_path: 'C:\\Users\\Alice\\My Documents\\runtime note.md',
            runtime_session_id: 'session_import_1',
            runtime_job_id: 'job_import_1',
            runtime_approval_id: 'approval_import_1',
            evidence_integrity_gate: { status: 'block' },
            runtime_recovery: {
              agent_handoff_card: '/runtime/job/job_import_1/agent-handoff-card',
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
    });

    render(<AgentWorkspace />);

    const recoveryRegion = await screen.findByRole('region', { name: 'Wiki import recovery' });
    expect(within(recoveryRegion).getByText('Wiki Import Recovery')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('pending 1')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('runtime refs 1')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('gate block 1')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('read-only true')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('import-synthesis-runtime-note')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('private/imports/runtime-note.md')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('requested final')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('gate block')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('job_import_1')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('session_import_1')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('approval_import_1')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('handoff card available')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('review probe available')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('direct_zotero_db_write')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('external_upload')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('auto_approve_import')).toBeInTheDocument();
    expect(within(recoveryRegion).getByText('No auto approval, external upload, Zotero DB mutation, or published knowledge write is exposed from Agent Workspace.')).toBeInTheDocument();
    expect(within(recoveryRegion).queryByText('/runtime/job/job_import_1/agent-handoff-card')).not.toBeInTheDocument();
    expect(within(recoveryRegion).queryByText('C:\\Users\\Alice\\My Documents\\runtime note.md')).not.toBeInTheDocument();
    expect(within(recoveryRegion).queryByText(/My Documents/)).not.toBeInTheDocument();
    expect(within(recoveryRegion).queryByRole('button', { name: /approve|reject|write|publish/i })).not.toBeInTheDocument();
    expect(within(recoveryRegion).queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders Knowledge Runtime conformance in Agent Workspace recovery state', async () => {
    render(<AgentWorkspace />);

    const knowledgeRegion = await screen.findByRole('region', { name: 'Knowledge runtime conformance' });
    expect(mockedGetKnowledgeRuntimeConformance).toHaveBeenCalledTimes(1);
    expect(within(knowledgeRegion).getByText('Knowledge Runtime')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('conformance visible')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('read-only true')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('packages 2')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('blocked 1')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('proved 1')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('live gate blocked')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('Actual loading gate')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('missing_artifact · evidence 0 · missing 2 · errors 0 · checks 10')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('contract scholar-ai-live-context-receipt-smoke/v1')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('validation errors 0')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('required checks 10')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('recovery blocked_provider_preflight_and_missing_live_smoke')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('recovery read-only true')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('blocked by 2')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('provider ready false')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('auth required 1')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('tool-call ok 0')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('preflight ready false')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('preflight records 1')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('live smoke required')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('check artifact.schema.valid')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('check artifact.generated_at.utc_aware')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('check artifact.verdict.ok')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('recovery blocker provider_preflight:blocked:auth_required')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('recovery blocker live_smoke:missing_artifact')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('recovery ref conformance_endpoint GET · read_only · blocked')).toBeInTheDocument();
    expect(
      within(knowledgeRegion).getByText(
        'recovery ref provider_preflight_endpoint POST · authorized_provider_preflight · requires_configured_credentials · auth',
      ),
    ).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('provider status auth_required 1')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('provider missing provider_tool_call_status=tool_call_ok')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('provider next Stop live actual-loading smoke while latest provider status is auth_required.')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText(/Package conformance proves deterministic source-to-context receipts only/)).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('missing authorized live provider smoke artifact with verdict=ok')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText(/authoritative source -> builder\/loader\/chunker -> runtime artifact/)).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('Source Vault')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('loaded false')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('blocked rows 1')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('Private Wiki')).toBeInTheDocument();
    expect(within(knowledgeRegion).getByText('focused-test · context-receipt · agent-resource · mcp-tool')).toBeInTheDocument();
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
    expect(within(workspaceStateRegion).getByText('goal-state 125 rows · proved 125 · incomplete 0 · out-of-scope 0 · latest N112-sandboxpolicy-current-state-alignment · lifecycle active_requirements_proved_pending_authorized_gates')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal-state visible')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('requirement status visible')).toBeInTheDocument();
    expect(
      within(workspaceStateRegion).getByText(
        'lifecycle record updated 2026-06-25T23:59:30+08:00 · latest requirement N173-goal-lifecycle-rollup · latest slice N173-goal-lifecycle-rollup',
      ),
    ).toBeInTheDocument();
    expect(
      within(workspaceStateRegion).getByText(
        'blocker detail actual_loading_gate_live_model_proof · blocked_pending_explicit_authorization · Knowledge Runtime Pipeline QA/agent actual model-context loading',
      ),
    ).toBeInTheDocument();
    expect(
      within(workspaceStateRegion).getByText(
        'missing evidence Authorized live provider/model smoke artifact with verdict=ok.',
      ),
    ).toBeInTheDocument();
    expect(
      within(workspaceStateRegion).getByText(
        'current boundary Deterministic contract and harness tests are proved.',
      ),
    ).toBeInTheDocument();
    expect(
      within(workspaceStateRegion).getByText(
        'completion rule Goal may be marked complete only after blockers clear.',
      ),
    ).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('why not complete All requirement rows are proved, but goal-level proof gates remain.')).toBeInTheDocument();
    const desktopSmokeRegion = within(workspaceStateRegion).getByRole('region', { name: 'Desktop smoke evidence' });
    expect(within(desktopSmokeRegion).getByText('Desktop Smoke Evidence')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('desktop smoke visible')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('read-only true')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('status passed')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('n75-desktop-smoke · passed · screenshot nonblank · a11y tree yes · candidates 2 · ignored 1')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('/__desktop_acceptance/agent-workspace')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('expected /__desktop_acceptance/agent-workspace')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('ignored 1')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('root 文献助手')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('control 窗口')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('nodes 20')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('named 9')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('workspace_artifacts/generated/desktop_smoke/n75-desktop-smoke/window.png')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).getByText('workspace_artifacts/generated/desktop_smoke/n75-desktop-smoke/accessibility-tree.json')).toBeInTheDocument();
    expect(within(desktopSmokeRegion).queryByText(/C:\\Users\\/)).not.toBeInTheDocument();
    const ocrRuntimeRegion = within(workspaceStateRegion).getByRole('region', { name: 'OCR runtime recovery' });
    expect(within(ocrRuntimeRegion).getByText('OCR Runtime')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('ocr runtime visible')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('read-only true')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('selected none')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('ocr engine · selected none · ready 1/2 · lang en · source config')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('configured remote_api')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('ready engines 1')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('engine inventory 2')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('api_key ***')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('base_url https://ocr.example.test')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('warning OCR policy is engine but remote_api is not ready')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('blocker remote_api: allow_remote_upload must be true')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('Remote OCR API · configuration_required · unavailable · remote · network · blocker allow_remote_upload must be true')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('Mock Local OCR · ready · available · local')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).getByText('next Inspect literature.ocr_engines before running OCR.')).toBeInTheDocument();
    expect(within(ocrRuntimeRegion).queryByText('raw-secret-should-not-leak')).not.toBeInTheDocument();
    const actualLoadingRegion = within(workspaceStateRegion).getByRole('region', { name: 'Knowledge actual-loading gate recovery' });
    expect(within(actualLoadingRegion).getByText('KRT Actual Loading')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('actual-loading blocked')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('read-only true')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('artifact missing')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('contract false')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('provider ready false')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('live smoke required')).toBeInTheDocument();
    expect(
      within(actualLoadingRegion).getByText(
        'recovery blocked_provider_preflight_and_missing_live_smoke · verdict missing_artifact · preflight blocked · latest auth_required',
      ),
    ).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('auth required 1')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('tool-call ok 0')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('preflight records 1')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('blocked by 2')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('auth refs 2')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('recovery refs 5')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json')).toBeInTheDocument();
    expect(
      within(actualLoadingRegion).getByText('boundary Deterministic context receipts are proved, but live QA/model loading is not.'),
    ).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('blocker provider_preflight:blocked:auth_required')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('blocker live_smoke_artifact:missing')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('missing authorized live provider smoke artifact with verdict=ok')).toBeInTheDocument();
    expect(within(actualLoadingRegion).getByText('missing provider_preflight.status=proved')).toBeInTheDocument();
    expect(
      within(actualLoadingRegion).getByText('next Require provider_preflight.status=proved before running live context-receipt smoke.'),
    ).toBeInTheDocument();
    expect(within(actualLoadingRegion).queryByRole('button')).not.toBeInTheDocument();
    const wikiDoctorRegion = within(workspaceStateRegion).getByRole('region', { name: 'Wiki Doctor recovery' });
    expect(within(wikiDoctorRegion).getByText('Wiki Doctor')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('wiki doctor visible')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('read-only true')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('needs replay true')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('pending sources 1')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('pending chunks 2')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('wiki doctor warning · sources 3 · chunks 7 · pending 1/2')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('sources 3')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('chunks 7')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('samples 3')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('actions 1')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('workspace_artifacts/runtime_state/wiki.db')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('source mirrored 2')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('source not_mirrored 1')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('chunk mirrored 5')).toBeInTheDocument();
    expect(within(wikiDoctorRegion).getByText('chunk not_mirrored 2')).toBeInTheDocument();
    expect(
      within(wikiDoctorRegion).getByText('sample source markdown-source-backlog · source markdown-source-backlog · not_mirrored'),
    ).toBeInTheDocument();
    expect(
      within(wikiDoctorRegion).getByText(
        'sample chunk markdown-source-backlog:0 · source markdown-source-backlog · blocked · error Source Vault write requires explicit replay authority.',
      ),
    ).toBeInTheDocument();
    expect(
      within(wikiDoctorRegion).getByText('warning Source Vault mirror backlog has 1 source rows and 2 chunk rows pending replay.'),
    ).toBeInTheDocument();
    expect(
      within(wikiDoctorRegion).getByText(
        'next Read /api/wiki/doctor, then run an explicit local maintenance slice before WikiRegistry.replay_source_vault_mirror().',
      ),
    ).toBeInTheDocument();
    expect(within(wikiDoctorRegion).queryByRole('button')).not.toBeInTheDocument();
    expect(within(wikiDoctorRegion).queryByText(/replay now/i)).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText('Open Requirements')).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText(/B01-computer-use-accessibility-tree · incomplete/)).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByRole('region', { name: 'Requirement evidence drilldown' })).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('full goal status visible')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('lifecycle active_requirements_proved_pending_authorized_gates')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('slice completion N112 aligned current recovery state with local UIA accessibility-tree evidence.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('full goal The full Scholar AI workflow spine remains active, not complete.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('completion claim can complete false')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('completion claim why not complete Live provider/model actual-loading is still blocked.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('rollback caveat Restore only with explicit user intent after checking dirty worktree ownership.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal next 1 Create a rollback checkpoint and search mature references before nontrivial edits.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal next 2 Continue deterministic local recovery and proof hardening.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal next 3 Keep live provider/model actual-loading blocked until preflight is proved.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal boundary 1 Do not call the long-run goal complete while can_mark_goal_complete is false.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal boundary 3 Do not run live provider/model or remote OCR upload without explicit authorization.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal boundary 4 Do not reset squad state, mutate Zotero DB, modify github/ references, or add Feishu/Lark integration without explicit authorization.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal record 1 AI_WORKSPACE_GUIDE.md')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal record 2 AGENTS.md')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal record 3 docs/plans/autonomous-execution-framework.md')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('goal record 4 docs/plans/autonomous-execution-planning-playbook.md')).toBeInTheDocument();
    expect(
      within(workspaceStateRegion).getByText(
        'mature reference 1 FastAPI response-model documentation · N112 recovery state response model at [redacted-local-path] · HEAD checked 200 · checked 2026-06-24T17:55:00+08:00 · use Keep recovery state on the typed status response.',
      ),
    ).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('lifecycle blockers 1 · can complete false')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('checkpoint 20260624-173328-n112-sandboxpolicy-knowledge-runtime-continuatio')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json')).toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText(/C:\\Users\\/)).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText(/restore_command/)).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('literature_assistant/core/routers/agent_workspace_router.py')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('docs/plans/local-goal-state.json')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Desktop Smoke Evidence · read-only true · literature.agent_workspace_status')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('OCR Runtime Status · read-only true · literature.ocr_status')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Wiki Doctor · read-only true · literature.wiki_doctor')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Knowledge Runtime Conformance · read-only true · literature.knowledge_runtime_conformance')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Knowledge Packages · read-only true · literature.knowledge_packages')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Wiki Search · read-only true · needs query · literature.wiki_search')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Academic English Search · read-only true · needs query · literature.academic_english_search')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Product Docs Search · read-only true · needs query · literature.product_docs_search')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Source Vault Status · read-only true · literature.source_vault_status')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Source Vault Search · read-only true · needs query · literature.source_vault_search')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Source Vault Resource Read · read-only true · needs ref_id · literature.source_vault_read')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Knowledge Context Receipt · read-only true · needs ref_id · literature.knowledge_context_receipt')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('MCP Result Envelope · read-only true · source.read_file')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Goal Lifecycle Completion Gate · read-only true · literature.agent_workspace_status')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Workflow Passport · read-only true · literature.workflow_passport')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Evidence Integrity Gate · read-only true · literature.evidence_integrity_gate')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Research Action Lifecycle · read-only true · literature.research_action_lifecycle')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Agent Handoff Card · read-only true · needs job_id · literature.agent_handoff_card')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Agent Workspace Status · read-only true · literature.agent_workspace_status')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Goal Requirement Drilldown · read-only true · needs requirement_id · literature.agent_workspace_requirement')).toBeInTheDocument();
    expect(within(workspaceStateRegion).getByText('Create a rollback checkpoint and re-check official or mature references before nontrivial edits.')).toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText('/runtime/workflow-passport')).not.toBeInTheDocument();
    expect(within(workspaceStateRegion).queryByText('/runtime/job/{job_id}/agent-handoff-card')).not.toBeInTheDocument();
    expect(mockedGetAgentWorkspaceRequirement).not.toHaveBeenCalled();
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
