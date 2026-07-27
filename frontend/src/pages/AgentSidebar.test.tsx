import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const sendMessage = vi.hoisted(() => vi.fn(async () => undefined));
const stopMessage = vi.hoisted(() => vi.fn());
const getConversation = vi.hoisted(() => vi.fn());
const setActiveProjectId = vi.hoisted(() => vi.fn());
const listProjects = vi.hoisted(() => vi.fn());
const getAgentSidebarHealth = vi.hoisted(() => vi.fn());
const listAgentSidebarReceipts = vi.hoisted(() => vi.fn());
const readAgentSidebarReceipt = vi.hoisted(() => vi.fn());
const revalidateAgentSidebarReceipt = vi.hoisted(() => vi.fn());
const createAgentSidebarAnswerRequest = vi.hoisted(() => vi.fn());
const openAgentSidebarDesktop = vi.hoisted(() => vi.fn());
const readVisualObservationDetail = vi.hoisted(() => vi.fn());
const transitionVisualObservation = vi.hoisted(() => vi.fn());

function deferred<T>() {
  let resolvePromise!: (value: T) => void;
  let rejectPromise!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return { promise, reject: rejectPromise, resolve: resolvePromise };
}

vi.mock('@/contexts/SmartReadContext', () => ({
  smartReadDialogScope: (projectId: string) => `dialog-${projectId}`,
  useSmartRead: () => ({
    getConversation,
    sendMessage,
    stopMessage,
    setConversation: vi.fn(),
    appendMessages: vi.fn(),
    clearConversation: vi.fn(),
  }),
}));

vi.mock('@/contexts/WritingContext', () => ({
  useWriting: () => ({
    activeProjectId: 'project-a',
    setActiveProjectId,
  }),
}));

vi.mock('@/services/writingBackend', () => ({
  getWritingBackendService: () => ({
    listProjects,
  }),
}));

vi.mock('@/services/agentSidebarApi', () => ({
  getAgentSidebarHealth,
  listAgentSidebarReceipts,
  readAgentSidebarReceipt,
  revalidateAgentSidebarReceipt,
  createAgentSidebarAnswerRequest,
  openAgentSidebarDesktop,
  agentSidebarEvidenceToPill: (ref: { ref_id?: string; chunk_id?: string; material_id?: string; page?: number; source_title?: string; summary?: string }) => ({
    evidence_id: ref.ref_id ?? ref.chunk_id ?? null,
    chunk_id: ref.chunk_id ?? null,
    material_id: ref.material_id ?? null,
    page: ref.page ?? null,
    source: ref.source_title ?? null,
    source_title: ref.source_title ?? null,
    text: ref.summary ?? null,
    source_kind: 'local',
    source_type: 'project',
  }),
}));

vi.mock('@/services/visualObservationApi', () => ({
  readVisualObservationDetail,
  transitionVisualObservation,
}));

import { AgentSidebar } from './AgentSidebar';

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

const receiptRead = {
  conversation_id: 'session-sidebar-1',
  project_id: 'project-a',
  answer: 'Saved answer from the shared receipt.',
  receipt: {
    receipt_schema_version: 'scholar-ai-answer-receipt/v1',
    question: 'What does the evidence say?',
    generated_in: 'mcp_sidebar',
    answer_origin: 'host_agent',
    answer_model: 'codex-host',
    evidence_pack_ref: 'evidence_pack:abc',
    lifecycle_state: 'saved',
    staleness_status: 'saved',
    qrels_status: {
      schema_version: 'retrieval-qrels-status/v1',
      status: 'candidate',
      candidate_qrels_count: 1,
      semantic_quality_claim_allowed: false,
    },
    evidence_gate_status: { status: 'passed' },
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
    checked: ['qrels_content_hash', 'gate_config_hash'],
    warnings: [],
    mismatches: [],
  },
};

function receiptWith(overrides: {
  gateStatus?: string;
  qrelsStatus?: 'missing' | 'candidate' | 'reviewed' | 'canonical' | 'unknown';
  staleStatus?: string;
  semanticQualityClaimAllowed?: boolean;
}) {
  return {
    ...receiptRead,
    receipt: {
      ...receiptRead.receipt,
      evidence_gate_status: { status: overrides.gateStatus ?? 'passed' },
      qrels_status: {
        ...receiptRead.receipt.qrels_status,
        status: overrides.qrelsStatus ?? 'candidate',
        semantic_quality_claim_allowed: overrides.semanticQualityClaimAllowed ?? false,
      },
      staleness_status: overrides.staleStatus ?? receiptRead.receipt.staleness_status,
    },
    staleness: {
      ...receiptRead.staleness,
      status: overrides.staleStatus ?? receiptRead.staleness.status,
    },
  };
}

function renderSidebar() {
  render(
    <MemoryRouter initialEntries={['/agent-sidebar?project_id=project-a']}>
      <AgentSidebar />
    </MemoryRouter>,
  );
}

function renderSidebarInStrictMode() {
  render(
    <StrictMode>
      <MemoryRouter initialEntries={['/agent-sidebar?project_id=project-a']}>
        <AgentSidebar />
      </MemoryRouter>
    </StrictMode>,
  );
}

function SidebarWithProjectNavigation() {
  const navigate = useNavigate();
  return (
    <>
      <button
        type="button"
        onClick={() => navigate('/agent-sidebar?project_id=project-b')}
      >
        导航到项目 B
      </button>
      <AgentSidebar />
    </>
  );
}

function renderSidebarWithProjectNavigation() {
  render(
    <MemoryRouter initialEntries={['/agent-sidebar?project_id=project-a']}>
      <SidebarWithProjectNavigation />
    </MemoryRouter>,
  );
}

