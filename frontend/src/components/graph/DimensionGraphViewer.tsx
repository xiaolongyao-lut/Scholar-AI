import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Background,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Copy, ExternalLink, Crosshair, Maximize2, Minus, Plus, X } from 'lucide-react';

import { cn } from '@/lib/utils';
import { DimensionNode, type DimensionNodeData } from './DimensionNode';
import { DimensionBusEdge } from './DimensionBusEdge';
import {
  DIMENSION_DISPLAY_ORDER,
  DIMENSION_META,
  buildDimensionGraph,
  type DimensionGraphNode,
  type ReasoningDimension,
} from './dimensionGraph';
import { layoutDimensionGraph, type DimensionLane } from './dimensionLayout';
import { readNodeEvidenceText } from './graphEvidenceDisplay';
import { resolveMaterialTarget, type GraphPayloadV0 } from './payloadToRf';

/** rail = 右栏轻量预览；explorer = 全宽工作台。 */
export type GraphDensity = 'rail' | 'explorer';

/** 详情面板落位：浮层（rail）或右侧固定栏（explorer）。 */
export type DetailPlacement = 'panel' | 'sidebar';

interface DimensionGraphViewerProps {
  payload: GraphPayloadV0 | null;
  loading?: boolean;
  error?: string | null;
  className?: string;
  /** 选中节点回调（仅通知宿主，不触发跳转）。 */
  onSelectNode?: (entry: DimensionGraphNode | null) => void;
  /** 「打开原文」按钮回调；返回 false 表示该节点无可跳转材料。 */
  onOpenSource?: (entry: DimensionGraphNode) => Promise<boolean> | boolean;
  /** 隐藏空泳道，默认开。 */
  hideEmptyLanes?: boolean;
  /** 是否显示图例 / 筛选条（默认显示）。 */
  showLegend?: boolean;
  /** 密度模式，决定 MiniMap、详情落位、默认精简。 */
  density?: GraphDensity;
  /** 显式覆盖是否显示 MiniMap（默认 explorer 显示、rail 隐藏）。 */
  showMiniMap?: boolean;
  /** 显式覆盖详情落位（默认 explorer=sidebar、rail=panel）。 */
  detailPlacement?: DetailPlacement;
  /** 受控筛选状态（切 tab 不丢）。不传则内部自管。 */
  selectedDimensions?: Set<ReasoningDimension>;
  onChangeSelectedDimensions?: (next: Set<ReasoningDimension>) => void;
  /** 「展开图谱」按钮回调；rail 模式下显示在工具条。 */
  onExpand?: () => void;
}

const NODE_TYPES = { dimensionNode: DimensionNode } as const;
const EDGE_TYPES = { dimensionBusEdge: DimensionBusEdge } as const;

/** 证据维度集合，用于「只看证据」快捷筛选。 */
const EVIDENCE_DIMENSIONS: ReadonlySet<ReasoningDimension> = new Set<ReasoningDimension>([
  'evidence',
  'counter_evidence',
]);

function relationStroke(relation: string | undefined): string {
  switch (relation) {
    case 'contradicts':
    case 'challenges':
    case 'refutes':
      return 'hsl(0 70% 55%)';
    case 'supports':
    case 'supported_by':
      return 'hsl(155 55% 38%)';
    case 'cites':
      return 'hsl(35 80% 45%)';
    case 'derives_from':
    case 'builds_on':
    case 'extends':
      return 'hsl(220 85% 56%)';
    default:
      return 'hsl(220 8% 50%)';
  }
}

function relationDashed(relation: string | undefined): string | undefined {
  return relation === 'cites' ? '6 4' : undefined;
}

