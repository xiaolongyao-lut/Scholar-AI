import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Projects, formatProjectActionError } from './Projects';
import { useWriting } from '@/contexts/WritingContext';
import { getWritingBackendService } from '@/services/writingBackend';

vi.mock('@/contexts/I18nContext', () => ({
  useI18n: () => ({
    t: (key: string) => {
      const labels: Record<string, string> = {
        'projects.title': '项目',
        'projects.subtitle': '项目总览',
        'projects.new_project': '新建项目',
        'projects.status_draft': '草稿',
        'projects.status_active': '进行中',
        'projects.status_archived': '已归档',
        'projects.status_indexing': '索引中',
        'projects.status_failed': '失败',
        'projects.filter_all': '全部',
        'projects.filter_active': '进行中',
        'projects.filter_draft': '草稿',
        'projects.filter_archived': '已归档',
        'projects.search_placeholder': '搜索项目',
        'projects.empty_title': '暂无项目',
        'projects.empty_description': '创建一个项目开始',
        'projects.create_title': '创建项目',
        'projects.field_title': '项目名称',
        'projects.field_title_placeholder': '输入项目名称',
        'projects.field_desc': '项目描述',
        'projects.field_desc_placeholder': '输入项目描述',
        'projects.create_btn': '创建',
        'common.close': '关闭',
        'common.cancel': '取消',
      };
      return labels[key] ?? key;
    },
  }),
}));

vi.mock('@/contexts/WritingContext', () => ({
  useWriting: vi.fn(),
}));

vi.mock('@/services/writingBackend', () => ({
  getWritingBackendService: vi.fn(),
}));

const mockedUseWriting = vi.mocked(useWriting);
const mockedGetService = vi.mocked(getWritingBackendService);

