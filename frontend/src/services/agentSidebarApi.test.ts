import { beforeEach, describe, expect, it, vi } from 'vitest';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());

vi.mock('axios', () => ({
  default: {
    get,
    post,
  },
}));

vi.mock('./apiBaseUrl', () => ({
  getApiBaseUrl: () => 'http://127.0.0.1:8000',
}));

import axios from 'axios';
import {
  agentSidebarEvidenceToPill,
  buildAgentSidebarReceiptMarkdown,
  createAgentSidebarAnswerRequest,
  listAgentSidebarReceipts,
  openAgentSidebarDesktop,
  parseAnswerRequestResponse,
  parseDesktopOpenResponse,
  parseReceiptReadResponse,
  revalidateAgentSidebarReceipt,
} from './agentSidebarApi';

const mockedAxios = axios as unknown as {
  get: typeof get;
  post: typeof post;
};

const visualObservationRefs = [
  {
    schema_version: 'scholar-ai-visual-observation-ref/v1',
    candidate_id: 'visual-candidate-direct',
    turn_id: 'turn-sidebar-1',
    route: 'direct_model',
    generation_status: 'succeeded',
    review_status: 'candidate',
    selection_ids: ['selection-text-1', 'selection-formula-1'],
    output_sha256: `sha256:${'1'.repeat(64)}`,
    cache_status: 'miss',
    read_endpoint: '/api/chat/visual-observations/visual-candidate-direct',
  },
  {
    schema_version: 'scholar-ai-visual-observation-ref/v1',
    candidate_id: 'visual-candidate-failed',
    turn_id: 'turn-sidebar-1',
    route: 'vision_aux_mcp',
    generation_status: 'failed',
    review_status: 'stale',
    selection_ids: ['selection-figure-1'],
    cache_status: 'unavailable',
    read_endpoint: '/api/chat/visual-observations/visual-candidate-failed',
  },
  {
    schema_version: 'scholar-ai-visual-observation-ref/v1',
    candidate_id: 'visual-candidate-cached',
    turn_id: 'turn-sidebar-1',
    route: 'vision_aux_mcp',
    generation_status: 'succeeded',
    review_status: 'accepted',
    selection_ids: ['selection-table-1'],
    output_sha256: `sha256:${'2'.repeat(64)}`,
    cache_status: 'hit',
    cache_key_hash: `sha256:${'3'.repeat(64)}`,
    read_endpoint: '/api/chat/visual-observations/visual-candidate-cached',
  },
] as const;

const receiptPayload = {
  conversation_id: 'session-sidebar-1',
  project_id: 'project-a',
  answer: 'The saved answer uses bounded evidence [1].',
  receipt: {
    receipt_schema_version: 'scholar-ai-answer-receipt/v1',
    question: 'What evidence supports the claim?',
    generated_in: 'mcp_sidebar',
    answer_origin: 'host_agent',
    answer_model: 'codex-host',
    evidence_pack_ref: 'evidence_pack:abc',
    lifecycle_state: 'saved',
    qrels_status: {
      schema_version: 'retrieval-qrels-status/v1',
      status: 'candidate',
      candidate_qrels_count: 1,
      semantic_quality_claim_allowed: false,
      qrels_content_hash: 'sha256:qrels',
    },
    evidence_gate_status: {
      status: 'passed',
      gate_config_hash: 'sha256:gate',
    },
    retrieval_diagnostics: {
      retrieval_method: 'hybrid',
      retrieval_provider: 'scholar_ai',
      rerank_status: 'active',
    },
    top_evidence_refs: [
      {
        ref_id: 'chunk:1',
        chunk_id: 'chunk-1',
        material_id: 'mat-1',
        page: 3,
        source_title: 'Paper A',
        summary: 'Bounded evidence.',
      },
    ],
    visual_observation_refs: visualObservationRefs,
    knowledge_consumer_refs: {
      read_only: true,
      agent_request_id: 'agentreq_wiki_graph',
      runtime_job_id: 'job-wiki-graph',
      project_id: 'project-a',
      wiki_candidate_ref: {
        ref_type: 'wiki_candidate_review_page',
        ref_id: 'wiki:synthesis/agent-result.md',
        read_endpoint: '/api/agent-bridge/resource/wiki:synthesis/agent-result.md',
        page_path: 'synthesis/agent-result.md',
        slug: 'synthesis-agent-result',
        status: 'draft',
        read_only: true,
      },
      wiki_review_item_ref: {
        ref_type: 'wiki_review_queue_item',
        endpoint: '/api/wiki/review',
        item_id: 'review_wiki_graph',
        read_only: true,
      },
      graph_candidate_ref: {
        ref_type: 'graph_candidate',
        status: 'attached_to_wiki_candidate',
        graph_patch_ref_count: 1,
        wiki_slug: 'synthesis-agent-result',
        read_endpoint: '/api/agent-bridge/resource/wiki:synthesis/agent-result.md',
        read_only: true,
      },
    },
  },
  staleness: {
    status: 'saved',
    checked: ['qrels_content_hash', 'gate_config_hash', 'evidence_pack_ref'],
    warnings: [],
    mismatches: [],
  },
};

