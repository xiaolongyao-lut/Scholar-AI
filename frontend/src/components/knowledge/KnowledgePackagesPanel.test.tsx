import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { KnowledgePackagesPanel } from './KnowledgePackagesPanel';

vi.mock('@/services/knowledgeApi', () => ({
  getKnowledgePackages: vi.fn(async () => ({
    schema_version: 'scholar-ai-knowledge-packages/v1',
    packages: [
      {
        package_id: 'wiki',
        kind: 'wiki',
        title: 'Wiki',
        source_label: 'generated wiki pages',
        status: 'loaded',
        available: true,
        loaded: true,
        manifest_loaded: true,
        source_path: 'C:\\workspace_artifacts\\wiki',
        source_hash: 'a'.repeat(64),
        content_hash: 'b'.repeat(64),
        updated_at: '2026-06-24T00:00:00Z',
        read_endpoint: '/api/wiki/status',
        search_endpoint: '/api/wiki/search',
        notes: ['ready'],
        manifest: { enabled: true },
      },
      {
        package_id: 'source_vault',
        kind: 'source_vault',
        title: 'Source Vault',
        source_label: 'deduped originals and searchable chunks',
        status: 'missing',
        available: true,
        loaded: false,
        manifest_loaded: true,
        source_path: 'C:\\workspace_artifacts\\source_vault',
        source_hash: 'c'.repeat(64),
        content_hash: 'd'.repeat(64),
        updated_at: '2026-06-24T00:00:00Z',
        read_endpoint: '/api/knowledge/source-vault',
        search_endpoint: '/api/knowledge/source-vault/search',
        notes: [],
        manifest: { total_sources: 0 },
      },
      {
        package_id: 'skill_package:academic-english-discourse',
        kind: 'skill_package',
        title: 'Academic English Discourse',
        source_label: 'repo-local Skill package source',
        status: 'loaded',
        available: true,
        loaded: true,
        manifest_loaded: true,
        source_path: 'extension_packages/skills/academic-english-discourse/SKILL.md',
        source_hash: 'e'.repeat(64),
        content_hash: 'f'.repeat(64),
        updated_at: '2026-06-24T00:00:01Z',
        read_endpoint: '/api/knowledge/skill-packages/academic-english-discourse/status',
        search_endpoint: '/api/knowledge/skill-packages/academic-english-discourse/search',
        notes: ['Repo-local Skill package metadata is read-only; scripts are not executed.'],
        manifest: { chunk_count: 3 },
      },
      {
        package_id: 'config:scoring_rules',
        kind: 'config',
        title: 'Scoring Rules',
        source_label: 'repo-local JSON scoring configuration',
        status: 'loaded',
        available: true,
        loaded: true,
        manifest_loaded: true,
        source_path: 'literature_assistant/core/config/scoring_rules.json',
        source_hash: 'g'.repeat(64),
        content_hash: 'h'.repeat(64),
        updated_at: '2026-06-24T00:00:02Z',
        read_endpoint: '/api/knowledge/scoring-rules/status',
        search_endpoint: '/api/knowledge/scoring-rules/search',
        notes: ['Scoring rules config is read-only.'],
        manifest: { section_count: 4 },
      },
    ],
  })),
  getKnowledgeRuntimeConformance: vi.fn(async () => ({
    schema_version: 'scholar-ai-knowledge-runtime-conformance/v1',
    generated_at: '2026-06-24T00:00:03Z',
    pipeline: [
      'authoritative_source',
      'builder_or_loader',
      'structured_runtime_artifact',
      'searchable_index',
      'evidence_or_resource_ref',
      'bounded_context_loading',
      'prompt_assembly_context_receipt',
      'qa_agent_actual_loading_gate',
      'manifest_audit_test_proof',
    ],
    summary: {
      proved: 12,
      pending: 1,
      blocked: 3,
      not_applicable: 0,
    },
    actual_loading_gate: {
      status: 'blocked',
      evidence_level: 'contract_evidence',
      artifact_path: 'C:\\workspace\\workspace_artifacts\\generated\\output\\live_api_chat_knowledge_context_receipt_smoke.summary.json',
      artifact_ref: 'workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json',
      artifact_contract: 'scholar-ai-live-context-receipt-smoke/v1',
      artifact_exists: false,
      artifact_schema_valid: false,
      artifact_contract_valid: false,
      artifact_checked_at: '2026-06-26T03:39:00Z',
      verdict: 'missing_artifact',
      evidence_scope: ['/api/chat', 'assembled_context_hash_backflow'],
      evidence: [],
      missing: ['authorized live provider smoke artifact with verdict=ok'],
      validation_errors: [],
      required_checks: ['artifact.verdict.ok'],
      next_safe_local_actions: [
        'Require provider_preflight.status=proved before running live context-receipt smoke.',
      ],
      claim_boundary: 'Package conformance proves deterministic source-to-context receipts only.',
      provider_preflight: {
        status: 'blocked',
        evidence_level: 'contract_evidence',
        artifact_path: 'C:\\workspace\\workspace_artifacts\\runtime_state\\provider-capabilities.json',
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
            required_before_completion: true,
            requires_authorization: false,
          },
          {
            ref_type: 'live_smoke_harness',
            ref: 'workspace_tests/evaluation_scripts/live_api_chat_knowledge_context_receipt_smoke.py',
            status: 'authorization_required',
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
        package_id: 'wiki',
        kind: 'wiki',
        title: 'Wiki',
        overall_status: 'proved',
        loaded: true,
        source_path: 'C:\\workspace_artifacts\\wiki',
        source_hash: 'a'.repeat(64),
        content_hash: 'b'.repeat(64),
        read_endpoint: '/api/wiki/status',
        search_endpoint: '/api/wiki/search',
        manifest: { page_count: 1 },
        runtime_consumers: [{ consumer: 'api.wiki.search', use: 'searchable refs' }],
        mcp_tools: ['literature.wiki_search'],
        test_evidence: {
          focused_test_exists: true,
          source_edit_hash_test: true,
          context_receipt_test: true,
          evidence_pack_test: true,
          agent_resource_read_test: true,
          mcp_tool_test: true,
          test_nodes: ['tests/test_knowledge_router.py::test_wiki_runtime'],
        },
        conformance: [
          {
            requirement: 'authoritative_source',
            status: 'proved',
            evidence_level: 'runtime_projection',
            evidence_scope: ['runtime_status'],
            evidence: ['wiki manifest'],
            missing: [],
          },
        ],
      },
      {
        package_id: 'source_vault',
        kind: 'source_vault',
        title: 'Source Vault',
        overall_status: 'blocked',
        loaded: false,
        source_path: 'C:\\workspace_artifacts\\source_vault',
        source_hash: 'unknown',
        content_hash: 'd'.repeat(64),
        read_endpoint: '/api/knowledge/source-vault',
        search_endpoint: '/api/knowledge/source-vault/search',
        manifest: {
          total_sources: 0,
          empty_runtime: true,
          loaded_ref_count: 0,
          required_for_loaded_context: ['at least one source_assets row', 'at least one source_chunks row'],
        },
        runtime_consumers: [
          { consumer: 'literature.agent_resource_read', use: 'bounded source-vault chunk resource loading' },
        ],
        mcp_tools: ['literature.source_vault_search'],
        test_evidence: {
          focused_test_exists: true,
          source_edit_hash_test: true,
          context_receipt_test: true,
          evidence_pack_test: true,
          agent_resource_read_test: true,
          mcp_tool_test: true,
          test_nodes: ['tests/test_knowledge_router.py::test_source_vault_search_returns_chunk_hits'],
        },
        conformance: [
          {
            requirement: 'bounded_context_loading',
            status: 'blocked',
            evidence_level: 'runtime_projection',
            evidence_scope: ['read_endpoint', 'loaded_ref_count'],
            evidence: ['/api/knowledge/source-vault'],
            missing: ['loaded Source Vault chunks/resources'],
          },
          {
            requirement: 'agent_resource_read',
            status: 'blocked',
            evidence_level: 'runtime_projection',
            evidence_scope: ['agent_bridge_router', 'bounded_resource_read', 'loaded_ref_count'],
            evidence: [],
            missing: ['loaded Source Vault chunks/resources'],
          },
        ],
      },
    ],
  })),
}));