function renderProjects(): void {
  render(
    <MemoryRouter>
      <Projects />
    </MemoryRouter>,
  );
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe('Projects', () => {
  beforeEach(() => {
    mockedUseWriting.mockReturnValue({
      activeProjectId: 'project-a',
      setActiveProjectId: vi.fn(),
      activeJournalStyleProfileId: '',
      setActiveJournalStyleProfileId: vi.fn(),
      projectDataVersion: 0,
      markProjectDataChanged: vi.fn(),
      activeSectionId: '',
      setActiveSectionId: vi.fn(),
      outputMode: 'markdown',
      setOutputMode: vi.fn(),
      scope: 'section',
      setScope: vi.fn(),
      connectionState: 'online',
      setConnectionState: vi.fn(),
      sessionStatus: 'idle',
      setSessionStatus: vi.fn(),
      sessionMessage: null,
      setSessionMessage: vi.fn(),
      activeJobTimeline: null,
      setActiveJobTimeline: vi.fn(),
      leftNavCollapsed: false,
      setLeftNavCollapsed: vi.fn(),
      rightDockMode: 'assistant',
      setRightDockMode: vi.fn(),
      zenMode: false,
      setZenMode: vi.fn(),
      citationDrawerOpen: false,
      setCitationDrawerOpen: vi.fn(),
    });
    mockedGetService.mockReturnValue({
      listProjects: vi.fn(async () => [
        {
          project_id: 'project-a',
          title: '项目 A',
          description: 'A desc',
          status: 'active',
          created_at: '2026-05-01T00:00:00.000Z',
          updated_at: '2026-05-02T00:00:00.000Z',
        },
        {
          project_id: 'project-b',
          title: '项目 B',
          description: 'B desc',
          status: 'draft',
          created_at: '2026-05-03T00:00:00.000Z',
          updated_at: '2026-05-04T00:00:00.000Z',
        },
      ]),
      cleanupHistoricalData: vi.fn(),
      deleteProject: vi.fn(),
      createProject: vi.fn(),
    } as unknown as ReturnType<typeof getWritingBackendService>);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows all projects even when one project is currently active', async () => {
    renderProjects();

    await waitFor(() => {
      expect(screen.getAllByText('项目 A').length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText('项目 B')).toBeInTheDocument();
    });
    expect(screen.getByTitle('当前激活项目：项目 A')).toBeInTheDocument();
  });

  it('describes batch removal as a recoverable archive that retains project resources', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);

    renderProjects();
    expect(await screen.findByText('项目 B')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '批量管理' }));
    fireEvent.click(screen.getByRole('button', { name: '归档 (2)' }));

    expect(confirm).toHaveBeenCalledWith(
      '确定要归档选中的 2 个项目吗？归档后项目资源会保留，之后可以恢复。',
    );
  });

  it('shows first-load progress instead of a false empty project state', async () => {
    const pendingProjects = deferred<Awaited<ReturnType<ReturnType<typeof getWritingBackendService>['listProjects']>>>();
    mockedGetService.mockReturnValue({
      listProjects: vi.fn(() => pendingProjects.promise),
      cleanupHistoricalData: vi.fn(),
      deleteProject: vi.fn(),
      createProject: vi.fn(),
    } as unknown as ReturnType<typeof getWritingBackendService>);

    renderProjects();

    expect(screen.getByRole('status')).toHaveTextContent('正在加载项目');
    expect(screen.queryByText('暂无项目')).not.toBeInTheDocument();

    await act(async () => {
      pendingProjects.resolve([]);
      await pendingProjects.promise;
    });

    expect(await screen.findByText('暂无项目')).toBeInTheDocument();
    expect(screen.queryByText('正在加载项目')).not.toBeInTheDocument();
  });

  it('keeps the last project snapshot visible when a refresh fails', async () => {
    const projectList = [
      {
        project_id: 'project-a',
        title: '项目 A',
        description: 'A desc',
        status: 'active',
        created_at: '2026-05-01T00:00:00.000Z',
        updated_at: '2026-05-02T00:00:00.000Z',
      },
      {
        project_id: 'project-b',
        title: '项目 B',
        description: 'B desc',
        status: 'draft',
        created_at: '2026-05-03T00:00:00.000Z',
        updated_at: '2026-05-04T00:00:00.000Z',
      },
    ];
    const listProjects = vi
      .fn()
      .mockResolvedValueOnce(projectList)
      .mockRejectedValueOnce(new Error('GET /resources/projects failed token=hidden'));
    mockedGetService.mockReturnValue({
      listProjects,
      cleanupHistoricalData: vi.fn(),
      deleteProject: vi.fn(async () => undefined),
      createProject: vi.fn(),
    } as unknown as ReturnType<typeof getWritingBackendService>);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderProjects();
    expect(await screen.findByText('项目 B')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '批量管理' }));
    fireEvent.click(screen.getByRole('button', { name: '归档 (2)' }));

    await waitFor(() => expect(listProjects).toHaveBeenCalledTimes(2));
    expect(screen.getByText('项目 B')).toBeInTheDocument();
    expect(screen.queryByText('暂无项目')).not.toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('项目列表暂时不可用，请稍后重试。');
    expect(document.body.textContent).not.toContain('/resources/projects');
    expect(document.body.textContent).not.toContain('token=hidden');
  });

  it('shows a retryable error instead of an empty state when the first load fails', async () => {
    mockedGetService.mockReturnValue({
      listProjects: vi.fn(async () => {
        throw new Error('GET /resources/projects failed token=hidden');
      }),
      cleanupHistoricalData: vi.fn(),
      deleteProject: vi.fn(),
      createProject: vi.fn(),
    } as unknown as ReturnType<typeof getWritingBackendService>);

    renderProjects();

    expect(await screen.findByText('项目加载失败')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();
    expect(screen.queryByText('暂无项目')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('/resources/projects');
    expect(document.body.textContent).not.toContain('token=hidden');
  });

  it('closes the create-project dialog with Escape without creating a project', async () => {
    const createProject = vi.fn();
    mockedGetService.mockReturnValue({
      listProjects: vi.fn(async () => []),
      cleanupHistoricalData: vi.fn(),
      deleteProject: vi.fn(),
      createProject,
    } as unknown as ReturnType<typeof getWritingBackendService>);

    renderProjects();

    fireEvent.click(await screen.findByRole('button', { name: '新建项目' }));
    expect(screen.getByRole('dialog', { name: '创建项目' })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('项目名称'), {
      target: { value: '桌面端回归测试-不创建' },
    });
    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' });

    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '创建项目' })).not.toBeInTheDocument();
    });
    expect(createProject).not.toHaveBeenCalled();
  });

  it('sanitizes project action errors before they are shown', () => {
    expect(formatProjectActionError(new Error('/resources/project/project-a failed env=VISION_PROVIDER'), '项目创建失败，请稍后重试。')).toBe('项目创建失败，请稍后重试。');
    expect(formatProjectActionError('capability_resolved', '项目清理失败，请稍后重试。')).toBe('项目清理失败，请稍后重试。');
    expect(formatProjectActionError('项目名称已存在，请换一个名称。')).toBe('项目名称已存在，请换一个名称。');
  });
});