beforeEach(() => {
  mockedAxios.get.mockReset();
  mockedAxios.post.mockReset();
});

describe('agentSidebarApi', () => {
  it('parses saved answer receipts and projects bounded handoff markdown', () => {
    const parsed = parseReceiptReadResponse(receiptPayload);

    expect(parsed.receipt.generated_in).toBe('mcp_sidebar');
    expect(parsed.receipt.qrels_status?.status).toBe('candidate');
    expect(parsed.receipt.evidence_gate_status?.status).toBe('passed');
    expect(parsed.receipt.top_evidence_refs[0].source_title).toBe('Paper A');
    expect(parsed.receipt.knowledge_consumer_refs?.read_only).toBe(true);
    expect(parsed.receipt.knowledge_consumer_refs?.wiki_candidate_ref?.status).toBe('draft');
    expect(parsed.receipt.knowledge_consumer_refs?.graph_candidate_ref?.graph_patch_ref_count).toBe(1);
    expect(parsed.receipt.visual_observation_refs).toEqual(visualObservationRefs);

    const markdown = buildAgentSidebarReceiptMarkdown(parsed);
    expect(markdown).toContain('### 回答');
    expect(markdown).toContain('### 证据状态');
    expect(markdown).toContain('qrels: candidate；允许质量声明: 否');
    expect(markdown).toContain('[E1] Paper A, 第 3 页，chunk:1');
    expect(markdown).toContain('### 后续动作');
  });

  it('rejects polluted or forged visual observation references as complete items', () => {
    const parsed = parseReceiptReadResponse({
      ...receiptPayload,
      receipt: {
        ...receiptPayload.receipt,
        visual_observation_refs: [
          {
            ...visualObservationRefs[0],
            output_text: 'candidate output must not hitchhike inside a receipt reference',
          },
          {
            ...visualObservationRefs[1],
            read_endpoint: 'https://example.test/visual-candidate-failed',
          },
        ],
      },
    });

    expect(parsed.receipt.visual_observation_refs).toEqual([]);
  });

  it('keeps exact evidence fields in pills and never promotes summary over text or quote', () => {
    const parsed = parseReceiptReadResponse({
      ...receiptPayload,
      receipt: {
        ...receiptPayload.receipt,
        top_evidence_refs: [{
          ref_id: 'chunk:exact',
          chunk_id: 'chunk-exact',
          material_id: 'material-exact',
          page: 8,
          bbox: [72, 144, 180, 36],
          bbox_unit: 'pdf_points',
          source: 'Exact paper.pdf',
          summary: 'Generated summary must stay a fallback.',
          text: 'Full chunk text.',
          quote: 'Exact sentence quote.',
          anchor_kind: 'text',
          content_hash: 'a'.repeat(64),
          locator_hash: 'b'.repeat(64),
          chunk_hash: 'c'.repeat(64),
          embedding_input_hash: 'd'.repeat(64),
          hash_version: 'scholar-ai-chunk-hash/v2',
        }],
      },
    });

    expect(agentSidebarEvidenceToPill(parsed.receipt.top_evidence_refs[0])).toMatchObject({
      text: 'Full chunk text.',
      quote: 'Exact sentence quote.',
      anchor_kind: 'text',
      bbox: [72, 144, 180, 36],
      bbox_unit: 'pdf_points',
      content_hash: 'a'.repeat(64),
      locator_hash: 'b'.repeat(64),
      chunk_hash: 'c'.repeat(64),
      embedding_input_hash: 'd'.repeat(64),
      hash_version: 'scholar-ai-chunk-hash/v2',
    });
  });

  it('degrades a unitless Sidebar bbox to page-only evidence', () => {
    const parsed = parseReceiptReadResponse({
      ...receiptPayload,
      receipt: {
        ...receiptPayload.receipt,
        top_evidence_refs: [{
          ref_id: 'chunk:unitless',
          chunk_id: 'chunk-unitless',
          material_id: 'material-unitless',
          page: 6,
          bbox: [0.1, 0.2, 0.4, 0.1],
          text: 'Unitless evidence.',
          quote: 'Unitless quote.',
        }],
      },
    });

    expect(agentSidebarEvidenceToPill(parsed.receipt.top_evidence_refs[0])).toMatchObject({
      page: 6,
      bbox: null,
      bbox_unit: null,
    });
  });

  it('normalizes non-canonical qrels so handoff cannot claim semantic retrieval quality', async () => {
    mockedAxios.post.mockResolvedValueOnce({
      data: {
        request_id: 'agentreq_qrels_boundary',
        job: {
          job_id: 'job-qrels-boundary',
          status: 'in_progress',
          metadata: {},
        },
        poll: { job: '/runtime/job/job-qrels-boundary' },
        envelope: {
          intent: 'sidebar_answer',
          project_id: 'project-a',
          user_text: 'What evidence supports the claim?',
          resource_refs: [{ ref_id: 'chunk:1', kind: 'chunk', project_id: 'project-a' }],
        },
      },
    });
    const parsed = parseReceiptReadResponse({
      ...receiptPayload,
      receipt: {
        ...receiptPayload.receipt,
        qrels_status: {
          ...receiptPayload.receipt.qrels_status,
          status: 'candidate',
          semantic_quality_claim_allowed: true,
          quality_claim: 'semantic retrieval quality is confirmed',
        },
      },
    });

    expect(parsed.receipt.qrels_status?.semantic_quality_claim_allowed).toBe(false);
    expect(parsed.receipt.qrels_status?.quality_claim).toBeUndefined();
    expect(buildAgentSidebarReceiptMarkdown(parsed)).toContain('qrels: candidate；允许质量声明: 否');

    await createAgentSidebarAnswerRequest(parsed, { projectId: 'project-a', agentHost: 'codex' });
    const payload = mockedAxios.post.mock.calls[0]?.[1] as {
      metadata?: { qrels_status?: { semantic_quality_claim_allowed?: unknown; quality_claim?: unknown } };
    };
    expect(payload.metadata?.qrels_status?.semantic_quality_claim_allowed).toBe(false);
    expect(payload.metadata?.qrels_status?.quality_claim).toBeUndefined();
  });

  it('calls the existing receipt list and revalidate routes without a sidebar-specific schema', async () => {
    mockedAxios.get.mockResolvedValueOnce({
      data: {
        project_id: 'project-a',
        receipts: [
          {
            conversation_id: 'session-sidebar-1',
            project_id: 'project-a',
            title: '',
            mode: 'literature_qa',
            created_at: '2026-07-07T00:00:00Z',
            updated_at: '2026-07-07T00:00:01Z',
            lifecycle_state: 'saved',
            staleness_status: 'saved',
            receipt: receiptPayload.receipt,
          },
        ],
      },
    });
    mockedAxios.post.mockResolvedValueOnce({
      data: {
        conversation_id: 'session-sidebar-1',
        project_id: 'project-a',
        applied: false,
        apply_allowed: true,
        status: 'ready',
        previous_staleness: receiptPayload.staleness,
        revalidated_staleness: receiptPayload.staleness,
        top_ref_delta: { changed: false },
        receipt: receiptPayload.receipt,
        evidence_pack: { evidence_pack_ref: 'evidence_pack:def' },
        gate: { status: 'passed' },
      },
    });

    const list = await listAgentSidebarReceipts('project-a', 7);
    const revalidated = await revalidateAgentSidebarReceipt('session-sidebar-1', { apply: false, topK: 7 });

    expect(list.receipts).toHaveLength(1);
    expect(list.receipts[0]?.receipt.visual_observation_refs).toEqual(visualObservationRefs);
    expect(mockedAxios.get).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/chat/answer-receipts',
      { params: { project_id: 'project-a', limit: 7 }, timeout: 15000 },
    );
    expect(revalidated.status).toBe('ready');
    expect(revalidated.receipt.visual_observation_refs).toEqual(visualObservationRefs);
    expect(mockedAxios.post).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/chat/answer-receipts/session-sidebar-1/revalidate',
      { apply: false, top_k: 7 },
      { timeout: 60000 },
    );
  });

  it('creates sidebar_answer handoff requests through the existing agent bridge', async () => {
    mockedAxios.post.mockResolvedValueOnce({
      data: {
        request_id: 'agentreq_sidebar',
        job: {
          job_id: 'job-sidebar',
          status: 'in_progress',
          metadata: {
            output_targets: {
              smart_read_conversation: true,
              wiki_candidate: false,
              graph_candidate: false,
              evolution_capture: false,
            },
          },
        },
        poll: { job: '/runtime/job/job-sidebar' },
        envelope: {
          intent: 'sidebar_answer',
          project_id: 'project-a',
          user_text: 'What evidence supports the claim?',
          resource_refs: [{ ref_id: 'chunk:1', kind: 'chunk', project_id: 'project-a' }],
        },
      },
    });

    const parsed = parseReceiptReadResponse(receiptPayload);
    const request = await createAgentSidebarAnswerRequest(parsed, { projectId: 'project-a', agentHost: 'codex' });

    expect(request.request_id).toBe('agentreq_sidebar');
    expect(request.envelope.intent).toBe('sidebar_answer');
    expect(request.envelope.resource_refs?.[0].ref_id).toBe('chunk:1');
    expect(mockedAxios.post).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/agent-bridge/request',
      expect.objectContaining({
        source: 'agent_sidebar',
        agent_host: 'codex',
        intent: 'sidebar_answer',
        user_text: 'What evidence supports the claim?',
        project_id: 'project-a',
        route: '/agent-sidebar',
        context_budget: {
          max_chars: 12000,
          max_chunks: 12,
          include_full_text: false,
        },
        output_targets: {
          runtime_job: true,
          smart_read_conversation: true,
          agent_workspace: true,
          wiki_candidate: false,
          graph_candidate: false,
          evolution_capture: false,
        },
        metadata: expect.objectContaining({
          source_conversation_id: 'session-sidebar-1',
          receipt_schema_version: 'scholar-ai-answer-receipt/v1',
          evidence_pack_ref: 'evidence_pack:abc',
          generated_in: 'mcp_sidebar',
          qrels_status: expect.objectContaining({ status: 'candidate' }),
          evidence_gate_status: expect.objectContaining({ status: 'passed' }),
        }),
      }),
      { timeout: 15000 },
    );
  });

  it('can create desktop-origin Claude handoff requests without changing the shared schema', async () => {
    mockedAxios.post.mockResolvedValueOnce({
      data: {
        request_id: 'agentreq_desktop',
        job: {
          job_id: 'job-desktop',
          status: 'started',
          metadata: {},
        },
        poll: { job: '/runtime/job/job-desktop' },
        envelope: {
          intent: 'sidebar_answer',
          project_id: 'project-a',
          user_text: 'What evidence supports the claim?',
          resource_refs: [{ ref_id: 'chunk:1', kind: 'chunk', project_id: 'project-a' }],
        },
      },
    });

    const parsed = parseReceiptReadResponse(receiptPayload);
    const request = await createAgentSidebarAnswerRequest(parsed, {
      projectId: 'project-a',
      agentHost: 'claude',
      source: 'desktop',
      route: '/dialog',
      generatedIn: 'desktop_dialog',
    });

    expect(request.request_id).toBe('agentreq_desktop');
    expect(mockedAxios.post).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/agent-bridge/request',
      expect.objectContaining({
        source: 'desktop',
        agent_host: 'claude',
        intent: 'sidebar_answer',
        route: '/dialog',
        output_targets: expect.objectContaining({
          smart_read_conversation: true,
          wiki_candidate: false,
          graph_candidate: false,
          evolution_capture: false,
        }),
        metadata: expect.objectContaining({
          source_conversation_id: 'session-sidebar-1',
          generated_in: 'desktop_dialog',
        }),
      }),
      { timeout: 15000 },
    );
  });

  it('rejects malformed agent request responses', () => {
    expect(() => parseAnswerRequestResponse({ job: { job_id: 'job-1' } })).toThrow(/request_id/);
    expect(() => parseAnswerRequestResponse({ request_id: 'agentreq_1', job: {} })).toThrow(/job_id/);
  });

  it('opens the native desktop through the agent bridge desktop route', async () => {
    mockedAxios.post.mockResolvedValueOnce({
      data: {
        schema_version: 'scholar-ai-agent-sidebar-desktop-open/v1',
        status: 'running',
        started: false,
        product_name: 'Scholar AI',
        window_title: '文献助手',
        base_url: 'http://127.0.0.1:8000',
        pid: 1234,
        focused: true,
        message: '文献助手桌面端已在运行。',
      },
    });

    const opened = await openAgentSidebarDesktop();

    expect(opened.window_title).toBe('文献助手');
    expect(opened.started).toBe(false);
    expect(opened.focused).toBe(true);
    expect(mockedAxios.post).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/agent-bridge/desktop/open',
      {},
      { timeout: 15000 },
    );
  });

  it('parses partial desktop-open responses with safe defaults', () => {
    const parsed = parseDesktopOpenResponse({ status: 'starting', started: true });

    expect(parsed.status).toBe('starting');
    expect(parsed.product_name).toBe('Scholar AI');
    expect(parsed.window_title).toBe('文献助手');
    expect(parsed.focused).toBe(false);
    expect(parsed.message).toContain('正在启动');
  });

  it('shows a Chinese offline message when desktop-open cannot reach the backend', async () => {
    mockedAxios.post.mockRejectedValueOnce({
      isAxiosError: true,
      code: 'ERR_NETWORK',
      message: 'Network Error',
      request: {},
    });

    await expect(openAgentSidebarDesktop()).rejects.toThrow('文献助手后端已断开');
  });
});
