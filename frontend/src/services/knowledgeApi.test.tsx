import { beforeEach, describe, expect, it, vi } from 'vitest';

const get = vi.hoisted(() => vi.fn());

vi.mock('axios', () => ({
  default: {
    get,
  },
}));

vi.mock('./apiBaseUrl', () => ({
  getApiBaseUrl: () => 'http://127.0.0.1:8000',
}));

import axios from 'axios';
import {
  getKnowledgePackages,
  getKnowledgeRuntimeConformance,
  parseKnowledgePackageProjection,
  parseKnowledgePackagesResponse,
  parseKnowledgeRuntimeConformanceResponse,
} from './knowledgeApi';

const mockedAxios = axios as unknown as {
  get: typeof get;
};

beforeEach(() => {
  mockedAxios.get.mockClear();
});

describe('knowledgeApi.parseKnowledgePackagesResponse', () => {
  it('accepts the unified registry shape for all knowledge packages', () => {
    const parsed = parseKnowledgePackagesResponse({
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
          source_path: 'C:\\workspace\\wiki',
          source_hash: 'a'.repeat(64),
          content_hash: 'b'.repeat(64),
          updated_at: '2026-06-24T08:00:00Z',
          read_endpoint: '/api/wiki/status',
          search_endpoint: '/api/wiki/search',
          notes: ['ready'],
          manifest: { page_count: 1, integrity_status: 'aligned' },
        },
        {
          package_id: 'source_vault',
          kind: 'source_vault',
          title: 'Source Vault',
          source_label: 'deduped originals and searchable chunks',
          status: 'loaded',
          available: true,
          loaded: true,
          manifest_loaded: true,
          source_path: 'C:\\workspace\\source_vault',
          source_hash: 'c'.repeat(64),
          content_hash: 'd'.repeat(64),
          updated_at: '2026-06-24T08:00:01Z',
          read_endpoint: '/api/knowledge/source-vault',
          search_endpoint: '/api/knowledge/source-vault/search',
          notes: [],
          manifest: { total_sources: 1, total_project_links: 2 },
        },
        {
          package_id: 'academic_english',
          kind: 'academic_english',
          title: 'Academic English',
          source_label: 'generated discourse habits and phrase resources',
          status: 'missing',
          available: false,
          loaded: false,
          manifest_loaded: false,
          source_path: 'C:\\workspace\\english_discourse',
          source_hash: 'e'.repeat(64),
          content_hash: 'f'.repeat(64),
          updated_at: 'unknown',
          read_endpoint: '/api/knowledge/academic-english/status',
          search_endpoint: '/api/knowledge/academic-english/search',
          notes: ['Academic English policy source is not currently loaded.'],
          manifest: { manifest_loaded: false },
        },
        {
          package_id: 'bridge_lexicon',
          kind: 'bridge_lexicon',
          title: 'Bridge Lexicon',
          source_label: 'CJK bridge expansion terms',
          status: 'loaded',
          available: true,
          loaded: true,
          manifest_loaded: true,
          source_path: 'C:\\workspace\\bridge_lexicon.json',
          source_hash: 'g'.repeat(64),
          content_hash: 'h'.repeat(64),
          updated_at: '2026-06-24T08:00:02Z',
          read_endpoint: '/api/knowledge/bridge-lexicon/status',
          search_endpoint: null,
          notes: ['Bridge lexicon is loaded.'],
          manifest: { entry_count: 2, runtime_consumers: [] },
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
          source_hash: 'i'.repeat(64),
          content_hash: 'j'.repeat(64),
          updated_at: '2026-06-24T08:00:03Z',
          read_endpoint: '/api/knowledge/skill-packages/academic-english-discourse/status',
          search_endpoint: '/api/knowledge/skill-packages/academic-english-discourse/search',
          notes: ['Repo-local Skill package metadata is read-only; scripts are not executed.'],
          manifest: { chunk_count: 3, high_risk_flags: ['script.execute'] },
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
          source_hash: 'k'.repeat(64),
          content_hash: 'l'.repeat(64),
          updated_at: '2026-06-24T08:00:04Z',
          read_endpoint: '/api/knowledge/scoring-rules/status',
          search_endpoint: '/api/knowledge/scoring-rules/search',
          notes: ['Scoring rules config is read-only.'],
          manifest: { config_id: 'scoring_rules', section_count: 4 },
        },
        {
          package_id: 'product_docs',
          kind: 'product_docs',
          title: 'Product Documentation',
          source_label: 'repo-local README and product docs',
          status: 'loaded',
          available: true,
          loaded: true,
          manifest_loaded: true,
          source_path: 'README.md + docs/*.md',
          source_hash: 'm'.repeat(64),
          content_hash: 'n'.repeat(64),
          updated_at: '2026-06-24T08:00:05Z',
          read_endpoint: '/api/knowledge/product-docs/status',
          search_endpoint: '/api/knowledge/product-docs/search',
          notes: ['Product documentation is read-only.'],
          manifest: { source_count: 2, chunk_count: 4 },
        },
      ],
    });

    expect(parsed.schema_version).toBe('scholar-ai-knowledge-packages/v1');
    expect(parsed.packages.map((item) => item.package_id)).toEqual([
      'wiki',
      'source_vault',
      'academic_english',
      'bridge_lexicon',
      'skill_package:academic-english-discourse',
      'config:scoring_rules',
      'product_docs',
    ]);
    expect(parsed.packages[0].manifest.integrity_status).toBe('aligned');
    expect(parsed.packages[2].search_endpoint).toBe('/api/knowledge/academic-english/search');
  });

  it('rejects malformed package projections', () => {
    expect(() =>
      parseKnowledgePackageProjection({
        package_id: 'wiki',
        kind: 'wiki',
        title: 'Wiki',
        source_label: 'generated wiki pages',
        status: 'loaded',
        available: true,
        loaded: true,
        manifest_loaded: true,
        source_path: 'C:\\workspace\\wiki',
        source_hash: 'a'.repeat(64),
        content_hash: 'b'.repeat(64),
        updated_at: '2026-06-24T08:00:00Z',
        read_endpoint: '/api/wiki/status',
        search_endpoint: '/api/wiki/search',
        notes: 'ready',
        manifest: {},
      }),
    ).toThrow('notes must be a string array');
  });
});

