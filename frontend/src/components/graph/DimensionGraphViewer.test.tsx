import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { applyWikiGraphReview, undoWikiGraphReview } from '@/services/wikiApi';
import { DimensionGraphViewer } from './DimensionGraphViewer';
import type { GraphPayloadV0 } from './payloadToRf';

vi.mock('@/services/wikiApi', () => ({
  applyWikiGraphReview: vi.fn(),
  undoWikiGraphReview: vi.fn(),
}));

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
      elementsSelectable,
      nodesFocusable,
      edgesFocusable,
      selectNodesOnDrag,
      onlyRenderVisibleElements,
      children,
    }: {
      nodes?: Array<{ id: string; data?: Record<string, unknown>; style?: React.CSSProperties }>;
      edges?: Array<{ id: string; data?: Record<string, unknown>; hidden?: boolean; style?: React.CSSProperties }>;
      onNodeClick?: (event: React.MouseEvent<HTMLButtonElement>, node: unknown) => void;
      onNodeMouseEnter?: (event: React.MouseEvent<HTMLButtonElement>, node: { id: string; data?: Record<string, unknown> }) => void;
      onNodeMouseLeave?: (event: React.MouseEvent<HTMLButtonElement>, node: { id: string; data?: Record<string, unknown> }) => void;
      onEdgeMouseEnter?: (event: React.MouseEvent<HTMLOutputElement>, edge: { id: string; data?: Record<string, unknown> }) => void;
      onEdgeMouseLeave?: (event: React.MouseEvent<HTMLOutputElement>, edge: { id: string; data?: Record<string, unknown> }) => void;
      elementsSelectable?: boolean;
      nodesFocusable?: boolean;
      edgesFocusable?: boolean;
      selectNodesOnDrag?: boolean;
      onlyRenderVisibleElements?: boolean;
      children?: React.ReactNode;
    }) => (
      <div
        data-testid="react-flow-stub"
        data-elements-selectable={String(elementsSelectable ?? true)}
        data-nodes-focusable={String(nodesFocusable ?? true)}
        data-edges-focusable={String(edgesFocusable ?? true)}
        data-select-nodes-on-drag={String(selectNodesOnDrag ?? true)}
        data-only-render-visible={String(onlyRenderVisibleElements ?? false)}
      >
        {(nodes ?? []).map((node) => {
          const dimensionEntry = node.data?.dimensionEntry as {
            display?: { title?: string; previewText?: string | null };
          } | undefined;
          return (
            <button
              key={node.id}
              type="button"
              aria-label={node.id}
              data-testid={`node-${node.id}`}
              data-focus-visibility={String(node.data?.focusVisibility ?? '')}
              data-opacity={String(node.style?.opacity ?? '')}
              data-performance-mode={String(node.data?.performanceMode ?? false)}
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
              <span>{node.id}</span>
              {dimensionEntry?.display?.title ? <span>{dimensionEntry.display.title}</span> : null}
              {dimensionEntry?.display?.previewText ? <span>{dimensionEntry.display.previewText}</span> : null}
            </button>
          );
        })}
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
    useViewport: () => ({ x: 0, y: 0, zoom: 1 }),
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

  it('uses the paper network presentation and visible-element rendering for large project graphs', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: Array.from({ length: 50 }, (_, index) => ({
        id: `paper-${index}`,
        type: 'material',
        label: `Paper ${index}`,
        confidence: 1,
        material_id: `m${index}`,
        metadata: { graph_presentation: 'paper_network', status: '可信' },
        source_ref: { material_id: `m${index}` },
        evidence_refs: [],
      })),
      edges: Array.from({ length: 49 }, (_, index) => ({
        id: `edge-${index}`,
        source: `paper-${index}`,
        target: `paper-${index + 1}`,
        relation: 'related',
        metadata: { graph_presentation: 'paper_network' },
        source_ref: null,
        evidence_refs: [],
      })),
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} showLegend={false} />);

    expect(screen.getByTestId('react-flow-stub')).toHaveAttribute('data-only-render-visible', 'true');
    expect(screen.getByTestId('node-paper-0')).toHaveAttribute('data-performance-mode', 'true');
    expect(screen.queryByText('材料与支持证据')).not.toBeInTheDocument();
  });

  it('shows evidence text on graph nodes when the visible label is only a chunk id', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'chunk-node',
          type: 'evidence',
          label: 'chunk-17',
          confidence: null,
          material_id: 'm1',
          metadata: { reasoning_dimension: 'evidence' },
          source_ref: { material_id: 'm1', page: 3, chunk_id: 'chunk-17', text: '可判断内容来自论文原文片段' },
          evidence_refs: [{ material_id: 'm1', page: 3, chunk_id: 'chunk-17', text: '可判断内容来自论文原文片段' }],
        },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} />);

    expect(screen.getByRole('button', { name: 'chunk-node' })).toHaveTextContent('chunk-17');
    expect(screen.getByRole('button', { name: 'chunk-node' })).toHaveTextContent('可判断内容来自论文原文片段');
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
    const queue = screen.getByLabelText('图谱处理队列');
    expect(within(panel).getByText('需要复审')).toBeInTheDocument();
    expect(within(panel).getByText('待处理')).toBeInTheDocument();
    expect(within(queue).getByText('孤立节点')).toBeInTheDocument();
    expect(within(queue).getByText('重复标签')).toBeInTheDocument();
    expect(within(queue).getByText('缺少来源锚点')).toBeInTheDocument();
    expect(within(queue).getAllByText('上游缺口').length).toBeGreaterThan(0);
    expect(within(queue).getByText(/回到生成它的 wiki 页面或导入记录/)).toBeInTheDocument();
  });

  it('focuses the graph on a selected review queue bucket', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'a', type: 'evidence', label: '重复证据', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'b', type: 'evidence', label: '重复证据', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'c', type: 'evidence', label: '唯一证据', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} />);
    const queue = screen.getByLabelText('图谱处理队列');

    fireEvent.click(within(queue).getByRole('button', { name: '定位重复标签' }));

    expect(screen.getByRole('button', { name: 'a' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'b' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'c' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('图谱筛选状态')).toHaveTextContent('复审: 重复标签');
    expect(within(queue).getByRole('button', { name: '定位重复标签' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(queue).queryByText('清除聚焦: 重复标签')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: '复审控制台' })).toHaveTextContent('重复标签 ·');
    expect(screen.getByRole('region', { name: '复审控制台' })).toHaveTextContent('合并 / 消歧');
    expect(screen.getAllByText('重复证据').length).toBeGreaterThan(0);
  });

  it('opens one inline operation console for duplicate labels with direct merge, disambiguation, and undo actions', async () => {
    vi.mocked(applyWikiGraphReview).mockResolvedValue({
      enabled: true,
      operation_id: 'op-1',
      operation_kind: 'disambiguate_nodes',
      updated_page_paths: ['evidence/dup-b.md'],
      snapshots: [{
        page_path: 'evidence/dup-b.md',
        content: 'before',
        content_hash: 'hash-before',
        expected_current_hash: 'hash-after',
      }],
      message: '已保存 1 个节点的消歧信息。',
      warnings: [],
    });
    vi.mocked(undoWikiGraphReview).mockResolvedValue({
      enabled: true,
      operation_id: 'op-1',
      operation_kind: 'undo_graph_review',
      updated_page_paths: ['evidence/dup-b.md'],
      snapshots: [],
      message: '已撤回 1 个页面的图谱复审修改。',
      warnings: [],
    });
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'dup-a',
          type: 'evidence',
          label: '重复证据',
          confidence: null,
          material_id: 'm1',
          metadata: { reasoning_dimension: 'evidence', page_path: 'evidence/dup-a.md' },
          source_ref: { material_id: 'm1', page: 1, chunk_id: 'c-a', text: 'A' },
          evidence_refs: [{ material_id: 'm1', page: 1, chunk_id: 'c-a', text: 'A' }],
        },
        {
          id: 'dup-b',
          type: 'evidence',
          label: '重复证据',
          confidence: null,
          material_id: 'm2',
          metadata: { reasoning_dimension: 'evidence', page_path: 'evidence/dup-b.md' },
          source_ref: { material_id: 'm2', page: 2, chunk_id: 'c-b', text: 'B' },
          evidence_refs: [{ material_id: 'm2', page: 2, chunk_id: 'c-b', text: 'B' }],
        },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} />);
    const queue = screen.getByLabelText('图谱处理队列');

    fireEvent.click(within(queue).getByRole('button', { name: '定位重复标签' }));

    const consolePanel = screen.getByRole('region', { name: '复审控制台' });
    expect(within(consolePanel).queryByLabelText('复审操作类型')).not.toBeInTheDocument();
    expect(within(consolePanel).getByText(/重复标签同屏处理/)).toBeInTheDocument();
    expect(within(consolePanel).getByText('同一概念：合并')).toBeInTheDocument();
    expect(within(consolePanel).getByText('不同概念：消歧')).toBeInTheDocument();
    expect(within(consolePanel).getByText('保留节点')).toBeInTheDocument();
    expect(within(consolePanel).getByText('并入节点')).toBeInTheDocument();
    expect(within(consolePanel).getByText(/可直接写回 2 个 Wiki 来源/)).toBeInTheDocument();
    expect(within(consolePanel).getAllByText('A').length).toBeGreaterThan(0);
    expect(within(consolePanel).getAllByText('B').length).toBeGreaterThan(0);
    expect(within(consolePanel).queryByLabelText('新标题 - dup-b')).not.toBeInTheDocument();
    expect(within(consolePanel).queryByText(/"kind": "resolve_duplicate_label_group"/)).not.toBeInTheDocument();
    expect(within(consolePanel).getByRole('button', { name: '合并选中' })).toBeEnabled();
    expect(within(consolePanel).getByRole('button', { name: '保存消歧' })).toBeDisabled();

    expect(within(consolePanel).getAllByLabelText('新标题')).toHaveLength(1);
    expect(within(consolePanel).getAllByLabelText('消歧说明')).toHaveLength(1);
    fireEvent.change(within(consolePanel).getByLabelText('新标题'), { target: { value: '重复证据（材料 m2）' } });
    fireEvent.change(within(consolePanel).getByLabelText('消歧说明'), { target: { value: '它来自材料 m2，不能和材料 m1 合并。' } });
    expect(within(consolePanel).getByText('待保存')).toBeInTheDocument();

    const saveDisambiguation = within(consolePanel).getByRole('button', { name: '保存消歧' });
    expect(saveDisambiguation).toBeEnabled();
    fireEvent.click(saveDisambiguation);

    await waitFor(() => {
      expect(applyWikiGraphReview).toHaveBeenCalledWith(expect.objectContaining({
        operation_kind: 'disambiguate_nodes',
        nodes: [expect.objectContaining({
          node_id: 'dup-b',
          page_path: 'evidence/dup-b.md',
          label: '重复证据（材料 m2）',
          disambiguation: '它来自材料 m2，不能和材料 m1 合并。',
        })],
      }));
    });

    await waitFor(() => expect(within(consolePanel).getByRole('button', { name: '撤回上次' })).toBeEnabled());
    fireEvent.click(within(consolePanel).getByRole('button', { name: '撤回上次' }));
    await waitFor(() => expect(undoWikiGraphReview).toHaveBeenCalledWith(expect.objectContaining({
      operation_id: 'op-1',
      snapshots: [{
        page_path: 'evidence/dup-b.md',
        content: 'before',
        content_hash: 'hash-before',
        expected_current_hash: 'hash-after',
      }],
    })));
  });

  it('explains read-only current context graph review when duplicate nodes have no wiki page paths', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'dup-a',
          type: 'evidence',
          label: '重复证据',
          confidence: null,
          material_id: 'm1',
          metadata: { reasoning_dimension: 'evidence' },
          source_ref: { material_id: 'm1', page: 1, chunk_id: 'c-a', text: 'A' },
          evidence_refs: [{ material_id: 'm1', page: 1, chunk_id: 'c-a', text: 'A' }],
        },
        {
          id: 'dup-b',
          type: 'evidence',
          label: '重复证据',
          confidence: null,
          material_id: 'm2',
          metadata: { reasoning_dimension: 'evidence' },
          source_ref: { material_id: 'm2', page: 2, chunk_id: 'c-b', text: 'B' },
          evidence_refs: [{ material_id: 'm2', page: 2, chunk_id: 'c-b', text: 'B' }],
        },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} />);

    const queue = screen.getByLabelText('图谱处理队列');
    fireEvent.click(within(queue).getByRole('button', { name: '定位重复标签' }));

    const consolePanel = screen.getByRole('region', { name: '复审控制台' });
    expect(within(consolePanel).getByText(/当前图谱只读/)).toBeInTheDocument();
    expect(within(consolePanel).getByText(/先把上下文沉淀成 Wiki 页面/)).toBeInTheDocument();
    expect(within(consolePanel).getByRole('button', { name: '合并选中' })).toBeDisabled();
    expect(within(consolePanel).getByRole('button', { name: '保存消歧' })).toBeDisabled();
  });

  it('applies node evidence from the graph review console and keeps the audit patch visible', async () => {
    vi.mocked(applyWikiGraphReview).mockClear();
    vi.mocked(applyWikiGraphReview).mockResolvedValue({
      enabled: true,
      operation_id: 'op-node',
      operation_kind: 'add_node_evidence',
      updated_page_paths: ['evidence/missing.md'],
      snapshots: [{
        page_path: 'evidence/missing.md',
        content: 'before',
        content_hash: 'hash-before',
        expected_current_hash: 'hash-after',
      }],
      message: '已给 1 个节点补充证据。',
      warnings: [],
    });
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'missing-ev',
          type: 'evidence',
          label: '缺证据节点',
          confidence: null,
          material_id: null,
          metadata: { reasoning_dimension: 'evidence', page_path: 'evidence/missing.md' },
          source_ref: null,
          evidence_refs: [],
        },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} />);
    const queue = screen.getByLabelText('图谱处理队列');

    fireEvent.click(within(queue).getByRole('button', { name: '定位证据节点缺少 refs' }));

    const consolePanel = screen.getByRole('region', { name: '复审控制台' });
    fireEvent.change(within(consolePanel).getByLabelText('material_id'), { target: { value: 'mat-1' } });
    fireEvent.change(within(consolePanel).getByLabelText('chunk_id'), { target: { value: 'chunk-9' } });
    fireEvent.change(within(consolePanel).getByLabelText('page'), { target: { value: '7' } });
    fireEvent.change(within(consolePanel).getByLabelText('证据摘录'), { target: { value: '原文证据片段' } });

    const applyButton = within(consolePanel).getByRole('button', { name: '应用补节点证据' });
    expect(applyButton).toBeEnabled();
    fireEvent.click(applyButton);

    await waitFor(() => {
      expect(applyWikiGraphReview).toHaveBeenCalledWith(expect.objectContaining({
        operation_kind: 'add_node_evidence',
        nodes: [{ node_id: 'missing-ev', page_path: 'evidence/missing.md' }],
        evidence_refs: [{ material_id: 'mat-1', chunk_id: 'chunk-9', page: 7, text: '原文证据片段' }],
      }));
    });
    await waitFor(() => expect(within(consolePanel).getByRole('button', { name: '撤回上次' })).toBeEnabled());
    expect(within(consolePanel).getByText(/"kind": "add_node_evidence"/)).toBeInTheDocument();
    expect(within(consolePanel).getByText(/"material_id": "mat-1"/)).toBeInTheDocument();
    expect(within(consolePanel).getByText(/"chunk_id": "chunk-9"/)).toBeInTheDocument();
    expect(within(consolePanel).getByText(/"page": 7/)).toBeInTheDocument();
  });

  it('fills the review evidence form from the selected graph node without applying changes', () => {
    vi.mocked(applyWikiGraphReview).mockClear();
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'source-ev',
          type: 'evidence',
          label: '可用证据',
          confidence: null,
          material_id: 'mat-auto',
          metadata: { reasoning_dimension: 'evidence', page_path: 'evidence/source.md' },
          source_ref: { material_id: 'mat-auto', page: 9, chunk_id: 'chunk-auto', text: '可一键填入的原文证据' },
          evidence_refs: [{ material_id: 'mat-auto', page: 9, chunk_id: 'chunk-auto', text: '可一键填入的原文证据' }],
        },
        {
          id: 'missing-ev',
          type: 'evidence',
          label: '缺证据节点',
          confidence: null,
          material_id: null,
          metadata: { reasoning_dimension: 'evidence', page_path: 'evidence/missing.md' },
          source_ref: null,
          evidence_refs: [],
        },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} />);

    fireEvent.click(screen.getByRole('button', { name: 'source-ev' }));
    fireEvent.click(screen.getByRole('button', { name: '填入证据' }));

    const queue = screen.getByLabelText('图谱处理队列');
    const consolePanel = screen.getByRole('region', { name: '复审控制台' });
    expect(within(queue).getByRole('button', { name: '定位证据节点缺少 refs' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(consolePanel).getByText('已填入选中证据')).toBeInTheDocument();
    expect(within(consolePanel).getByLabelText('material_id')).toHaveValue('mat-auto');
    expect(within(consolePanel).getByLabelText('chunk_id')).toHaveValue('chunk-auto');
    expect(within(consolePanel).getByLabelText('page')).toHaveValue('9');
    expect(within(consolePanel).getByLabelText('证据摘录')).toHaveValue('可一键填入的原文证据');
    expect(applyWikiGraphReview).not.toHaveBeenCalled();
  });

  it('applies relation evidence for edges that lack evidence refs', async () => {
    vi.mocked(applyWikiGraphReview).mockClear();
    vi.mocked(applyWikiGraphReview).mockResolvedValue({
      enabled: true,
      operation_id: 'op-edge',
      operation_kind: 'add_relation_evidence',
      updated_page_paths: ['claims/a.md'],
      snapshots: [{
        page_path: 'claims/a.md',
        content: 'before',
        content_hash: 'hash-before',
        expected_current_hash: 'hash-after',
      }],
      message: '已给 1 条关系补充证据。',
      warnings: [],
    });
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'claim-a',
          type: 'claim',
          label: '主张 A',
          confidence: 0.8,
          material_id: 'm1',
          metadata: { reasoning_dimension: 'observation', page_path: 'claims/a.md' },
          source_ref: { material_id: 'm1', page: 1, chunk_id: 'a1', text: 'A' },
          evidence_refs: [{ material_id: 'm1', page: 1, chunk_id: 'a1', text: 'A' }],
        },
        {
          id: 'claim-b',
          type: 'claim',
          label: '主张 B',
          confidence: 0.8,
          material_id: 'm2',
          metadata: { reasoning_dimension: 'mechanism', page_path: 'claims/b.md' },
          source_ref: { material_id: 'm2', page: 2, chunk_id: 'b1', text: 'B' },
          evidence_refs: [{ material_id: 'm2', page: 2, chunk_id: 'b1', text: 'B' }],
        },
      ],
      edges: [
        {
          id: 'a-supports-b',
          source: 'claim-a',
          target: 'claim-b',
          relation: 'supports',
          confidence: 0.9,
          material_id: null,
          metadata: { source_path: 'claims/a.md', frontmatter_field: 'relations' },
          source_ref: null,
          evidence_refs: [],
        },
      ],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} />);
    const queue = screen.getByLabelText('图谱处理队列');

    fireEvent.click(within(queue).getByRole('button', { name: '定位关系缺少证据' }));

    const consolePanel = screen.getByRole('region', { name: '复审控制台' });
    expect(within(consolePanel).getByRole('button', { name: '补关系证据' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(consolePanel).getByText('补证据关系')).toBeInTheDocument();
    fireEvent.change(within(consolePanel).getByLabelText('material_id'), { target: { value: 'mat-1' } });
    fireEvent.change(within(consolePanel).getByLabelText('chunk_id'), { target: { value: 'chunk-2' } });
    fireEvent.change(within(consolePanel).getByLabelText('page'), { target: { value: '4' } });
    fireEvent.change(within(consolePanel).getByLabelText('证据摘录'), { target: { value: '关系证据' } });

    const applyButton = within(consolePanel).getByRole('button', { name: '应用补关系证据' });
    expect(applyButton).toBeEnabled();
    fireEvent.click(applyButton);

    await waitFor(() => {
      expect(applyWikiGraphReview).toHaveBeenCalledWith(expect.objectContaining({
        operation_kind: 'add_relation_evidence',
        nodes: [],
        edges: [expect.objectContaining({
          edge_id: 'a-supports-b',
          source: 'claim-a',
          target: 'claim-b',
          relation: 'supports',
          source_path: 'claims/a.md',
          frontmatter_field: 'relations',
        })],
        evidence_refs: [{ material_id: 'mat-1', chunk_id: 'chunk-2', page: 4, text: '关系证据' }],
      }));
    });
    expect(within(consolePanel).getByText(/"kind": "add_relation_evidence"/)).toBeInTheDocument();
    expect(within(consolePanel).getByText(/"edge_id": "a-supports-b"/)).toBeInTheDocument();
    expect(within(consolePanel).getByText(/"source": "claim-a"/)).toBeInTheDocument();
    expect(within(consolePanel).getByText(/"target": "claim-b"/)).toBeInTheDocument();
    expect(within(consolePanel).getAllByText(/claims\/a\.md/).length).toBeGreaterThan(0);
    expect(within(consolePanel).getByText(/"frontmatter_fields":/)).toBeInTheDocument();
  });

  it('keeps the semantic review queue actionable from the sidebar', () => {
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
    const queue = screen.getByLabelText('图谱处理队列');

    expect(within(panel).queryByRole('button', { name: '折叠语义复审' })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: '展开语义复审' })).not.toBeInTheDocument();
    expect(within(panel).queryByText('处理队列')).not.toBeInTheDocument();
    expect(within(queue).getByText('先选问题，再在下方合并、消歧或补证据。')).toBeInTheDocument();
  });

  it('keeps the review console visible when the current graph has no queued repair item', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'claim-ok',
          type: 'claim',
          label: '完整结论',
          confidence: 0.9,
          material_id: 'm1',
          metadata: { reasoning_dimension: 'observation' },
          source_ref: { material_id: 'm1', page: 1, chunk_id: 'c1', text: '可判断的原文片段' },
          evidence_refs: [{ material_id: 'm1', page: 1, chunk_id: 'c1', text: '可判断的原文片段' }],
        },
        {
          id: 'evidence-ok',
          type: 'evidence',
          label: '完整证据',
          confidence: 0.9,
          material_id: 'm2',
          metadata: { reasoning_dimension: 'evidence' },
          source_ref: { material_id: 'm2', page: 2, chunk_id: 'c2', text: '另一段可判断的原文片段' },
          evidence_refs: [{ material_id: 'm2', page: 2, chunk_id: 'c2', text: '另一段可判断的原文片段' }],
        },
      ],
      edges: [
        {
          id: 'evidence-supports-claim',
          source: 'evidence-ok',
          target: 'claim-ok',
          relation: 'supports',
          confidence: 0.9,
          metadata: {},
          source_ref: { material_id: 'm3', page: 3, chunk_id: 'c3', text: '关系证据' },
          evidence_refs: [{ material_id: 'm3', page: 3, chunk_id: 'c3', text: '关系证据' }],
        },
      ],
    } as unknown as GraphPayloadV0;

    render(<DimensionGraphViewer payload={payload} density="explorer" />);

    expect(screen.getByRole('region', { name: '复审控制台' })).toHaveTextContent('当前图谱没有待处理项');
    expect(screen.getByLabelText('图谱处理队列')).toHaveTextContent('暂无需要处理的图谱复审项');
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

    const queue = screen.getByLabelText('图谱处理队列');
    const diagnostics = within(queue).getByLabelText('图谱结构诊断');
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

  it('keeps graph expansion outside the embedded filter toolbar', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;
    render(<DimensionGraphViewer payload={payload} density="rail" />);

    expect(screen.queryByRole('button', { name: '展开图谱' })).not.toBeInTheDocument();
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
    expect(screen.queryByRole('button', { name: '放大图谱' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '缩小图谱' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '适配视图' })).toBeInTheDocument();
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

  it('keeps node hover stable and focuses connected routes only after click', () => {
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

    expect(screen.getByTestId('react-flow-stub')).toHaveAttribute('data-elements-selectable', 'false');
    expect(screen.getByTestId('react-flow-stub')).toHaveAttribute('data-nodes-focusable', 'true');
    expect(screen.getByTestId('react-flow-stub')).toHaveAttribute('data-edges-focusable', 'false');
    expect(screen.getByTestId('react-flow-stub')).toHaveAttribute('data-select-nodes-on-drag', 'false');
    expect(reasoningEdge).toHaveAttribute('data-route-visibility', 'visible');
    expect(evidenceEdge).toHaveAttribute('data-route-visibility', 'visible');
    const defaultOpacity = Number(reasoningEdge.dataset.opacity);

    fireEvent.mouseEnter(screen.getByRole('button', { name: 'q' }));

    expect(screen.getByTestId('edge-q-to-obs')).toHaveAttribute('data-route-visibility', 'visible');
    expect(screen.getByTestId('edge-ev-to-obs')).toHaveAttribute('data-route-visibility', 'visible');
    expect(Number(screen.getByTestId('edge-q-to-obs').dataset.opacity)).toBe(defaultOpacity);

    fireEvent.click(screen.getByRole('button', { name: 'q' }));

    expect(screen.getByTestId('edge-q-to-obs')).toHaveAttribute('data-route-visibility', 'visible');
    expect(screen.getByTestId('edge-ev-to-obs')).toHaveAttribute('data-route-visibility', 'ghost');
    expect(Number(screen.getByTestId('edge-q-to-obs').dataset.opacity)).toBeGreaterThan(Number(screen.getByTestId('edge-ev-to-obs').dataset.opacity));
  });

  it('dims unrelated rectangles while a node is focused', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'obs', type: 'claim', label: '观察结论', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'ev', type: 'evidence', label: '证据片段', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'other', type: 'claim', label: '无关节点', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [
        { id: 'q-to-obs', source: 'q', target: 'obs', relation: 'derives_from', confidence: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'ev-to-obs', source: 'ev', target: 'obs', relation: 'supports', confidence: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
    } as unknown as GraphPayloadV0;
    render(<DimensionGraphViewer payload={payload} />);

    fireEvent.click(screen.getByRole('button', { name: 'q' }));

    expect(screen.getByTestId('node-q')).toHaveAttribute('data-focus-visibility', 'focused');
    expect(screen.getByTestId('node-obs')).toHaveAttribute('data-focus-visibility', 'focused');
    expect(screen.getByTestId('node-ev')).toHaveAttribute('data-focus-visibility', 'muted');
    expect(screen.getByTestId('node-other')).toHaveAttribute('data-focus-visibility', 'muted');
    expect(Number(screen.getByTestId('node-other').dataset.opacity)).toBeLessThan(0.3);
  });

  it('filters route categories down to matching edges and connected nodes', () => {
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

    expect(screen.queryByRole('button', { name: 'q' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'counter' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ev' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'obs' })).toBeInTheDocument();
    expect(screen.queryByTestId('edge-q-to-obs')).not.toBeInTheDocument();
    expect(screen.getByTestId('edge-ev-to-obs')).toHaveAttribute('data-hidden', 'false');
    expect(screen.queryByTestId('edge-counter-to-obs')).not.toBeInTheDocument();
    expect(screen.getByLabelText('图谱筛选状态')).toHaveTextContent('显示 2/4 节点 · 1/3 关系');
  });

  it('combines dimension and route filters with an explicit empty state', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        { id: 'q', type: 'topic', label: '研究主题', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'obs', type: 'claim', label: '观察结论', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
        { id: 'ev', type: 'evidence', label: '证据片段', confidence: null, material_id: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
      edges: [
        { id: 'ev-to-obs', source: 'ev', target: 'obs', relation: 'supports', confidence: null, metadata: {}, source_ref: null, evidence_refs: [] },
      ],
    } as unknown as GraphPayloadV0;
    render(<DimensionGraphViewer payload={payload} />);

    fireEvent.click(screen.getByTitle('当前要解决的问题或主题。 - 点击筛选'));
    fireEvent.click(screen.getByTitle('支持和被支持关系'));

    expect(screen.queryByRole('button', { name: 'q' })).not.toBeInTheDocument();
    expect(screen.getByText('当前筛选没有匹配的节点或关系。')).toBeInTheDocument();
    expect(screen.getByLabelText('图谱筛选状态')).toHaveTextContent('显示 0/3 节点 · 0/1 关系');
  });

  it('keeps edge hover passive so the canvas does not flicker', () => {
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

    const edge = screen.getByTestId('edge-q-to-obs');
    expect(edge).toHaveAttribute('data-route-visibility', 'visible');
    const defaultOpacity = Number(edge.dataset.opacity);

    fireEvent.mouseEnter(screen.getByTestId('edge-q-to-obs'));

    expect(screen.getByTestId('edge-q-to-obs')).toHaveAttribute('data-route-visibility', 'visible');
    expect(Number(screen.getByTestId('edge-q-to-obs').dataset.opacity)).toBe(defaultOpacity);
  });
});
