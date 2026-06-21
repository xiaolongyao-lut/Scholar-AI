import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Jobs } from './Jobs';
import { getWritingRuntimeClient } from '@/services/runtimeClient';

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

function runtimeClientWithJobs(jobs: Awaited<ReturnType<RuntimeClient['listJobs']>>): RuntimeClient {
  return {
    listJobs: vi.fn(async () => jobs),
    pauseJob: vi.fn(),
    resumeJob: vi.fn(),
    cancelJob: vi.fn(),
    startJob: vi.fn(),
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
});