function styleEdges(edges: Edge[]): Edge[] {
  return edges.map((edge) => {
    const rel = (edge.data as { raw?: { relation?: string } } | undefined)?.raw?.relation;
    const stroke = relationStroke(rel);
    return {
      ...edge,
      labelStyle: { fill: 'hsl(var(--foreground) / 0.62)', fontSize: 10, fontWeight: 500 },
      labelBgStyle: { fill: 'hsl(var(--surface-lowest) / 0.85)' },
      style: { stroke, strokeWidth: rel === 'supports' || rel === 'contradicts' ? 1.8 : 1.3, strokeDasharray: relationDashed(rel) },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: stroke },
      animated: rel === 'supports' || rel === 'contradicts',
    };
  });
}

function FilterBar({
  counts,
  selectedDimensions,
  onToggleDimension,
  onResetFilter,
  onlyEvidence,
  onToggleOnlyEvidence,
}: {
  counts: Record<ReasoningDimension, number>;
  selectedDimensions: Set<ReasoningDimension>;
  onToggleDimension: (dimension: ReasoningDimension) => void;
  onResetFilter: () => void;
  onlyEvidence: boolean;
  onToggleOnlyEvidence: () => void;
}) {
  const totalFiltered = Array.from(selectedDimensions).reduce((sum, d) => sum + (counts[d] ?? 0), 0);
  const totalAll = DIMENSION_DISPLAY_ORDER.reduce((sum, d) => sum + (counts[d] ?? 0), 0);
  const isFiltering = selectedDimensions.size > 0 && selectedDimensions.size < DIMENSION_DISPLAY_ORDER.length;

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-outline-variant/50 bg-surface-low px-2 py-1 text-[10px]">
      <button
        type="button"
        onClick={onToggleOnlyEvidence}
        className={cn(
          'rounded-sm border px-1.5 py-0.5 transition-colors',
          onlyEvidence
            ? 'border-primary/50 bg-primary/15 text-primary'
            : 'border-outline-variant/60 bg-surface text-foreground/65 hover:text-foreground',
        )}
        aria-pressed={onlyEvidence}
        title="只看证据 / 反证"
      >
        {onlyEvidence ? '看全部' : '只看证据'}
      </button>
      <span className="mx-0.5 h-3 w-px bg-outline-variant/50" aria-hidden />
      {DIMENSION_DISPLAY_ORDER.map((dimension) => {
        const meta = DIMENSION_META[dimension];
        const count = counts[dimension] ?? 0;
        const isSelected = selectedDimensions.has(dimension);
        const isActive = !isFiltering || isSelected;
        return (
          <button
            key={dimension}
            type="button"
            onClick={() => onToggleDimension(dimension)}
            title={`${meta.description} - 点击筛选`}
            className={cn(
              'inline-flex items-center gap-1 rounded-sm border px-1 py-0.5 transition-opacity',
              isActive ? 'opacity-100' : 'opacity-40',
              count === 0 && 'opacity-30',
            )}
            style={{ borderColor: meta.border, background: meta.surface, color: meta.accent }}
            aria-pressed={isSelected}
            disabled={count === 0}
          >
            <span
              className="inline-flex h-3 min-w-3 items-center justify-center rounded-sm text-white"
              style={{ background: meta.accent, fontSize: 9 }}
            >
              {meta.glyph}
            </span>
            <span className="text-foreground/75">{meta.label}</span>
            <span className="text-foreground/45">{count}</span>
          </button>
        );
      })}
      {isFiltering && (
        <button
          type="button"
          onClick={onResetFilter}
          className="ml-1 rounded-sm border border-outline-variant/60 bg-surface px-1.5 py-0.5 text-foreground/65 hover:bg-surface-high transition-colors"
          title="重置筛选"
        >
          已筛选 {totalFiltered}/{totalAll} · 重置
        </button>
      )}
    </div>
  );
}

