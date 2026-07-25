import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Jobs } from './Jobs';
import { getWritingRuntimeClient } from '@/services/runtimeClient';
import type {
  JobEventSnapshot,
  JobStatus,
  WritingArtifact,
  WritingEvent,
} from '@/types/runtime';

vi.mock('@/contexts/I18nContext', () => ({
  useI18n: () => ({
    t: (key: string, vars?: Record<string, unknown>) => {
      const labels: Record<string, string> = {
        'jobs.title': '任务',
        'jobs.subtitle': `运行中 ${String(vars?.running ?? 0)} / 总计 ${String(vars?.total ?? 0)}`,
        'jobs.filter_all': '全部',
        'jobs.filter_running': '运行中',
        'jobs.filter_completed': '已完成',
        'jobs.filter_failed': '失败',
        'jobs.status_running': '运行中',
        'jobs.status_completed': '已完成',
        'jobs.status_failed': '失败',
        'jobs.status_queued': '排队中',
        'jobs.status_paused': '已暂停',
        'jobs.status_cancelled': '已取消',
        'jobs.started_at': '开始',
        'jobs.duration': '耗时',
        'jobs.retry': '重试',
        'jobs.pause': '暂停',
        'jobs.resume': '继续',
        'jobs.cancel': '取消',
        'jobs.empty_title': '暂无任务',
        'jobs.empty_description': '当前没有任务。',
        'writing.event.job_completed': '任务已完成',
        'writing.event.job_progress': '运行进度',
      };
      return labels[key] ?? key;
    },
  }),
}));

vi.mock('@/services/runtimeClient', () => ({
  getWritingRuntimeClient: vi.fn(),
}));

const mockedGetWritingRuntimeClient = vi.mocked(getWritingRuntimeClient);

type RuntimeClient = ReturnType<typeof getWritingRuntimeClient>;
type RuntimeJobList = Awaited<ReturnType<RuntimeClient['listJobs']>>;
type RuntimeDetailMethods = Pick<RuntimeClient, 'getJobEventSnapshot' | 'getJobArtifacts'>;

interface SnapshotOptions {
  jobId: string;
  status?: JobStatus;
  events?: WritingEvent[];
  metadata?: Record<string, unknown>;
}

function makeRuntimeEvent({
  jobId,
  sequence,
  timestamp,
  data = {},
  eventType = 'job_progress',
  eventId = `event_${sequence}`,
}: {
  jobId: string;
  sequence: number;
  timestamp: string;
  data?: Record<string, unknown>;
  eventType?: string;
  eventId?: string;
}): WritingEvent {
  return {
    event_id: eventId,
    job_id: jobId,
    session_id: 'session_internal_1',
    event_type: eventType,
    timestamp,
    sequence,
    data,
    metadata: {},
  } as WritingEvent;
}

function makeRuntimeSnapshot({
  jobId,
  status = 'completed',
  events = [],
  metadata = {},
}: SnapshotOptions): JobEventSnapshot {
  const latestSequence = events.at(-1)?.sequence ?? 0;
  return {
    job_id: jobId,
    session_id: 'session_internal_1',
    job: {
      job_id: jobId,
      session_id: 'session_internal_1',
      kind: 'skill_action',
      status,
      input_text: '整理引用',
      created_at: '2026-07-22T01:00:00.000Z',
      started_at: '2026-07-22T01:00:01.000Z',
      completed_at: status === 'completed' ? '2026-07-22T01:00:10.000Z' : null,
      action_id: '生成摘要',
      skill_id: null,
      error: null,
      tags: [],
      metadata,
      writing_workflow_state_summary: {},
      material_processing_task_summary: {},
    },
    status: {
      job_id: jobId,
      session_id: 'session_internal_1',
      status,
      kind: 'skill_action',
      created_at: '2026-07-22T01:00:00.000Z',
      started_at: '2026-07-22T01:00:01.000Z',
      completed_at: status === 'completed' ? '2026-07-22T01:00:10.000Z' : null,
      is_paused: status === 'paused',
      is_cancelled: status === 'cancelled',
      error: null,
      metadata,
    },
    events,
    next_after_sequence: latestSequence || null,
    latest_sequence: latestSequence,
    has_more: false,
  } as JobEventSnapshot;
}