describe('knowledgeApi.getKnowledgePackages', () => {
  beforeEach(() => {
    mockedAxios.get.mockClear();
  });

  it('loads the unified registry from the contract route', async () => {
    mockedAxios.get.mockResolvedValueOnce({
      data: {
        schema_version: 'scholar-ai-knowledge-packages/v1',
        packages: [],
      },
    });

    const parsed = await getKnowledgePackages();

    expect(parsed.schema_version).toBe('scholar-ai-knowledge-packages/v1');
    expect(mockedAxios.get).toHaveBeenCalledWith('http://127.0.0.1:8000/api/knowledge/packages');
  });
});

describe('knowledgeApi.parseKnowledgeRuntimeConformanceResponse', () => {
  it('accepts the runtime conformance proof shape used by the workbench', () => {
    const parsed = parseKnowledgeRuntimeConformanceResponse({
      schema_version: 'scholar-ai-knowledge-runtime-conformance/v1',
      generated_at: '2026-06-24T08:00:06Z',
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
        proved: 9,
        pending: 1,
        blocked: 2,
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
        required_checks: [
          'artifact.verdict.ok',
          'artifact.chat_evidence.required_tools',
          'artifact.receipt_hash.final_answer',
        ],
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
          package_id: 'source_vault',
          kind: 'source_vault',
          title: 'Source Vault',
          overall_status: 'blocked',
          loaded: false,
          source_path: 'C:\\workspace\\source_vault',
          source_hash: 'unknown',
          content_hash: 'd'.repeat(64),
          read_endpoint: '/api/knowledge/source-vault',
          search_endpoint: '/api/knowledge/source-vault/search',
          manifest: {
            empty_runtime: true,
            loaded_ref_count: 0,
            required_for_loaded_context: ['source_assets', 'source_chunks'],
          },
          runtime_consumers: [
            {
              consumer: 'literature_assistant.core.routers.agent_bridge_router',
              use: 'bounded source-vault chunk resource loading',
            },
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
          ],
        },
      ],
    });

    expect(parsed.schema_version).toBe('scholar-ai-knowledge-runtime-conformance/v1');
    expect(parsed.summary.blocked).toBe(2);
    expect(parsed.actual_loading_gate.status).toBe('blocked');
    expect(parsed.actual_loading_gate.artifact_ref).toBe(
      'workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json',
    );
    expect(parsed.actual_loading_gate.artifact_contract).toBe('scholar-ai-live-context-receipt-smoke/v1');
    expect(parsed.actual_loading_gate.artifact_exists).toBe(false);
    expect(parsed.actual_loading_gate.artifact_schema_valid).toBe(false);
    expect(parsed.actual_loading_gate.artifact_contract_valid).toBe(false);
    expect(parsed.actual_loading_gate.artifact_checked_at).toBe('2026-06-26T03:39:00Z');
    expect(parsed.actual_loading_gate.verdict).toBe('missing_artifact');
    expect(parsed.actual_loading_gate.missing).toEqual(['authorized live provider smoke artifact with verdict=ok']);
    expect(parsed.actual_loading_gate.validation_errors).toEqual([]);
    expect(parsed.actual_loading_gate.required_checks).toContain('artifact.receipt_hash.final_answer');
    expect(parsed.actual_loading_gate.next_safe_local_actions[0]).toBe(
      'Require provider_preflight.status=proved before running live context-receipt smoke.',
    );
    expect(parsed.actual_loading_gate.provider_preflight.status).toBe('blocked');
    expect(parsed.actual_loading_gate.provider_preflight.latest_status).toBe('auth_required');
    expect(parsed.actual_loading_gate.provider_preflight.status_counts).toEqual({ auth_required: 1 });
    expect(parsed.actual_loading_gate.provider_preflight.auth_required_count).toBe(1);
    expect(parsed.actual_loading_gate.provider_preflight.tool_call_ok_count).toBe(0);
    expect(parsed.actual_loading_gate.provider_preflight.provider_ready_for_authorized_live_smoke).toBe(false);
    expect(parsed.actual_loading_gate.provider_preflight.next_safe_local_actions[0]).toBe(
      'Stop live actual-loading smoke while latest provider status is auth_required.',
    );
    expect(parsed.actual_loading_gate.provider_preflight.records[0].base_url_host).toBe('free.hanhanapi.top');
    expect(parsed.actual_loading_gate.recovery.state).toBe('blocked_provider_preflight_and_missing_live_smoke');
    expect(parsed.actual_loading_gate.recovery.blocked_by).toContain('live_smoke:missing_artifact');
    expect(parsed.actual_loading_gate.recovery.recovery_refs[1].requires_authorization).toBe(true);
    expect(parsed.packages[0].overall_status).toBe('blocked');
    expect(parsed.packages[0].manifest.empty_runtime).toBe(true);
    expect(parsed.packages[0].runtime_consumers[0].consumer).toBe(
      'literature_assistant.core.routers.agent_bridge_router',
    );
    expect(parsed.packages[0].test_evidence.context_receipt_test).toBe(true);
    expect(parsed.packages[0].conformance[0].missing).toEqual(['loaded Source Vault chunks/resources']);
  });

  it('rejects malformed runtime conformance evidence', () => {
    expect(() =>
      parseKnowledgeRuntimeConformanceResponse({
        schema_version: 'scholar-ai-knowledge-runtime-conformance/v1',
        generated_at: '2026-06-24T08:00:06Z',
        pipeline: ['authoritative_source'],
        summary: {
          proved: '9',
        },
        packages: [],
      }),
    ).toThrow('summary.proved must be a finite number');

    expect(() =>
      parseKnowledgeRuntimeConformanceResponse({
        schema_version: 'scholar-ai-knowledge-runtime-conformance/v1',
        generated_at: '2026-06-24T08:00:06Z',
        pipeline: ['authoritative_source'],
        summary: {
          proved: 1,
        },
        actual_loading_gate: {
          status: 'blocked',
          evidence_level: 'contract_evidence',
          artifact_path: 'C:\\workspace\\live_api_chat_knowledge_context_receipt_smoke.summary.json',
          artifact_ref: 'workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json',
          artifact_contract: 'scholar-ai-live-context-receipt-smoke/v1',
          artifact_exists: false,
          artifact_schema_valid: false,
          artifact_contract_valid: false,
          artifact_checked_at: '2026-06-26T03:39:00Z',
          verdict: 'missing_artifact',
          evidence_scope: [],
          evidence: [],
          missing: ['authorized live provider smoke artifact with verdict=ok'],
          validation_errors: [],
          required_checks: ['artifact.verdict.ok'],
          next_safe_local_actions: [],
          claim_boundary: '',
          provider_preflight: {
            status: 'pending',
            evidence_level: 'contract_evidence',
            artifact_path: 'C:\\workspace\\provider-capabilities.json',
            artifact_ref: 'workspace_artifacts/runtime_state/provider-capabilities.json',
            artifact_exists: false,
            artifact_schema_valid: false,
            checked_at: '2026-06-26T03:40:00Z',
            record_count: 0,
            latest_status: 'unknown',
            status_counts: {},
            auth_required_count: 0,
            tool_call_ok_count: 0,
            provider_ready_for_authorized_live_smoke: false,
            records: [],
            evidence_scope: [],
            evidence: [],
            missing: ['provider tool-call capability preflight record'],
            validation_errors: [],
            next_safe_local_actions: [],
            claim_boundary: '',
          },
          recovery: {
            schema_version: 'scholar-ai-knowledge-runtime-recovery/v1',
            read_only: true,
            state: 'blocked_provider_preflight_and_missing_live_smoke',
            blocked_by: ['provider_preflight:pending:unknown'],
            recovery_refs: [],
            provider_ready_for_authorized_live_smoke: false,
            completion_requires_authorized_live_smoke: true,
          },
        },
        packages: [
          {
            package_id: 'wiki',
            kind: 'wiki',
            title: 'Wiki',
            overall_status: 'maybe',
            loaded: true,
            source_path: 'C:\\workspace\\wiki',
            source_hash: 'a'.repeat(64),
            content_hash: 'b'.repeat(64),
            read_endpoint: '/api/wiki/status',
            search_endpoint: '/api/wiki/search',
            manifest: {},
            runtime_consumers: [],
            mcp_tools: [],
            test_evidence: {
              focused_test_exists: true,
              source_edit_hash_test: true,
              context_receipt_test: true,
              evidence_pack_test: true,
              agent_resource_read_test: true,
              mcp_tool_test: true,
              test_nodes: [],
            },
            conformance: [],
          },
        ],
      }),
    ).toThrow('conformance status is unknown');
  });
});

