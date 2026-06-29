import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SparkEvidencePills } from './SparkEvidencePills';
import { __resetEvidencePillCacheForTests } from '@/components/evidence/EvidencePill';
import type { SparkEvidenceRef } from '@/types/writing';

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

describe('SparkEvidencePills', () => {
  it('renders nothing when refs is undefined', () => {
    const { container } = render(
      <MemoryRouter>
        <SparkEvidencePills />
      </MemoryRouter>,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when refs is empty', () => {
    const { container } = render(
      <MemoryRouter>
        <SparkEvidencePills refs={[]} />
      </MemoryRouter>,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders one button per ref with truncated text label', () => {
    const refs: SparkEvidenceRef[] = [
      { material_id: 'mat_a', chunk_id: 'c1', text: 'short' },
      { material_id: 'mat_b', chunk_id: 'c2', text: 'a fairly long evidence body that should get truncated' },
    ];
    render(
      <MemoryRouter>
        <SparkEvidencePills refs={refs} projectId="proj-1" />
      </MemoryRouter>,
    );
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(2);
    expect(buttons[0].textContent).toContain('short');
    // Second pill is truncated to <= 30 chars + ellipsis.
    expect(buttons[1].textContent?.endsWith('…')).toBe(true);
  });

  it('falls back to friendly Chinese label when text is empty (R5: no raw chunk_id leak)', () => {
    render(
      <MemoryRouter>
        <SparkEvidencePills
          refs={[{ material_id: 'mat_a', chunk_id: 'mat_a_chunk_3' }]}
          projectId="proj-1"
        />
      </MemoryRouter>,
    );
    const label = screen.getByRole('button').textContent ?? '';
    // The canonical EvidencePill (Slice 2) deliberately suppresses
    // raw chunk_id / material_id as user-visible text per R5/R5.1.
    expect(label).not.toContain('mat_a_chunk_3');
    expect(label).toContain('证据');
  });

  it('navigates with the given page when ref already has page', async () => {
    render(
      <MemoryRouter>
        <SparkEvidencePills
          refs={[{ material_id: 'mat_a', chunk_id: 'c1', page: 7, text: 't' }]}
          projectId="proj-1"
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
      expect(parsed.searchParams.get('material_id')).toBe('mat_a');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('proj-1');
      expect(parsed.searchParams.get('page')).toBe('7');
      expect(parsed.searchParams.get('chunk')).toBe('c1');
    });
    expect(locateChunkMock).not.toHaveBeenCalled();
  });

  it('calls locateChunk when ref lacks page and uses resolved page', async () => {
    locateChunkMock.mockResolvedValueOnce({
      material_id: 'mat_b',
      chunk_id: 'c2',
      page: 11,
      chunk_index: 2,
    });
    render(
      <MemoryRouter>
        <SparkEvidencePills
          refs={[{ material_id: 'mat_b', chunk_id: 'c2', text: 't' }]}
          projectId="proj-1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      expect(url).toContain('page=11');
    });
    expect(locateChunkMock).toHaveBeenCalledWith('c2', 'proj-1');
  });

  it('falls back to no page param when locator returns null', async () => {
    locateChunkMock.mockResolvedValueOnce(null);
    render(
      <MemoryRouter>
        <SparkEvidencePills
          refs={[{ material_id: 'mat_b', chunk_id: 'c2', text: 't' }]}
          projectId="proj-1"
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
      expect(parsed.searchParams.get('material_id')).toBe('mat_b');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('proj-1');
      expect(parsed.searchParams.get('chunk')).toBe('c2');
      expect(parsed.searchParams.has('page')).toBe(false);
    });
  });

  it('skips locator when no projectId is provided', async () => {
    render(
      <MemoryRouter>
        <SparkEvidencePills
          refs={[{ material_id: 'mat_b', chunk_id: 'c2', text: 't' }]}
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
      expect(parsed.searchParams.get('material_id')).toBe('mat_b');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.has('page')).toBe(false);
    });
    expect(locateChunkMock).not.toHaveBeenCalled();
  });

  it('caches locator result per chunk_id (per-spark cache)', async () => {
    locateChunkMock.mockResolvedValueOnce({
      material_id: 'mat_b',
      chunk_id: 'c2',
      page: 11,
      chunk_index: 2,
    });
    render(
      <MemoryRouter>
        <SparkEvidencePills
          refs={[
            { material_id: 'mat_b', chunk_id: 'c2', text: 'first ref' },
            { material_id: 'mat_b', chunk_id: 'c2', text: 'duplicate ref' },
          ]}
          projectId="proj-1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    const buttons = screen.getAllByRole('button');
    fireEvent.click(buttons[0]);
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('page=11');
    });
    fireEvent.click(buttons[1]);
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('page=11');
    });
    expect(locateChunkMock).toHaveBeenCalledTimes(1);
  });

  it('skips ref with empty material_id without navigating', async () => {
    render(
      <MemoryRouter>
        <SparkEvidencePills
          refs={[{ material_id: '', chunk_id: 'c1', text: 't' }]}
          projectId="proj-1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button'));
    // No navigation occurred; LocationProbe stays at the initial route ("/")
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      expect(url).not.toContain('/knowledge');
    });
  });

  it('renders distinct React keys for refs sharing (material_id, chunk_id)', () => {
    // Audit finding (3): server-side dedup runs but the UI must
    // tolerate duplicate payload without a React key warning.
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      render(
        <MemoryRouter>
          <SparkEvidencePills
            refs={[
              { material_id: 'mat_a', chunk_id: 'c1', text: 'first sighting' },
              { material_id: 'mat_a', chunk_id: 'c1', text: 'duplicate' },
              { material_id: 'mat_a', chunk_id: 'c1', text: 'third copy' },
            ]}
            projectId="proj-1"
          />
        </MemoryRouter>,
      );
      // Three buttons rendered (the component does not dedupe; it
      // renders what it's given).
      expect(screen.getAllByRole('button')).toHaveLength(3);
      // No "Encountered two children with the same key" warning.
      const keyWarning = errorSpy.mock.calls.find(call => {
        const message = call[0];
        return typeof message === 'string' && message.includes('two children with the same key');
      });
      expect(keyWarning).toBeUndefined();
    } finally {
      errorSpy.mockRestore();
    }
  });

  it('renders distinct keys when chunk_id is null/missing on multiple refs', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    try {
      render(
        <MemoryRouter>
          <SparkEvidencePills
            refs={[
              { material_id: 'mat_a', text: 'no chunk id 1' },
              { material_id: 'mat_a', text: 'no chunk id 2' },
              { material_id: 'mat_a', chunk_id: null, text: 'explicit null' },
            ]}
            projectId="proj-1"
          />
        </MemoryRouter>,
      );
      expect(screen.getAllByRole('button')).toHaveLength(3);
      const keyWarning = errorSpy.mock.calls.find(call => {
        const message = call[0];
        return typeof message === 'string' && message.includes('two children with the same key');
      });
      expect(keyWarning).toBeUndefined();
    } finally {
      errorSpy.mockRestore();
    }
  });
});
