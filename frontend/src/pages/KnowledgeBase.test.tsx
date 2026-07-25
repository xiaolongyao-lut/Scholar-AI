import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios from 'axios';

import { KnowledgeBase } from './KnowledgeBase';

const mocks = vi.hoisted(() => ({
  activeProjectId: 'project-a',
  setActiveProjectId: vi.fn(),
  listMaterials: vi.fn(),
  getJobEventSnapshot: vi.fn(),
  visibilityState: 'visible' as DocumentVisibilityState,
}));

vi.mock('@/contexts/I18nContext', () => ({
  useI18n: () => ({
    t: (key: string, vars?: Record<string, unknown>) => {
      const labels: Record<string, string> = {
        'kb.title': '文献库',
        'kb.title_with_project': `文献库 · ${String(vars?.name ?? '')}`,
        'kb.subtitle': '管理项目文献',
        'kb.no_project_title': '请选择项目',
        'kb.no_project_desc': '选择项目后查看文献。',
        'kb.empty_title': '暂无文献',
        'kb.empty_desc': '导入文献后会显示在这里。',
        'kb.no_search_results': '没有匹配文献',
        'kb.no_search_results_desc': '请调整筛选条件。',
        'kb.select_files': '选择文件',
        'kb.select_folder': '选择文件夹',
        'kb.upload_hint': '拖入或选择文献',
        'kb.upload_batch_hint': '支持批量导入',
        'common.refresh': '刷新',
      };
      return labels[key] ?? key;
    },
  }),
}));

vi.mock('@/contexts/WritingContext', () => ({
  useWriting: () => ({
    activeProjectId: mocks.activeProjectId,
    setActiveProjectId: mocks.setActiveProjectId,
  }),
}));

vi.mock('@/services/writingBackend', () => ({
  getWritingBackendService: () => ({
    listMaterials: mocks.listMaterials,
  }),
}));

vi.mock('@/services/apiBaseUrl', () => ({
  getApiBaseUrl: () => 'http://localhost:8000',
}));

vi.mock('@/services/runtimeClient', () => ({
  getWritingRuntimeClient: () => ({
    getJobEventSnapshot: mocks.getJobEventSnapshot,
  }),
}));

vi.mock('./UploadBatchSummaryView', () => ({
  UploadBatchSummary: ({ result }: {
    result: {
      completed_files?: number;
      queued_files?: number;
      failed_files?: number;
      total_chunks?: number;
      results?: Array<{ status?: string }>;
    };
  }) => (
    <div data-testid="upload-summary">
      completed={String(result.completed_files ?? 0)} queued={String(result.queued_files ?? 0)}
      {' '}failed={String(result.failed_files ?? 0)} chunks={String(result.total_chunks ?? 0)}
      {' '}status={String(result.results?.[0]?.status ?? '')}
    </div>
  ),
}));

vi.mock('@/components/knowledge/ReasoningBiasBar', () => ({
  ReasoningBiasBar: () => null,
}));

vi.mock('@/components/knowledge/MetadataLinterPanel', () => ({
  MetadataLinterPanel: () => null,
}));

vi.mock('@/components/workbench/ReparseWithMarkerButton', () => ({
  ReparseWithMarkerButton: () => null,
}));

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function renderKnowledgeBase() {
  return render(
    <MemoryRouter initialEntries={['/knowledge']}>
      <KnowledgeBase />
    </MemoryRouter>,
  );
}

function material(materialId: string, title: string) {
  return {
    material_id: materialId,
    title,
    created_at: '2026-07-23T01:00:00.000Z',
  };
}