describe('knowledgeApi.getKnowledgeRuntimeConformance', () => {
  beforeEach(() => {
    mockedAxios.get.mockClear();
  });

  it('loads the runtime conformance registry from the contract route', async () => {
    mockedAxios.get.mockResolvedValueOnce({
      data: {
        schema_version: 'scholar-ai-knowledge-runtime-conformance/v1',
        generated_at: '2026-06-24T08:00:06Z',
        pipeline: [],
        summary: {},
        actual_loading_gate: {
          status: 'blocked',
          evidence_level: 'contract_evidence',
          artifact_path: 'C:\\workspace\\live_api_chat_knowledge_context_receipt_smoke.summary.json',
          artifact_ref: 'workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json',
          artifact_contract: 'scholar-ai-live-context-receipt-smoke/v1',
          artifact_exists: false,
          artifact_schema_valid: false,
          artifact_contract_valid: false,
          artifact_checked_at: '2026-06-26T03:39:00Z',
          verdict: 'missing_artifact',
          evidence_scope: [],
          evidence: [],
          missing: ['authorized live provider smoke artifact with verdict=ok'],
          validation_errors: [],
          required_checks: ['artifact.verdict.ok'],
          next_safe_local_actions: [],
          claim_boundary: '',
          provider_preflight: {
            status: 'pending',
            evidence_level: 'contract_evidence',
            artifact_path: 'C:\\workspace\\provider-capabilities.json',
            artifact_ref: 'workspace_artifacts/runtime_state/provider-capabilities.json',
            artifact_exists: false,
            artifact_schema_valid: false,
            checked_at: '2026-06-26T03:40:00Z',
            record_count: 0,
            latest_status: 'unknown',
            status_counts: {},
            auth_required_count: 0,
            tool_call_ok_count: 0,
            provider_ready_for_authorized_live_smoke: false,
            records: [],
            evidence_scope: [],
            evidence: [],
            missing: ['provider tool-call capability preflight record'],
            validation_errors: [],
            next_safe_local_actions: [],
            claim_boundary: '',
          },
          recovery: {
            schema_version: 'scholar-ai-knowledge-runtime-recovery/v1',
            read_only: true,
            state: 'blocked_provider_preflight_and_missing_live_smoke',
            blocked_by: ['provider_preflight:pending:unknown'],
            recovery_refs: [],
            provider_ready_for_authorized_live_smoke: false,
            completion_requires_authorized_live_smoke: true,
          },
        },
        packages: [],
      },
    });

    const parsed = await getKnowledgeRuntimeConformance();

    expect(parsed.schema_version).toBe('scholar-ai-knowledge-runtime-conformance/v1');
    expect(mockedAxios.get).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/knowledge/runtime-conformance',
    );
  });
});