function makeRuntimeArtifact({
  jobId,
  artifactId,
  createdAt,
}: {
  jobId: string;
  artifactId: string;
  createdAt: string;
}): WritingArtifact {
  return {
    artifact_id: artifactId,
    job_id: jobId,
    session_id: 'session_internal_1',
    artifact_type: 'draft',
    content: {
      raw_content_marker: 'raw-artifact-content-secret',
      local_path: 'C:\\private\\artifact-secret.json',
    },
    created_at: createdAt,
    created_by: null,
    metadata: {
      checkpoint_id: 'checkpoint_internal_456',
    },
    mime_type: 'application/json',
  } as WritingArtifact;
}

function runtimeClientWithJobs(
  jobs: RuntimeJobList,
  detailMethods: Partial<RuntimeDetailMethods> = {},
): RuntimeClient {
  return {
    listJobs: vi.fn(async () => jobs),
    getJobEventSnapshot: vi.fn(async (jobId: string) => makeRuntimeSnapshot({ jobId })),
    getJobArtifacts: vi.fn(async () => []),
    pauseJob: vi.fn(),
    resumeJob: vi.fn(),
    cancelJob: vi.fn(),
    startJob: vi.fn(),
    deleteJob: vi.fn(),
    ...detailMethods,
  } as unknown as RuntimeClient;
}

function renderJobs(): void {
  render(
    <MemoryRouter>
      <Jobs />
    </MemoryRouter>,
  );
}