describe('KnowledgeBase refresh UX', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    mocks.activeProjectId = 'project-a';
    mocks.visibilityState = 'visible';
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => mocks.visibilityState,
    });
    vi.spyOn(axios, 'get').mockImplementation(async (url) => {
      if (String(url).includes('/resources/chunks')) {
        return { data: { chunks: [] } } as never;
      }
      return { data: { title: '项目 A' } } as never;
    });
  });

  it('shows a stable loading state instead of a false empty library before the first response', async () => {
    const request = deferred<unknown[]>();
    mocks.listMaterials.mockReturnValueOnce(request.promise);

    renderKnowledgeBase();

    expect(screen.getByRole('status')).toHaveTextContent('正在加载文献');
    expect(screen.queryByText('暂无文献')).not.toBeInTheDocument();

    await act(async () => {
      request.resolve([]);
      await request.promise;
    });
  });

  it('keeps the same material row mounted while a background refresh is pending', async () => {
    const refresh = deferred<unknown[]>();
    mocks.listMaterials
      .mockResolvedValueOnce([material('mat-a', 'paper-a.pdf')])
      .mockReturnValueOnce(refresh.promise);

    renderKnowledgeBase();
    const table = await screen.findByRole('table');
    const row = within(table).getByText('paper-a.pdf').closest('tr');
    expect(row).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '刷新' }));

    expect(screen.getByRole('status')).toHaveTextContent('正在刷新');
    expect(within(table).getByText('paper-a.pdf').closest('tr')).toBe(row);
    expect(screen.queryByText('暂无文献')).not.toBeInTheDocument();

    await act(async () => {
      refresh.resolve([material('mat-a', 'paper-a.pdf')]);
      await refresh.promise;
    });
  });

  it('keeps the last material snapshot and shows a retryable safe error after refresh failure', async () => {
    mocks.listMaterials
      .mockResolvedValueOnce([material('mat-a', 'paper-a.pdf')])
      .mockRejectedValueOnce(new Error('GET /resources/materials token=sk-hidden'));

    renderKnowledgeBase();
    const table = await screen.findByRole('table');
    const row = within(table).getByText('paper-a.pdf').closest('tr');
    expect(row).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '刷新' }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('文献列表暂时无法加载，请稍后重试。');
    });
    expect(within(table).getByText('paper-a.pdf').closest('tr')).toBe(row);
    expect(document.body.textContent).not.toMatch(/sk-hidden|\/resources\/materials/);
  });

  it('does not let an older project response overwrite the current project snapshot', async () => {
    const projectARequest = deferred<unknown[]>();
    const projectBRequest = deferred<unknown[]>();
    mocks.listMaterials.mockImplementation((projectId: string) => (
      projectId === 'project-a' ? projectARequest.promise : projectBRequest.promise
    ));

    const view = renderKnowledgeBase();
    mocks.activeProjectId = 'project-b';
    view.rerender(
      <MemoryRouter initialEntries={['/knowledge']}>
        <KnowledgeBase />
      </MemoryRouter>,
    );

    await act(async () => {
      projectBRequest.resolve([material('mat-b', 'paper-b.pdf')]);
      await projectBRequest.promise;
    });
    const table = await screen.findByRole('table');
    expect(within(table).getByText('paper-b.pdf')).toBeInTheDocument();

    await act(async () => {
      projectARequest.resolve([material('mat-a', 'paper-a.pdf')]);
      await projectARequest.promise;
    });

    await waitFor(() => {
      expect(within(table).getByText('paper-b.pdf')).toBeInTheDocument();
      expect(within(table).queryByText('paper-a.pdf')).not.toBeInTheDocument();
    });
  });

  it('does not let an older project detail response overwrite the current project header', async () => {
    const projectARequest = deferred<{ data: { title: string } }>();
    const projectBRequest = deferred<{ data: { title: string } }>();
    mocks.listMaterials.mockResolvedValue([]);
    vi.spyOn(axios, 'get').mockImplementation((url) => {
      const requestUrl = String(url);
      if (requestUrl.includes('/resources/chunks')) {
        return Promise.resolve({ data: { chunks: [] } }) as never;
      }
      if (requestUrl.includes('/resources/project/project-a')) {
        return projectARequest.promise as never;
      }
      if (requestUrl.includes('/resources/project/project-b')) {
        return projectBRequest.promise as never;
      }
      return Promise.reject(new Error(`unexpected request: ${requestUrl}`)) as never;
    });

    const view = renderKnowledgeBase();
    mocks.activeProjectId = 'project-b';
    view.rerender(
      <MemoryRouter initialEntries={['/knowledge']}>
        <KnowledgeBase />
      </MemoryRouter>,
    );

    await act(async () => {
      projectBRequest.resolve({ data: { title: '项目 B' } });
      await projectBRequest.promise;
    });
    expect(await screen.findByText('文献库 · 项目 B')).toBeInTheDocument();

    await act(async () => {
      projectARequest.resolve({ data: { title: '项目 A' } });
      await projectARequest.promise;
    });

    await waitFor(() => {
      expect(screen.getByText('文献库 · 项目 B')).toBeInTheDocument();
      expect(screen.queryByText('文献库 · 项目 A')).not.toBeInTheDocument();
    });
  });

  it('converges a queued upload job into a completed summary and reloads its material', async () => {
    let runtimeCompleted = false;
    mocks.listMaterials.mockImplementation(async () => (
      runtimeCompleted ? [material('mat-imported', 'imported-paper.pdf')] : []
    ));
    vi.spyOn(axios, 'post').mockResolvedValueOnce({
      data: {
        project_id: 'project-a',
        batch_id: 'batch-visible',
        submitted_at: '2026-07-23T01:00:00.000Z',
        total_files: 1,
        accepted_files: 1,
        completed_files: 0,
        successful_files: 0,
        duplicate_files: 0,
        skipped_files: 0,
        queued_files: 1,
        failed_files: 0,
        total_chunks: 0,
        results: [{
          material_id: 'mat-imported',
          title: 'imported-paper.pdf',
          status: 'queued',
          job_id: 'job-imported',
        }],
      },
    } as never);
    mocks.getJobEventSnapshot.mockImplementationOnce(async () => {
      runtimeCompleted = true;
      return {
        job: {
          status: 'completed',
          material_processing_task_summary: {
            chunks: 7,
            content_length: 2048,
          },
        },
        status: { status: 'completed' },
        events: [],
      };
    });

    renderKnowledgeBase();
    await screen.findByText('暂无文献');
    fireEvent.change(screen.getByLabelText('选择文件'), {
      target: { files: [new File(['%PDF-1.7'], 'imported-paper.pdf', { type: 'application/pdf' })] },
    });

    await waitFor(() => {
      expect(screen.getByTestId('upload-summary')).toHaveTextContent(
        'completed=1 queued=0 failed=0 chunks=7 status=ok',
      );
    });
    expect(mocks.getJobEventSnapshot).toHaveBeenCalledWith('job-imported', {
      afterSequence: null,
      limit: 50,
    });
    const table = await screen.findByRole('table');
    expect(within(table).getByText('imported-paper.pdf')).toBeInTheDocument();
  });

  it('pauses queued upload polling while hidden and resumes immediately when visible', async () => {
    mocks.visibilityState = 'hidden';
    mocks.listMaterials.mockResolvedValue([]);
    vi.spyOn(axios, 'post').mockResolvedValueOnce({
      data: {
        project_id: 'project-a',
        batch_id: 'batch-hidden',
        submitted_at: '2026-07-23T01:00:00.000Z',
        total_files: 1,
        accepted_files: 1,
        completed_files: 0,
        successful_files: 0,
        duplicate_files: 0,
        skipped_files: 0,
        queued_files: 1,
        failed_files: 0,
        total_chunks: 0,
        results: [{
          material_id: 'mat-hidden',
          title: 'hidden-paper.pdf',
          status: 'queued',
          job_id: 'job-hidden',
        }],
      },
    } as never);
    mocks.getJobEventSnapshot.mockResolvedValue({
      job: { status: 'started', material_processing_task_summary: {} },
      status: { status: 'started' },
      events: [],
    });

    renderKnowledgeBase();
    await screen.findByText('暂无文献');
    fireEvent.change(screen.getByLabelText('选择文件'), {
      target: { files: [new File(['%PDF-1.7'], 'hidden-paper.pdf', { type: 'application/pdf' })] },
    });
    await screen.findByTestId('upload-summary');
    expect(mocks.getJobEventSnapshot).not.toHaveBeenCalled();

    mocks.visibilityState = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));

    await waitFor(() => {
      expect(mocks.getJobEventSnapshot).toHaveBeenCalledTimes(1);
    });
  });
});