function mockTwoProjectReceiptLoads(
  projectARead: typeof receiptRead,
  projectBRead: typeof receiptRead,
): void {
  listProjects.mockResolvedValue([
    {
      project_id: 'project-a',
      title: 'Project A',
      description: '',
      status: 'active',
      created_at: '2026-07-07T00:00:00Z',
      updated_at: '2026-07-07T00:00:00Z',
    },
    {
      project_id: 'project-b',
      title: 'Project B',
      description: '',
      status: 'active',
      created_at: '2026-07-07T00:00:00Z',
      updated_at: '2026-07-07T00:00:00Z',
    },
  ]);
  listAgentSidebarReceipts.mockImplementation(async (projectId: string) => {
    const read = projectId === 'project-b' ? projectBRead : projectARead;
    return {
      project_id: projectId,
      receipts: [{
        conversation_id: read.conversation_id,
        project_id: projectId,
        title: '',
        mode: 'literature_qa',
        created_at: '2026-07-07T00:00:00Z',
        updated_at: '2026-07-07T00:00:01Z',
        lifecycle_state: read.receipt.lifecycle_state,
        staleness_status: read.receipt.staleness_status,
        receipt: read.receipt,
      }],
    };
  });
  readAgentSidebarReceipt.mockImplementation(async (conversationId: string) => (
    conversationId === projectBRead.conversation_id ? projectBRead : projectARead
  ));
}

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {
      writeText: vi.fn(async () => undefined),
    },
  });
  getConversation.mockReturnValue({ messages: [], updatedAt: 0, pending: false });
  listProjects.mockResolvedValue([
    {
      project_id: 'project-a',
      title: 'Project A',
      description: '',
      status: 'active',
      created_at: '2026-07-07T00:00:00Z',
      updated_at: '2026-07-07T00:00:00Z',
    },
  ]);
  getAgentSidebarHealth.mockResolvedValue({ status: 'ok', version: '0.1.9.1', raw: {} });
  listAgentSidebarReceipts.mockResolvedValue({
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
        receipt: receiptRead.receipt,
      },
    ],
  });
  readAgentSidebarReceipt.mockResolvedValue(receiptRead);
  revalidateAgentSidebarReceipt.mockResolvedValue({
    conversation_id: 'session-sidebar-1',
    project_id: 'project-a',
    applied: false,
    apply_allowed: true,
    status: 'ready',
    previous_staleness: receiptRead.staleness,
    revalidated_staleness: receiptRead.staleness,
    top_ref_delta: { changed: false },
    receipt: receiptRead.receipt,
    evidence_pack: {},
    gate: { status: 'passed' },
  });
  createAgentSidebarAnswerRequest.mockResolvedValue({
    request_id: 'agentreq_sidebar',
    job: {
      job_id: 'job-sidebar',
      status: 'in_progress',
      metadata: {},
    },
    poll: { job: '/runtime/job/job-sidebar' },
    envelope: {
      intent: 'sidebar_answer',
      project_id: 'project-a',
      user_text: 'What does the evidence say?',
      resource_refs: [],
    },
  });
  openAgentSidebarDesktop.mockResolvedValue({
    status: 'running',
    started: false,
    product_name: 'Scholar AI',
    window_title: '文献助手',
    base_url: 'http://127.0.0.1:8000',
    pid: 1234,
    focused: true,
    message: '文献助手桌面端已在运行。',
  });
  readVisualObservationDetail.mockResolvedValue({
    candidateId: 'visual-candidate-direct',
    sessionId: 'session-sidebar-1',
    projectId: 'project-a',
    turnId: 'turn-sidebar-1',
    route: 'direct_model',
    generationStatus: 'succeeded',
    reviewStatus: 'candidate',
    freshnessStatus: 'fresh',
    selectionIds: ['selection-text-1', 'selection-formula-1'],
    updatedAt: '2026-07-16T10:00:00Z',
    outputText: 'The selected formula defines the normalization term.',
  });
  transitionVisualObservation.mockResolvedValue({
    candidate: {
      candidateId: 'visual-candidate-direct',
      sessionId: 'session-sidebar-1',
      projectId: 'project-a',
      turnId: 'turn-sidebar-1',
      route: 'direct_model',
      generationStatus: 'succeeded',
      reviewStatus: 'accepted',
      freshnessStatus: 'fresh',
      selectionIds: ['selection-text-1', 'selection-formula-1'],
      updatedAt: '2026-07-16T10:05:00Z',
      outputText: 'The selected formula defines the normalization term.',
    },
    receipt: {
      axis: 'review',
      previousReviewStatus: 'candidate',
      previousFreshnessStatus: 'fresh',
      resultReviewStatus: 'accepted',
      resultFreshnessStatus: 'fresh',
      occurredAt: '2026-07-16T10:05:00Z',
    },
    replayed: false,
  });
});