function LaneHeaders({ lanes, height }: { lanes: DimensionLane[]; height: number }) {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 z-0"
      style={{ minWidth: lanes.reduce((max, lane) => Math.max(max, lane.x + lane.width), 0) }}
    >
      {lanes.map((lane) => {
        const meta = DIMENSION_META[lane.dimension];
        return (
          <div
            key={lane.dimension}
            className="absolute"
            style={{
              top: lane.y ?? 0,
              left: lane.x,
              width: lane.width,
              height: lane.height ?? height,
            }}
          >
            <div
              className="mx-auto mt-2 inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px]"
              style={{ borderColor: meta.border, background: meta.surface, color: meta.accent }}
            >
              <span
                className="inline-flex h-3 min-w-3 items-center justify-center rounded-sm text-white"
                style={{ background: meta.accent, fontSize: 9 }}
              >
                {meta.glyph}
              </span>
              {lane.title}
            </div>
            <div
              className="absolute inset-x-2 top-7 bottom-2 rounded-md"
              style={{ background: meta.surface, opacity: 0.5 }}
            />
          </div>
        );
      })}
    </div>
  );
}

function PlaceholderShell({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex h-full min-h-[280px] w-full items-center justify-center rounded-md border border-dashed border-outline-variant/50 bg-surface-low text-xs text-foreground/55',
        className,
      )}
    >
      {children}
    </div>
  );
}

/**
 * 维度图谱 viewer。把 GraphPayloadV0 投影到维度泳道，再丢给 React Flow 渲染。
 *
 * 两种密度：
 * - rail：右栏轻量预览，弱化 MiniMap，详情走浮层。
 * - explorer：全宽工作台，显示 MiniMap + 右侧固定详情栏。
 *
 * 交互契约（与用户约定）：节点点击只「选中」，不自动跳转；跳转只在详情面板
 * 的「打开原文」按钮触发，避免误点节点就跳走。
 */
