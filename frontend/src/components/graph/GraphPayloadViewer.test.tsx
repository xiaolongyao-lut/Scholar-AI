import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';

import { GraphPayloadViewer, __resetGraphPayloadViewerCacheForTests } from './GraphPayloadViewer';
import type { GraphPayloadV0 } from './payloadToRf';

const locateChunkMock = vi.fn();

vi.mock('@/services/resourcesApi', () => ({
  locateChunk: (chunkId: string, projectId: string | null | undefined) =>
    locateChunkMock(chunkId, projectId),
}));

vi.mock('@xyflow/react', async () => {
  const React = await import('react');
  return {
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Background: () => <div data-testid="graph-background" />,
    Controls: () => <div data-testid="graph-controls" />,
    MarkerType: { ArrowClosed: 'arrowclosed' },
    ReactFlow: ({
      nodes,
      onNodeClick,
      onNodeMouseEnter,
      onNodeMouseLeave,
      children,
    }: {
      nodes: Array<{ id: string; data?: { label?: string; raw?: unknown } }>;
      onNodeClick?: (event: React.MouseEvent<HTMLButtonElement>, node: unknown) => void;
      onNodeMouseEnter?: (event: React.MouseEvent<HTMLButtonElement>, node: unknown) => void;
      onNodeMouseLeave?: (event: React.MouseEvent<HTMLButtonElement>, node: unknown) => void;
      children?: React.ReactNode;
    }) => (
      <div data-testid="graph-flow">
        {nodes.map((node) => (
          <button
            key={node.id}
            type="button"
            onClick={(event) => onNodeClick?.(event, node)}
            onMouseEnter={(event) => onNodeMouseEnter?.(event, node)}
            onMouseLeave={(event) => onNodeMouseLeave?.(event, node)}
          >
            {node.data?.label ?? node.id}
          </button>
        ))}
        {children}
      </div>
    ),
  };
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function parseLocationUrl(value: string): URL {
  return new URL(value, 'http://localhost');
}

function materialBackedPayload(): GraphPayloadV0 {
  return {
    version: 'v0',
    scope: { kind: 'question', ref: 'kg-smoke' },
    updated_at: '2026-05-15T00:00:00Z',
    nodes: [
      {
        id: 'claim_1',
        label: 'Evidence-backed claim',
        type: 'claim',
        material_id: 'mat_c7',
        source_ref: { material_id: 'mat_c7', page: 4, chunk_id: 'chunk_007' },
        evidence_refs: [
          {
            material_id: 'mat_c7',
            page: 4,
            chunk_id: 'chunk_007',
            text: 'Fixture evidence text.',
            score: 0.91,
          },
        ],
      },
      { id: 'method_1', label: 'Method node', type: 'method' },
    ],
    edges: [
      { id: 'edge_1', source: 'claim_1', target: 'method_1', relation: 'supports' },
    ],
  };
}

describe('GraphPayloadViewer', () => {
  beforeEach(() => {
    locateChunkMock.mockReset();
    __resetGraphPayloadViewerCacheForTests();
  });

  it('renders a material-backed fixture and deep-links node clicks to SmartRead reader mode', () => {
    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <GraphPayloadViewer payload={materialBackedPayload()} />
        <LocationProbe />
      </MemoryRouter>,
    );

    expect(screen.getByTestId('graph-flow')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Evidence-backed claim' }));

    const parsed = parseLocationUrl(screen.getByTestId('location').textContent ?? '');
    expect(parsed.pathname).toBe('/dialog');
    expect(parsed.searchParams.get('scope')).toBe('paper');
    expect(parsed.searchParams.get('material_id')).toBe('mat_c7');
    expect(parsed.searchParams.get('tab')).toBe('reader');
    expect(parsed.searchParams.get('page')).toBe('4');
    expect(parsed.searchParams.get('chunk')).toBe('chunk_007');
  });

  it('uses source_ref bbox in graph node deep-links when available', async () => {
    const payload = materialBackedPayload();
    payload.nodes[0] = {
      ...payload.nodes[0],
      source_ref: {
        material_id: 'mat_c7',
        page: 4,
        chunk_id: 'chunk_007',
        bbox: [0.12, 0.25, 0.3, 0.08],
        bbox_unit: 'normalized_ratio',
      },
    };

    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <GraphPayloadViewer payload={payload} projectId="project-a" />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Evidence-backed claim' }));

    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      const parsed = parseLocationUrl(url);
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('scope')).toBe('paper');
      expect(parsed.searchParams.get('material_id')).toBe('mat_c7');
      expect(parsed.searchParams.get('tab')).toBe('reader');
      expect(parsed.searchParams.get('project_id')).toBe('project-a');
      expect(parsed.searchParams.get('page')).toBe('4');
      expect(parsed.searchParams.get('chunk')).toBe('chunk_007');
      expect(parsed.searchParams.get('bbox')).toBe('0.12,0.25,0.3,0.08');
    });
    expect(locateChunkMock).not.toHaveBeenCalled();
  });

  it('upgrades chunk-only graph node clicks through the project chunk locator', async () => {
    locateChunkMock.mockResolvedValueOnce({
      material_id: 'mat_c7',
      chunk_id: 'chunk_007',
      page: 6,
      chunk_index: 7,
      bbox: [0.2, 0.3, 0.25, 0.1],
    });
    const payload = materialBackedPayload();
    payload.nodes[0] = {
      ...payload.nodes[0],
      source_ref: {
        material_id: 'mat_c7',
        page: null,
        chunk_id: 'chunk_007',
        bbox: null,
      },
      evidence_refs: [
        {
          material_id: 'mat_c7',
          page: null,
          chunk_id: 'chunk_007',
          text: 'Fixture evidence text.',
          score: 0.91,
        },
      ],
    };

    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <GraphPayloadViewer payload={payload} projectId="project-a" />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Evidence-backed claim' }));

    await waitFor(() => {
      const url = screen.getByTestId('location').textContent ?? '';
      expect(url).toContain('page=6');
      expect(url).toContain('chunk=chunk_007');
      expect(url).toContain('bbox=0.2%2C0.3%2C0.25%2C0.1');
    });
    expect(locateChunkMock).toHaveBeenCalledWith('chunk_007', 'project-a');
  });

  it('shows evidence preview while hovering a graph node', () => {
    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <GraphPayloadViewer payload={materialBackedPayload()} />
      </MemoryRouter>,
    );

    fireEvent.mouseEnter(screen.getByRole('button', { name: 'Evidence-backed claim' }));

    expect(screen.getByText('Fixture evidence text.')).toBeInTheDocument();
    expect(screen.getByText(/p\.4/)).toBeInTheDocument();

    fireEvent.mouseLeave(screen.getByRole('button', { name: 'Evidence-backed claim' }));

    expect(screen.queryByText('Fixture evidence text.')).not.toBeInTheDocument();
  });

  it('shows long prose evidence previews without exposing internal fields', () => {
    const payload = materialBackedPayload();
    payload.nodes[0] = {
      ...payload.nodes[0],
      metadata: {
        evidence_text: 'Full length article Spatio-temporal beam shaping for optimized weld formation and microstructural control in laser tailor welding of Zn-Al-Mg coated steel. The paper studies how beam shaping changes weld formation and microstructure.',
      },
    };

    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <GraphPayloadViewer payload={payload} />
      </MemoryRouter>,
    );

    fireEvent.mouseEnter(screen.getByRole('button', { name: 'Evidence-backed claim' }));

    expect(screen.getByText(/Spatio-temporal beam shaping/)).toBeInTheDocument();
    expect(screen.queryByText('证据内容已隐藏，避免显示内部路径或系统字段。')).not.toBeInTheDocument();
  });

  it('shows the empty state for an empty payload', () => {
    render(
      <MemoryRouter>
        <GraphPayloadViewer
          payload={{
            version: 'v0',
            scope: { kind: 'question', ref: 'empty' },
            updated_at: '2026-05-15T00:00:00Z',
            nodes: [],
            edges: [],
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('当前没有图谱数据')).toBeInTheDocument();
  });
});