describe('AgentSidebar', () => {
  it('shows a compact history-loading state before the startup receipt is selected', async () => {
    let resolveReceipts!: (value: Awaited<ReturnType<typeof listAgentSidebarReceipts>>) => void;
    listAgentSidebarReceipts.mockReturnValueOnce(new Promise((resolve) => {
      resolveReceipts = resolve;
    }));

    renderSidebar();

    expect(await screen.findByLabelText('证据状态：读取历史；正在同步保存记录')).toBeInTheDocument();
    expect(screen.getByText('读取中')).toBeInTheDocument();
    expect(screen.getByText('正在读取历史…')).toBeInTheDocument();
    expect(screen.queryByLabelText('证据状态：未选择记录；提问或从历史打开')).not.toBeInTheDocument();

    await act(async () => {
      resolveReceipts({
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
            receipt: receiptRead.receipt,
          },
        ],
      });
    });

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    expect(screen.queryByText('正在读取历史…')).not.toBeInTheDocument();
  });

  it('keeps a selected project from the newest StrictMode load when an older success finishes last', async () => {
    const olderProjectLoad = deferred<Awaited<ReturnType<typeof listProjects>>>();
    const projectA = {
      project_id: 'project-a',
      title: 'Project A',
      description: '',
      status: 'active',
      created_at: '2026-07-07T00:00:00Z',
      updated_at: '2026-07-07T00:00:00Z',
    };
    const projectB = {
      ...projectA,
      project_id: 'project-b',
      title: 'Project B',
    };
    let projectLoadCount = 0;
    listProjects.mockReset();
    listProjects.mockImplementation(() => {
      projectLoadCount += 1;
      return projectLoadCount === 1
        ? olderProjectLoad.promise
        : Promise.resolve([projectA, projectB]);
    });
    listAgentSidebarReceipts.mockImplementation(async (projectId: string) => ({
      project_id: projectId,
      receipts: [],
    }));

    renderSidebarInStrictMode();

    await waitFor(() => expect(listProjects).toHaveBeenCalledTimes(2));
    const projectSelect = await screen.findByLabelText('Scholar AI 项目');
    await screen.findByRole('option', { name: 'Project B' });
    fireEvent.change(projectSelect, { target: { value: 'project-b' } });
    await waitFor(() => expect(projectSelect).toHaveValue('project-b'));

    await act(async () => {
      olderProjectLoad.resolve([projectA]);
    });

    await waitFor(() => {
      expect(projectSelect).toHaveValue('project-b');
      expect(projectSelect.querySelector('option[value="project-b"]')).toBeInTheDocument();
    });
  });

  it('keeps the newest offline state when an older StrictMode project load succeeds late', async () => {
    const olderProjectLoad = deferred<Awaited<ReturnType<typeof listProjects>>>();
    const newerProjectLoad = deferred<Awaited<ReturnType<typeof listProjects>>>();
    const projectA = {
      project_id: 'project-a',
      title: 'Project A',
      description: '',
      status: 'active',
      created_at: '2026-07-07T00:00:00Z',
      updated_at: '2026-07-07T00:00:00Z',
    };
    listProjects.mockReset();
    listProjects
      .mockReturnValueOnce(olderProjectLoad.promise)
      .mockReturnValueOnce(newerProjectLoad.promise);

    renderSidebarInStrictMode();

    await waitFor(() => expect(listProjects).toHaveBeenCalledTimes(2));
    await act(async () => {
      newerProjectLoad.reject(new Error('Newest project load is offline.'));
    });
    const textarea = await screen.findByLabelText('侧栏提问');
    expect(await screen.findByText('Newest project load is offline.')).toBeInTheDocument();
    expect(textarea).toBeDisabled();

    await act(async () => {
      olderProjectLoad.resolve([projectA]);
    });

    await waitFor(() => {
      expect(screen.getByText('Newest project load is offline.')).toBeInTheDocument();
      expect(textarea).toBeDisabled();
      expect(listAgentSidebarReceipts).not.toHaveBeenCalled();
    });
  });

  it('ignores an older StrictMode project-load failure after the newest load succeeds', async () => {
    const olderProjectLoad = deferred<Awaited<ReturnType<typeof listProjects>>>();
    const newerProjectLoad = deferred<Awaited<ReturnType<typeof listProjects>>>();
    const projectA = {
      project_id: 'project-a',
      title: 'Project A',
      description: '',
      status: 'active',
      created_at: '2026-07-07T00:00:00Z',
      updated_at: '2026-07-07T00:00:00Z',
    };
    listProjects.mockReset();
    listProjects
      .mockReturnValueOnce(olderProjectLoad.promise)
      .mockReturnValueOnce(newerProjectLoad.promise);

    renderSidebarInStrictMode();

    await waitFor(() => expect(listProjects).toHaveBeenCalledTimes(2));
    await act(async () => {
      newerProjectLoad.resolve([projectA]);
    });
    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    const textarea = screen.getByLabelText('侧栏提问');
    expect(textarea).not.toBeDisabled();

    await act(async () => {
      olderProjectLoad.reject(new Error('Stale project load failed.'));
    });

    await waitFor(() => {
      expect(screen.queryByText('Stale project load failed.')).not.toBeInTheDocument();
      expect(textarea).not.toBeDisabled();
      expect(screen.getByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    });
  });

  it('ignores a delayed receipt list from the previous project after switching projects', async () => {
    const projectAList = deferred<Awaited<ReturnType<typeof listAgentSidebarReceipts>>>();
    const projectARead = {
      ...receiptRead,
      answer: 'Stale Project A answer.',
    };
    const projectBRead = {
      ...receiptRead,
      conversation_id: 'session-project-b',
      project_id: 'project-b',
      answer: 'Current Project B answer.',
      receipt: {
        ...receiptRead.receipt,
        question: 'Project B question',
      },
    };
    listProjects.mockResolvedValue([
      {
        project_id: 'project-a',
        title: 'Project A',
        description: '',
        status: 'active',
        created_at: '2026-07-07T00:00:00Z',
        updated_at: '2026-07-07T00:00:00Z',
      },
      {
        project_id: 'project-b',
        title: 'Project B',
        description: '',
        status: 'active',
        created_at: '2026-07-07T00:00:00Z',
        updated_at: '2026-07-07T00:00:00Z',
      },
    ]);
    listAgentSidebarReceipts.mockImplementation((projectId: string) => {
      if (projectId === 'project-a') return projectAList.promise;
      return Promise.resolve({
        project_id: 'project-b',
        receipts: [{
          conversation_id: 'session-project-b',
          project_id: 'project-b',
          title: '',
          mode: 'literature_qa',
          created_at: '2026-07-07T00:00:00Z',
          updated_at: '2026-07-07T00:00:01Z',
          lifecycle_state: 'saved',
          staleness_status: 'saved',
          receipt: projectBRead.receipt,
        }],
      });
    });
    readAgentSidebarReceipt.mockImplementation(async (conversationId: string) => (
      conversationId === 'session-project-b' ? projectBRead : projectARead
    ));

    renderSidebar();

    const projectSelect = await screen.findByLabelText('Scholar AI 项目');
    await screen.findByRole('option', { name: 'Project B' });
    fireEvent.change(projectSelect, { target: { value: 'project-b' } });
    expect(await screen.findByText('Current Project B answer.')).toBeInTheDocument();

    await act(async () => {
      projectAList.resolve({
        project_id: 'project-a',
        receipts: [{
          conversation_id: 'session-sidebar-1',
          project_id: 'project-a',
          title: '',
          mode: 'literature_qa',
          created_at: '2026-07-07T00:00:00Z',
          updated_at: '2026-07-07T00:00:01Z',
          lifecycle_state: 'saved',
          staleness_status: 'saved',
          receipt: projectARead.receipt,
        }],
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Current Project B answer.')).toBeInTheDocument();
      expect(screen.queryByText('Stale Project A answer.')).not.toBeInTheDocument();
    });
  });

  it('ignores a delayed receipt read from the previous project after switching projects', async () => {
    const projectARead = deferred<Awaited<ReturnType<typeof readAgentSidebarReceipt>>>();
    const staleProjectARead = {
      ...receiptRead,
      answer: 'Delayed Project A receipt read.',
    };
    const projectBRead = {
      ...receiptRead,
      conversation_id: 'session-project-b',
      project_id: 'project-b',
      answer: 'Selected Project B receipt read.',
      receipt: {
        ...receiptRead.receipt,
        question: 'Project B question',
      },
    };
    listProjects.mockResolvedValue([
      {
        project_id: 'project-a',
        title: 'Project A',
        description: '',
        status: 'active',
        created_at: '2026-07-07T00:00:00Z',
        updated_at: '2026-07-07T00:00:00Z',
      },
      {
        project_id: 'project-b',
        title: 'Project B',
        description: '',
        status: 'active',
        created_at: '2026-07-07T00:00:00Z',
        updated_at: '2026-07-07T00:00:00Z',
      },
    ]);
    listAgentSidebarReceipts.mockImplementation(async (projectId: string) => ({
      project_id: projectId,
      receipts: [{
        conversation_id: projectId === 'project-a' ? 'session-sidebar-1' : 'session-project-b',
        project_id: projectId,
        title: '',
        mode: 'literature_qa',
        created_at: '2026-07-07T00:00:00Z',
        updated_at: '2026-07-07T00:00:01Z',
        lifecycle_state: 'saved',
        staleness_status: 'saved',
        receipt: projectId === 'project-a' ? staleProjectARead.receipt : projectBRead.receipt,
      }],
    }));
    readAgentSidebarReceipt.mockImplementation((conversationId: string) => (
      conversationId === 'session-sidebar-1'
        ? projectARead.promise
        : Promise.resolve(projectBRead)
    ));

    renderSidebar();

    await waitFor(() => {
      expect(readAgentSidebarReceipt).toHaveBeenCalledWith('session-sidebar-1');
    });
    const projectSelect = await screen.findByLabelText('Scholar AI 项目');
    await screen.findByRole('option', { name: 'Project B' });
    fireEvent.change(projectSelect, { target: { value: 'project-b' } });
    expect(await screen.findByText('Selected Project B receipt read.')).toBeInTheDocument();

    await act(async () => {
      projectARead.resolve(staleProjectARead);
    });

    await waitFor(() => {
      expect(screen.getByText('Selected Project B receipt read.')).toBeInTheDocument();
      expect(screen.queryByText('Delayed Project A receipt read.')).not.toBeInTheDocument();
    });
  });

  it('renders saved receipt evidence status from the shared receipt APIs', async () => {
    renderSidebar();

    expect(await screen.findByLabelText('Scholar AI 项目')).toHaveValue('project-a');
    expect(screen.queryByText('Scholar AI 文献桥')).not.toBeInTheDocument();
    expect(screen.queryByText('就绪 0.1.9.1')).not.toBeInTheDocument();
    expect(await screen.findByText('已绑定证据')).toBeInTheDocument();
    expect(screen.getByText('codex-host')).toBeInTheDocument();
    expect(screen.queryByText('Scholar AI')).not.toBeInTheDocument();
    expect(screen.queryByText(/qrels/)).not.toBeInTheDocument();
    expect(screen.queryByText(/门禁/)).not.toBeInTheDocument();
    expect(screen.queryByText(/证据包/)).not.toBeInTheDocument();
    expect(screen.getByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    expect(listAgentSidebarReceipts).toHaveBeenCalledWith('project-a', 20);
    expect(readAgentSidebarReceipt).toHaveBeenCalledWith('session-sidebar-1');
  });

  it('keeps smoke or slice-diagnostic receipts out of the compact history UI', async () => {
    const diagnosticReceipt = {
      ...receiptRead,
      conversation_id: 's83_live_workflow_refs_20260709_0508',
      answer: 'Diagnostic smoke answer with internal workflow terms.',
      receipt: {
        ...receiptRead.receipt,
        question: 'S83 workflow refs smoke check',
        answer_model: 'codex-s83-live',
      },
    };
    const userReceipt = {
      ...receiptRead,
      conversation_id: 'session-user-visible',
      answer: 'User-facing saved answer.',
      receipt: {
        ...receiptRead.receipt,
        question: 'What does the paper conclude?',
        answer_model: 'codex-host',
      },
    };
    listAgentSidebarReceipts.mockResolvedValueOnce({
      project_id: 'project-a',
      receipts: [
        {
          conversation_id: diagnosticReceipt.conversation_id,
          project_id: 'project-a',
          title: '',
          mode: 'literature_qa',
          created_at: '2026-07-09T05:08:00Z',
          updated_at: '2026-07-09T05:08:00Z',
          lifecycle_state: 'saved',
          staleness_status: 'saved',
          receipt: diagnosticReceipt.receipt,
        },
        {
          conversation_id: userReceipt.conversation_id,
          project_id: 'project-a',
          title: '',
          mode: 'literature_qa',
          created_at: '2026-07-09T05:09:00Z',
          updated_at: '2026-07-09T05:09:00Z',
          lifecycle_state: 'saved',
          staleness_status: 'saved',
          receipt: userReceipt.receipt,
        },
      ],
    });
    readAgentSidebarReceipt.mockImplementation(async (conversationId: string) => (
      conversationId === diagnosticReceipt.conversation_id ? diagnosticReceipt : userReceipt
    ));

    renderSidebar();

    expect(await screen.findByText('User-facing saved answer.')).toBeInTheDocument();
    expect(screen.queryByText('Diagnostic smoke answer with internal workflow terms.')).not.toBeInTheDocument();
    await waitFor(() => {
      expect(readAgentSidebarReceipt).toHaveBeenCalledWith('session-user-visible');
    });
    expect(readAgentSidebarReceipt).not.toHaveBeenCalledWith('s83_live_workflow_refs_20260709_0508');

    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByText('历史'));

    expect(screen.queryByText('S83 workflow refs smoke check')).not.toBeInTheDocument();
    expect(screen.getByText('What does the paper conclude?')).toBeInTheDocument();
    expect(readAgentSidebarReceipt).not.toHaveBeenCalledWith('s83_live_workflow_refs_20260709_0508');
  });

  it('keeps evidence, history, actions, and handoff folded behind the compact toolbar by default', async () => {
    renderSidebar();

    expect(await screen.findByText('已绑定证据')).toBeInTheDocument();
    expect(screen.queryByText('证据')).not.toBeInTheDocument();
    expect(screen.queryByText('连续性')).not.toBeInTheDocument();
    expect(screen.queryByText('历史')).not.toBeInTheDocument();
    expect(screen.queryByText('操作')).not.toBeInTheDocument();
    expect(screen.queryByText('交接')).not.toBeInTheDocument();
    expect(screen.queryByText('视觉观察审查')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));

    expect(screen.getByText('证据')).toBeInTheDocument();
    expect(screen.getByText('连续性')).toBeInTheDocument();
    expect(screen.getByText('历史')).toBeInTheDocument();
    expect(screen.getByText('操作')).toBeInTheDocument();
    expect(screen.getByText('交接')).toBeInTheDocument();
    expect(screen.getByText('视觉观察审查')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '收起侧栏工具' })).toBeInTheDocument();
  });

  it('keeps visual observations folded and reads details only after a candidate click', async () => {
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));

    const disclosure = screen.getByRole('button', { name: /视觉观察审查/ });
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('候选 1')).not.toBeInTheDocument();
    expect(readVisualObservationDetail).not.toHaveBeenCalled();

    fireEvent.click(disclosure);

    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('视觉结果仅供审查，不会自动进入回答证据、Wiki 或图谱。')).toBeInTheDocument();
    expect(screen.getByText('生成成功 · 待审 · 新鲜')).toBeInTheDocument();
    expect(screen.getByText('方式：直接模型')).toBeInTheDocument();
    expect(screen.getByText('关联选区：2')).toBeInTheDocument();
    expect(screen.getByText('生成失败 · 待审 · 已过期')).toBeInTheDocument();
    expect(screen.getByText('生成成功 · 已接受 · 新鲜')).toBeInTheDocument();
    expect(readVisualObservationDetail).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '读取视觉观察候选 1' }));

    expect(await screen.findByText('The selected formula defines the normalization term.')).toBeInTheDocument();
    expect(readVisualObservationDetail).toHaveBeenCalledWith(visualObservationRefs[0]);
  });

  it('shows visual observation loading and a safe failed-candidate detail', async () => {
    let resolveDetail!: (value: {
      candidateId: string;
      sessionId: string;
      projectId: string;
      turnId: string;
      route: 'vision_aux_mcp';
      generationStatus: 'failed';
      reviewStatus: 'candidate';
      freshnessStatus: 'stale';
      selectionIds: string[];
      updatedAt: string;
      error: { code: string; message: string; recoverable: boolean };
    }) => void;
    readVisualObservationDetail.mockReturnValueOnce(new Promise((resolve) => {
      resolveDetail = resolve;
    }));
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByRole('button', { name: /视觉观察审查/ }));
    fireEvent.click(screen.getByRole('button', { name: '读取视觉观察候选 2' }));

    expect(screen.getByText('读取候选详情…')).toBeInTheDocument();
    await act(async () => {
      resolveDetail({
        candidateId: 'visual-candidate-failed',
        sessionId: 'session-sidebar-1',
        projectId: 'project-a',
        turnId: 'turn-sidebar-1',
        route: 'vision_aux_mcp',
        generationStatus: 'failed',
        reviewStatus: 'candidate',
        freshnessStatus: 'stale',
        selectionIds: ['selection-figure-1'],
        updatedAt: '2026-07-16T10:00:00Z',
        error: {
          code: 'vision_timeout',
          message: '视觉辅助分析超时。',
          recoverable: true,
        },
      });
    });

    expect(await screen.findByText('视觉辅助分析超时。')).toBeInTheDocument();
    expect(screen.getByText('可重试')).toBeInTheDocument();
    expect(screen.getByText('审查：待审')).toBeInTheDocument();
    expect(screen.getByText('新鲜度：已过期')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '接受' })).toBeDisabled();
    expect(readVisualObservationDetail).toHaveBeenCalledWith(visualObservationRefs[1]);
  });

  it('requires a reason and saves accept review with dual-axis expected state', async () => {
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByRole('button', { name: /视觉观察审查/ }));
    fireEvent.click(screen.getByRole('button', { name: '读取视觉观察候选 1' }));

    expect(await screen.findByText('The selected formula defines the normalization term.')).toBeInTheDocument();
    expect(screen.getByText('审查：待审')).toBeInTheDocument();
    expect(screen.getByText('新鲜度：新鲜')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '接受' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '拒绝' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '撤回' })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('审查理由（必填）'), {
      target: { value: '公式解释与选区内容一致。' },
    });
    fireEvent.click(screen.getByRole('button', { name: '接受' }));

    await waitFor(() => {
      expect(transitionVisualObservation).toHaveBeenCalledWith(
        expect.objectContaining({
          candidateId: 'visual-candidate-direct',
          reviewStatus: 'candidate',
          freshnessStatus: 'fresh',
        }),
        expect.objectContaining({
          operationId: expect.stringMatching(/^visual_review_/),
          expectedReviewStatus: 'candidate',
          expectedFreshnessStatus: 'fresh',
          targetReviewStatus: 'accepted',
          reason: '公式解释与选区内容一致。',
          changedBy: 'agent-sidebar',
        }),
      );
    });
    expect(await screen.findByText('已接受。已按当前候选状态保存审查结果。')).toBeInTheDocument();
    expect(screen.getByText('审查：已接受')).toBeInTheDocument();
    expect(screen.getAllByText('生成成功 · 已接受 · 新鲜')).toHaveLength(2);
  });

  it('keeps accept reject and withdraw as explicit reasoned review actions without exposing contract internals', async () => {
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByRole('button', { name: /视觉观察审查/ }));
    fireEvent.click(screen.getByRole('button', { name: '读取视觉观察候选 1' }));

    const surface = await screen.findByTestId('visual-observation-review-surface');
    expect(screen.getByRole('button', { name: '接受' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '拒绝' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '撤回' })).toBeInTheDocument();
    expect(surface).not.toHaveTextContent('visual-candidate-direct');
    expect(surface).not.toHaveTextContent('sha256:');
    expect(surface).not.toHaveTextContent('schema_version');
    expect(surface).not.toHaveTextContent('operation_id');
  });

  it('shows a localized visual observation read failure', async () => {
    readVisualObservationDetail.mockRejectedValueOnce(new Error('Network Error'));
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByRole('button', { name: /视觉观察审查/ }));
    fireEvent.click(screen.getByRole('button', { name: '读取视觉观察候选 1' }));

    expect(await screen.findByText('文献助手后端已断开。请启动或切回文献助手后重试。')).toBeInTheDocument();
  });

  it('does not expose visual observation contract details in the sidebar', async () => {
    readVisualObservationDetail.mockRejectedValueOnce(new Error(
      'Visual observation detail does not match reference field: read_endpoint https://private.example.test/schema',
    ));
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByRole('button', { name: /视觉观察审查/ }));
    fireEvent.click(screen.getByRole('button', { name: '读取视觉观察候选 1' }));

    expect(await screen.findByText('候选详情校验失败，请稍后重试。')).toBeInTheDocument();
    expect(screen.queryByText(/read_endpoint/)).not.toBeInTheDocument();
    expect(screen.queryByText(/private\.example\.test/)).not.toBeInTheDocument();
    expect(screen.queryByText(/schema/)).not.toBeInTheDocument();
  });

  it('shows an explicit empty state when a receipt has no visual observations', async () => {
    readAgentSidebarReceipt.mockResolvedValueOnce({
      ...receiptRead,
      receipt: {
        ...receiptRead.receipt,
        visual_observation_refs: [],
      },
    });
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByRole('button', { name: /视觉观察审查/ }));

    expect(screen.getByText('当前记录没有视觉观察候选。')).toBeInTheDocument();
    expect(readVisualObservationDetail).not.toHaveBeenCalled();
  });

  it('summarizes Wiki graph and citation continuity without exposing internal refs', async () => {
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByText('连续性'));

    const summary = screen.getByTestId('agent-sidebar-continuity-summary');
    expect(summary).toHaveTextContent('引用可回读');
    expect(summary).toHaveTextContent('1 条回答引用保留在保存记录；这只证明可追溯，不代表检索质量。');
    expect(summary).toHaveTextContent('Wiki 候选待审');
    expect(summary).toHaveTextContent('回答摘要已进入审查队列，确认后才进入知识库。');
    expect(summary).toHaveTextContent('图谱候选待审');
    expect(summary).toHaveTextContent('1 条关系随 Wiki 草稿保存，未作为最终图谱结论。');
    expect(summary).not.toHaveTextContent('agentreq_wiki_graph');
    expect(summary).not.toHaveTextContent('job-wiki-graph');
    expect(summary).not.toHaveTextContent('/api/');
    expect(summary).not.toHaveTextContent('synthesis/agent-result.md');
    expect(summary).not.toHaveTextContent('jsonl');
  });

  it('localizes receipt-list timeout errors instead of showing raw Axios text', async () => {
    listAgentSidebarReceipts.mockRejectedValueOnce(new Error('timeout of 15000ms exceeded'));

    renderSidebar();

    expect(await screen.findByText('读取超时。文献助手可能正在整理历史，请稍后刷新。')).toBeInTheDocument();
    expect(screen.queryByText(/timeout of 15000ms exceeded/)).not.toBeInTheDocument();
  });

  it('omits a bridge-only saved receipt from normal answer bubbles', async () => {
    readAgentSidebarReceipt.mockResolvedValueOnce({
      ...receiptRead,
      answer: [
        '已切换为外部智能体回答模式。',
        '文献助手未调用内部聊天模型；已完成本地检索，并把证据交给 Codex/Claude 等外部智能体生成最终回答。',
        '外部智能体应优先使用 evidence_refs / context_metadata.chunks 中的引用和 chunk_id 组织最终回答。',
        '检索结果：4 个上下文片段，4 条证据引用。',
      ].join('\n'),
    });

    renderSidebar();

    await waitFor(() => expect(readAgentSidebarReceipt).toHaveBeenCalled());
    expect(document.querySelector('.message-bubble')).not.toBeInTheDocument();
    expect(screen.queryByText('codex-host')).not.toBeInTheDocument();
    expect(screen.queryByText(/已切换为外部智能体回答模式/)).not.toBeInTheDocument();
    expect(screen.queryByText(/文献助手未调用内部聊天模型/)).not.toBeInTheDocument();
    expect(screen.queryByText(/evidence_refs/)).not.toBeInTheDocument();
    expect(screen.queryByText(/检索结果/)).not.toBeInTheDocument();
  });

  it('keeps the full saved answer after removing a repeated question line', async () => {
    const longAnswer = `完整回答：${'依据充分。'.repeat(150)}`;
    readAgentSidebarReceipt.mockResolvedValueOnce({
      ...receiptRead,
      answer: `问题：请直接回答。\n${longAnswer}`,
    });

    renderSidebar();

    expect(await screen.findByText(longAnswer)).toBeInTheDocument();
    expect(screen.queryByText(/问题：请直接回答/)).not.toBeInTheDocument();
    expect(screen.queryByText(/…$/)).not.toBeInTheDocument();
  });

  it('keeps question restatements and evidence summaries out of the live stream', async () => {
    getConversation.mockReturnValue({
      messages: [
        {
          id: 'sidebar-user-live',
          role: 'user',
          content: '请比较两种方法。',
          status: 'done',
        },
        {
          id: 'sidebar-assistant-live',
          role: 'assistant',
          content: [
            '问题：请比较两种方法。',
            '实时答案正文。',
            '',
            '## 证据摘要：',
            '- 不应显示。',
          ].join('\n'),
          status: 'streaming',
        },
      ],
      updatedAt: Date.now(),
      pending: true,
    });

    renderSidebar();

    expect(await screen.findByText('实时答案正文。')).toBeInTheDocument();
    expect(screen.getAllByText('请比较两种方法。')).toHaveLength(1);
    expect(screen.queryByText(/证据摘要/)).not.toBeInTheDocument();
    expect(screen.queryByText('不应显示。')).not.toBeInTheDocument();
  });

  it('omits external-agent placeholder receipts from normal answer bubbles', async () => {
    readAgentSidebarReceipt.mockResolvedValueOnce({
      ...receiptRead,
      answer: [
        '问题：Which bounded evidence should host agents inspect?',
        '提示：上下文已按当前研读档位截断。',
        'Yadav 等 - 2025 - Reducing… · p.3',
      ].join('\n\n'),
      receipt: {
        ...receiptRead.receipt,
        answer_model: 'external_agent',
        answer_model_origin: 'external_agent',
      },
    });

    renderSidebar();

    await waitFor(() => expect(readAgentSidebarReceipt).toHaveBeenCalled());
    expect(document.querySelector('.message-bubble')).not.toBeInTheDocument();
    expect(screen.queryByText('Codex 智能体')).not.toBeInTheDocument();
    expect(screen.queryByText('外部智能体')).not.toBeInTheDocument();
    expect(screen.queryByText('external_agent')).not.toBeInTheDocument();
    expect(screen.queryByText(/问题：Which bounded evidence/)).not.toBeInTheDocument();
    expect(screen.queryByText(/上下文已按当前研读档位截断/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Yadav 等 - 2025 - Reducing/)).not.toBeInTheDocument();
  });

  it.each([
    [receiptWith({ gateStatus: 'blocked' }), '证据被阻断', '需要先修复证据或重新检索'],
    [receiptWith({ staleStatus: 'stale' }), '证据需复核', '项目或证据已变化，建议重新检查'],
    [receiptWith({ qrelsStatus: 'missing' }), '有引用，未评估', '可回答内容，但不评价检索质量'],
    [receiptWith({ qrelsStatus: 'candidate', semanticQualityClaimAllowed: true }), '已绑定证据', '引用已保存，质量评估待确认'],
    [receiptWith({ qrelsStatus: 'canonical', semanticQualityClaimAllowed: false }), '证据可用', '引用可追溯，不评价检索质量'],
    [receiptWith({ qrelsStatus: 'canonical', semanticQualityClaimAllowed: true }), '证据可用', '回答已绑定可追溯引用'],
  ])('separates evidence lifecycle state for %s', async (read, label, detail) => {
    readAgentSidebarReceipt.mockResolvedValueOnce(read);

    renderSidebar();

    expect(await screen.findByLabelText(`证据状态：${label}；${detail}`)).toBeInTheDocument();
    expect(screen.queryByText(/qrels/)).not.toBeInTheDocument();
    expect(screen.queryByText(/门禁/)).not.toBeInTheDocument();
  });

  it('flags saved receipts with evidence refs but missing qrels and gate metadata', async () => {
    readAgentSidebarReceipt.mockResolvedValueOnce({
      ...receiptRead,
      receipt: {
        ...receiptRead.receipt,
        evidence_gate_status: {},
        qrels_status: {},
        evidence_pack_ref: null,
      },
      staleness: {
        ...receiptRead.staleness,
        warnings: ['evidence_pack_ref missing; pack restore unchecked'],
      },
    });

    renderSidebar();

    expect(await screen.findByLabelText('证据状态：有引用，未评估；可回答内容，但不评价检索质量')).toBeInTheDocument();
    expect(screen.queryByText(/qrels/)).not.toBeInTheDocument();
    expect(screen.queryByText(/门禁/)).not.toBeInTheDocument();
    expect(screen.queryByText(/不可声称质量/)).not.toBeInTheDocument();
  });

  it('submits sidebar asks through SmartRead with generatedIn=mcp_sidebar', async () => {
    listAgentSidebarReceipts.mockResolvedValueOnce({ project_id: 'project-a', receipts: [] });
    renderSidebar();

    const textarea = await screen.findByLabelText('侧栏提问');
    fireEvent.change(textarea, { target: { value: 'How does the paper ground this claim?' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith(
        'dialog-project-a',
        'How does the paper ground this claim?',
        expect.objectContaining({
          projectId: 'project-a',
          answerOrigin: 'internal_smartread',
          generatedIn: 'mcp_sidebar',
          tier: 'medium',
        }),
      );
    });
  });

  it('rejects a same-tick duplicate Enter submit before responding state renders', async () => {
    const activeSend = deferred<undefined>();
    listAgentSidebarReceipts.mockResolvedValue({ project_id: 'project-a', receipts: [] });
    sendMessage.mockReturnValueOnce(activeSend.promise);
    renderSidebar();

    const textarea = await screen.findByLabelText('侧栏提问');
    fireEvent.change(textarea, { target: { value: 'Submit this question only once.' } });
    act(() => {
      fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' });
      fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' });
    });
    const sendCallsBeforeCompletion = sendMessage.mock.calls.length;

    await act(async () => {
      activeSend.resolve(undefined);
    });

    expect(sendCallsBeforeCompletion).toBe(1);
  });

  it('keeps the composer disabled and rejects another submit while saving the receipt', async () => {
    const savingReceiptList = deferred<Awaited<ReturnType<typeof listAgentSidebarReceipts>>>();
    let receiptListCallCount = 0;
    listAgentSidebarReceipts.mockImplementation(() => {
      receiptListCallCount += 1;
      if (receiptListCallCount === 2) return savingReceiptList.promise;
      return Promise.resolve({ project_id: 'project-a', receipts: [] });
    });
    renderSidebar();

    const textarea = await screen.findByLabelText('侧栏提问');
    fireEvent.change(textarea, { target: { value: 'Wait for this receipt to save.' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' });

    expect(await screen.findByText('保存中')).toBeInTheDocument();
    const disabledDuringSave = textarea.hasAttribute('disabled');
    fireEvent.change(textarea, { target: { value: 'Do not submit while saving.' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' });
    const sendCallsDuringSave = sendMessage.mock.calls.length;

    await act(async () => {
      savingReceiptList.resolve({ project_id: 'project-a', receipts: [] });
    });

    expect(disabledDuringSave).toBe(true);
    expect(sendCallsDuringSave).toBe(1);
  });

  it('releases the new project composer after a previous-project send finishes', async () => {
    const activeProjectASend = deferred<undefined>();
    listProjects.mockResolvedValue([
      {
        project_id: 'project-a',
        title: 'Project A',
        description: '',
        status: 'active',
        created_at: '2026-07-07T00:00:00Z',
        updated_at: '2026-07-07T00:00:00Z',
      },
      {
        project_id: 'project-b',
        title: 'Project B',
        description: '',
        status: 'active',
        created_at: '2026-07-07T00:00:00Z',
        updated_at: '2026-07-07T00:00:00Z',
      },
    ]);
    listAgentSidebarReceipts.mockImplementation(async (projectId: string) => ({
      project_id: projectId,
      receipts: [],
    }));
    sendMessage.mockReturnValueOnce(activeProjectASend.promise);
    renderSidebar();

    const textarea = await screen.findByLabelText('侧栏提问');
    await screen.findByRole('option', { name: 'Project B' });
    fireEvent.change(textarea, { target: { value: 'Finish only for Project A.' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter' });
    expect(textarea).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Scholar AI 项目'), { target: { value: 'project-b' } });
    await act(async () => {
      activeProjectASend.resolve(undefined);
    });

    await waitFor(() => {
      expect(screen.getByLabelText('Scholar AI 项目')).toHaveValue('project-b');
      expect(screen.getByLabelText('侧栏提问')).not.toBeDisabled();
    });
  });

  it('loads only the receipt created by the current sidebar ask', async () => {
    const question = 'How does the current ask save a fresh receipt?';
    const savedAt = new Date().toISOString();
    const newReceiptRead = {
      ...receiptRead,
      conversation_id: 'session-sidebar-new',
      answer: 'Fresh saved answer for the current ask.',
      receipt: {
        ...receiptRead.receipt,
        question,
      },
    };
    listAgentSidebarReceipts
      .mockResolvedValueOnce({ project_id: 'project-a', receipts: [] })
      .mockResolvedValueOnce({
        project_id: 'project-a',
        receipts: [
          {
            conversation_id: 'session-sidebar-new',
            project_id: 'project-a',
            title: '',
            mode: 'literature_qa',
            created_at: savedAt,
            updated_at: savedAt,
            lifecycle_state: 'saved',
            staleness_status: 'saved',
            receipt: newReceiptRead.receipt,
          },
        ],
      });
    readAgentSidebarReceipt.mockResolvedValueOnce(newReceiptRead);
    renderSidebar();

    const textarea = await screen.findByLabelText('侧栏提问');
    fireEvent.change(textarea, { target: { value: question } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(readAgentSidebarReceipt).toHaveBeenCalledWith('session-sidebar-new');
    });
    expect(await screen.findByText('Fresh saved answer for the current ask.')).toBeInTheDocument();
  });

  it('does not select an old latest receipt when provider persistence creates no receipt', async () => {
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    const readsBeforeSubmit = readAgentSidebarReceipt.mock.calls.length;
    const textarea = await screen.findByLabelText('侧栏提问');
    fireEvent.change(textarea, { target: { value: 'Provider timeout should not reuse old history.' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByText('本次提问没有生成可保存的 Scholar AI receipt；历史不会自动选中旧记录。')).toBeInTheDocument();
    expect(screen.getByLabelText('证据状态：未选择记录；提问或从历史打开')).toBeInTheDocument();
    expect(screen.queryByText('Saved answer from the shared receipt.')).not.toBeInTheDocument();
    expect(readAgentSidebarReceipt).toHaveBeenCalledTimes(readsBeforeSubmit);
  });

  it('keeps old idle SmartRead drafts out of the compact sidebar when no receipt is selected', async () => {
    listAgentSidebarReceipts.mockResolvedValueOnce({ project_id: 'project-a', receipts: [] });
    getConversation.mockReturnValue({
      messages: [{
        id: 'old-draft',
        role: 'assistant',
        content: 'Old unsaved English evidence dump should not fill the sidebar.',
        status: 'done',
      }],
      updatedAt: 0,
      pending: false,
    });

    renderSidebar();

    expect(await screen.findByText('输入文献问题，或从历史打开。')).toBeInTheDocument();
    expect(screen.queryByText('Old unsaved English evidence dump should not fill the sidebar.')).not.toBeInTheDocument();
  });

  it('labels Stop as stopping future sidebar steps without promising backend cancellation', async () => {
    getConversation.mockReturnValue({ messages: [], updatedAt: 0, pending: true });
    renderSidebar();

    const stopButton = await screen.findByRole('button', { name: '停止后续步骤' });
    fireEvent.click(stopButton);

    expect(stopMessage).toHaveBeenCalledWith('dialog-project-a');
    expect(await screen.findByText('已停止')).toBeInTheDocument();
    expect(screen.getByText('停止只影响前端流和后续步骤；已完成的工具或保存不会撤销。')).toBeInTheDocument();
  });

  it('ignores a delayed revalidation completion after switching to another project', async () => {
    const delayedRevalidation = deferred<Awaited<ReturnType<typeof revalidateAgentSidebarReceipt>>>();
    const projectARead = {
      ...receiptWith({ staleStatus: 'stale' }),
      answer: 'Project A receipt awaiting revalidation.',
    };
    const projectBRead = {
      ...receiptRead,
      conversation_id: 'session-project-b',
      project_id: 'project-b',
      answer: 'Project B receipt remains selected.',
      receipt: {
        ...receiptRead.receipt,
        question: 'Project B question',
      },
    };
    mockTwoProjectReceiptLoads(projectARead, projectBRead);
    revalidateAgentSidebarReceipt.mockReturnValueOnce(delayedRevalidation.promise);
    renderSidebar();

    expect(await screen.findByText('Project A receipt awaiting revalidation.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByText('操作'));
    fireEvent.click(screen.getByRole('button', { name: '复核' }));
    await waitFor(() => {
      expect(revalidateAgentSidebarReceipt).toHaveBeenCalledWith(
        'session-sidebar-1',
        { apply: false, topK: 10 },
      );
    });

    fireEvent.change(screen.getByLabelText('Scholar AI 项目'), { target: { value: 'project-b' } });
    expect(await screen.findByText('Project B receipt remains selected.')).toBeInTheDocument();

    await act(async () => {
      delayedRevalidation.resolve({
        conversation_id: 'session-sidebar-1',
        project_id: 'project-a',
        applied: false,
        apply_allowed: true,
        status: 'stale',
        previous_staleness: projectARead.staleness,
        revalidated_staleness: projectARead.staleness,
        top_ref_delta: { changed: false },
        receipt: projectARead.receipt,
        evidence_pack: {},
        gate: { status: 'passed' },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Project B receipt remains selected.')).toBeInTheDocument();
      expect(screen.queryByText('预检：stale')).not.toBeInTheDocument();
      expect(screen.queryByText('结果需要更新。')).not.toBeInTheDocument();
      expect(screen.queryByText('需复核')).not.toBeInTheDocument();
      expect(screen.getByText('已保存')).toBeInTheDocument();
    });
  });

  it('ignores a delayed handoff completion after switching to another project', async () => {
    const delayedHandoff = deferred<Awaited<ReturnType<typeof createAgentSidebarAnswerRequest>>>();
    const projectARead = {
      ...receiptRead,
      answer: 'Project A receipt for handoff.',
    };
    const projectBRead = {
      ...receiptRead,
      conversation_id: 'session-project-b',
      project_id: 'project-b',
      answer: 'Project B receipt without a handoff.',
      receipt: {
        ...receiptRead.receipt,
        question: 'Project B question',
      },
    };
    mockTwoProjectReceiptLoads(projectARead, projectBRead);
    createAgentSidebarAnswerRequest.mockReturnValueOnce(delayedHandoff.promise);
    renderSidebar();

    expect(await screen.findByText('Project A receipt for handoff.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByText('交接'));
    fireEvent.click(screen.getByRole('button', { name: '创建接手任务' }));
    await waitFor(() => {
      expect(createAgentSidebarAnswerRequest).toHaveBeenCalledWith(
        projectARead,
        { projectId: 'project-a', agentHost: 'codex' },
      );
    });

    fireEvent.change(screen.getByLabelText('Scholar AI 项目'), { target: { value: 'project-b' } });
    expect(await screen.findByText('Project B receipt without a handoff.')).toBeInTheDocument();

    await act(async () => {
      delayedHandoff.resolve({
        request_id: 'agentreq_project_a',
        job: {
          job_id: 'job-project-a',
          status: 'in_progress',
          metadata: {},
        },
        poll: { job: '/runtime/job/job-project-a' },
        envelope: {
          intent: 'sidebar_answer',
          project_id: 'project-a',
          user_text: 'Project A receipt for handoff.',
          resource_refs: [],
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Project B receipt without a handoff.')).toBeInTheDocument();
      expect(screen.queryByText('已创建待接手任务。')).not.toBeInTheDocument();
      expect(screen.queryByLabelText('待主栏接手')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: '创建接手任务' })).toBeEnabled();
    });
  });

  it('clears the previous receipt before a URL-selected project loads receipts', async () => {
    const projectBReceipts = deferred<Awaited<ReturnType<typeof listAgentSidebarReceipts>>>();
    const projectBRead = {
      ...receiptRead,
      conversation_id: 'session-project-b',
      project_id: 'project-b',
      answer: 'Project B receipt.',
    };
    mockTwoProjectReceiptLoads(receiptRead, projectBRead);
    listAgentSidebarReceipts.mockImplementation((projectId: string) => {
      if (projectId === 'project-b') return projectBReceipts.promise;
      return Promise.resolve({
        project_id: 'project-a',
        receipts: [{
          conversation_id: receiptRead.conversation_id,
          project_id: 'project-a',
          title: '',
          mode: 'literature_qa',
          created_at: '2026-07-07T00:00:00Z',
          updated_at: '2026-07-07T00:00:01Z',
          lifecycle_state: receiptRead.receipt.lifecycle_state,
          staleness_status: receiptRead.receipt.staleness_status,
          receipt: receiptRead.receipt,
        }],
      });
    });
    renderSidebarWithProjectNavigation();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByText('交接'));
    fireEvent.click(screen.getByRole('button', { name: '导航到项目 B' }));
    await waitFor(() => {
      expect(screen.getByLabelText('Scholar AI 项目')).toHaveValue('project-b');
    });

    const staleHandoffButton = screen.queryByRole('button', { name: '创建接手任务' });
    if (staleHandoffButton) fireEvent.click(staleHandoffButton);
    expect(screen.queryByText('Saved answer from the shared receipt.')).not.toBeInTheDocument();
    expect(createAgentSidebarAnswerRequest).not.toHaveBeenCalled();

    await act(async () => {
      projectBReceipts.resolve({ project_id: 'project-b', receipts: [] });
    });
  });

  it('releases handoff busy state when a same-project refresh supersedes it', async () => {
    const delayedHandoff = deferred<Awaited<ReturnType<typeof createAgentSidebarAnswerRequest>>>();
    createAgentSidebarAnswerRequest.mockReturnValueOnce(delayedHandoff.promise);
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByText('操作'));
    fireEvent.click(screen.getByText('交接'));
    fireEvent.click(screen.getByRole('button', { name: '创建接手任务' }));
    await waitFor(() => {
      expect(createAgentSidebarAnswerRequest).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByRole('button', { name: '刷新' }));
    await waitFor(() => {
      expect(listAgentSidebarReceipts).toHaveBeenCalledTimes(2);
    });
    await act(async () => {
      delayedHandoff.resolve({
        request_id: 'agentreq_stale_refresh',
        job: {
          job_id: 'job-stale-refresh',
          status: 'in_progress',
          metadata: {},
        },
        poll: { job: '/runtime/job/job-stale-refresh' },
        envelope: {
          intent: 'sidebar_answer',
          project_id: 'project-a',
          user_text: 'What does the evidence say?',
          resource_refs: [],
        },
      });
    });

    expect(screen.queryByLabelText('待主栏接手')).not.toBeInTheDocument();
    expect(screen.queryByText('创建中…')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '创建接手任务' })).toBeEnabled();
  });

  it('creates compact main-column handoff status from a saved receipt', async () => {
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByText('交接'));
    expect(screen.queryByRole('textbox', { name: '交接用 receipt markdown' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '创建接手任务' }));

    await waitFor(() => {
      expect(createAgentSidebarAnswerRequest).toHaveBeenCalledWith(
        receiptRead,
        expect.objectContaining({
          projectId: 'project-a',
          agentHost: 'codex',
        }),
      );
    });
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
    expect(await screen.findByText('已创建待接手任务。')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '接手任务已创建' })).not.toBeInTheDocument();
    expect(screen.queryByText('查看弹窗')).not.toBeInTheDocument();
    const card = await screen.findByLabelText('待主栏接手');
    expect(card).toHaveTextContent('待主栏接手');
    expect(card).toHaveTextContent('主栏交接卡会读取此任务。');
    expect(card).toHaveTextContent('未弹出时可备用复制。');
    expect(card).not.toHaveTextContent('request_id');
    expect(card).not.toHaveTextContent('project_id');
    expect(card).not.toHaveTextContent('receipt');
    expect(card).not.toHaveTextContent('refs');
    expect(card).not.toHaveTextContent('agentreq_sidebar');

    fireEvent.click(screen.getByRole('button', { name: '复制交接指令' }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('agentreq_sidebar'));
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('侧栏交接任务'));
    });
    expect(await screen.findByText('已复制。')).toBeInTheDocument();
    expect(screen.queryByText(/主栏任务/)).not.toBeInTheDocument();
    expect(screen.queryByText(/生成注释卡/)).not.toBeInTheDocument();
    expect(screen.queryByText(/注释交接/)).not.toBeInTheDocument();
    expect(screen.queryByText(/请接手 Scholar AI 侧栏任务/)).not.toBeInTheDocument();
    expect(screen.queryByText(/请求：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/任务：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/literature.agent_result/)).not.toBeInTheDocument();
  });

  it('keeps folded tool panel content unmounted until the panel is opened', async () => {
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));

    expect(screen.queryByRole('button', { name: '打开文献助手' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '创建接手任务' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('操作'));
    expect(screen.getByRole('button', { name: '打开文献助手' })).toBeInTheDocument();

    fireEvent.click(screen.getByText('操作'));
    expect(screen.queryByRole('button', { name: '打开文献助手' })).not.toBeInTheDocument();
  });

  it('opens the native desktop app instead of linking to the duplicate dialog route', async () => {
    renderSidebar();

    expect(await screen.findByText('Saved answer from the shared receipt.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示侧栏工具' }));
    fireEvent.click(screen.getByText('操作'));
    expect(screen.queryByRole('link', { name: '打开文献助手' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '打开文献助手' }));

    await waitFor(() => {
      expect(openAgentSidebarDesktop).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText('文献助手桌面端已在运行。')).toBeInTheDocument();
  });
});
