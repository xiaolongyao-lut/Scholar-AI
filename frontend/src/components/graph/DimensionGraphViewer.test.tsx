import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DimensionGraphViewer } from './DimensionGraphViewer';
import type { GraphPayloadV0 } from './payloadToRf';

// React Flow 在 jsdom 下会因为缺 ResizeObserver/Viewport 直接抛错，做最小桩。
// 测试只验证「投影 + 图例 + 状态切换」，渲染细节交给 vitest dom snapshot 之外的 e2e。
vi.mock('@xyflow/react', async () => {
  const actual = await vi.importActual<typeof import('@xyflow/react')>('@xyflow/react');
  return {
    ...actual,
    ReactFlow: ({
      nodes,
      edges,
      onNodeClick,
      onNodeMouseEnter,
      onNodeMouseLeave,
      onEdgeMouseEnter,
      onEdgeMouseLeave,
      children,
    }: {
      nodes?: Array<{ id: string; data?: Record<string, unknown> }>;
      edges?: Array<{ id: string; data?: Record<string, unknown>; hidden?: boolean; style?: React.CSSProperties }>;
      onNodeClick?: (event: React.MouseEvent<HTMLButtonElement>, node: unknown) => void;
      onNodeMouseEnter?: (event: React.MouseEvent<HTMLButtonElement>, node: { id: string; data?: Record<string, unknown> }) => void;
      onNodeMouseLeave?: (event: React.MouseEvent<HTMLButtonElement>, node: { id: string; data?: Record<string, unknown> }) => void;
      onEdgeMouseEnter?: (event: React.MouseEvent<HTMLOutputElement>, edge: { id: string; data?: Record<string, unknown> }) => void;
      onEdgeMouseLeave?: (event: React.MouseEvent<HTMLOutputElement>, edge: { id: string; data?: Record<string, unknown> }) => void;
      children?: React.ReactNode;
    }) => (
      <div data-testid="react-flow-stub">
        {(nodes ?? []).map((node) => (
          <button
            key={node.id}
            type="button"
            onMouseEnter={(event) => onNodeMouseEnter?.(event, node)}
            onMouseLeave={(event) => onNodeMouseLeave?.(event, node)}
            onClick={(event) => {
              onNodeClick?.(event, node);
              const callback = node.data?.onNodeClick;
              if (typeof callback === 'function') {
                callback(node.data?.dimensionEntry);
              }
            }}
          >
            {node.id}
          </button>
        ))}
        {(edges ?? []).map((edge) => (
          <output
            key={edge.id}
            data-testid={`edge-${edge.id}`}
            data-evidence-visible={String(edge.data?.evidenceWeightVisible ?? false)}
            data-route-kind={String(edge.data?.routeKind ?? '')}
            data-route-visibility={String(edge.data?.routeVisibility ?? '')}
            data-hidden={String(edge.hidden ?? false)}
            data-opacity={String(edge.style?.opacity ?? '')}
            data-stroke-width={String(edge.style?.strokeWidth ?? '')}
            onMouseEnter={(event) => onEdgeMouseEnter?.(event, edge)}
            onMouseLeave={(event) => onEdgeMouseLeave?.(event, edge)}
          />
        ))}
        {children}
      </div>
    ),
    Controls: () => null,
    Background: () => null,
    MiniMap: () => null,
    Panel: ({ children }: { children: React.ReactNode }) => <div data-testid="panel-stub">{children}</div>,
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    useReactFlow: () => ({
      fitView: vi.fn().mockResolvedValue(undefined),
      zoomIn: vi.fn().mockResolvedValue(undefined),
      zoomOut: vi.fn().mockResolvedValue(undefined),
      getNodes: vi.fn(() => []),
      getEdges: vi.fn(() => []),
      setNodes: vi.fn(),
      setEdges: vi.fn(),
    }),
  };
});