export function DimensionGraphViewer({
  payload,
  loading = false,
  error = null,
  className,
  onSelectNode,
  onOpenSource,
  hideEmptyLanes = true,
  showLegend = true,
  density = 'explorer',
  showMiniMap,
  detailPlacement,
  selectedDimensions: controlledDimensions,
  onChangeSelectedDimensions,
  onExpand,
}: DimensionGraphViewerProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [internalDimensions, setInternalDimensions] = useState<Set<ReasoningDimension>>(new Set());

  const selectedDimensions = controlledDimensions ?? internalDimensions;
  const setSelectedDimensions = useCallback(
    (next: Set<ReasoningDimension>) => {
      if (onChangeSelectedDimensions) onChangeSelectedDimensions(next);
      else setInternalDimensions(next);
    },
    [onChangeSelectedDimensions],
  );

  const resolvedMiniMap = showMiniMap ?? density === 'explorer';
  const resolvedDetailPlacement: DetailPlacement = detailPlacement ?? (density === 'explorer' ? 'sidebar' : 'panel');

  const dimensionGraph = useMemo(() => (payload ? buildDimensionGraph(payload) : null), [payload]);

  const filteredGraph = useMemo(() => {
    if (!dimensionGraph || selectedDimensions.size === 0) return dimensionGraph;
    const filteredNodes = dimensionGraph.nodes.filter((entry) => selectedDimensions.has(entry.dimension));
    const nodeIds = new Set(filteredNodes.map((entry) => entry.node.id));
    const filteredEdges = dimensionGraph.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
    return { ...dimensionGraph, nodes: filteredNodes, edges: filteredEdges };
  }, [dimensionGraph, selectedDimensions]);

  const layout = useMemo(
    () => (filteredGraph ? layoutDimensionGraph(filteredGraph, { hideEmptyLanes }) : null),
    [filteredGraph, hideEmptyLanes],
  );

  const selectedEntry = useMemo(() => {
    if (!selectedNodeId || !dimensionGraph) return null;
    return dimensionGraph.nodes.find((candidate) => candidate.node.id === selectedNodeId) ?? null;
  }, [dimensionGraph, selectedNodeId]);

  const handleNodeClick = useCallback(
    (entry: DimensionGraphNode) => {
      setSelectedNodeId(entry.node.id);
      onSelectNode?.(entry);
    },
    [onSelectNode],
  );

  const handleCloseDetail = useCallback(() => {
    setSelectedNodeId(null);
    onSelectNode?.(null);
  }, [onSelectNode]);

  const handleToggleDimension = useCallback(
    (dimension: ReasoningDimension) => {
      const next = new Set(selectedDimensions);
      if (next.has(dimension)) next.delete(dimension);
      else next.add(dimension);
      setSelectedDimensions(next);
    },
    [selectedDimensions, setSelectedDimensions],
  );

  const handleResetFilter = useCallback(() => {
    setSelectedDimensions(new Set());
  }, [setSelectedDimensions]);

  const onlyEvidence = useMemo(() => {
    if (selectedDimensions.size === 0) return false;
    return Array.from(selectedDimensions).every((d) => EVIDENCE_DIMENSIONS.has(d))
      && Array.from(EVIDENCE_DIMENSIONS).every((d) => selectedDimensions.has(d) || (dimensionGraph?.counts[d] ?? 0) === 0);
  }, [selectedDimensions, dimensionGraph]);

  const handleToggleOnlyEvidence = useCallback(() => {
    if (onlyEvidence) {
      setSelectedDimensions(new Set());
    } else {
      const next = new Set<ReasoningDimension>();
      for (const d of EVIDENCE_DIMENSIONS) {
        if ((dimensionGraph?.counts[d] ?? 0) > 0) next.add(d);
      }
      setSelectedDimensions(next);
    }
  }, [onlyEvidence, dimensionGraph, setSelectedDimensions]);

  const nodes = useMemo(() => (layout ? layout.nodes : []), [layout]);
  const edges = useMemo(() => (layout ? styleEdges(layout.edges) : []), [layout]);

  useEffect(() => {
    if (!selectedNodeId) return;
    if (nodes.some((node) => node.id === selectedNodeId)) return;
    handleCloseDetail();
  }, [handleCloseDetail, nodes, selectedNodeId]);

  if (error) {
    return (
      <PlaceholderShell className={className}>
        <span className="text-red-500/80">{error}</span>
      </PlaceholderShell>
    );
  }

  if (loading) {
    return (
      <PlaceholderShell className={className}>
        <span>正在加载维度图谱…</span>
      </PlaceholderShell>
    );
  }

  if (!dimensionGraph || dimensionGraph.nodes.length === 0) {
    return (
      <PlaceholderShell className={className}>
        <span>暂无可投影的节点。</span>
      </PlaceholderShell>
    );
  }

  const showSidebar = resolvedDetailPlacement === 'sidebar' && selectedEntry !== null;

  return (
    <div className={cn('relative flex h-full min-h-[280px] w-full flex-col', className)}>
      {showLegend ? (
        <div className="z-10 flex items-center gap-2 px-2 pt-2">
          <FilterBar
            counts={dimensionGraph.counts}
            selectedDimensions={selectedDimensions}
            onToggleDimension={handleToggleDimension}
            onResetFilter={handleResetFilter}
            onlyEvidence={onlyEvidence}
            onToggleOnlyEvidence={handleToggleOnlyEvidence}
          />
          {onExpand ? (
            <button
              type="button"
              onClick={onExpand}
              className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-outline-variant/60 bg-surface px-2 py-1 text-[11px] text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
              title="展开为全宽图谱工作台"
            >
              <ExternalLink className="h-3 w-3" aria-hidden />
              展开图谱
            </button>
          ) : null}
        </div>
      ) : null}
      <div className="relative flex min-h-0 flex-1 gap-2">
        <div className="relative min-h-0 flex-1 overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest">
          {layout ? <LaneHeaders lanes={layout.lanes} height={layout.total.height} /> : null}
          <ReactFlowProvider>
            <DimensionFlow
              nodes={nodes}
              edges={edges}
              onNodeClick={handleNodeClick}
              showMiniMap={resolvedMiniMap}
              detailPlacement={resolvedDetailPlacement}
              selectedEntry={selectedEntry}
              onOpenSource={onOpenSource}
              onCloseDetail={handleCloseDetail}
            />
          </ReactFlowProvider>
        </div>
        {showSidebar && selectedEntry ? (
          <div className="w-72 shrink-0 overflow-auto rounded-md border border-outline-variant/60 bg-surface-low">
            <SelectionDetail
              entry={selectedEntry}
              onOpenSource={onOpenSource}
              onClose={handleCloseDetail}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * 内层组件，处在 ReactFlowProvider 之内，因此可以用 useReactFlow 调 fitView。
 * panel 落位的详情面板渲染在画布右上角浮层；sidebar 落位时详情由外层渲染。
 */
function DimensionFlow({
  nodes,
  edges,
  onNodeClick,
  showMiniMap,
  detailPlacement,
  selectedEntry,
  onOpenSource,
  onCloseDetail,
}: {
  nodes: Node[];
  edges: Edge[];
  onNodeClick: (entry: DimensionGraphNode) => void;
  showMiniMap: boolean;
  detailPlacement: DetailPlacement;
  selectedEntry: DimensionGraphNode | null;
  onOpenSource?: (entry: DimensionGraphNode) => Promise<boolean> | boolean;
  onCloseDetail: () => void;
}) {
  const { fitView, zoomIn, zoomOut } = useReactFlow();
  const nodeViewportSignature = useMemo(() => nodes.map((node) => node.id).join('|'), [nodes]);

  useEffect(() => {
    if (nodes.length === 0) return undefined;
    const timeoutId = window.setTimeout(() => {
      void fitView({
        duration: 260,
        maxZoom: nodes.length <= 1 ? 1.25 : 1.08,
        padding: nodes.length <= 1 ? 0.42 : 0.12,
      });
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [fitView, nodeViewportSignature, nodes.length]);

  const handleFitToNode = useCallback(
    (entry: DimensionGraphNode) => {
      void fitView({ nodes: [{ id: entry.node.id }], duration: 320, maxZoom: 1.4, padding: 0.3 });
    },
    [fitView],
  );
  const handleFitView = useCallback(() => {
    void fitView({ duration: 260, maxZoom: nodes.length <= 1 ? 1.25 : 1.08, padding: nodes.length <= 1 ? 0.42 : 0.12 });
  }, [fitView, nodes.length]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      edgeTypes={EDGE_TYPES}
      fitView
      fitViewOptions={{ maxZoom: 1.2, padding: 0.08 }}
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, node) => {
        const dimensionEntry = (node.data as DimensionNodeData | undefined)?.dimensionEntry;
        if (dimensionEntry) onNodeClick(dimensionEntry);
      }}
      nodesConnectable={false}
      nodesDraggable={false}
      elementsSelectable
      panOnScroll
      zoomOnPinch
    >
      <Background gap={28} size={1} />
      <Panel position="bottom-left">
        <div className="flex flex-col overflow-hidden rounded-md border border-outline-variant/60 bg-surface/95 shadow-sm backdrop-blur-sm">
          <button
            type="button"
            onClick={() => void zoomIn({ duration: 180 })}
            className="inline-flex h-7 w-7 items-center justify-center border-b border-outline-variant/50 text-foreground/70 transition-colors hover:bg-surface-high hover:text-foreground"
            aria-label="放大图谱"
            title="放大图谱"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => void zoomOut({ duration: 180 })}
            className="inline-flex h-7 w-7 items-center justify-center border-b border-outline-variant/50 text-foreground/70 transition-colors hover:bg-surface-high hover:text-foreground"
            aria-label="缩小图谱"
            title="缩小图谱"
          >
            <Minus className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={handleFitView}
            className="inline-flex h-7 w-7 items-center justify-center text-foreground/70 transition-colors hover:bg-surface-high hover:text-foreground"
            aria-label="适配视图"
            title="适配视图"
          >
            <Maximize2 className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      </Panel>
      {showMiniMap ? (
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) => {
            const entry = (node.data as DimensionNodeData | undefined)?.dimensionEntry;
            return entry ? DIMENSION_META[entry.dimension].accent : '#ccc';
          }}
          className="!bg-surface-low/80 !border-outline-variant/50"
        />
      ) : null}
      {detailPlacement === 'panel' && selectedEntry ? (
        <Panel position="top-right">
          <SelectionDetail
            entry={selectedEntry}
            onOpenSource={onOpenSource}
            onFitToNode={handleFitToNode}
            onClose={onCloseDetail}
            compact
          />
        </Panel>
      ) : null}
      {detailPlacement === 'sidebar' && selectedEntry ? (
        // sidebar 模式：详情在外层右栏，这里只暴露定位节点的浮层按钮。
        <Panel position="top-right">
          <button
            type="button"
            onClick={() => handleFitToNode(selectedEntry)}
            className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 bg-surface/90 px-2 py-1 text-[11px] text-foreground/70 shadow-sm backdrop-blur-sm transition-colors hover:border-primary/40 hover:text-foreground"
            title="把视图聚焦到选中节点"
          >
            <Crosshair className="h-3 w-3" aria-hidden />
            定位节点
          </button>
        </Panel>
      ) : null}
    </ReactFlow>
  );
}

function describeReason(reason: DimensionGraphNode['reason']): string {
  switch (reason) {
    case 'metadata':
      return '后端显式声明';
    case 'analysis_chain_field':
      return '思维链字段映射';
    case 'node_type':
      return '节点类型推断';
    case 'edge_relations':
      return '邻接关系推断';
    case 'evidence_anchor':
      return '证据锚点推断';
    case 'fallback':
    default:
      return '尚未分类';
  }
}

/**
 * 节点详情 / 操作面板。展示证据元信息，并提供明确动作按钮：
 * 打开原文（需有材料定位）、复制证据、定位节点。
 */
function SelectionDetail({
  entry,
  onOpenSource,
  onFitToNode,
  onClose,
  compact = false,
}: {
  entry: DimensionGraphNode;
  onOpenSource?: (entry: DimensionGraphNode) => Promise<boolean> | boolean;
  onFitToNode?: (entry: DimensionGraphNode) => void;
  onClose: () => void;
  compact?: boolean;
}) {
  const [copyState, setCopyState] = useState<'idle' | 'done'>('idle');
  const [openState, setOpenState] = useState<'idle' | 'failed'>('idle');

  const meta = DIMENSION_META[entry.dimension];
  const node = entry.node;
  const target = useMemo(() => resolveMaterialTarget(node), [node]);
  const evidenceText = useMemo(() => readNodeEvidenceText(node), [node]);
  const confidence = entry.display.confidence;
  const confidenceText = confidence !== null && !Number.isNaN(confidence)
    ? `${(confidence * 100).toFixed(0)}%`
    : null;

  const canOpenSource = Boolean(onOpenSource && target);

  const handleCopy = useCallback(() => {
    const text = evidenceText ?? entry.display.title;
    if (!text) return;
    void navigator.clipboard?.writeText(text).then(() => {
      setCopyState('done');
      window.setTimeout(() => setCopyState('idle'), 1500);
    }).catch(() => {
      // 剪贴板被拒时静默：动作非关键，不打断研读。
    });
  }, [evidenceText, entry.display.title]);

  const handleOpen = useCallback(async () => {
    if (!onOpenSource) return;
    setOpenState('idle');
    const ok = await onOpenSource(entry);
    if (!ok) setOpenState('failed');
  }, [onOpenSource, entry]);

  return (
    <div
      className={cn(
        'rounded-lg border border-outline-variant/70 bg-surface shadow-lg',
        compact ? 'w-64 backdrop-blur-sm' : 'w-full border-0 shadow-none',
      )}
    >
      <div className="flex items-start justify-between gap-2 border-b border-outline-variant/50 px-3 py-2">
        <div className="flex min-w-0 items-center gap-1.5 text-[11px]">
          <span
            className="inline-flex h-4 min-w-4 shrink-0 items-center justify-center rounded-sm px-1 text-[10px] font-semibold text-white"
            style={{ background: meta.accent }}
            title={meta.description}
          >
            {meta.glyph}
          </span>
          <span style={{ color: meta.accent }} className="font-semibold">
            {meta.label}
          </span>
          <span className="rounded-sm border border-outline-variant/50 px-1 text-foreground/60">
            {entry.display.typeLabel}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-sm p-0.5 text-foreground/45 hover:bg-surface-high hover:text-foreground/80"
          aria-label="关闭详情"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>

      <div className="space-y-2 px-3 py-2.5 text-[11px]">
        <div className="text-xs font-medium leading-snug text-foreground">
          {entry.display.title}
        </div>

        <dl className="space-y-1 text-foreground/70">
          {entry.display.sourceLabel && (
            <div className="flex items-start gap-1.5">
              <dt className="shrink-0 text-foreground/45">文献</dt>
              <dd className="break-words">{entry.display.sourceLabel}</dd>
            </div>
          )}
          {target?.page && (
            <div className="flex items-start gap-1.5">
              <dt className="shrink-0 text-foreground/45">页码</dt>
              <dd>p.{target.page}</dd>
            </div>
          )}
          {entry.display.evidenceCount > 0 && (
            <div className="flex items-start gap-1.5">
              <dt className="shrink-0 text-foreground/45">证据</dt>
              <dd>{entry.display.evidenceCount} 条</dd>
            </div>
          )}
          {confidenceText && (
            <div className="flex items-start gap-1.5">
              <dt className="shrink-0 text-foreground/45">置信</dt>
              <dd>{confidenceText}</dd>
            </div>
          )}
          {target?.chunk_id && (
            <div className="flex items-start gap-1.5">
              <dt className="shrink-0 text-foreground/45">chunk</dt>
              <dd className="break-all font-mono text-[10px] text-foreground/55">{target.chunk_id}</dd>
            </div>
          )}
        </dl>

        {evidenceText && (
          <div className="rounded border border-outline-variant/40 bg-surface-lowest px-2 py-1.5">
            <p className={cn('text-foreground/70 leading-relaxed', compact ? 'line-clamp-3' : 'line-clamp-6')}>
              {evidenceText}
            </p>
          </div>
        )}

        <div className="text-[10px] text-foreground/45">分类来自: {describeReason(entry.reason)}</div>

        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          {onOpenSource && (
            <button
              type="button"
              onClick={() => void handleOpen()}
              disabled={!canOpenSource}
              className={cn(
                'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition-colors',
                canOpenSource
                  ? 'border-primary/50 bg-primary/10 text-primary hover:bg-primary/20'
                  : 'cursor-not-allowed border-outline-variant/40 text-foreground/35',
              )}
              title={canOpenSource ? '在阅读器中打开对应原文' : '该节点无可定位的原文'}
            >
              <ExternalLink className="h-3 w-3" aria-hidden />
              打开原文
            </button>
          )}
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 bg-surface px-2 py-1 text-[11px] text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
            title="复制证据文本"
          >
            <Copy className="h-3 w-3" aria-hidden />
            {copyState === 'done' ? '已复制' : '复制证据'}
          </button>
          {onFitToNode && (
            <button
              type="button"
              onClick={() => onFitToNode(entry)}
              className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 bg-surface px-2 py-1 text-[11px] text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
              title="把视图聚焦到选中节点"
            >
              <Crosshair className="h-3 w-3" aria-hidden />
              定位节点
            </button>
          )}
        </div>
        {openState === 'failed' && (
          <p className="text-[10px] text-amber-600 dark:text-amber-400">
            未能定位原文：缺少可用的页码或 chunk 锚点。
          </p>
        )}
      </div>
    </div>
  );
}

export default DimensionGraphViewer;
