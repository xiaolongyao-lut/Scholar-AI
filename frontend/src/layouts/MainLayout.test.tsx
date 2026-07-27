import { readFileSync } from 'node:fs';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MainLayout } from './MainLayout';
import { useWriting } from '@/contexts/WritingContext';
import { getWritingBackendService } from '@/services/writingBackend';

vi.mock('@/contexts/I18nContext', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      if (key === 'nav.notifications_projects_loaded') return `已加载 ${String(params?.count ?? 0)} 个项目`;
      return key;
    },
  }),
}));

vi.mock('@/contexts/WritingContext', () => ({
  useWriting: vi.fn(),
}));

vi.mock('@/services/writingBackend', () => ({
  getWritingBackendService: vi.fn(),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock('@/components/ui/ThemeToggle', () => ({
  ThemeToggle: () => <button type="button">主题</button>,
}));

const mockedUseWriting = vi.mocked(useWriting);
const mockedGetWritingBackendService = vi.mocked(getWritingBackendService);

function renderMainLayout(initialEntry: string): void {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <MainLayout>
        <div>页面内容</div>
      </MainLayout>
    </MemoryRouter>,
  );
}

describe('MainLayout route project synchronization', () => {
  const setActiveProjectId = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseWriting.mockReturnValue({
      activeProjectId: 'project-a',
      setActiveProjectId,
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
    mockedGetWritingBackendService.mockReturnValue({
      listProjects: vi.fn(async () => [
        {
          project_id: 'project-a',
          title: '项目 A',
          description: '',
          status: 'active',
          created_at: '2026-05-29T00:00:00.000Z',
          updated_at: '2026-05-29T00:00:00.000Z',
        },
      ]),
      deleteProject: vi.fn(),
    } as unknown as ReturnType<typeof getWritingBackendService>);
  });

  it('keeps an explicit route project id even when it is not in the visible project list', async () => {
    renderMainLayout('/dialog?project_id=missing-project');

    await waitFor(() => {
      expect(setActiveProjectId).toHaveBeenCalledWith('missing-project');
    });
    expect(setActiveProjectId).not.toHaveBeenCalledWith('project-a');
  });

  it('describes header project removal as a recoverable archive that retains resources', () => {
    const source = readFileSync('src/layouts/MainLayout.tsx', 'utf8');

    expect(source).toContain(
      '确定要归档项目「${project.title}」吗？归档后项目资源会保留，之后可以恢复。',
    );
    expect(source).not.toContain('删除后无法恢复');
  });
});
