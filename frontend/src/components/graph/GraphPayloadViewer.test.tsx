import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';

import { GraphPayloadViewer, __resetGraphPayloadViewerCacheForTests } from './GraphPayloadViewer';
import type { GraphViewportProps } from './GraphViewport';
import type {
  GraphNode,
  GraphPayloadV0,
  GraphViewportPayloadEdge,
} from './payloadToRf';

const locateChunkMock = vi.fn();

vi.mock('@/services/resourcesApi', () => ({
  locateChunk: (chunkId: string, projectId: string | null | undefined) =>
    locateChunkMock(chunkId, projectId),
}));

vi.mock('./GraphViewport', async () => {
  const React = await import('react');

  function MockGraphViewport({
    nodes,
    edges,
    selection,
    layoutDirection,
    presentation,
    loading,
    error,
    emptyMessage,
    onNodeSelect,
    onSelectionClear,
  }: GraphViewportProps<GraphNode, GraphViewportPayloadEdge>) {
    const commonProps = {
      'data-testid': 'shared-graph-viewport',
      'data-edge-directions': edges.map((edge) => `${edge.id}:${edge.direction}`).join(','),
      'data-edge-label-count': edges.filter((edge) => Object.hasOwn(edge, 'label')).length,
      'data-layout-direction': layoutDirection,
      'data-presentation': presentation,
      'data-selection': selection ? `${selection.kind}:${selection.id}` : 'none',
    };

    if (error) {
      return <div {...commonProps} role="alert">{error}</div>;
    }
    if (loading) {
      return <div {...commonProps} role="status">正在加载图谱…</div>;
    }
    if (nodes.length === 0) {
      return <div {...commonProps} role="status">{emptyMessage}</div>;
    }

    return (
      <div {...commonProps}>
        {nodes.map((node) => (
          <button key={node.id} type="button" onClick={() => onNodeSelect?.(node)}>
            {node.label}
          </button>
        ))}
        <button type="button" onClick={() => onSelectionClear?.()}>
          清除公共画布选择
        </button>
      </div>
    );
  }

  return { GraphViewport: MockGraphViewport, default: MockGraphViewport };
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
      {
        id: 'method_1',
        label: 'Method node',
        type: 'method',
        metadata: { evidence_text: 'Method detail evidence.' },
      },
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

  it('routes payloads through the shared viewport with explicit directions and no edge labels', () => {
    const payload = materialBackedPayload();
    payload.edges = [
      ...payload.edges,
      { id: 'edge_2', source: 'method_1', target: 'claim_1', relation: 'related' },
      {
        id: 'edge_3',
        source: 'method_1',
        target: 'claim_1',
        relation: 'uses',
        metadata: { direction: 'undirected' },
      },
    ];

    render(
      <MemoryRouter>
        <GraphPayloadViewer payload={payload} />
      </MemoryRouter>,
    );

    const viewport = screen.getByTestId('shared-graph-viewport');
    expect(viewport).toHaveAttribute(
      'data-edge-directions',
      'edge_1:directed,edge_2:undirected,edge_3:undirected',
    );
    expect(viewport).toHaveAttribute('data-edge-label-count', '0');
    expect(viewport).toHaveAttribute('data-layout-direction', 'horizontal');
    expect(viewport).toHaveAttribute('data-presentation', 'cards');
    expect(screen.queryByText('supports')).not.toBeInTheDocument();
  });

  it('canonicalizes and deduplicates reversed legacy undirected edges', () => {
    const payload = materialBackedPayload();
    payload.edges = [
      { id: 'related-b-a', source: 'method_1', target: 'claim_1', relation: 'related' },
      { id: 'related-a-b', source: 'claim_1', target: 'method_1', relation: 'related' },
    ];

    render(
      <MemoryRouter>
        <GraphPayloadViewer payload={payload} />
      </MemoryRouter>,
    );

    expect(screen.getByTestId('shared-graph-viewport')).toHaveAttribute(
      'data-edge-directions',
      'related-b-a:undirected',
    );
  });

  it('deep-links material node clicks to SmartRead reader mode', () => {
    render(
      <MemoryRouter initialEntries={['/wiki']}>
        <GraphPayloadViewer payload={materialBackedPayload()} />
        <LocationProbe />
      </MemoryRouter>,
    );

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
      const parsed = parseLocationUrl(screen.getByTestId('location').textContent ?? '');
      expect(parsed.pathname).toBe('/dialog');
      expect(parsed.searchParams.get('project_id')).toBe('project-a');
      expect(parsed.searchParams.get('page')).toBe('4');
      expect(parsed.searchParams.get('chunk')).toBe('chunk_007');
      expect(parsed.searchParams.get('bbox')).toBe('0.12,0.25,0.3,0.08');
    });
    expect(locateChunkMock).not.toHaveBeenCalled();
  });

  it('upgrades chunk-only material clicks through the project chunk locator', async () => {
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

  it('sends resolved material targets to an embedded reader callback', async () => {
    const onNavigateTarget = vi.fn();
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
        <GraphPayloadViewer
          payload={payload}
          projectId="project-a"
          onNavigateTarget={onNavigateTarget}
        />
        <LocationProbe />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Evidence-backed claim' }));

    await waitFor(() => {
      expect(onNavigateTarget).toHaveBeenCalledWith({
        material_id: 'mat_c7',
        page: 4,
        chunk_id: 'chunk_007',
        bbox: [0.12, 0.25, 0.3, 0.08],
        bbox_unit: 'normalized_ratio',
      });
    });
    expect(screen.getByTestId('location')).toHaveTextContent('/wiki');
  });

  it('keeps non-material details outside the viewport and clears controlled selection', () => {
    render(
      <MemoryRouter>
        <GraphPayloadViewer payload={materialBackedPayload()} />
      </MemoryRouter>,
    );

    const viewport = screen.getByTestId('shared-graph-viewport');
    expect(viewport).toHaveAttribute('data-selection', 'none');

    fireEvent.click(screen.getByRole('button', { name: 'Method node' }));

    expect(viewport).toHaveAttribute('data-selection', 'node:method_1');
    expect(screen.getByText('Method detail evidence.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '关闭' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '清除公共画布选择' }));

    expect(viewport).toHaveAttribute('data-selection', 'none');
    expect(screen.queryByText('Method detail evidence.')).not.toBeInTheDocument();
  });

  it('delegates loading, error, and empty states to the shared viewport', () => {
    const emptyPayload: GraphPayloadV0 = {
      version: 'v0',
      scope: { kind: 'question', ref: 'empty' },
      updated_at: '2026-05-15T00:00:00Z',
      nodes: [],
      edges: [],
    };
    const { rerender } = render(
      <MemoryRouter>
        <GraphPayloadViewer payload={null} loading />
      </MemoryRouter>,
    );

    expect(screen.getByTestId('shared-graph-viewport')).toHaveTextContent('正在加载图谱…');

    rerender(
      <MemoryRouter>
        <GraphPayloadViewer payload={null} error="网络不可用" />
      </MemoryRouter>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('网络不可用');

    rerender(
      <MemoryRouter>
        <GraphPayloadViewer payload={emptyPayload} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('status')).toHaveTextContent('当前没有图谱数据');
  });
});
