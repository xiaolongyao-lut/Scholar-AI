import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { WikiApiError } from '@/services/wikiApi';
import { formatPanelError, WikiWorkbench } from './WikiWorkbench';

vi.mock('@/services/wikiApi', async () => {
  const actual = await vi.importActual<typeof import('@/services/wikiApi')>('@/services/wikiApi');
  return {
    ...actual,
    getWikiStatus: vi.fn(async () => ({
      enabled: false,
      stale: false,
      integrity_status: 'disabled',
      index_hash: 'none',
      source_manifest_hash: 'unknown',
      indexed_source_manifest_hash: 'unknown',
      indexed_page_count: 0,
      source_page_count: null,
      page_count: 0,
      graph_json_exists: false,
      graph_db_exists: false,
      query_index_exists: false,
      review_queue_exists: false,
      paths: {},
      warnings: [],
      manifest_drilldown: {
        schema_version: 'scholar-ai-wiki-manifest-drilldown/v1',
        status: 'disabled',
        hash_algorithm: 'sha256',
        limit: 10,
        missing_count: 0,
        extra_count: 0,
        mismatched_count: 0,
        truncated: false,
        missing_pages: [],
        extra_pages: [],
        mismatched_pages: [],
      },
      index_exists: false,
    })),
    getWikiPages: vi.fn(async () => ({ enabled: false, pages: [] })),
    getWikiDoctor: vi.fn(async () => ({
      enabled: false,
      report: {},
      warnings: [],
      structuredReport: null,
    })),
    getWikiReview: vi.fn(async () => ({ enabled: false, items: [] })),
    getWikiGraph: vi.fn(async () => ({
      enabled: false,
      graph: {},
      structuredGraph: { updated_at: '', node_count: 0, edge_count: 0, nodes: [], edges: [] },
    })),
    runWikiCompileDryRun: vi.fn(),
    createWikiImportMarkdown: vi.fn(),
    searchWiki: vi.fn(),
    exportWikiMarkdown: vi.fn(),
  };
});

vi.mock('@/services/graphApi', () => ({
  getGraphPayload: vi.fn(async () => ({ version: 'v0', nodes: [], edges: [] })),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

describe('WikiWorkbench panel error formatting', () => {
  it('hides backend routes, env labels, capability ids, and local paths', () => {
    const error = new Error(
      'GET /api/wiki/search failed env=VISION_PROVIDER capability_resolved C:\\Users\\xiao\\wiki',
    );

    const message = formatPanelError(error, 'Wiki 搜索');

    expect(message).toBe('读取Wiki 搜索失败。');
    expect(message).not.toContain('/api/wiki/search');
    expect(message).not.toContain('env=VISION_PROVIDER');
    expect(message).not.toContain('capability_resolved');
    expect(message).not.toContain('C:\\Users\\xiao');
  });

  it('keeps safe user-facing Wiki API errors', () => {
    expect(formatPanelError(new WikiApiError('Wiki 集成尚未启用。', 400), 'Wiki 状态')).toBe(
      'Wiki 集成尚未启用。',
    );
  });

  it('summarizes server-side Wiki failures without raw detail', () => {
    const message = formatPanelError(
      new WikiApiError('{"detail":"page_store_path missing"}', 503),
      'Wiki 图谱',
    );

    expect(message).toBe('Wiki 图谱暂不可用（503）。请确认后端服务已启动并已启用对应功能。');
    expect(message).not.toContain('page_store_path');
  });

  it('opens the Settings feature switchboard from the disabled Wiki prompt', async () => {
    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
          <Route path="/settings" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('Wiki 当前未启用')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '查看功能开关' }));

    expect(screen.getByTestId('location')).toHaveTextContent('/settings?section=experimental');
  });

  it('renders local markdown import controls and keeps the flow dry-run-first', async () => {
    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <Routes>
          <Route path="/wiki" element={<WikiWorkbench />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('本地 Markdown 导入')).toBeInTheDocument());
    expect(screen.getByText('先 dry-run，再确认写入。写入结果会进入 private review queue，且保留 runtime recovery 记录。')).toBeInTheDocument();
    expect(screen.getByLabelText('Markdown 路径')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '运行预览' })).toBeDisabled();
  });
});