describe('KnowledgePackagesPanel', () => {
  it('renders the unified knowledge package registry and detail pane', async () => {
    render(
      <MemoryRouter>
        <KnowledgePackagesPanel />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByRole('heading', { name: '知识包注册表' })).toBeInTheDocument());
    const summaryCard = (() => {
      const heading = screen.getByRole('heading', { name: '知识包注册表' });
      const card = heading.closest('.rounded-md');
      if (!(card instanceof HTMLElement)) {
        throw new Error('Missing summary card');
      }
      return card;
    })();

    const getStatValue = (label: string): HTMLElement => {
      const statLabel = within(summaryCard).getByText(label, { exact: true });
      const card = statLabel.parentElement;
      const value = card?.lastElementChild;
      if (!(value instanceof HTMLElement)) {
        throw new Error(`Missing stat value for ${label}`);
      }
      return value;
    };

    expect(screen.getByRole('button', { name: 'Wiki' })).toBeInTheDocument();
    expect(screen.getByText('知识包注册表')).toBeInTheDocument();
    expect(getStatValue('知识包')).toHaveTextContent('4');
    expect(getStatValue('已加载')).toHaveTextContent('3');
    expect(getStatValue('可搜索')).toHaveTextContent('4');
    expect(getStatValue('KRT 阻断项')).toHaveTextContent('3');
    expect(screen.getByText('Live 模型门禁')).toBeInTheDocument();
    expect(screen.getByText('missing_artifact')).toBeInTheDocument();
    expect(screen.getByText('exists=false')).toBeInTheDocument();
    expect(screen.getByText('schema=false')).toBeInTheDocument();
    expect(screen.getByText('contract=false')).toBeInTheDocument();
    expect(screen.getByText('Recovery state')).toBeInTheDocument();
    expect(screen.getByText('blocked_provider_preflight_and_missing_live_smoke')).toBeInTheDocument();
    expect(screen.getByText('read_only=true')).toBeInTheDocument();
    expect(screen.getByText('blocked_by=2')).toBeInTheDocument();
    expect(screen.getAllByText('provider_ready=false').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('live_smoke_required=true')).toBeInTheDocument();
    expect(screen.getByText('live_smoke_harness · authorization_required · auth=true')).toBeInTheDocument();
    expect(screen.getByText('Provider preflight')).toBeInTheDocument();
    expect(screen.getByText('auth_required')).toBeInTheDocument();
    expect(screen.getByText('records=1')).toBeInTheDocument();
    expect(screen.getAllByText('auth_required=1').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('tool_call_ok=0')).toBeInTheDocument();
    expect(screen.getByText('hhl · free.hanhanapi.top · gpt-5.5 · auth_required')).toBeInTheDocument();
    expect(screen.getByText('provider_tool_call_status=tool_call_ok')).toBeInTheDocument();
    expect(screen.getByText(/Stop live actual-loading smoke while latest provider status is auth_required/)).toBeInTheDocument();
    expect(
      screen.getByText('workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json'),
    ).toBeInTheDocument();
    expect(screen.getByText('authorized live provider smoke artifact with verdict=ok')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Source Vault' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Academic English Discourse' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Scoring Rules' })).toBeInTheDocument();
    expect(screen.getByText('/api/wiki/status')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Source Vault' }));
    expect(
      within(screen.getByRole('complementary')).getByText('deduped originals and searchable chunks'),
    ).toBeInTheDocument();
    expect(within(screen.getByRole('complementary')).getByText('已阻断')).toBeInTheDocument();
    const sourceVaultAlert = screen
      .getAllByRole('alert')
      .find((alert) => alert.textContent?.includes('Knowledge Runtime Pipeline 阻断'));
    if (!(sourceVaultAlert instanceof HTMLElement)) {
      throw new Error('Missing Source Vault blocker alert');
    }
    expect(sourceVaultAlert).toHaveTextContent('Knowledge Runtime Pipeline 阻断');
    expect(sourceVaultAlert).toHaveTextContent('loaded_ref_count');
    expect(sourceVaultAlert).toHaveTextContent('0');
    expect(sourceVaultAlert).toHaveTextContent('bounded context loading');
    expect(sourceVaultAlert).toHaveTextContent('loaded Source Vault chunks/resources');
    expect(sourceVaultAlert).toHaveTextContent('at least one source_assets row');
    expect(screen.getByText('运行时证据链')).toBeInTheDocument();
    expect(screen.getByText('literature.agent_resource_read · bounded source-vault chunk resource loading')).toBeInTheDocument();
    expect(screen.getByText('literature.source_vault_search')).toBeInTheDocument();
    expect(screen.getByText('context receipt: proved')).toBeInTheDocument();
    expect(screen.getByText('agent resource read: proved')).toBeInTheDocument();
    expect(screen.getByText('tests/test_knowledge_router.py::test_source_vault_search_returns_chunk_hits')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '刷新' }));
    expect(await screen.findByRole('button', { name: 'Wiki' })).toBeInTheDocument();
  });
});