describe('Jobs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', {
      headers: { 'Content-Type': 'application/json' },
      status: 200,
    })) as unknown as typeof fetch);
  });

  it('does not render raw internal job errors', async () => {
    mockedGetWritingRuntimeClient.mockReturnValue(runtimeClientWithJobs([
      {
        job_id: 'job_secret_123',
        kind: 'skill_action',
        action_id: '生成摘要',
        skill_id: null,
        session_id: 'session_secret_456',
        status: 'failed',
        input_text: '整理引用',
        created_at: '2026-05-29T01:00:00.000Z',
        started_at: '2026-05-29T01:00:01.000Z',
        completed_at: '2026-05-29T01:00:03.000Z',
        error: 'HTTP 500 /api/internal/secret job_id=job_secret_123 token=sk-hidden',
      },
    ]));

    renderJobs();

    await waitFor(() => {
      expect(screen.getByText('任务执行失败，详细诊断已记录到本地日志。')).toBeInTheDocument();
    });
    expect(screen.queryByText(/\/api\/internal\/secret/)).not.toBeInTheDocument();
    expect(screen.queryByText(/job_secret_123/)).not.toBeInTheDocument();
    expect(screen.queryByText(/sk-hidden/)).not.toBeInTheDocument();
  });

  it('sanitizes load failures before rendering them', async () => {
    mockedGetWritingRuntimeClient.mockReturnValue({
      listJobs: vi.fn(async () => {
        throw new Error('GET /api/internal/secret failed with api_key=sk-hidden');
      }),
    } as unknown as RuntimeClient);

    renderJobs();

    await waitFor(() => {
      expect(screen.getByText('任务加载失败')).toBeInTheDocument();
      expect(screen.getByText('任务操作失败，请稍后重试。')).toBeInTheDocument();
    });
    expect(screen.queryByText(/api_key=sk-hidden/)).not.toBeInTheDocument();
  });

  it('uses the unified knowledge-deposition shortcut instead of legacy wiki/evolution buttons', async () => {
    mockedGetWritingRuntimeClient.mockReturnValue(runtimeClientWithJobs([]));

    renderJobs();

    await waitFor(() => {
      expect(screen.getByText('知识沉淀')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /待确认/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /已沉淀/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /来源/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /关联/ })).toBeInTheDocument();
    expect(screen.queryByText('Wiki 知识沉淀')).not.toBeInTheDocument();
    expect(screen.queryByText('学到的经验')).not.toBeInTheDocument();
  });

  it('renders linter tasks from the task-center endpoint', async () => {
    mockedGetWritingRuntimeClient.mockReturnValue(runtimeClientWithJobs([]));
    const fetchSpy = vi.fn(async (_input: Parameters<typeof fetch>[0], _init?: Parameters<typeof fetch>[1]) => new Response(JSON.stringify([
      {
        task_id: 'linter_frontend_1',
        status: 'completed',
        progress: {
          current: 36,
          total: 36,
          message: '已检查 36/36 条文献',
        },
        result: { checked: 36, total: 36, issues: 324, results: [] },
        error: null,
        created_at: '2026-06-15T16:00:00.000Z',
      },
    ]), {
      headers: { 'Content-Type': 'application/json' },
      status: 200,
    }));
    vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch);

    renderJobs();

    await waitFor(() => {
      expect(screen.getByText('元数据检查')).toBeInTheDocument();
      expect(screen.getByText('已检查 36/36 条文献')).toBeInTheDocument();
    });
    const requestedUrl = fetchSpy.mock.calls[0]?.[0];
    expect(String(requestedUrl)).toMatch(/\/api\/linter\/tasks\/list$/);
  });

  it('times out a hanging linter request so the next background poll can proceed', async () => {
    vi.useFakeTimers();
    mockedGetWritingRuntimeClient.mockReturnValue(runtimeClientWithJobs([]));
    let fetchCount = 0;
    const fetchSpy = vi.fn((_input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
      fetchCount += 1;
      if (fetchCount === 1) {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted.', 'AbortError'));
          }, { once: true });
        });
      }
      return Promise.resolve(new Response('[]', {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }));
    });
    vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch);

    try {
      renderJobs();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(15000);
      });
      expect(screen.getByRole('alert')).toHaveTextContent(
        '元数据检查任务仍显示上次结果，请稍后重试。',
      );

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(fetchSpy).toHaveBeenCalledTimes(2);
      const firstSignal = fetchSpy.mock.calls[0]?.[1]?.signal;
      expect(firstSignal?.aborted).toBe(true);
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  it('keeps the current task row mounted while a background poll is pending', async () => {
    vi.useFakeTimers();
    let resolveRefresh!: (jobs: RuntimeJobList) => void;
    const pendingRefresh = new Promise<RuntimeJobList>((resolve) => {
      resolveRefresh = resolve;
    });
    const initialJobs: RuntimeJobList = [{
      job_id: 'runtime_stale_while_refreshing',
      kind: 'skill_action',
      action_id: '生成摘要',
      skill_id: null,
      session_id: 'session_internal_1',
      status: 'started',
      input_text: '保留中的任务',
      created_at: '2026-07-22T01:00:00.000Z',
      started_at: '2026-07-22T01:00:01.000Z',
      completed_at: null,
      error: null,
    }];
    const client = runtimeClientWithJobs(initialJobs);
    client.listJobs = vi
      .fn()
      .mockResolvedValueOnce(initialJobs)
      .mockReturnValueOnce(pendingRefresh);
    mockedGetWritingRuntimeClient.mockReturnValue(client);

    try {
      renderJobs();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const initialRow = screen.getByText(/保留中的任务/).closest('li');
      expect(initialRow).not.toBeNull();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
      });

      expect(screen.getByText(/保留中的任务/).closest('li')).toBe(initialRow);
      expect(screen.queryByText('正在加载任务')).not.toBeInTheDocument();

      resolveRefresh(initialJobs);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  it('keeps the last task snapshot and shows a safe non-blocking error when a background poll fails', async () => {
    vi.useFakeTimers();
    let rejectRefresh!: (reason: unknown) => void;
    const pendingRefresh = new Promise<RuntimeJobList>((_resolve, reject) => {
      rejectRefresh = reject;
    });
    const initialJobs: RuntimeJobList = [{
      job_id: 'runtime_stale_after_failure',
      kind: 'skill_action',
      action_id: '生成摘要',
      skill_id: null,
      session_id: 'session_internal_1',
      status: 'started',
      input_text: '失败后仍保留',
      created_at: '2026-07-22T01:00:00.000Z',
      started_at: '2026-07-22T01:00:01.000Z',
      completed_at: null,
      error: null,
    }];
    const client = runtimeClientWithJobs(initialJobs);
    client.listJobs = vi
      .fn()
      .mockResolvedValueOnce(initialJobs)
      .mockReturnValueOnce(pendingRefresh);
    mockedGetWritingRuntimeClient.mockReturnValue(client);

    try {
      renderJobs();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const initialRow = screen.getByText(/失败后仍保留/).closest('li');
      expect(initialRow).not.toBeNull();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
      });
      await act(async () => {
        rejectRefresh(new Error('GET /runtime/jobs token=sk-hidden C:\\private\\jobs.json'));
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(screen.getByText(/失败后仍保留/).closest('li')).toBe(initialRow);
      expect(screen.queryByText('任务加载失败')).not.toBeInTheDocument();
      expect(screen.getByRole('alert')).toHaveTextContent('任务操作失败，请稍后重试。');
      expect(document.body.textContent).not.toMatch(/sk-hidden|\/runtime\/jobs|C:\\private/i);
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  it('keeps the last linter task snapshot when its background refresh fails', async () => {
    vi.useFakeTimers();
    mockedGetWritingRuntimeClient.mockReturnValue(runtimeClientWithJobs([]));
    const linterPayload = [{
      task_id: 'linter_stale_after_failure',
      status: 'running',
      progress: {
        current: 4,
        total: 10,
        message: '已检查 4/10 条文献',
      },
      result: null,
      error: null,
      created_at: '2026-07-22T01:00:00.000Z',
    }];
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(linterPayload), {
        headers: { 'Content-Type': 'application/json' },
        status: 200,
      }))
      .mockResolvedValueOnce(new Response(
        'GET /api/linter/tasks/list token=sk-hidden C:\\private\\linter.json',
        { status: 503 },
      ));
    vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch);

    try {
      renderJobs();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const initialRow = screen.getByText('已检查 4/10 条文献').closest('li');
      expect(initialRow).not.toBeNull();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
      });

      expect(screen.getByText('已检查 4/10 条文献').closest('li')).toBe(initialRow);
      expect(screen.getByRole('alert')).toHaveTextContent(
        '元数据检查任务仍显示上次结果，请稍后重试。',
      );
      expect(document.body.textContent).not.toMatch(/sk-hidden|\/api\/linter|C:\\private/i);
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  it('does not start overlapping polls while a background refresh is pending', async () => {
    vi.useFakeTimers();
    let resolveRefresh!: (jobs: RuntimeJobList) => void;
    const pendingRefresh = new Promise<RuntimeJobList>((resolve) => {
      resolveRefresh = resolve;
    });
    const initialJobs: RuntimeJobList = [{
      job_id: 'runtime_single_in_flight',
      kind: 'skill_action',
      action_id: '生成摘要',
      skill_id: null,
      session_id: 'session_internal_1',
      status: 'started',
      input_text: '单请求刷新',
      created_at: '2026-07-22T01:00:00.000Z',
      started_at: '2026-07-22T01:00:01.000Z',
      completed_at: null,
      error: null,
    }];
    const client = runtimeClientWithJobs(initialJobs);
    client.listJobs = vi
      .fn()
      .mockResolvedValueOnce(initialJobs)
      .mockReturnValue(pendingRefresh);
    mockedGetWritingRuntimeClient.mockReturnValue(client);

    try {
      renderJobs();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText(/单请求刷新/)).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(12000);
      });

      expect(client.listJobs).toHaveBeenCalledTimes(2);

      resolveRefresh(initialJobs);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  it('keeps a confirmed empty state visible during a background refresh', async () => {
    vi.useFakeTimers();
    let resolveRefresh!: (jobs: RuntimeJobList) => void;
    const pendingRefresh = new Promise<RuntimeJobList>((resolve) => {
      resolveRefresh = resolve;
    });
    const client = runtimeClientWithJobs([]);
    client.listJobs = vi
      .fn()
      .mockResolvedValueOnce([])
      .mockReturnValueOnce(pendingRefresh);
    mockedGetWritingRuntimeClient.mockReturnValue(client);

    try {
      renderJobs();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText('暂无任务')).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
      });

      expect(screen.getByText('暂无任务')).toBeInTheDocument();
      expect(screen.queryByText('正在加载任务')).not.toBeInTheDocument();

      resolveRefresh([]);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });

  it('keeps large task batches inside a dedicated scroll list', async () => {
    const manyJobs: RuntimeJobList = Array.from({ length: 36 }, (_, index) => ({
      job_id: `runtime_job_${index}`,
      kind: 'smart_read',
      action_id: `研读任务 ${index + 1}`,
      skill_id: null,
      session_id: 's',
      status: index % 3 === 0 ? 'started' : 'completed',
      input_text: `批量任务 ${index + 1}`,
      created_at: '2026-05-29T01:00:00.000Z',
      started_at: '2026-05-29T01:00:01.000Z',
      completed_at: index % 3 === 0 ? null : '2026-05-29T01:00:03.000Z',
      error: null,
    }));
    mockedGetWritingRuntimeClient.mockReturnValue(runtimeClientWithJobs(manyJobs));

    renderJobs();

    const list = await screen.findByTestId('jobs-scroll-list');

    expect(within(list).getAllByRole('listitem')).toHaveLength(36);
    expect(screen.getByTestId('jobs-list-panel')).toHaveClass('min-h-0', 'flex-1', 'overflow-hidden');
    expect(list).toHaveClass('min-h-0', 'flex-1', 'overflow-y-auto');
  });

  it('bulk-cancels selected runtime jobs without calling linter task ids', async () => {
    const client = runtimeClientWithJobs([
      {
        job_id: 'runtime_running_1',
        kind: 'skill_action',
        action_id: 'a',
        skill_id: null,
        session_id: 's',
        status: 'started',
        input_text: '整理引用',
        created_at: '2026-05-29T01:00:00.000Z',
        started_at: '2026-05-29T01:00:01.000Z',
        completed_at: null,
        error: null,
      },
      {
        job_id: 'runtime_running_2',
        kind: 'prompt_action',
        action_id: 'b',
        skill_id: null,
        session_id: 's',
        status: 'queued',
        input_text: '生成摘要',
        created_at: '2026-05-29T01:01:00.000Z',
        started_at: null,
        completed_at: null,
        error: null,
      },
    ]);
    mockedGetWritingRuntimeClient.mockReturnValue(client);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([
      {
        task_id: 'linter_frontend_1',
        status: 'running',
        progress: {
          current: 3,
          total: 10,
          message: '已检查 3/10 条文献',
        },
        error: null,
        created_at: '2026-06-15T16:00:00.000Z',
      },
    ]), {
      headers: { 'Content-Type': 'application/json' },
      status: 200,
    })) as unknown as typeof fetch);

    renderJobs();

    await waitFor(() => {
      expect(screen.getByText('技能任务 · 整理引用')).toBeInTheDocument();
      expect(screen.getByText('元数据检查')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText('选择当前筛选中的任务'));
    fireEvent.click(screen.getByRole('button', { name: '取消 2' }));

    await waitFor(() => {
      expect(client.cancelJob).toHaveBeenCalledWith('runtime_running_1');
      expect(client.cancelJob).toHaveBeenCalledWith('runtime_running_2');
    });
    expect(client.cancelJob).not.toHaveBeenCalledWith('linter_frontend_1');
  });

  it('opens only runtime details and renders a safe server-backed snapshot before closing it', async () => {
    const jobId = 'runtime_job_secret_123';
    const eventId = 'event_internal_777';
    const artifactId = 'artifact_internal_999';
    const eventTimestamp = '2026-07-22T02:03:04.000Z';
    const artifactTimestamp = '2026-07-22T02:04:05.000Z';
    const getJobEventSnapshot = vi.fn(async () => makeRuntimeSnapshot({
      jobId,
      status: 'completed',
      metadata: { progress: 5 },
      events: [makeRuntimeEvent({
        jobId,
        eventId,
        sequence: 7,
        timestamp: eventTimestamp,
        data: {
          progress: 42,
          stage: '检索证据',
          message: '正在读取来源',
          raw_content_marker: 'raw-event-content-secret',
          local_path: 'C:\\private\\event-secret.json',
          checkpoint_id: 'checkpoint_internal_456',
        },
      })],
    }));
    const getJobArtifacts = vi.fn(async () => [makeRuntimeArtifact({
      jobId,
      artifactId,
      createdAt: artifactTimestamp,
    })]);
    const client = runtimeClientWithJobs([
      {
        job_id: jobId,
        kind: 'skill_action',
        action_id: '生成摘要',
        skill_id: null,
        session_id: 'session_internal_1',
        status: 'started',
        input_text: '整理引用',
        created_at: '2026-07-22T01:00:00.000Z',
        started_at: '2026-07-22T01:00:01.000Z',
        completed_at: null,
        error: null,
      },
    ], { getJobEventSnapshot, getJobArtifacts });
    mockedGetWritingRuntimeClient.mockReturnValue(client);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([
      {
        task_id: 'linter_internal_1',
        status: 'completed',
        progress: { current: 1, total: 1, message: '已检查 1/1 条文献' },
        error: null,
        created_at: '2026-07-22T01:10:00.000Z',
      },
    ]), {
      headers: { 'Content-Type': 'application/json' },
      status: 200,
    })) as unknown as typeof fetch);

    renderJobs();

    const detailButton = await screen.findByRole('button', {
      name: '查看任务详情 技能任务 · 整理引用',
    });
    expect(screen.getAllByRole('button', { name: /^查看任务详情 / })).toHaveLength(1);
    expect(screen.getByText('元数据检查')).toBeInTheDocument();
    expect(getJobEventSnapshot).not.toHaveBeenCalled();
    expect(getJobArtifacts).not.toHaveBeenCalled();

    fireEvent.click(detailButton);

    await waitFor(() => {
      expect(getJobEventSnapshot).toHaveBeenCalledWith(jobId, {
        afterSequence: null,
        limit: 50,
      });
      expect(getJobArtifacts).toHaveBeenCalledWith(jobId);
    });
    const panel = await screen.findByTestId('runtime-job-detail');
    expect(within(panel).getByRole('progressbar', { name: '任务真实进度' })).toHaveAttribute(
      'aria-valuenow',
      '42',
    );
    expect(within(panel).getAllByText('检索证据')).not.toHaveLength(0);
    expect(within(panel).getAllByText('正在读取来源')).not.toHaveLength(0);
    expect(within(panel).getByText('运行进度')).toBeInTheDocument();
    expect(within(panel).getByText('#7')).toBeInTheDocument();
    expect(within(panel).getByText(new Date(eventTimestamp).toLocaleString())).toBeInTheDocument();
    expect(within(panel).getByText('草稿')).toBeInTheDocument();
    expect(within(panel).getByText(new Date(artifactTimestamp).toLocaleString())).toBeInTheDocument();

    const visibleText = document.body.textContent ?? '';
    expect(visibleText).not.toContain(jobId);
    expect(visibleText).not.toContain(eventId);
    expect(visibleText).not.toContain(artifactId);
    expect(visibleText).not.toContain('raw-event-content-secret');
    expect(visibleText).not.toContain('raw-artifact-content-secret');
    expect(visibleText).not.toContain('C:\\private');
    expect(visibleText).not.toContain('checkpoint_internal_456');

    fireEvent.click(within(panel).getByRole('button', { name: '关闭任务详情' }));
    await waitFor(() => {
      expect(screen.queryByTestId('runtime-job-detail')).not.toBeInTheDocument();
    });
  });

  it('keeps runtime progress explicitly unknown when the snapshot has no real progress', async () => {
    const jobId = 'runtime_unknown_progress';
    const getJobEventSnapshot = vi.fn(async () => makeRuntimeSnapshot({
      jobId,
      status: 'completed',
      events: [makeRuntimeEvent({
        jobId,
        sequence: 1,
        timestamp: '2026-07-22T03:00:00.000Z',
        eventType: 'job_completed',
      })],
    }));
    const client = runtimeClientWithJobs([
      {
        job_id: jobId,
        kind: 'skill_action',
        action_id: '生成摘要',
        skill_id: null,
        session_id: 'session_internal_1',
        status: 'started',
        input_text: '未知进度',
        created_at: '2026-07-22T01:00:00.000Z',
        started_at: '2026-07-22T01:00:01.000Z',
        completed_at: null,
        error: null,
        metadata: {
          progress: 91,
          progress_stage: '旧阶段',
          progress_message: '旧进度',
        },
      },
    ], {
      getJobEventSnapshot,
      getJobArtifacts: vi.fn(async () => []),
    });
    mockedGetWritingRuntimeClient.mockReturnValue(client);

    renderJobs();
    fireEvent.click(await screen.findByRole('button', {
      name: '查看任务详情 技能任务 · 未知进度',
    }));

    const panel = await screen.findByTestId('runtime-job-detail');
    const detailProgress = within(panel).getByRole('progressbar', { name: '任务真实进度' });
    await waitFor(() => {
      expect(detailProgress).toHaveAttribute('aria-valuetext', '进度未知');
      expect(detailProgress).not.toHaveAttribute('aria-valuenow');
    });
    expect(screen.getByRole('progressbar', { name: '技能任务 · 未知进度 进度' })).toHaveAttribute(
      'aria-valuetext',
      '进度未知',
    );
    expect(within(panel).getByText('--')).toBeInTheDocument();
    expect(screen.queryByText('旧阶段')).not.toBeInTheDocument();
    expect(screen.queryByText('旧进度')).not.toBeInTheDocument();
    expect(within(panel).queryByText('60%')).not.toBeInTheDocument();
    expect(within(panel).queryByText('50%')).not.toBeInTheDocument();
  });

  it('shows bounded snapshot and artifact failures and retries both detail requests', async () => {
    const jobId = 'runtime_retry_secret';
    const getJobEventSnapshot = vi
      .fn()
      .mockRejectedValueOnce(new Error('GET /runtime/job/job_secret token=sk-hidden C:\\private\\trace.log'))
      .mockResolvedValueOnce(makeRuntimeSnapshot({ jobId, status: 'completed' }));
    const getJobArtifacts = vi
      .fn()
      .mockRejectedValueOnce(new Error('artifact api_key=sk-hidden C:\\private\\artifact.json'))
      .mockResolvedValueOnce([]);
    const client = runtimeClientWithJobs([
      {
        job_id: jobId,
        kind: 'skill_action',
        action_id: '生成摘要',
        skill_id: null,
        session_id: 'session_internal_1',
        status: 'failed',
        input_text: '失败任务',
        created_at: '2026-07-22T01:00:00.000Z',
        started_at: '2026-07-22T01:00:01.000Z',
        completed_at: '2026-07-22T01:00:03.000Z',
        error: null,
      },
    ], { getJobEventSnapshot, getJobArtifacts });
    mockedGetWritingRuntimeClient.mockReturnValue(client);

    renderJobs();
    fireEvent.click(await screen.findByRole('button', {
      name: '查看任务详情 技能任务 · 失败任务',
    }));

    const panel = await screen.findByTestId('runtime-job-detail');
    await waitFor(() => {
      expect(within(panel).getByRole('alert')).toHaveTextContent('任务运行详情暂不可用，请稍后重试。');
      expect(within(panel).getByRole('status')).toHaveTextContent('任务产物暂不可用，请稍后重试。');
    });
    expect(document.body.textContent).not.toMatch(/sk-hidden|job_secret|C:\\private/i);

    fireEvent.click(within(panel).getByRole('button', { name: '重试' }));

    await waitFor(() => {
      expect(getJobEventSnapshot).toHaveBeenCalledTimes(2);
      expect(getJobArtifacts).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(within(panel).queryByRole('alert')).not.toBeInTheDocument();
      expect(within(panel).queryByRole('status')).not.toBeInTheDocument();
    });
  });

  it('restarts a selected terminal detail after the row retry succeeds', async () => {
    const jobId = 'runtime_row_retry';
    const getJobEventSnapshot = vi
      .fn()
      .mockResolvedValueOnce(makeRuntimeSnapshot({
        jobId,
        status: 'failed',
        events: [makeRuntimeEvent({
          jobId,
          sequence: 1,
          timestamp: '2026-07-22T04:00:00.000Z',
          eventType: 'job_failed',
        })],
      }))
      .mockResolvedValueOnce(makeRuntimeSnapshot({
        jobId,
        status: 'completed',
        events: [makeRuntimeEvent({
          jobId,
          sequence: 2,
          timestamp: '2026-07-22T04:01:00.000Z',
          eventType: 'job_completed',
        })],
      }));
    const client = runtimeClientWithJobs([
      {
        job_id: jobId,
        kind: 'skill_action',
        action_id: '生成摘要',
        skill_id: null,
        session_id: 'session_internal_1',
        status: 'failed',
        input_text: '单项重试',
        created_at: '2026-07-22T01:00:00.000Z',
        started_at: '2026-07-22T01:00:01.000Z',
        completed_at: '2026-07-22T01:00:03.000Z',
        error: null,
      },
    ], {
      getJobEventSnapshot,
      getJobArtifacts: vi.fn(async () => []),
    });
    mockedGetWritingRuntimeClient.mockReturnValue(client);

    renderJobs();
    fireEvent.click(await screen.findByRole('button', {
      name: '查看任务详情 技能任务 · 单项重试',
    }));
    await waitFor(() => expect(getJobEventSnapshot).toHaveBeenCalledTimes(1));

    fireEvent.click(within(screen.getByTestId('jobs-scroll-list')).getByRole('button', { name: '重试' }));

    await waitFor(() => {
      expect(client.startJob).toHaveBeenCalledWith(jobId);
      expect(getJobEventSnapshot).toHaveBeenCalledTimes(2);
    });
  });

  it('restarts the selected detail after that job succeeds in a bulk retry', async () => {
    const selectedJobId = 'runtime_bulk_retry_1';
    const otherJobId = 'runtime_bulk_retry_2';
    const getJobEventSnapshot = vi
      .fn()
      .mockResolvedValueOnce(makeRuntimeSnapshot({
        jobId: selectedJobId,
        status: 'failed',
        events: [makeRuntimeEvent({
          jobId: selectedJobId,
          sequence: 1,
          timestamp: '2026-07-22T05:00:00.000Z',
          eventType: 'job_failed',
        })],
      }))
      .mockResolvedValueOnce(makeRuntimeSnapshot({
        jobId: selectedJobId,
        status: 'completed',
        events: [makeRuntimeEvent({
          jobId: selectedJobId,
          sequence: 2,
          timestamp: '2026-07-22T05:01:00.000Z',
          eventType: 'job_completed',
        })],
      }));
    const jobs: RuntimeJobList = [selectedJobId, otherJobId].map((jobId, index) => ({
      job_id: jobId,
      kind: 'skill_action',
      action_id: '生成摘要',
      skill_id: null,
      session_id: 'session_internal_1',
      status: 'failed',
      input_text: `批量重试 ${index + 1}`,
      created_at: '2026-07-22T01:00:00.000Z',
      started_at: '2026-07-22T01:00:01.000Z',
      completed_at: '2026-07-22T01:00:03.000Z',
      error: null,
    }));
    const client = runtimeClientWithJobs(jobs, {
      getJobEventSnapshot,
      getJobArtifacts: vi.fn(async () => []),
    });
    mockedGetWritingRuntimeClient.mockReturnValue(client);

    renderJobs();
    fireEvent.click(await screen.findByRole('button', {
      name: '查看任务详情 技能任务 · 批量重试 1',
    }));
    await waitFor(() => expect(getJobEventSnapshot).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByLabelText('选择当前筛选中的任务'));
    fireEvent.click(await screen.findByRole('button', { name: /开始\/重试/ }));

    await waitFor(() => {
      expect(client.startJob).toHaveBeenCalledWith(selectedJobId);
      expect(client.startJob).toHaveBeenCalledWith(otherJobId);
      expect(getJobEventSnapshot).toHaveBeenCalledTimes(2);
    });
  });
});
