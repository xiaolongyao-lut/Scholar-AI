import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MessageBubble } from './MessageBubble';
import type { EvidenceReference } from '@/services/intelligentChatApi';
import { __resetEvidencePillCacheForTests } from '@/components/evidence/EvidencePill';

const locateChunkMock = vi.fn();

vi.mock('@/services/resourcesApi', () => ({
  locateChunk: (chunkId: string, projectId: string | null | undefined) =>
    locateChunkMock(chunkId, projectId),
}));

// Probe component that surfaces the current router URL into the DOM so
// tests can assert on the deep-link target after a click.
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function parseLocationUrl(value: string): URL {
  return new URL(value, 'http://localhost');
}

function refWithPage(): EvidenceReference {
  return {
    chunk_id: 'mat_a_chunk_3',
    source: 'Paper A',
    text: 'evidence body',
    quote: 'evidence body',
    score: 0.95,
    material_id: 'mat_a',
    page: 7,
  } as EvidenceReference;
}

function refWithoutPage(): EvidenceReference {
  return {
    chunk_id: 'mat_b_chunk_5',
    source: 'Paper B',
    text: 'evidence body',
    quote: 'evidence body',
    score: 0.9,
    material_id: 'mat_b',
    page: undefined,
  } as EvidenceReference;
}

beforeEach(() => {
  locateChunkMock.mockReset();
  __resetEvidencePillCacheForTests();
});

function getEvidenceButton(name: RegExp | string): HTMLElement {
  return screen.getByRole('button', { name });
}

describe('MessageBubble openMaterial locator wiring', () => {
  it('uses the page already on the EvidenceReference and skips the locator', async () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="answer"
          evidenceRefs={[refWithPage()]}
          projectId="proj-1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(getEvidenceButton(/Paper A/));
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('scope')).toBe('paper');
      expect(parsed.searchParams.get('material_id')).toBe('mat_a');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('proj-1');
      expect(parsed.searchParams.get('page')).toBe('7');
      expect(parsed.searchParams.get('chunk')).toBe('mat_a_chunk_3');
    });
    expect(locateChunkMock).not.toHaveBeenCalled();
  });

  it('calls locateChunk and uses the resolved page when EvidenceReference has chunk_id but no page', async () => {
    locateChunkMock.mockResolvedValueOnce({
      material_id: 'mat_b',
      chunk_id: 'mat_b_chunk_5',
      page: 12,
      chunk_index: 5,
    });
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="answer"
          evidenceRefs={[refWithoutPage()]}
          projectId="proj-1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(getEvidenceButton(/Paper B/));
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('scope')).toBe('paper');
      expect(parsed.searchParams.get('material_id')).toBe('mat_b');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('proj-1');
      expect(parsed.searchParams.get('page')).toBe('12');
      expect(parsed.searchParams.get('chunk')).toBe('mat_b_chunk_5');
    });
    expect(locateChunkMock).toHaveBeenCalledWith('mat_b_chunk_5', 'proj-1');
    expect(locateChunkMock).toHaveBeenCalledTimes(1);
  });

  it('falls back without a page param when locator returns null', async () => {
    locateChunkMock.mockResolvedValueOnce(null);
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="answer"
          evidenceRefs={[refWithoutPage()]}
          projectId="proj-1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(getEvidenceButton(/Paper B/));
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('scope')).toBe('paper');
      expect(parsed.searchParams.get('material_id')).toBe('mat_b');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('proj-1');
      expect(parsed.searchParams.get('chunk')).toBe('mat_b_chunk_5');
      expect(parsed.searchParams.has('page')).toBe(false);
    });
    expect(locateChunkMock).toHaveBeenCalledTimes(1);
  });

  it('falls back to page=1 when locator returns page=null', async () => {
    locateChunkMock.mockResolvedValueOnce({
      material_id: 'mat_b',
      chunk_id: 'mat_b_chunk_5',
      page: null,
      chunk_index: 5,
    });
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="answer"
          evidenceRefs={[refWithoutPage()]}
          projectId="proj-1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(getEvidenceButton(/Paper B/));
    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      expect(url).not.toContain('page=');
    });
  });

  it('skips the locator when no projectId is provided', async () => {
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="answer"
          evidenceRefs={[refWithoutPage()]}
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(getEvidenceButton(/Paper B/));
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

  it('caches the locator result per chunk_id (second click reuses it)', async () => {
    locateChunkMock.mockResolvedValueOnce({
      material_id: 'mat_b',
      chunk_id: 'mat_b_chunk_5',
      page: 12,
      chunk_index: 5,
    });
    render(
      <MemoryRouter>
        <MessageBubble
          role="assistant"
          content="answer"
          evidenceRefs={[refWithoutPage()]}
          projectId="proj-1"
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    const button = getEvidenceButton(/Paper B/);
    fireEvent.click(button);
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toContain('page=12');
    });

    fireEvent.click(button);
    await waitFor(() => {
      // URL still has page=12 after the second click.
      expect(screen.getByTestId('location').textContent).toContain('page=12');
    });
    // Cache hit: locator called only once even though button was clicked twice.
    expect(locateChunkMock).toHaveBeenCalledTimes(1);
  });
});