describe('DimensionGraphViewer', () => {
  it('renders empty placeholder when payload has no nodes', () => {
    render(<DimensionGraphViewer payload={{ version: 'v0', nodes: [], edges: [] } as unknown as GraphPayloadV0} />);
    expect(screen.getByText(/暂无可投影的节点/)).toBeInTheDocument();
  });

  it('renders error state when error is provided', () => {
    render(<DimensionGraphViewer payload={null} error="读取失败" />);
    expect(screen.getByText('读取失败')).toBeInTheDocument();
  });

  it('shows loading placeholder when loading=true', () => {
    render(<DimensionGraphViewer payload={null} loading />);
    expect(screen.getByText(/正在加载维度图谱/)).toBeInTheDocument();
  });

  it('shows dimension legend counts when payload has nodes', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'src', type: 'source', label: '论文 A', confidence: null, material_id: 'm1', metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;
    render(<DimensionGraphViewer payload={payload} />);
    // 图例同时显示「问题」「证据」标签，每个旁边带计数。
    expect(screen.getAllByText('问题').length).toBeGreaterThan(0);
    expect(screen.getAllByText('证据').length).toBeGreaterThan(0);
  });

  it('renders the semantic review panel with actionable buckets', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'a', type: 'evidence', label: '重复证据', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'b', type: 'evidence', label: '重复证据', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} />);

    const panel = screen.getByLabelText('语义复审面板');
    expect(within(panel).getByText('需要复审')).toBeInTheDocument();
    expect(within(panel).getByText('孤立节点')).toBeInTheDocument();
    expect(within(panel).getByText('重复标签')).toBeInTheDocument();
    expect(within(panel).getByText('缺少来源锚点')).toBeInTheDocument();
  });

  it('renders graph diagnostics for dangling, weak, and source-overlap relations', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'a',
          type: 'claim',
          label: '同源结论 A',
          confidence: 0.8,
          material_id: 'm1',
          metadata: { reasoning_dimension: 'observation' },
          source_ref: null,
          evidence_refs: [],
        },
        {
          id: 'b',
          type: 'claim',
          label: '同源结论 B',
          confidence: 0.7,
          material_id: 'm1',
          metadata: { reasoning_dimension: 'mechanism' },
          source_ref: null,
          evidence_refs: [],
        },
      ],
      edges: [
        {
          id: 'weak-overlap',
          source: 'a',
          target: 'b',
          relation: 'supports',
          confidence: 0.2,
          metadata: {},
          source_ref: null,
          evidence_refs: [],
        },
        {
          id: 'dangling',
          source: 'a',
          target: 'missing-node',
          relation: 'supports',
          confidence: 0.9,
          metadata: {},
          source_ref: null,
          evidence_refs: [],
        },
      ],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} />);

    const panel = screen.getByLabelText('语义复审面板');
    const diagnostics = within(panel).getByLabelText('图谱结构诊断');
    expect(within(diagnostics).getByText('悬空关系')).toBeInTheDocument();
    expect(within(diagnostics).getByText('关系缺少证据')).toBeInTheDocument();
    expect(within(diagnostics).getByText('低置信关系')).toBeInTheDocument();
    expect(within(diagnostics).getByText('同源关系')).toBeInTheDocument();
  });

  it('does not render the semantic review panel when legend is hidden', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} showLegend={false} />);

    expect(screen.queryByLabelText('语义复审面板')).not.toBeInTheDocument();
  });

  it('calls onSelectNode once when a dimension node is clicked', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;
    const onSelectNode = vi.fn();
    render(<DimensionGraphViewer payload={payload} onSelectNode={onSelectNode} />);
    screen.getByRole('button', { name: 'q' }).click();
    expect(onSelectNode).toHaveBeenCalledTimes(1);
  });

  it('shows the rail expand action when onExpand is provided', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;
    const onExpand = vi.fn();
    render(<DimensionGraphViewer payload={payload} density="rail" onExpand={onExpand} />);

    fireEvent.click(screen.getByRole('button', { name: '展开图谱' }));

    expect(onExpand).toHaveBeenCalledTimes(1);
  });

  it('uses Chinese copy for the selected-node focus action', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;
    render(<DimensionGraphViewer payload={payload} />);

    fireEvent.click(screen.getByRole('button', { name: 'q' }));

    expect(screen.getByRole('button', { name: '定位节点' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Fit' })).not.toBeInTheDocument();
  });

  it('toggles evidence weight styling on graph edges', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'obs', type: 'claim', label: '观察结论', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [
        {
          id: 'q-to-obs',
          source: 'q',
          target: 'obs',
          relation: 'supports',
          confidence: 0.8,
          metadata: { tolf_evidence_score: 0.9 },
          source_ref: null,
          evidence_refs: [],
        },
      ],
    } as unknown as GraphPayloadV0;
    render(<DimensionGraphViewer payload={payload} />);

    const toggle = screen.getByRole('button', { name: '证据权重' });
    fireEvent.mouseEnter(screen.getByRole('button', { name: 'q' }));
    const beforeWidth = Number(screen.getByTestId('edge-q-to-obs').dataset.strokeWidth);

    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('edge-q-to-obs')).toHaveAttribute('data-evidence-visible', 'false');

    fireEvent.click(toggle);

    const afterEdge = screen.getByTestId('edge-q-to-obs');
    const afterWidth = Number(afterEdge.dataset.strokeWidth);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(afterEdge).toHaveAttribute('data-evidence-visible', 'true');
    expect(afterWidth).toBeGreaterThan(beforeWidth);
  });

  it('keeps routes ghosted until hovering a connected node', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'obs', type: 'claim', label: '观察结论', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'ev', type: 'evidence', label: '证据片段', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [
        { id: 'q-to-obs', source: 'q', target: 'obs', relation: 'derives_from', confidence: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'ev-to-obs', source: 'ev', target: 'obs', relation: 'supports', confidence: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
    } as unknown as GraphPayloadV0;
    render(<DimensionGraphViewer payload={payload} />);

    const reasoningEdge = screen.getByTestId('edge-q-to-obs');
    const evidenceEdge = screen.getByTestId('edge-ev-to-obs');

    expect(reasoningEdge).toHaveAttribute('data-route-visibility', 'ghost');
    expect(Number(reasoningEdge.dataset.opacity)).toBeLessThan(0.05);

    fireEvent.mouseEnter(screen.getByRole('button', { name: 'q' }));

    expect(screen.getByTestId('edge-q-to-obs')).toHaveAttribute('data-route-visibility', 'visible');
    expect(screen.getByTestId('edge-ev-to-obs')).toHaveAttribute('data-route-visibility', 'ghost');
    expect(Number(screen.getByTestId('edge-q-to-obs').dataset.opacity)).toBeGreaterThan(Number(evidenceEdge.dataset.opacity));

    fireEvent.mouseLeave(screen.getByRole('button', { name: 'q' }));

    expect(screen.getByTestId('edge-q-to-obs')).toHaveAttribute('data-route-visibility', 'ghost');
  });

  it('filters route categories without moving node dimension filters', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'obs', type: 'claim', label: '观察结论', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'ev', type: 'evidence', label: '证据片段', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'counter', type: 'evidence', label: '反例片段', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [
        { id: 'q-to-obs', source: 'q', target: 'obs', relation: 'extends', confidence: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'ev-to-obs', source: 'ev', target: 'obs', relation: 'supports', confidence: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'counter-to-obs', source: 'counter', target: 'obs', relation: 'contradicts', confidence: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
    } as unknown as GraphPayloadV0;
    render(<DimensionGraphViewer payload={payload} />);

    fireEvent.click(screen.getByTitle('支持和被支持关系'));

    expect(screen.getByTestId('edge-q-to-obs')).toHaveAttribute('data-hidden', 'false');
    expect(screen.getByTestId('edge-ev-to-obs')).toHaveAttribute('data-hidden', 'true');
    expect(screen.getByTestId('edge-counter-to-obs')).toHaveAttribute('data-hidden', 'false');
  });

  it('reveals a hovered edge even when no node is hovered', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'obs', type: 'claim', label: '观察结论', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [
        { id: 'q-to-obs', source: 'q', target: 'obs', relation: 'extends', confidence: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
    } as unknown as GraphPayloadV0;
    render(<DimensionGraphViewer payload={payload} />);

    expect(screen.getByTestId('edge-q-to-obs')).toHaveAttribute('data-route-visibility', 'ghost');

    fireEvent.mouseEnter(screen.getByTestId('edge-q-to-obs'));

    expect(screen.getByTestId('edge-q-to-obs')).toHaveAttribute('data-route-visibility', 'visible');
  });
});
