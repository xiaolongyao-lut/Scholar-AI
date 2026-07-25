import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { EvidencePill, __resetEvidencePillCacheForTests } from './EvidencePill';

const locateChunkMock = vi.fn();

vi.mock('@/services/resourcesApi', () => ({
  locateChunk: (chunkId: string, projectId: string | null | undefined) =>
    locateChunkMock(chunkId, projectId),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function parseLocationUrl(value: string): URL {
  return new URL(value, 'http://localhost');
}

beforeEach(() => {
  locateChunkMock.mockReset();
  __resetEvidencePillCacheForTests();
});

describe('EvidencePill', () => {
  it('renders a friendly source label with page badge', () => {
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{ source: 'Vaswani 2017', page: 7, material_id: 'm1' }}
        />
      </MemoryRouter>,
    );
    const btn = screen.getByRole('button');
    expect(btn.textContent).toContain('Vaswani 2017');
    expect(btn.textContent).toContain('p.7');
  });

  it('exposes cited-project evidence role without adding a separate evidence summary', () => {
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{
            source: 'Referenced paper',
            material_id: 'm-cited',
            evidence_role: 'cited_project_material',
          }}
        />
      </MemoryRouter>,
    );

    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('data-evidence-role', 'cited_project_material');
    expect(button).toHaveAttribute('title', expect.stringContaining('被引项目文献'));
    expect(screen.queryByText('证据摘要')).not.toBeInTheDocument();
  });

  it('never displays raw chunk_id / material_id as user-visible text (R5)', () => {
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{
            material_id: 'mat_42',
            chunk_id: 'chunk_xyz',
          }}
        />
      </MemoryRouter>,
    );
    const label = screen.getByRole('button').textContent ?? '';
    expect(label).not.toContain('mat_42');
    expect(label).not.toContain('chunk_xyz');
    expect(label).toContain('证据');
  });

  it('marks selected pill with aria-pressed (focused pair, MC-4)', () => {
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{ source: 'src', material_id: 'm1' }}
          selected
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true');
  });

  it('invokes onActivate instead of navigating when provided', () => {
    const onActivate = vi.fn();
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{ source: 'src', material_id: 'm1', page: 3 }}
          onActivate={onActivate}
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    expect(onActivate).toHaveBeenCalledTimes(1);
    // No navigation
    expect(screen.getByTestId('location').textContent).toBe('/');
    expect(
      screen.getByRole('button').querySelector('[data-navigation-status]')?.getAttribute('data-navigation-status'),
    ).toBe('selected');
  });

  it('can select evidence and still navigate for Workbench evidence focus', async () => {
    const onActivate = vi.fn();
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{ source: 'src', material_id: 'm1', page: 3, chunk_id: 'c1' }}
          onActivate={onActivate}
          navigateAfterActivate
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    expect(onActivate).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('scope')).toBe('paper');
      expect(parsed.searchParams.get('material_id')).toBe('m1');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('page')).toBe('3');
      expect(parsed.searchParams.get('chunk')).toBe('c1');
      expect(
        screen.getByRole('button').querySelector('[data-navigation-status]')?.getAttribute('data-navigation-status'),
      ).toBe('opened');
    });
  });

  it('keeps the given page and attempts locator enrichment when bbox is missing', async () => {
    locateChunkMock.mockResolvedValueOnce(null);
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{ source: 'src', material_id: 'm1', page: 5, chunk_id: 'c1' }}
          projectId="p1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('scope')).toBe('paper');
      expect(parsed.searchParams.get('material_id')).toBe('m1');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('p1');
      expect(parsed.searchParams.get('page')).toBe('5');
      expect(parsed.searchParams.get('chunk')).toBe('c1');
    });
    expect(locateChunkMock).toHaveBeenCalledWith('c1', 'p1');
    expect(
      screen.getByRole('button').querySelector('[data-navigation-status]')?.getAttribute('data-navigation-status'),
    ).toBe('opened');
  });

  it('includes normalized bbox when ref carries a page-level target box', async () => {
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{
            source: 'src',
            material_id: 'm1',
            page: 5,
            chunk_id: 'c1',
            bbox: [0.12, 0.25, 0.3, 0.08],
          }}
          projectId="p1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('scope')).toBe('paper');
      expect(parsed.searchParams.get('material_id')).toBe('m1');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('p1');
      expect(parsed.searchParams.get('page')).toBe('5');
      expect(parsed.searchParams.get('chunk')).toBe('c1');
      expect(parsed.searchParams.get('bbox')).toBe('0.12,0.25,0.3,0.08');
    });
    expect(locateChunkMock).not.toHaveBeenCalled();
  });

  it('upgrades chunk_id to page via locator when page missing', async () => {
    locateChunkMock.mockResolvedValueOnce({ page: 9 });
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{ source: 'src', material_id: 'm1', chunk_id: 'c1' }}
          projectId="p1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('page=9');
    });
  });

  it('uses locator bbox when the evidence ref only carries chunk_id', async () => {
    locateChunkMock.mockResolvedValueOnce({
      material_id: 'm1',
      chunk_id: 'c1',
      page: 9,
      chunk_index: 1,
      bbox: [0.2, 0.3, 0.25, 0.1],
    });
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{ source: 'src', material_id: 'm1', chunk_id: 'c1' }}
          projectId="p1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      expect(url).toContain('page=9');
      expect(url).toContain('bbox=0.2%2C0.3%2C0.25%2C0.1');
    });
  });

  it('keeps a text quote alongside the locator bbox and its resolved page', async () => {
    locateChunkMock.mockResolvedValueOnce({
      material_id: 'm1',
      chunk_id: 'c-page-only',
      page: 7,
      chunk_index: 3,
      bbox: [0.14, 0.28, 0.32, 0.09],
      bbox_unit: 'normalized_ratio',
    });
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{
            source: 'src',
            material_id: 'm1',
            page: 5,
            chunk_id: 'c-page-only',
            quote: 'The exact cited sentence.',
          }}
          projectId="p1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      const parsed = parseLocationUrl(screen.getByTestId('location').textContent ?? '');
      expect(parsed.searchParams.get('page')).toBe('7');
      expect(parsed.searchParams.get('bbox')).toBe('0.14,0.28,0.32,0.09');
      expect(parsed.searchParams.get('quote')).toBe('The exact cited sentence.');
    });
    expect(locateChunkMock).toHaveBeenCalledWith('c-page-only', 'p1');
  });

  it('carries a bounded exact quote when bbox enrichment is unavailable', async () => {
    locateChunkMock.mockResolvedValueOnce(null);
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{
            source: 'src',
            material_id: 'm1',
            page: 5,
            chunk_id: 'c-quote',
            text: 'A broader evidence window.',
            quote: '  The exact\n cited sentence.  ',
          }}
          projectId="p1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      const parsed = parseLocationUrl(screen.getByTestId('location').textContent ?? '');
      expect(parsed.searchParams.get('page')).toBe('5');
      expect(parsed.searchParams.get('bbox')).toBeNull();
      expect(parsed.searchParams.get('quote')).toBe('The exact cited sentence.');
    });
  });

  it('does not use quote search for a visual anchor without bbox', async () => {
    locateChunkMock.mockResolvedValueOnce(null);
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{
            source: 'src',
            material_id: 'm1',
            page: 5,
            chunk_id: 'c-visual',
            quote: 'Figure 2 caption text.',
            anchor_kind: 'visual',
          }}
          projectId="p1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      const parsed = parseLocationUrl(screen.getByTestId('location').textContent ?? '');
      expect(parsed.searchParams.get('page')).toBe('5');
      expect(parsed.searchParams.get('quote')).toBeNull();
      expect(parsed.searchParams.get('anchor_kind')).toBe('visual');
    });
  });

  it('uses locator material_id when a persisted evidence ref only carries chunk_id', async () => {
    locateChunkMock.mockResolvedValueOnce({
      material_id: 'm-located',
      chunk_id: 'c-located',
      page: 4,
      chunk_index: 2,
      bbox: [0.1, 0.2, 0.3, 0.4],
    });
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{ source: 'src', chunk_id: 'c-located' }}
          projectId="p1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('scope')).toBe('paper');
      expect(parsed.searchParams.get('material_id')).toBe('m-located');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('p1');
      expect(parsed.searchParams.get('page')).toBe('4');
      expect(parsed.searchParams.get('chunk')).toBe('c-located');
      expect(parsed.searchParams.get('bbox')).toBe('0.1,0.2,0.3,0.4');
    });
    expect(locateChunkMock).toHaveBeenCalledWith('c-located', 'p1');
  });

  it('shares locator cache across instances with same (projectId, chunk_id)', async () => {
    locateChunkMock.mockResolvedValueOnce({ page: 9 });
    render(
      <MemoryRouter>
        <EvidencePill
          evidence={{ source: 'first', material_id: 'm1', chunk_id: 'c1' }}
          projectId="p1"
        />
        <EvidencePill
          evidence={{ source: 'second', material_id: 'm1', chunk_id: 'c1' }}
          projectId="p1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    const [a, b] = screen.getAllByRole('button');
    fireEvent.click(a);
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('page=9');
    });
    fireEvent.click(b);
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('page=9');
    });
    expect(locateChunkMock).toHaveBeenCalledTimes(1);
  });

  it('reports unavailable target when material_id is missing and no onActivate', async () => {
    render(
      <MemoryRouter>
        <EvidencePill evidence={{ source: 'src' }} />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByTestId('location').textContent).toBe('/');
    await waitFor(() => {
      expect(
        screen.getByRole('button').querySelector('[data-navigation-status]')?.getAttribute('data-navigation-status'),
      ).toBe('unavailable');
    });
  });

  it('reports locator failure when chunk lookup rejects', async () => {
    locateChunkMock.mockRejectedValueOnce(new Error('locator failed'));
    render(
      <MemoryRouter>
        <EvidencePill evidence={{ source: 'src', chunk_id: 'c-missing' }} projectId="p1" />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/');
      expect(
        screen.getByRole('button').querySelector('[data-navigation-status]')?.getAttribute('data-navigation-status'),
      ).toBe('locator_failed');
    });
  });

  it('retries locator lookup after a transient locator failure', async () => {
    locateChunkMock
      .mockRejectedValueOnce(new Error('transient locator failure'))
      .mockResolvedValueOnce({
        material_id: 'm-recovered',
        chunk_id: 'c-retry',
        page: 6,
      });
    render(
      <MemoryRouter>
        <EvidencePill evidence={{ source: 'src', chunk_id: 'c-retry' }} projectId="p1" />
        <LocationProbe />
      </MemoryRouter>,
    );

    const button = screen.getByRole('button');
    fireEvent.click(button);
    await waitFor(() => {
      expect(
        button.querySelector('[data-navigation-status]')?.getAttribute('data-navigation-status'),
      ).toBe('locator_failed');
    });

    fireEvent.click(button);
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('material_id')).toBe('m-recovered');
      expect(parsed.searchParams.get('page')).toBe('6');
      expect(
        button.querySelector('[data-navigation-status]')?.getAttribute('data-navigation-status'),
      ).toBe('opened');
    });
    expect(locateChunkMock).toHaveBeenCalledTimes(2);
  });

  describe('source_labels 召回路径 chip', () => {
    it('默认关闭: 不渲染 source_labels chip', () => {
      render(
        <MemoryRouter>
          <EvidencePill
            evidence={{
              source: 'Vaswani 2017',
              material_id: 'm1',
              source_labels: ['sibling', 'dense'],
            }}
          />
        </MemoryRouter>,
      );
      const btn = screen.getByRole('button');
      expect(btn.querySelector('[data-source-label]')).toBeNull();
    });

    it('开启时 sibling 标签优先于 dense, 渲染"上下文兄弟"', () => {
      render(
        <MemoryRouter>
          <EvidencePill
            showSourceLabels
            evidence={{
              source: 'Vaswani 2017',
              material_id: 'm1',
              source_labels: ['dense', 'sibling', 'bm25'],
            }}
          />
        </MemoryRouter>,
      );
      const chip = screen.getByRole('button').querySelector('[data-source-label]');
      expect(chip?.getAttribute('data-source-label')).toBe('上下文兄弟');
    });

    it('只有 dense 时渲染"语义匹配"', () => {
      render(
        <MemoryRouter>
          <EvidencePill
            showSourceLabels
            evidence={{
              source: 'src',
              material_id: 'm1',
              source_labels: ['dense'],
            }}
          />
        </MemoryRouter>,
      );
      const chip = screen.getByRole('button').querySelector('[data-source-label]');
      expect(chip?.textContent).toBe('语义匹配');
    });

    it('显示 fallback lexical 和 wiki joint recall 标签', () => {
      render(
        <MemoryRouter>
          <EvidencePill
            showSourceLabels
            evidence={{
              source: 'wiki',
              material_id: 'wiki',
              source_type: 'wiki',
              source_labels: ['wiki_joint_recall', 'lexical'],
            }}
          />
        </MemoryRouter>,
      );
      const chip = screen.getByRole('button').querySelector('[data-source-label]');
      expect(chip?.textContent).toBe('Wiki 扩展');
      const tooltip = screen.getByRole('button').getAttribute('title') ?? '';
      expect(tooltip).toContain('Wiki 扩展');
      expect(tooltip).toContain('词面匹配');
    });

    it('未识别标签 (project_chunks) 不渲染 chip', () => {
      render(
        <MemoryRouter>
          <EvidencePill
            showSourceLabels
            evidence={{
              source: 'src',
              material_id: 'm1',
              source_labels: ['project_chunks', 'local_context'],
            }}
          />
        </MemoryRouter>,
      );
      expect(
        screen.getByRole('button').querySelector('[data-source-label]'),
      ).toBeNull();
    });

    it('全部 friendly labels 出现在 tooltip', () => {
      render(
        <MemoryRouter>
          <EvidencePill
            showSourceLabels
            evidence={{
              source: 'src',
              material_id: 'm1',
              source_labels: ['sibling', 'dense', 'bm25'],
            }}
          />
        </MemoryRouter>,
      );
      const tooltip = screen.getByRole('button').getAttribute('title') ?? '';
      expect(tooltip).toContain('上下文兄弟');
      expect(tooltip).toContain('语义匹配');
      expect(tooltip).toContain('关键词');
    });
  });

  describe('citation_level badge', () => {
    it('显示 未标注 when backend citation_level is absent and does not infer from bbox', () => {
      render(
        <MemoryRouter>
          <EvidencePill
            showCitationLevel
            evidence={{
              source: 'src',
              material_id: 'm1',
              page: 5,
              bbox: [0.1, 0.2, 0.3, 0.4],
            }}
          />
        </MemoryRouter>,
      );

      const badge = screen.getByLabelText('引用等级: 未标注');
      expect(badge).toHaveAttribute('data-citation-level', 'unlabeled');
      expect(badge.textContent).toBe('未标注');
      expect(screen.queryByText('精确框')).toBeNull();
    });

    it('only displays exact precision when backend sends exact_bbox', () => {
      render(
        <MemoryRouter>
          <EvidencePill
            showCitationLevel
            evidence={{
              source: 'src',
              material_id: 'm1',
              citation_level: 'exact_bbox',
            }}
          />
        </MemoryRouter>,
      );

      const badge = screen.getByLabelText('引用等级: 精确框');
      expect(badge).toHaveAttribute('data-citation-level', 'exact_bbox');
      expect(badge.textContent).toBe('精确框');
    });
  });
});
