import { useCallback, useEffect, useId, useMemo, useState } from 'react';
import {
  Background,
  BackgroundVariant,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Copy,
  ExternalLink,
  Crosshair,
  FileSearch,
  Filter,
  GitBranch,
  GitMerge,
  Info,
  ListChecks,
  Scale,
  Wrench,
  X,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { DimensionNode, type DimensionNodeData } from './DimensionNode';
import { DimensionBusEdge } from './DimensionBusEdge';
import {
  DIMENSION_DISPLAY_ORDER,
  DIMENSION_META,
  buildDimensionGraph,
  type DimensionGraph,
  type DimensionGraphNode,
  type ReasoningDimension,
} from './dimensionGraph';
import { layoutDimensionGraph, type DimensionLane } from './dimensionLayout';
import { readNodeEvidenceText } from './graphEvidenceDisplay';
import { resolveMaterialTarget, type GraphEdge, type GraphPayloadV0 } from './payloadToRf';
import {
  buildSemanticReviewSpec,
  type ReviewDashboardSpecV1,
} from './semanticReviewSpec';
import { applyWikiGraphReview, undoWikiGraphReview } from '@/services/wikiApi';
import type {
  WikiGraphReviewApplyModel,
  WikiGraphReviewEdgeInputModel,
  WikiGraphReviewNodeInputModel,
} from '@/types/wiki';

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
  /** 密度模式，决定详情落位和默认精简。 */
  density?: GraphDensity;
  /** @deprecated 图谱不再渲染右下角 MiniMap；保留此属性仅兼容旧调用方。 */
  showMiniMap?: boolean;
  /** 显式覆盖详情落位（默认 explorer=sidebar、rail=panel）。 */
  detailPlacement?: DetailPlacement;
  /** 受控筛选状态（切 tab 不丢）。不传则内部自管。 */
  selectedDimensions?: Set<ReasoningDimension>;
  onChangeSelectedDimensions?: (next: Set<ReasoningDimension>) => void;
  /** 图谱复审写回成功后通知宿主刷新 wiki 图谱。 */
  onReviewApplied?: () => Promise<void> | void;
}

const NODE_TYPES = { dimensionNode: DimensionNode } as const;
const EDGE_TYPES = { dimensionBusEdge: DimensionBusEdge } as const;
const LARGE_GRAPH_NODE_THRESHOLD = 48;
const LARGE_GRAPH_EDGE_THRESHOLD = 160;

/** 证据维度集合，用于「只看证据」快捷筛选。 */
const EVIDENCE_DIMENSIONS: ReadonlySet<ReasoningDimension> = new Set<ReasoningDimension>([
  'evidence',
  'counter_evidence',
]);

const REVIEW_INLINE_CONTROL_CLASS =
  'min-w-0 w-full border-x-0 border-t-0 border-b border-outline-variant/55 bg-transparent px-0 py-1 text-[11px] text-foreground outline-none transition-colors placeholder:text-foreground/35 focus:border-primary/50';
const REVIEW_PANEL_SECTION_CLASS = 'min-w-0 border-t border-outline-variant/35 pt-2.5';
const REVIEW_MUTED_LINE_CLASS = 'min-w-0 break-words text-[10px] leading-relaxed text-foreground/48';

type DimensionRouteKind = 'reasoning' | 'support' | 'counter' | 'citation' | 'other';
type DimensionRouteVisibility = 'visible' | 'ghost';
type ReviewActionKind = 'locate' | 'manual' | 'upstream' | 'informational';
type ReviewConsoleMode = 'merge' | 'disambiguate' | 'node_evidence' | 'relation_evidence' | 'dimension' | 'relationship' | 'inspect';
type ReviewApplyState = 'idle' | 'applying' | 'applied' | 'undoing' | 'undone' | 'failed';

interface ReviewFocusTarget {
  id: string;
  label: string;
  nodeIds: string[];
  edgeIds: string[];
}

interface ReviewActionGuide {
  kind: ReviewActionKind;
  badge: string;
  primary: string;
  nextStep: string;
  detail: string;
  steps: readonly string[];
}

interface ReviewQueueItem {
  key: string;
  label: string;
  count: number;
  action: ReviewActionGuide;
  target: ReviewFocusTarget;
  tone: string;
  title: string;
}

interface ReviewConsoleModeOption {
  mode: ReviewConsoleMode;
  label: string;
  title: string;
}

interface DuplicateDisambiguationDraft {
  label: string;
  disambiguation: string;
}

interface ReviewEvidenceDraft {
  token: number;
  materialId: string;
  chunkId: string;
  page: string;
  evidenceText: string;
  sourceNodeId: string;
  sourceTitle: string;
}

const ROUTE_FILTERS: readonly {
  kind: DimensionRouteKind;
  label: string;
  title: string;
}[] = [
  { kind: 'reasoning', label: '推理', title: '推理和派生关系' },
  { kind: 'citation', label: '引用', title: '引用关系' },
  { kind: 'support', label: '支持', title: '支持和被支持关系' },
  { kind: 'counter', label: '反证', title: '反证和冲突关系' },
];

const SUPPORT_RELATIONS = new Set(['supports', 'supported_by']);
const COUNTER_RELATIONS = new Set(['contradicts', 'challenges', 'refutes']);
const REASONING_RELATIONS = new Set(['derives_from', 'builds_on', 'extends']);

interface RawEdgeLike {
  relation?: unknown;
  confidence?: unknown;
  metadata?: unknown;
  evidence_refs?: unknown;
}

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
      return 'hsl(var(--primary))';
    default:
      return 'hsl(220 8% 50%)';
  }
}

function relationStrokeWidth(relation: string | undefined): number {
  if (COUNTER_RELATIONS.has(relation ?? '')) return 1.6;
  if (SUPPORT_RELATIONS.has(relation ?? '')) return 1.5;
  if (REASONING_RELATIONS.has(relation ?? '')) return 1.4;
  if (relation === 'cites') return 1.25;
  return 1.2;
}

function relationDashed(relation: string | undefined): string | undefined {
  return relation === 'cites' ? '6 4' : undefined;
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function readRawEdge(edge: Edge): RawEdgeLike | null {
  const raw = (edge.data as { raw?: unknown } | undefined)?.raw;
  return raw && typeof raw === 'object' ? raw as RawEdgeLike : null;
}

function readEdgeRelation(edge: Edge): string | undefined {
  const relation = readRawEdge(edge)?.relation;
  return typeof relation === 'string' ? relation : undefined;
}

function readEdgeMetadataNumber(edge: Edge, key: string): number | null {
  const metadata = readRawEdge(edge)?.metadata;
  if (!metadata || typeof metadata !== 'object') return null;
  const value = (metadata as Record<string, unknown>)[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function readAverageEvidenceScore(edge: Edge): number | null {
  const refs = readRawEdge(edge)?.evidence_refs;
  if (!Array.isArray(refs)) return null;
  const scores = refs
    .map((ref) => (ref && typeof ref === 'object' ? (ref as Record<string, unknown>).score : null))
    .filter((score): score is number => typeof score === 'number' && Number.isFinite(score));
  if (scores.length === 0) return null;
  return scores.reduce((sum, score) => sum + score, 0) / scores.length;
}

function readEvidenceWeight(edge: Edge): number {
  const tolfScore = readEdgeMetadataNumber(edge, 'tolf_evidence_score');
  if (tolfScore !== null) return clampNumber(tolfScore, 0, 1);
  const confidence = readRawEdge(edge)?.confidence;
  if (typeof confidence === 'number' && Number.isFinite(confidence)) return clampNumber(confidence, 0, 1);
  const evidenceScore = readAverageEvidenceScore(edge);
  return evidenceScore === null ? 0 : clampNumber(evidenceScore, 0, 1);
}

function resolveRouteKind(relation: string | undefined): DimensionRouteKind {
  if (!relation) return 'other';
  if (SUPPORT_RELATIONS.has(relation)) return 'support';
  if (COUNTER_RELATIONS.has(relation)) return 'counter';
  if (REASONING_RELATIONS.has(relation)) return 'reasoning';
  if (relation === 'cites') return 'citation';
  return 'other';
}

function resolveGraphEdgeRouteKind(edge: GraphEdge): DimensionRouteKind {
  return resolveRouteKind(typeof edge.relation === 'string' ? edge.relation : undefined);
}

function emptyRouteCounts(): Record<DimensionRouteKind, number> {
  return {
    reasoning: 0,
    citation: 0,
    support: 0,
    counter: 0,
    other: 0,
  };
}

function countRouteKinds(edges: readonly GraphEdge[]): Record<DimensionRouteKind, number> {
  const counts = emptyRouteCounts();
  for (const edge of edges) {
    counts[resolveGraphEdgeRouteKind(edge)] += 1;
  }
  return counts;
}

function routeKindLabel(kind: DimensionRouteKind): string {
  return ROUTE_FILTERS.find((route) => route.kind === kind)?.label ?? '其他';
}

function styleEdges(edges: Edge[]): Edge[] {
  return edges.map((edge) => {
    const rel = readEdgeRelation(edge);
    const stroke = relationStroke(rel);
    return {
      ...edge,
      label: undefined,
      style: {
        stroke,
        strokeWidth: relationStrokeWidth(rel),
        strokeDasharray: relationDashed(rel),
      },
      markerEnd: undefined,
      animated: false,
    };
  });
}

function decorateInteractiveEdges(
  edges: Edge[],
  {
    activeNodeId,
    evidenceWeightVisible,
  }: {
    activeNodeId: string | null;
    evidenceWeightVisible: boolean;
  },
): Edge[] {
  return edges.map((edge) => {
    const relation = readEdgeRelation(edge);
    const routeKind = resolveRouteKind(relation);
    const hasFocus = activeNodeId !== null;
    const routeVisible = !hasFocus
      || (activeNodeId !== null && (edge.source === activeNodeId || edge.target === activeNodeId));
    const routeVisibility: DimensionRouteVisibility = routeVisible ? 'visible' : 'ghost';
    const baseWidth = typeof edge.style?.strokeWidth === 'number' ? edge.style.strokeWidth : 1.3;
    const evidenceWidth = evidenceWeightVisible ? readEvidenceWeight(edge) * 2.4 : 0;
    const opacity = routeVisible ? (hasFocus ? 0.9 : 0.42) : 0.06;
    return {
      ...edge,
      hidden: false,
      data: {
        ...(edge.data ?? {}),
        evidenceWeightVisible,
        routeKind,
        routeVisibility,
      },
      style: {
        ...edge.style,
        opacity,
        transition: 'opacity 120ms ease, stroke-width 120ms ease',
        strokeWidth: baseWidth + evidenceWidth,
      },
    };
  });
}

function focusedNodeIds(
  edges: Edge[],
  activeNodeId: string | null,
): Set<string> | null {
  if (!activeNodeId) {
    return null;
  }
  const ids = new Set<string>([activeNodeId]);
  for (const edge of edges) {
    if (edge.source === activeNodeId) {
      ids.add(edge.target);
    } else if (edge.target === activeNodeId) {
      ids.add(edge.source);
    }
  }
  return ids;
}

function decorateInteractiveNodes(
  nodes: Node[],
  {
    edges,
    activeNodeId,
  }: {
    edges: Edge[];
    activeNodeId: string | null;
  },
): Node[] {
  const visibleIds = focusedNodeIds(edges, activeNodeId);
  if (!visibleIds) {
    return nodes.map((node) => ({
      ...node,
      selected: false,
      data: {
        ...(node.data ?? {}),
        focusVisibility: 'normal',
      },
      style: {
        ...node.style,
        opacity: undefined,
        filter: undefined,
        transition: 'opacity 160ms ease, filter 160ms ease',
      },
      zIndex: undefined,
    }));
  }

  return nodes.map((node) => {
    const focused = visibleIds.has(node.id);
    const primary = node.id === activeNodeId;
    return {
      ...node,
      selected: primary,
      data: {
        ...(node.data ?? {}),
        focusVisibility: focused ? 'focused' : 'muted',
      },
      style: {
        ...node.style,
        opacity: focused ? 1 : 0.18,
        filter: focused ? undefined : 'saturate(0.45)',
        transition: 'opacity 160ms ease, filter 160ms ease',
      },
      zIndex: primary ? 20 : focused ? 10 : 0,
    };
  });
}

function FilterBar({
  counts,
  routeCounts,
  selectedDimensions,
  onToggleDimension,
  onlyEvidence,
  onToggleOnlyEvidence,
  evidenceWeightVisible,
  onToggleEvidenceWeight,
  selectedRouteKinds,
  onToggleRouteKind,
}: {
  counts: Record<ReasoningDimension, number>;
  routeCounts: Record<DimensionRouteKind, number>;
  selectedDimensions: Set<ReasoningDimension>;
  onToggleDimension: (dimension: ReasoningDimension) => void;
  onlyEvidence: boolean;
  onToggleOnlyEvidence: () => void;
  evidenceWeightVisible: boolean;
  onToggleEvidenceWeight: () => void;
  selectedRouteKinds: Set<DimensionRouteKind>;
  onToggleRouteKind: (kind: DimensionRouteKind) => void;
}) {
  const totalNodes = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const totalRoutes = Object.values(routeCounts).reduce((sum, count) => sum + count, 0);

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5 border-b border-outline-variant/45 bg-surface-lowest/95 px-2 py-1.5 text-[11px] shadow-sm backdrop-blur-sm">
      <span className="shrink-0 tabular-nums text-foreground/55">
        {totalNodes} 节点 · {totalRoutes} 关系
      </span>
      <span className="mx-0.5 h-4 w-px bg-outline-variant/55" aria-hidden />
      <details className="group relative">
        <summary
          className={cn(
            'flex h-7 cursor-pointer list-none items-center gap-1.5 rounded-sm border px-2 text-foreground/65 transition-colors hover:border-primary/40 hover:text-foreground [&::-webkit-details-marker]:hidden',
            selectedDimensions.size > 0
              ? 'border-primary/45 bg-primary/10 text-primary'
              : 'border-outline-variant/60 bg-surface-low',
          )}
          aria-label="维度筛选"
        >
          <Filter className="size-3.5" aria-hidden />
          <span>维度</span>
          {selectedDimensions.size > 0 ? (
            <span className="tabular-nums">{selectedDimensions.size}</span>
          ) : null}
          <ChevronDown className="size-3 transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <div className="absolute left-0 top-full z-30 mt-1 w-56 border border-outline-variant/60 bg-surface-lowest p-1.5 shadow-lg">
          {DIMENSION_DISPLAY_ORDER.map((dimension) => {
            const meta = DIMENSION_META[dimension];
            const count = counts[dimension] ?? 0;
            const isSelected = selectedDimensions.has(dimension);
            return (
              <button
                key={dimension}
                type="button"
                onClick={() => onToggleDimension(dimension)}
                title={`${meta.description} - 点击筛选`}
                className={cn(
                  'flex w-full items-center gap-2 px-2 py-1.5 text-left transition-colors hover:bg-surface-high',
                  isSelected ? 'bg-primary/10 text-primary' : 'text-foreground/68',
                  count === 0 && 'opacity-35',
                )}
                aria-pressed={isSelected}
                disabled={count === 0}
              >
                <span className="h-3 w-[3px] rounded-sm" style={{ background: meta.accent }} aria-hidden />
                <span className="min-w-0 flex-1 truncate">{meta.label}</span>
                <span className="tabular-nums text-foreground/42">{count}</span>
              </button>
            );
          })}
        </div>
      </details>
      <details className="group relative">
        <summary
          className={cn(
            'flex h-7 cursor-pointer list-none items-center gap-1.5 rounded-sm border px-2 text-foreground/65 transition-colors hover:border-primary/40 hover:text-foreground [&::-webkit-details-marker]:hidden',
            selectedRouteKinds.size > 0
              ? 'border-primary/45 bg-primary/10 text-primary'
              : 'border-outline-variant/60 bg-surface-low',
          )}
          aria-label="关系筛选"
        >
          <GitBranch className="size-3.5" aria-hidden />
          <span>关系</span>
          {selectedRouteKinds.size > 0 ? (
            <span className="tabular-nums">{selectedRouteKinds.size}</span>
          ) : null}
          <ChevronDown className="size-3 transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <div className="absolute left-0 top-full z-30 mt-1 w-52 border border-outline-variant/60 bg-surface-lowest p-1.5 shadow-lg">
          {ROUTE_FILTERS.map((route) => {
            const count = routeCounts[route.kind] ?? 0;
            const isSelected = selectedRouteKinds.has(route.kind);
            const relation = route.kind === 'support'
              ? 'supports'
              : route.kind === 'counter'
                ? 'contradicts'
                : route.kind === 'citation'
                  ? 'cites'
                  : 'extends';
            return (
              <button
                key={route.kind}
                type="button"
                onClick={() => onToggleRouteKind(route.kind)}
                className={cn(
                  'flex w-full items-center gap-2 px-2 py-1.5 text-left transition-colors hover:bg-surface-high',
                  isSelected ? 'bg-primary/10 text-primary' : 'text-foreground/68',
                  count === 0 && 'opacity-35',
                )}
                aria-pressed={isSelected}
                title={route.title}
                disabled={count === 0}
              >
                <span
                  className="h-px w-5 shrink-0"
                  style={{
                    background: relationStroke(relation),
                    borderTop: relation === 'cites' ? `1px dashed ${relationStroke(relation)}` : undefined,
                  }}
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate">{route.label}</span>
                <span className="tabular-nums text-foreground/42">{count}</span>
              </button>
            );
          })}
        </div>
      </details>
      <button
        type="button"
        onClick={onToggleOnlyEvidence}
        className={cn(
          'h-7 rounded-sm border px-2 transition-colors',
          onlyEvidence
            ? 'border-primary/50 bg-primary/15 text-primary'
            : 'border-outline-variant/60 bg-surface-low text-foreground/65 hover:border-primary/40 hover:text-foreground',
        )}
        aria-pressed={onlyEvidence}
        title="只看证据 / 反证"
      >
        {onlyEvidence ? '看全部' : '只看证据'}
      </button>
      <button
        type="button"
        onClick={onToggleEvidenceWeight}
        className={cn(
          'inline-flex size-7 items-center justify-center rounded-sm border transition-colors',
          evidenceWeightVisible
            ? 'border-primary/50 bg-primary/15 text-primary'
            : 'border-outline-variant/60 bg-surface-low text-foreground/65 hover:border-primary/40 hover:text-foreground',
        )}
        aria-pressed={evidenceWeightVisible}
        aria-label="证据权重"
        title="按证据分数加粗边线"
      >
        <Scale className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}

function ActiveFilterStatus({
  selectedDimensions,
  selectedRouteKinds,
  reviewFocusLabel,
  visibleNodeCount,
  totalNodeCount,
  visibleEdgeCount,
  totalEdgeCount,
  onResetFilter,
}: {
  selectedDimensions: Set<ReasoningDimension>;
  selectedRouteKinds: Set<DimensionRouteKind>;
  reviewFocusLabel: string | null;
  visibleNodeCount: number;
  totalNodeCount: number;
  visibleEdgeCount: number;
  totalEdgeCount: number;
  onResetFilter: () => void;
}) {
  const hasDimensionFilter = selectedDimensions.size > 0;
  const hasRouteFilter = selectedRouteKinds.size > 0;
  const hasReviewFocus = reviewFocusLabel !== null;
  if (!hasDimensionFilter && !hasRouteFilter && !hasReviewFocus) {
    return null;
  }
  const dimensionText = Array.from(selectedDimensions)
    .map((dimension) => DIMENSION_META[dimension].label)
    .join('、');
  const routeText = Array.from(selectedRouteKinds).map(routeKindLabel).join('、');
  const scopeText = [
    dimensionText ? `维度: ${dimensionText}` : null,
    routeText ? `关系: ${routeText}` : null,
    reviewFocusLabel ? `复审: ${reviewFocusLabel}` : null,
  ].filter((item): item is string => item !== null).join(' · ');

  return (
    <div
      className="flex flex-wrap items-center gap-1.5 rounded-md border border-primary/25 bg-primary/10 px-2 py-1 text-[11px] text-foreground/70"
      role="status"
      aria-label="图谱筛选状态"
    >
      <span className="font-semibold text-primary">筛选中</span>
      {scopeText ? <span>{scopeText}</span> : null}
      <span className="tabular-nums">
        显示 {visibleNodeCount}/{totalNodeCount} 节点 · {visibleEdgeCount}/{totalEdgeCount} 关系
      </span>
      <button
        type="button"
        onClick={onResetFilter}
        className="rounded-sm border border-primary/35 bg-surface px-1.5 py-0.5 text-primary transition-colors hover:bg-primary/10"
      >
        清除筛选
      </button>
    </div>
  );
}

function filterDimensionGraph(
  graph: DimensionGraph,
  selectedDimensions: Set<ReasoningDimension>,
  selectedRouteKinds: Set<DimensionRouteKind>,
  reviewFocus: ReviewFocusTarget | null,
): DimensionGraph {
  let candidateNodes = graph.nodes;
  let candidateEdges = graph.edges;

  if (reviewFocus) {
    const focusNodeIds = new Set(reviewFocus.nodeIds);
    const focusEdgeIds = new Set(reviewFocus.edgeIds);
    for (const edge of graph.edges) {
      if (!focusEdgeIds.has(edge.id)) continue;
      focusNodeIds.add(edge.source);
      focusNodeIds.add(edge.target);
    }
    candidateNodes = graph.nodes.filter((entry) => focusNodeIds.has(entry.node.id));
    const visibleNodeIds = new Set(candidateNodes.map((entry) => entry.node.id));
    candidateEdges = graph.edges.filter((edge) => (
      visibleNodeIds.has(edge.source)
      && visibleNodeIds.has(edge.target)
      && (focusEdgeIds.has(edge.id) || (reviewFocus.nodeIds.length > 0 && focusNodeIds.has(edge.source) && focusNodeIds.has(edge.target)))
    ));
  }

  const dimensionFilteredNodes = selectedDimensions.size === 0
    ? candidateNodes
    : candidateNodes.filter((entry) => selectedDimensions.has(entry.dimension));
  const dimensionNodeIds = new Set(dimensionFilteredNodes.map((entry) => entry.node.id));
  const dimensionFilteredEdges = candidateEdges.filter((edge) => (
    dimensionNodeIds.has(edge.source) && dimensionNodeIds.has(edge.target)
  ));

  if (selectedRouteKinds.size === 0) {
    return { ...graph, nodes: dimensionFilteredNodes, edges: dimensionFilteredEdges };
  }

  const routeFilteredEdges = dimensionFilteredEdges.filter((edge) => (
    selectedRouteKinds.has(resolveGraphEdgeRouteKind(edge))
  ));
  const routeNodeIds = new Set<string>();
  for (const edge of routeFilteredEdges) {
    routeNodeIds.add(edge.source);
    routeNodeIds.add(edge.target);
  }
  const filteredNodes = dimensionFilteredNodes.filter((entry) => routeNodeIds.has(entry.node.id));
  return { ...graph, nodes: filteredNodes, edges: routeFilteredEdges };
}

function diagnosticToneClass(severity: 'info' | 'warning' | 'critical'): string {
  switch (severity) {
    case 'critical':
      return 'border-red-500/60 text-red-700 dark:text-red-300';
    case 'warning':
      return 'border-amber-500/60 text-amber-700 dark:text-amber-300';
    case 'info':
    default:
      return 'border-sky-500/60 text-sky-700 dark:text-sky-300';
  }
}

function reviewBucketAction(bucketId: string): ReviewActionGuide {
  switch (bucketId) {
    case 'missing_source_anchor':
      return {
        kind: 'upstream',
        badge: '上游缺口',
        primary: '定位缺锚点节点',
        nextStep: '回到生成它的 wiki 页面或导入记录，补 source_ref / evidence_refs 后重建图谱。',
        detail: '图谱只能暴露缺口，不能凭空判断原文位置。',
        steps: [
          '先点队列定位目标节点，右侧详情确认节点标题、类型和当前材料信息。',
          '回到生成该节点的 wiki 页面、frontmatter 或导入记录，找到对应条目。',
          '补 source_ref 或 evidence_refs，至少包含 material_id；有页码、chunk_id 或原文摘录时一并补齐。',
          '重新生成/刷新图谱，确认该节点不再出现在缺少来源锚点队列。',
        ],
      };
    case 'missing_dimension_metadata':
      return {
        kind: 'upstream',
        badge: '标注缺失',
        primary: '定位未标注节点',
        nextStep: '补 reasoning_dimension 或 analysis_chain_field，让节点进入明确泳道。',
        detail: '若大量出现，说明分析链或 wiki frontmatter 没有输出显式维度。',
        steps: [
          '定位目标节点，确认它应属于问题、观察、机制、证据、反证或结论中的哪一类。',
          '在来源 wiki/frontmatter 中补 reasoning_dimension 或 analysis_chain_field。',
          '如果同类节点批量缺失，回查生成模板或分析链字段映射，而不是逐个在图上修。',
          '刷新图谱，确认节点进入正确泳道。',
        ],
      };
    case 'missing_evidence_refs':
      return {
        kind: 'upstream',
        badge: '不可跳转',
        primary: '定位证据节点',
        nextStep: '给证据节点绑定 material_id / chunk_id / page；否则无法打开原文。',
        detail: '这是证据链路缺字段，不是用户在图上拖线就能修好的问题。',
        steps: [
          '定位证据节点，查看标题和右侧详情中已有的文献、页码、chunk 信息。',
          '在材料库或来源 wiki 中找到支撑该证据的原文片段。',
          '给该证据条目补 evidence_refs，至少写入 material_id；可用时补 chunk_id、page 和 text。',
          '刷新图谱后点击节点详情里的“打开原文”，确认可以跳到材料位置。',
        ],
      };
    case 'orphan_nodes':
      return {
        kind: 'manual',
        badge: '待整理',
        primary: '定位孤立节点',
        nextStep: '确认它是否有用；有用就补关系，噪音节点就从上游页面移出。',
        detail: '孤立节点不一定错，但不能直接参与推理路径。',
        steps: [
          '定位孤立节点，判断它是可用知识、重复节点，还是导入噪音。',
          '如果可用，在来源页面为它补 supports、derives_from、contradicts 等关系。',
          '如果是重复节点，按重复标签流程合并到保留节点。',
          '如果是噪音，从上游 wiki/frontmatter 或导入记录移出后重建图谱。',
        ],
      };
    case 'duplicate_labels':
    case 'duplicate_label_groups':
      return {
        kind: 'manual',
        badge: '需消歧',
        primary: '定位同名节点',
        nextStep: '如果是同一概念，在上游 wiki 页面合并；如果不是，改标题或补 disambiguation。',
        detail: '当前图谱是只读视图，合并必须落回产生节点的页面/记录，否则刷新后会回来。',
        steps: [
          '定位同名节点组，逐个打开右侧详情，对比类型、来源材料、证据片段和相邻关系。',
          '如果它们是同一概念，选一个保留标题/页面，把其他节点的 evidence_refs、source_ref 和关系迁到保留条目。',
          '迁移完成后，在上游 wiki/frontmatter 删除重复条目或改为别名引用，避免重建时再次生成。',
          '如果它们不是同一概念，改成带限定词的标题，或补 disambiguation metadata 说明语境差异。',
          '重建图谱，确认重复标签队列清空，且相关关系仍连到正确节点。',
        ],
      };
    case 'dangling_edges':
      return {
        kind: 'upstream',
        badge: '图谱错误',
        primary: '定位异常关系',
        nextStep: '重建图谱或回查源页面，关系端点已经缺失。',
        detail: '这是生成链路输出了无效边，应在编译/导入阶段修复。',
        steps: [
          '复制异常关系 ID，回查生成它的 wiki/frontmatter 或导入记录。',
          '确认 source/target 指向的节点是否被删除、重命名或没有成功生成。',
          '把关系端点改为现存节点 ID；如果关系已经无效，就从上游记录删除。',
          '重新编译图谱，确认不再出现悬空关系。',
        ],
      };
    case 'relations_missing_evidence':
      return {
        kind: 'upstream',
        badge: '证据缺失',
        primary: '定位缺证据关系',
        nextStep: '给关系来源补 evidence_refs / source_ref；补齐前不要把它当引用证据。',
        detail: '关系本身可以存在，但用于回答或写作前必须能追溯到原文。',
        steps: [
          '定位缺证据关系，查看两端节点分别是什么主张或证据。',
          '回到定义该关系的 wiki/frontmatter 条目，找到 supports、derives_from 或 contradicts 等关系记录。',
          '为关系记录补 source_ref 或 evidence_refs，至少包含 material_id；可用时补 chunk_id、page、text。',
          '刷新图谱，确认关系不再出现在证据缺失队列，再用于回答或写作引用。',
        ],
      };
    case 'low_confidence_relations':
      return {
        kind: 'manual',
        badge: '人工判断',
        primary: '定位低置信关系',
        nextStep: '查看两端节点和证据；确认后删除、降权或保留。',
        detail: '低置信不是必错，它需要人工确认是否进入结论链。',
        steps: [
          '定位低置信关系，查看两端节点和已有证据。',
          '如果证据不足，补 evidence_refs 或把关系标记为待确认。',
          '如果关系方向或类型错误，在上游记录中修正 relation/source/target。',
          '如果确认有效，可保留并补充说明；刷新后确认置信提示符合预期。',
        ],
      };
    case 'source_overlap_relations':
      return {
        kind: 'informational',
        badge: '注意项',
        primary: '定位同源关系',
        nextStep: '确认是否同一材料被重复解释；合理时可保留，不合理时拆分证据。',
        detail: '同源关系是风险提示，不一定是错误。',
        steps: [
          '定位同源关系，查看两端节点是否来自同一材料或同一段证据。',
          '如果是合理的同源推理，保留关系并确保 evidence_refs 指向不同片段或说明同源原因。',
          '如果只是重复解释同一证据，合并节点或拆分为更具体的证据片段。',
          '刷新图谱，确认关系不再造成重复证据链。',
        ],
      };
    default:
      return {
        kind: 'locate',
        badge: '待复审',
        primary: '定位问题对象',
        nextStep: '先定位对象，再根据右侧详情回到来源处理。',
        detail: '该项还没有专门的自动修复入口。',
        steps: [
          '先定位目标对象，确认它是节点问题还是关系问题。',
          '根据右侧详情记录目标 ID、标题、材料和证据信息。',
          '回到来源 wiki/frontmatter 或导入记录修复后刷新图谱。',
        ],
      };
  }
}

function reviewActionTone(kind: ReviewActionKind): string {
  switch (kind) {
    case 'upstream':
      return 'border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-300';
    case 'manual':
      return 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300';
    case 'informational':
      return 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300';
    case 'locate':
    default:
      return 'border-primary/25 bg-primary/10 text-primary';
  }
}

function ReviewActionIcon({ kind }: { kind: ReviewActionKind }) {
  switch (kind) {
    case 'upstream':
      return <Wrench className="h-3 w-3" aria-hidden />;
    case 'manual':
      return <GitMerge className="h-3 w-3" aria-hidden />;
    case 'informational':
      return <Info className="h-3 w-3" aria-hidden />;
    case 'locate':
    default:
      return <FileSearch className="h-3 w-3" aria-hidden />;
  }
}

function reviewBucketTarget(bucket: { id: string; label: string; node_ids: string[] }): ReviewFocusTarget {
  return {
    id: `metadata:${bucket.id}`,
    label: bucket.label,
    nodeIds: bucket.node_ids,
    edgeIds: [],
  };
}

function diagnosticBucketTarget(bucket: {
  id: string;
  label: string;
  subject: 'edge' | 'node' | 'material' | 'label';
  item_ids: string[];
}): ReviewFocusTarget {
  const ids = bucket.item_ids;
  const edgeIds = bucket.subject === 'edge' || bucket.subject === 'material' ? ids : [];
  const nodeIds = bucket.subject === 'node' || bucket.subject === 'label' ? ids : [];
  return {
    id: `diagnostic:${bucket.id}`,
    label: bucket.label,
    nodeIds,
    edgeIds,
  };
}

function reviewTargetSummary(target: ReviewFocusTarget, maxIds = 8): string {
  const parts: string[] = [];
  if (target.nodeIds.length > 0) {
    const shown = target.nodeIds.slice(0, maxIds).join(', ');
    const suffix = target.nodeIds.length > maxIds ? ` +${target.nodeIds.length - maxIds}` : '';
    parts.push(`nodes: ${shown}${suffix}`);
  }
  if (target.edgeIds.length > 0) {
    const shown = target.edgeIds.slice(0, maxIds).join(', ');
    const suffix = target.edgeIds.length > maxIds ? ` +${target.edgeIds.length - maxIds}` : '';
    parts.push(`edges: ${shown}${suffix}`);
  }
  return parts.length > 0 ? parts.join(' | ') : '暂无可定位 ID';
}

function reviewRepairChecklist(item: ReviewQueueItem): string {
  const lines = [
    `复审项: ${item.label} (${item.count})`,
    `动作: ${item.action.badge} - ${item.action.primary}`,
    `目标: ${reviewTargetSummary(item.target, 20)}`,
    `说明: ${item.action.detail}`,
    '步骤:',
    ...item.action.steps.map((step, index) => `${index + 1}. ${step}`),
  ];
  return lines.join('\n');
}

function firstReviewNodeId(target: ReviewFocusTarget, graph: DimensionGraph): string | null {
  const nodeIds = new Set(graph.nodes.map((entry) => entry.node.id));
  for (const nodeId of target.nodeIds) {
    if (nodeIds.has(nodeId)) return nodeId;
  }
  for (const edgeId of target.edgeIds) {
    const edge = graph.edges.find((candidate) => candidate.id === edgeId);
    if (!edge) continue;
    if (nodeIds.has(edge.source)) return edge.source;
    if (nodeIds.has(edge.target)) return edge.target;
  }
  return null;
}

function buildReviewQueueItems(spec: ReviewDashboardSpecV1): ReviewQueueItem[] {
  const reviewBuckets = spec.missing_metadata_buckets.filter((bucket) => bucket.status === 'review_required');
  const diagnosticBuckets = spec.graph_diagnostics.filter((bucket) => bucket.status === 'review_required');
  return [
    ...reviewBuckets.map((bucket) => {
      const action = reviewBucketAction(bucket.id);
      return {
        key: `metadata:${bucket.id}`,
        label: bucket.label,
        count: bucket.count,
        action,
        target: reviewBucketTarget(bucket),
        tone: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
        title: `${action.primary}。${action.nextStep}`,
      };
    }),
    ...diagnosticBuckets.map((bucket) => {
      const action = reviewBucketAction(bucket.id);
      return {
        key: `diagnostic:${bucket.id}`,
        label: bucket.label,
        count: bucket.count,
        action,
        target: diagnosticBucketTarget(bucket),
        tone: diagnosticToneClass(bucket.severity),
        title: `${action.primary}。${action.nextStep}`,
      };
    }),
  ];
}

function SemanticReviewPanel({
  spec,
  compact,
  collapsed,
  selectedDimensions,
  selectedRouteKinds,
  activeReviewFocusId,
  onFocusReviewTarget,
  onClearReviewFocus,
  onFocusDimension,
  onFocusRelation,
}: {
  spec: ReviewDashboardSpecV1;
  compact: boolean;
  collapsed: boolean;
  selectedDimensions: Set<ReasoningDimension>;
  selectedRouteKinds: Set<DimensionRouteKind>;
  activeReviewFocusId: string | null;
  onFocusReviewTarget: (target: ReviewFocusTarget) => void;
  onClearReviewFocus: () => void;
  onFocusDimension: (dimension: ReasoningDimension) => void;
  onFocusRelation: (relation: string) => void;
}) {
  const contentId = useId();
  const [copiedReviewKey, setCopiedReviewKey] = useState<string | null>(null);
  const topDimensions = spec.dimensions
    .filter((bucket) => bucket.node_count > 0)
    .sort((left, right) => right.node_count - left.node_count)
    .slice(0, compact ? 3 : 5);
  const topRelations = spec.relations
    .filter((bucket) => bucket.edge_count > 0)
    .sort((left, right) => right.edge_count - left.edge_count)
    .slice(0, compact ? 3 : 5);
  const allReviewItems = useMemo(() => buildReviewQueueItems(spec), [spec]);
  const hasReviewWork = allReviewItems.length > 0 || spec.large_library_hints.length > 0;
  const reviewItems = allReviewItems.slice(0, compact ? 5 : 8);
  const activeReviewItem = activeReviewFocusId
    ? allReviewItems.find((item) => item.target.id === activeReviewFocusId) ?? null
    : null;
  const stats = [
    { label: '节点', value: spec.summary.node_count },
    { label: '关系', value: spec.summary.edge_count },
    { label: '材料', value: spec.summary.material_count },
    { label: '证据', value: spec.summary.evidence_ref_count },
  ];
  const handleCopyReviewChecklist = useCallback((item: ReviewQueueItem) => {
    const clipboard = navigator.clipboard;
    if (!clipboard) return;
    void clipboard.writeText(reviewRepairChecklist(item)).then(() => {
      setCopiedReviewKey(item.key);
      window.setTimeout(() => setCopiedReviewKey(null), 1500);
    }).catch(() => {
      // 剪贴板权限可能被桌面壳拒绝；定位和步骤仍然可读。
    });
  }, []);

  return (
    <section
      aria-label="语义复审面板"
      className={cn(
        'border-y border-outline-variant/45 bg-transparent px-2.5 py-2 text-[11px] text-foreground/70',
        compact || collapsed ? 'space-y-2' : 'grid gap-2 lg:grid-cols-[minmax(180px,0.8fr)_minmax(220px,1fr)_minmax(220px,1fr)]',
      )}
    >
      <div className="min-w-0 space-y-1.5">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <div className="inline-flex min-w-0 items-center gap-1.5 rounded-sm px-1 py-0.5 text-left">
            <ListChecks className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
            <span className="truncate text-xs font-semibold text-foreground">语义复审</span>
          </div>
          <span
            className={cn(
              'inline-flex shrink-0 items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[10px]',
              hasReviewWork
                ? 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300'
                : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
            )}
          >
            {hasReviewWork ? (
              <AlertTriangle className="h-3 w-3" aria-hidden />
            ) : (
              <CheckCircle2 className="h-3 w-3" aria-hidden />
            )}
            {hasReviewWork ? '需要复审' : '结构正常'}
          </span>
        </div>
        <div id={contentId}>
          {collapsed ? (
            <div className={cn('text-[10px] text-foreground/55', compact ? 'space-y-1.5' : 'flex flex-wrap items-center gap-1.5')}>
              <div className="flex flex-wrap items-center gap-1.5">
                {stats.map((item) => (
                  <span
                    key={item.label}
                    className="rounded-sm border border-outline-variant/40 bg-surface px-1.5 py-0.5"
                  >
                    {item.label} <span className="font-semibold tabular-nums text-foreground/75">{item.value}</span>
                  </span>
                ))}
                <span className="rounded-sm border border-outline-variant/40 bg-surface px-1.5 py-0.5">
                  待处理 <span className="font-semibold tabular-nums text-foreground/75">{reviewItems.length}</span>
                </span>
                {activeReviewItem ? (
                  <span className="max-w-full truncate rounded-sm border border-primary/25 bg-primary/10 px-1.5 py-0.5 text-primary">
                    当前: {activeReviewItem.label}
                  </span>
                ) : null}
              </div>
              {compact ? (
                reviewItems.length > 0 ? (
                  <div className="grid gap-1" aria-label="图谱处理队列">
                    {reviewItems.slice(0, 3).map((item) => {
                      const active = activeReviewFocusId === item.target.id;
                      return (
                        <button
                          key={item.key}
                          type="button"
                          onClick={() => onFocusReviewTarget(item.target)}
                          className={cn(
                            'grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-l-2 px-2 py-1 text-left transition-colors hover:bg-surface-lowest/70',
                            item.tone,
                            active && 'bg-primary/5 ring-1 ring-primary/25',
                          )}
                          title={item.title}
                          aria-pressed={active}
                          aria-label={`定位${item.label}`}
                        >
                          <span className="flex min-w-0 items-center gap-1">
                            <span className="truncate font-medium">{item.label}</span>
                            <span className="shrink-0 tabular-nums">{item.count}</span>
                            <span className={cn('inline-flex shrink-0 items-center gap-0.5 rounded-sm border px-1 py-px text-[9px]', reviewActionTone(item.action.kind))}>
                              <ReviewActionIcon kind={item.action.kind} />
                              {item.action.badge}
                            </span>
                          </span>
                          <span className="inline-flex shrink-0 items-center gap-1 rounded-sm border border-current/20 bg-surface/60 px-1.5 py-0.5 text-[10px]">
                            <Crosshair className="h-3 w-3" aria-hidden />
                            定位
                          </span>
                        </button>
                      );
                    })}
                    {reviewItems.length > 3 ? (
                      <div className="px-2 text-[10px] text-foreground/40">
                        另有 {reviewItems.length - 3} 项，展开图谱后处理。
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="border-l-2 border-emerald-500/45 px-2 py-1 text-emerald-700 dark:text-emerald-300">
                    暂无需要处理的图谱复审项。
                  </div>
                )
              ) : null}
            </div>
          ) : (
            <>
              {activeReviewFocusId ? (
                <button
                  type="button"
                  onClick={onClearReviewFocus}
                  className="inline-flex max-w-full items-center gap-1 rounded-sm border border-primary/35 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary transition-colors hover:bg-primary/15"
                  title="清除复审聚焦"
                >
                  <X className="h-3 w-3" aria-hidden />
                  <span className="truncate">清除复审聚焦</span>
                </button>
              ) : null}
              <div className="grid grid-cols-4 gap-1">
                {stats.map((item) => (
                  <div
                    key={item.label}
                    className="min-w-0 border-l border-outline-variant/45 px-1.5 py-1"
                  >
                    <div className="truncate text-[10px] text-foreground/45">{item.label}</div>
                    <div className="truncate font-semibold tabular-nums text-foreground">{item.value}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {!collapsed ? (
      <div className="min-w-0 space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-foreground/45">处理队列</div>
          {reviewItems.length > 0 ? (
            <span className="text-[10px] text-foreground/40">{reviewItems.length} 项</span>
          ) : null}
        </div>
        {reviewItems.length > 0 ? (
          <div className="grid gap-1" aria-label="图谱结构诊断">
            {reviewItems.map((item) => {
              const active = activeReviewFocusId === item.target.id;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => onFocusReviewTarget(item.target)}
                  className={cn(
                    'grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 border-l-2 px-2 py-1.5 text-left transition-colors hover:bg-surface-lowest/70',
                    item.tone,
                    active && 'bg-primary/5 ring-1 ring-primary/25',
                  )}
                  title={item.title}
                  aria-pressed={active}
                  aria-label={`定位${item.label}`}
                >
                  <span className="min-w-0 space-y-0.5">
                    <span className="flex min-w-0 items-center gap-1">
                      <span className="truncate font-medium">{item.label}</span>
                      <span className="shrink-0 tabular-nums">{item.count}</span>
                      <span className={cn('inline-flex shrink-0 items-center gap-0.5 rounded-sm border px-1 py-px text-[9px]', reviewActionTone(item.action.kind))}>
                        <ReviewActionIcon kind={item.action.kind} />
                        {item.action.badge}
                      </span>
                    </span>
                    <span className="block text-[10px] font-medium opacity-80">{item.action.primary}</span>
                    <span className="block line-clamp-2 text-[10px] leading-snug opacity-70">{item.action.nextStep}</span>
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-sm border border-current/20 bg-surface/60 px-1.5 py-0.5 text-[10px]">
                    <Crosshair className="h-3 w-3" aria-hidden />
                    定位
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="rounded-sm border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-700 dark:text-emerald-300">
            暂无缺失元数据、孤立节点、悬空关系或重复标签。
          </div>
        )}
        {activeReviewItem ? (
          <div
            className={cn(
              'rounded-sm border px-2 py-1.5 text-[10px] leading-snug',
              'border-y-0 border-r-0 border-l-2 bg-transparent',
              reviewActionTone(activeReviewItem.action.kind),
            )}
            aria-label="当前复审动作"
          >
            <div className="flex items-center gap-1 font-semibold">
              <ReviewActionIcon kind={activeReviewItem.action.kind} />
              <span>{activeReviewItem.action.badge}</span>
              <span>·</span>
              <span>{activeReviewItem.action.primary}</span>
            </div>
            <div className="mt-0.5 text-foreground/70">{activeReviewItem.action.detail}</div>
            <div className="mt-1 rounded-sm border border-current/15 bg-surface/60 px-1.5 py-1 font-mono text-[9px] text-foreground/55">
              {reviewTargetSummary(activeReviewItem.target)}
            </div>
            <div className="mt-1.5">
              <div className="font-semibold text-foreground/75">修复步骤</div>
              <ol className="mt-0.5 list-decimal space-y-0.5 pl-4 text-foreground/70">
                {activeReviewItem.action.steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            </div>
            <button
              type="button"
              onClick={() => handleCopyReviewChecklist(activeReviewItem)}
              className="mt-1.5 inline-flex items-center gap-1 rounded-sm border border-current/25 bg-surface/70 px-1.5 py-0.5 text-[10px] transition-colors hover:bg-surface"
              aria-label={`复制${activeReviewItem.label}修复清单`}
            >
              <Copy className="h-3 w-3" aria-hidden />
              {copiedReviewKey === activeReviewItem.key ? '已复制' : '复制清单'}
            </button>
          </div>
        ) : null}
        {spec.large_library_hints.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {spec.large_library_hints.slice(0, compact ? 2 : 3).map((hint) => (
              <span
                key={hint.kind}
                className="inline-flex max-w-full items-center gap-1 rounded-sm border border-outline-variant/50 bg-surface px-1.5 py-0.5 text-foreground/60"
                title={hint.message}
              >
                <span className="truncate">{hint.message}</span>
                <span className="shrink-0 tabular-nums">{hint.count}</span>
              </span>
            ))}
          </div>
        ) : null}
      </div>
      ) : null}

      {!collapsed ? (
      <div className="min-w-0 space-y-1.5">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-foreground/45">维度 / 关系</div>
        <div className="flex flex-wrap gap-1">
          {topDimensions.map((bucket) => (
            <button
              key={bucket.dimension}
              type="button"
              onClick={() => onFocusDimension(bucket.dimension)}
              className="inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5"
              style={{
                borderColor: DIMENSION_META[bucket.dimension].border,
                background: DIMENSION_META[bucket.dimension].surface,
                color: DIMENSION_META[bucket.dimension].accent,
              }}
              aria-pressed={selectedDimensions.has(bucket.dimension)}
              title={`缺少锚点 ${bucket.missing_anchor_count} · 证据 refs ${bucket.evidence_ref_count}`}
            >
              <span>{bucket.label}</span>
              <span className="tabular-nums">{bucket.node_count}</span>
            </button>
          ))}
          {topRelations.map((bucket) => (
            <button
              key={bucket.relation}
              type="button"
              onClick={() => onFocusRelation(bucket.relation)}
              className="inline-flex max-w-full items-center gap-1 rounded-sm border border-outline-variant/50 bg-surface px-1.5 py-0.5 text-foreground/60"
              aria-pressed={selectedRouteKinds.has(resolveRouteKind(bucket.relation))}
              title={`证据 refs ${bucket.evidence_ref_count} · 低置信 ${bucket.low_confidence_count}`}
            >
              <span className="truncate">{bucket.relation}</span>
              <span className="shrink-0 tabular-nums">{bucket.edge_count}</span>
            </button>
          ))}
          {topDimensions.length === 0 && topRelations.length === 0 ? (
            <span className="rounded-sm border border-outline-variant/40 bg-surface px-1.5 py-0.5 text-foreground/45">
              暂无可汇总维度或关系。
            </span>
          ) : null}
        </div>
      </div>
      ) : null}
    </section>
  );
}

function ReviewQueuePanel({
  items,
  activeReviewFocusId,
  onFocusReviewTarget,
  onClearReviewFocus,
  compact = false,
}: {
  items: ReviewQueueItem[];
  activeReviewFocusId: string | null;
  onFocusReviewTarget: (target: ReviewFocusTarget) => void;
  onClearReviewFocus: () => void;
  compact?: boolean;
}) {
  if (items.length === 0) {
    return (
      <section
        aria-label="图谱处理队列"
        className="border-l-2 border-emerald-500/45 px-2 py-1.5 text-xs text-emerald-700 dark:text-emerald-300"
      >
        <div className="flex items-center gap-1 font-semibold">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
          图谱处理队列
        </div>
        <div className="mt-1 text-[11px]">暂无需要处理的图谱复审项。</div>
      </section>
    );
  }

  const activeItem = activeReviewFocusId
    ? items.find((item) => item.target.id === activeReviewFocusId) ?? null
    : null;

  return (
    <section aria-label="图谱处理队列" className={cn('px-1 text-xs', compact ? 'space-y-1.5' : 'space-y-2')}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1 font-semibold text-foreground">
            <ListChecks className="h-3.5 w-3.5 text-primary" aria-hidden />
            图谱处理队列
          </div>
          <div className={cn('mt-0.5 text-[11px] text-foreground/55', compact && 'sr-only')}>
            先选问题，再在下方合并、消歧或补证据。
          </div>
        </div>
        <span className="shrink-0 rounded-sm border border-outline-variant/50 px-1.5 py-0.5 text-[10px] text-foreground/50">
          {items.length} 项
        </span>
      </div>

      {activeItem && !compact ? (
        <button
          type="button"
          onClick={onClearReviewFocus}
          className="inline-flex max-w-full items-center gap-1 rounded-sm border border-primary/35 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary transition-colors hover:bg-primary/15"
          title="清除当前复审聚焦"
        >
          <X className="h-3 w-3" aria-hidden />
          <span className="truncate">清除聚焦: {activeItem.label}</span>
        </button>
      ) : null}

      <div className={cn('grid', compact ? 'gap-0.5' : 'gap-1')} aria-label="图谱结构诊断">
        {items.map((item) => {
          const active = activeReviewFocusId === item.target.id;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => onFocusReviewTarget(item.target)}
              className={cn(
                'grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 border-l-2 text-left transition-colors hover:bg-surface-lowest/70',
                compact ? 'px-2 py-1' : 'px-2 py-1.5',
                item.tone,
                active && 'bg-primary/5 ring-1 ring-primary/25',
              )}
              title={item.title}
              aria-pressed={active}
              aria-label={`定位${item.label}`}
            >
              <span className="min-w-0 space-y-0.5">
                <span className="flex min-w-0 items-center gap-1">
                  <span className="truncate font-medium">{item.label}</span>
                  <span className="shrink-0 tabular-nums">{item.count}</span>
                  <span className={cn('inline-flex shrink-0 items-center gap-0.5 rounded-sm border px-1 py-px text-[9px]', reviewActionTone(item.action.kind))}>
                    <ReviewActionIcon kind={item.action.kind} />
                    {item.action.badge}
                  </span>
                </span>
                <span className={cn('block break-words text-[10px] font-medium leading-snug opacity-80', compact && 'sr-only')}>
                  {item.action.primary}
                </span>
                <span className={cn('block break-words text-[10px] leading-snug opacity-70', compact && 'sr-only')}>
                  {item.action.nextStep}
                </span>
              </span>
              <span className="inline-flex shrink-0 items-center gap-1 rounded-sm border border-current/20 bg-surface/60 px-1.5 py-0.5 text-[10px]">
                <Crosshair className="h-3 w-3" aria-hidden />
                定位
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function metadataRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function metadataString(value: unknown, key: string): string | null {
  const raw = metadataRecord(value)[key];
  return typeof raw === 'string' && raw.trim() ? raw.trim() : null;
}

function nodePagePath(entry: DimensionGraphNode): string | null {
  return metadataString(entry.node.metadata, 'page_path');
}

function compactMiddle(value: string, maxLength = 42): string {
  const text = value.trim();
  if (text.length <= maxLength) return text;
  const side = Math.max(6, Math.floor((maxLength - 1) / 2));
  return `${text.slice(0, side)}…${text.slice(-side)}`;
}

function shortNodeToken(nodeId: string): string {
  return compactMiddle(nodeId, 24);
}

function edgeSourcePath(edge: GraphEdge): string | null {
  return metadataString(edge.metadata, 'source_path');
}

function edgeFrontmatterField(edge: GraphEdge): string | null {
  return metadataString(edge.metadata, 'frontmatter_field');
}

function edgeTargetPath(edge: GraphEdge): string | null {
  return metadataString(edge.metadata, 'target_path') ?? metadataString(edge, 'target_path');
}

function edgeInputForReview(edge: GraphEdge | null): WikiGraphReviewEdgeInputModel | null {
  if (!edge) return null;
  const sourcePath = edgeSourcePath(edge);
  if (!sourcePath) return null;
  return {
    edge_id: edge.id,
    source: edge.source,
    target: edge.target,
    relation: edge.relation,
    source_path: sourcePath,
    target_path: edgeTargetPath(edge),
    frontmatter_field: edgeFrontmatterField(edge),
  };
}

function targetNodesForReview(item: ReviewQueueItem, graph: DimensionGraph): DimensionGraphNode[] {
  const nodeIds = new Set(item.target.nodeIds);
  for (const edge of graph.edges) {
    if (!item.target.edgeIds.includes(edge.id)) continue;
    nodeIds.add(edge.source);
    nodeIds.add(edge.target);
  }
  return graph.nodes.filter((entry) => nodeIds.has(entry.node.id));
}

function targetEdgesForReview(item: ReviewQueueItem, graph: DimensionGraph): GraphEdge[] {
  const edgeIds = new Set(item.target.edgeIds);
  return graph.edges.filter((edge) => edgeIds.has(edge.id));
}

function defaultReviewConsoleMode(item: ReviewQueueItem): ReviewConsoleMode {
  if (item.key.includes('duplicate')) return 'merge';
  if (item.key.includes('missing_evidence_refs') || item.key.includes('missing_source_anchor')) return 'node_evidence';
  if (item.key.includes('relations_missing_evidence') || item.key.includes('low_confidence') || item.key.includes('source_overlap')) return 'relation_evidence';
  if (item.key.includes('missing_dimension')) return 'dimension';
  if (item.key.includes('orphan') || item.key.includes('dangling')) return 'relationship';
  return 'inspect';
}

function reviewConsoleModeOptions(item: ReviewQueueItem): ReviewConsoleModeOption[] {
  if (item.key.includes('duplicate')) {
    return [];
  }
  if (item.key.includes('missing_evidence_refs') || item.key.includes('missing_source_anchor')) {
    return [
      { mode: 'node_evidence', label: '补节点证据', title: '给节点补 source_ref / evidence_refs' },
      { mode: 'dimension', label: '补维度', title: '同时补 reasoning_dimension 或 analysis_chain_field' },
    ];
  }
  if (item.key.includes('relations_missing_evidence') || item.key.includes('low_confidence') || item.key.includes('source_overlap')) {
    return [
      { mode: 'relation_evidence', label: '补关系证据', title: '给关系补 source_ref / evidence_refs' },
      { mode: 'relationship', label: '改关系', title: '修正 relation/source/target 或新增关系' },
    ];
  }
  if (item.key.includes('missing_dimension')) {
    return [
      { mode: 'dimension', label: '补维度', title: '给节点补语义维度' },
      { mode: 'disambiguate', label: '补说明', title: '用 disambiguation 说明语境' },
    ];
  }
  if (item.key.includes('orphan') || item.key.includes('dangling')) {
    return [
      { mode: 'relationship', label: '补关系', title: '给孤立节点补关系或修复悬空端点' },
      { mode: 'merge', label: '并入节点', title: '把孤立重复节点并入保留节点' },
    ];
  }
  return [{ mode: 'inspect', label: '检查', title: '只生成目标对象清单' }];
}

function compactNodeLabel(entry: DimensionGraphNode): string {
  const pagePath = nodePagePath(entry);
  return pagePath ? `${entry.display.title} · ${compactMiddle(pagePath, 42)}` : entry.display.title;
}

function compactNodeSelectLabel(entry: DimensionGraphNode): string {
  const context = nodeContextSummary(entry);
  return context ? `${compactMiddle(entry.display.title, 34)} · ${context}` : compactMiddle(entry.display.title, 54);
}

function isDuplicateReviewItem(item: ReviewQueueItem | null): boolean {
  return item ? item.key.includes('duplicate') : false;
}

function nodeContextSummary(entry: DimensionGraphNode): string {
  const target = resolveMaterialTarget(entry.node);
  const pieces = uniqueText([
    nodePagePath(entry) ? compactMiddle(nodePagePath(entry) ?? '', 46) : null,
    entry.display.sourceLabel ? compactMiddle(entry.display.sourceLabel, 36) : null,
    target?.material_id ? `mat ${compactMiddle(target.material_id, 20)}` : null,
    target?.chunk_id ? `chunk ${compactMiddle(target.chunk_id, 24)}` : null,
    target?.page ? `p.${target.page}` : null,
  ]);
  return pieces.join(' · ');
}

function defaultDisambiguationLabel(entry: DimensionGraphNode): string {
  const target = resolveMaterialTarget(entry.node);
  const context = entry.display.sourceLabel
    ?? (target?.material_id ? `材料 ${compactMiddle(target.material_id, 16)}` : null)
    ?? (target?.chunk_id ? `chunk ${compactMiddle(target.chunk_id, 18)}` : null)
    ?? (nodePagePath(entry) ? compactMiddle(nodePagePath(entry) ?? '', 24) : null)
    ?? shortNodeToken(entry.node.id);
  return `${compactMiddle(entry.display.title, 24)}（${context}）`;
}

function buildDuplicateDrafts(entries: DimensionGraphNode[]): Record<string, DuplicateDisambiguationDraft> {
  const drafts: Record<string, DuplicateDisambiguationDraft> = {};
  for (const entry of entries) {
    drafts[entry.node.id] = {
      label: '',
      disambiguation: '',
    };
  }
  return drafts;
}

function reviewWritebackBlockReason(writeTargets: string[]): string {
  if (writeTargets.length === 0) {
    return '缺少可写的 wiki_page_paths，无法确认应该修改哪个上游页面。';
  }
  return '当前操作还不能自动写回；请使用已支持的合并或消歧保存。';
}

function compactEdgeLabel(edge: GraphEdge): string {
  const sourcePath = edgeSourcePath(edge);
  const suffix = sourcePath ? ` · ${compactMiddle(sourcePath, 34)}` : '';
  return `${compactMiddle(edge.source, 18)} -> ${compactMiddle(edge.target, 18)} · ${edge.relation}${suffix}`;
}

function evidencePatchFromForm({
  materialId,
  chunkId,
  page,
  evidenceText,
}: {
  materialId: string;
  chunkId: string;
  page: string;
  evidenceText: string;
}): Record<string, unknown> {
  const pageNumber = Number(page);
  const patch: Record<string, unknown> = {
    material_id: materialId.trim() || '<material_id>',
  };
  if (chunkId.trim()) patch.chunk_id = chunkId.trim();
  if (Number.isInteger(pageNumber) && pageNumber > 0) patch.page = pageNumber;
  else if (page.trim()) patch.page = page.trim();
  if (evidenceText.trim()) patch.text = evidenceText.trim();
  else patch.text = '<evidence text>';
  return patch;
}

function evidenceRefFromForm({
  materialId,
  chunkId,
  page,
  evidenceText,
}: {
  materialId: string;
  chunkId: string;
  page: string;
  evidenceText: string;
}): Record<string, unknown> | null {
  const normalizedMaterialId = materialId.trim();
  const normalizedChunkId = chunkId.trim();
  const normalizedText = evidenceText.trim();
  if (!normalizedMaterialId && !normalizedChunkId && !normalizedText) {
    return null;
  }
  const pageNumber = Number(page);
  const ref: Record<string, unknown> = {};
  if (normalizedMaterialId) ref.material_id = normalizedMaterialId;
  if (normalizedChunkId) ref.chunk_id = normalizedChunkId;
  if (Number.isInteger(pageNumber) && pageNumber > 0) ref.page = pageNumber;
  else if (page.trim()) ref.page = page.trim();
  if (normalizedText) ref.text = normalizedText;
  return ref;
}

function evidenceDraftFromNode(entry: DimensionGraphNode, token: number): ReviewEvidenceDraft | null {
  const target = resolveMaterialTarget(entry.node);
  const evidenceText = readNodeEvidenceText(entry.node) ?? entry.display.previewText ?? '';
  if (!target && !evidenceText.trim()) {
    return null;
  }
  return {
    token,
    materialId: target?.material_id ?? '',
    chunkId: target?.chunk_id ?? '',
    page: typeof target?.page === 'number' ? String(target.page) : '',
    evidenceText,
    sourceNodeId: entry.node.id,
    sourceTitle: entry.display.title,
  };
}

function uniqueText(values: Array<string | null>): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value))));
}

async function copyTextToClipboard(text: string): Promise<boolean> {
  const writeText = navigator.clipboard?.writeText;
  if (writeText) {
    try {
      await writeText.call(navigator.clipboard, text);
      return true;
    } catch {
      // pywebview shells may reject navigator.clipboard even after a user click.
    }
  }

  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand('copy');
    document.body.removeChild(textarea);
    return copied;
  } catch {
    return false;
  }
}

function ReviewOperationConsole({
  items,
  activeItem,
  graph,
  evidenceDraft,
  onFocusReviewTarget,
  onSelectNodeId,
  onReviewApplied,
}: {
  items: ReviewQueueItem[];
  activeItem: ReviewQueueItem | null;
  graph: DimensionGraph;
  evidenceDraft: ReviewEvidenceDraft | null;
  onFocusReviewTarget: (target: ReviewFocusTarget) => void;
  onSelectNodeId: (nodeId: string) => void;
  onReviewApplied?: () => Promise<void> | void;
}) {
  const [mode, setMode] = useState<ReviewConsoleMode>('inspect');
  const [canonicalNodeId, setCanonicalNodeId] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [selectedEdgeId, setSelectedEdgeId] = useState('');
  const [mergeNodeIds, setMergeNodeIds] = useState<Set<string>>(new Set());
  const [materialId, setMaterialId] = useState('');
  const [chunkId, setChunkId] = useState('');
  const [page, setPage] = useState('');
  const [evidenceText, setEvidenceText] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [disambiguation, setDisambiguation] = useState('');
  const [duplicateDrafts, setDuplicateDrafts] = useState<Record<string, DuplicateDisambiguationDraft>>({});
  const [expandedDuplicateId, setExpandedDuplicateId] = useState<string | null>(null);
  const [relation, setRelation] = useState('supports');
  const [dimension, setDimension] = useState<ReasoningDimension>('observation');
  const [copyState, setCopyState] = useState<'idle' | 'done' | 'failed'>('idle');
  const [applyState, setApplyState] = useState<ReviewApplyState>('idle');
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const [lastApplyReceipt, setLastApplyReceipt] = useState<WikiGraphReviewApplyModel | null>(null);

  const targetNodes = useMemo(
    () => (activeItem ? targetNodesForReview(activeItem, graph) : []),
    [activeItem, graph],
  );
  const targetEdges = useMemo(
    () => (activeItem ? targetEdgesForReview(activeItem, graph) : []),
    [activeItem, graph],
  );
  const targetNodeIds = useMemo(() => targetNodes.map((entry) => entry.node.id), [targetNodes]);
  const targetEdgeIds = useMemo(() => targetEdges.map((edge) => edge.id), [targetEdges]);
  const allNodeOptions = useMemo(() => graph.nodes.map((entry) => ({
    id: entry.node.id,
    label: compactNodeLabel(entry),
  })), [graph.nodes]);

  useEffect(() => {
    if (!activeItem) {
      setMode('inspect');
      return;
    }
    const nextMode = defaultReviewConsoleMode(activeItem);
    const firstNodeId = targetNodeIds[0] ?? '';
    const firstDifferentNodeId = graph.nodes.find((entry) => entry.node.id !== firstNodeId)?.node.id ?? firstNodeId;
    const firstEdgeId = targetEdgeIds[0] ?? '';
    setMode(nextMode);
    setCanonicalNodeId(nextMode === 'relationship' ? firstDifferentNodeId : firstNodeId);
    setSelectedNodeId(firstNodeId);
    setSelectedEdgeId(firstEdgeId);
    setMergeNodeIds(new Set(targetNodeIds.filter((nodeId) => nodeId !== firstNodeId)));
    setMaterialId('');
    setChunkId('');
    setPage('');
    setEvidenceText('');
    setNewLabel('');
    setDisambiguation('');
    setDuplicateDrafts(buildDuplicateDrafts(targetNodes));
    setExpandedDuplicateId(targetNodeIds[1] ?? targetNodeIds[0] ?? null);
    setRelation('supports');
    setDimension('observation');
    setCopyState('idle');
    setApplyState('idle');
    setApplyMessage(null);
    setLastApplyReceipt(null);
  }, [activeItem, graph.nodes, targetEdgeIds, targetNodeIds, targetNodes]);

  useEffect(() => {
    if (!evidenceDraft || !activeItem) return;
    const activeMode = defaultReviewConsoleMode(activeItem);
    if (activeMode !== 'node_evidence' && activeMode !== 'relation_evidence') return;
    setMaterialId(evidenceDraft.materialId);
    setChunkId(evidenceDraft.chunkId);
    setPage(evidenceDraft.page);
    setEvidenceText(evidenceDraft.evidenceText);
    if (activeMode === 'node_evidence') {
      setMode('node_evidence');
    } else {
      setMode('relation_evidence');
    }
  }, [activeItem, evidenceDraft]);

  const modeOptions = activeItem ? reviewConsoleModeOptions(activeItem) : [];
  const duplicateReview = isDuplicateReviewItem(activeItem);
  const selectedEdge = targetEdges.find((edge) => edge.id === selectedEdgeId) ?? targetEdges[0] ?? null;
  const selectedEdgeInput = useMemo(() => edgeInputForReview(selectedEdge), [selectedEdge]);
  const writeTargets = useMemo(() => {
    if (!activeItem) return [];
    return uniqueText([
      ...targetNodes.map(nodePagePath),
      ...targetEdges.map(edgeSourcePath),
    ]);
  }, [activeItem, targetEdges, targetNodes]);
  const frontmatterFields = useMemo(() => uniqueText(targetEdges.map(edgeFrontmatterField)), [targetEdges]);
  const targetNodeById = useMemo(
    () => new Map(targetNodes.map((entry) => [entry.node.id, entry])),
    [targetNodes],
  );
  const targetNodeInput = useCallback((entry: DimensionGraphNode): WikiGraphReviewNodeInputModel | null => {
    const pagePath = nodePagePath(entry);
    if (!pagePath) return null;
    return {
      node_id: entry.node.id,
      page_path: pagePath,
    };
  }, []);
  const selectedNodeInput = useMemo(() => {
    const entry = targetNodeById.get(selectedNodeId);
    return entry ? targetNodeInput(entry) : null;
  }, [selectedNodeId, targetNodeById, targetNodeInput]);
  const evidenceRefForApply = useMemo(
    () => evidenceRefFromForm({ materialId, chunkId, page, evidenceText }),
    [chunkId, evidenceText, materialId, page],
  );
  const nodeInputsForIds = useCallback((nodeIds: string[]): WikiGraphReviewNodeInputModel[] => {
    const inputs: WikiGraphReviewNodeInputModel[] = [];
    for (const nodeId of nodeIds) {
      const entry = targetNodeById.get(nodeId);
      if (!entry) continue;
      const input = targetNodeInput(entry);
      if (input) inputs.push(input);
    }
    return inputs;
  }, [targetNodeById, targetNodeInput]);
  const selectedMergeNodeIds = useMemo(
    () => Array.from(mergeNodeIds).filter((nodeId) => nodeId !== canonicalNodeId),
    [canonicalNodeId, mergeNodeIds],
  );
  const mergeNodeIdsForApply = useMemo(
    () => (canonicalNodeId ? [canonicalNodeId, ...selectedMergeNodeIds] : [...selectedMergeNodeIds]),
    [canonicalNodeId, selectedMergeNodeIds],
  );
  const mergeApplyNodes = useMemo(
    () => nodeInputsForIds(mergeNodeIdsForApply),
    [mergeNodeIdsForApply, nodeInputsForIds],
  );
  const missingMergeTargets = useMemo(
    () => mergeNodeIdsForApply
      .filter((nodeId) => {
        const entry = targetNodeById.get(nodeId);
        return !entry || !nodePagePath(entry);
      }),
    [mergeNodeIdsForApply, targetNodeById],
  );
  const changedDisambiguationNodes = useMemo(() => {
    const inputs: WikiGraphReviewNodeInputModel[] = [];
    for (const entry of targetNodes) {
      const draft = duplicateDrafts[entry.node.id] ?? { label: '', disambiguation: '' };
      const label = draft.label.trim();
      const disambiguationText = draft.disambiguation.trim();
      if (!label && !disambiguationText) continue;
      const input = targetNodeInput(entry);
      if (!input) continue;
      inputs.push({
        ...input,
        ...(label ? { label } : {}),
        ...(disambiguationText ? { disambiguation: disambiguationText } : {}),
      });
    }
    return inputs;
  }, [duplicateDrafts, targetNodeInput, targetNodes]);
  const missingDisambiguationTargets = useMemo(
    () => targetNodes
      .filter((entry) => {
        const draft = duplicateDrafts[entry.node.id] ?? { label: '', disambiguation: '' };
        return Boolean(draft.label.trim() || draft.disambiguation.trim()) && !nodePagePath(entry);
      })
      .map((entry) => entry.node.id),
    [duplicateDrafts, targetNodes],
  );
  const canRunApply = applyState !== 'applying' && applyState !== 'undoing';
  const canApplyMerge = duplicateReview
    && canRunApply
    && Boolean(canonicalNodeId)
    && selectedMergeNodeIds.length > 0
    && mergeApplyNodes.length === selectedMergeNodeIds.length + 1
    && missingMergeTargets.length === 0;
  const canApplyDisambiguation = duplicateReview
    && canRunApply
    && changedDisambiguationNodes.length > 0
    && missingDisambiguationTargets.length === 0;
  const canApplyNodeEvidence = mode === 'node_evidence'
    && canRunApply
    && selectedNodeInput !== null
    && evidenceRefForApply !== null;
  const canApplyRelationEvidence = mode === 'relation_evidence'
    && canRunApply
    && selectedEdgeInput !== null
    && evidenceRefForApply !== null;
  const missingWriteTargetCount = new Set([...missingMergeTargets, ...missingDisambiguationTargets]).size;
  const writebackReady = writeTargets.length > 0;
  const duplicateWritebackBlocked = duplicateReview && !writebackReady;
  const evidenceWritebackBlocked = (mode === 'node_evidence' && selectedNodeInput === null)
    || (mode === 'relation_evidence' && selectedEdgeInput === null);
  const currentContextReadOnly = !writebackReady
    || duplicateWritebackBlocked
    || evidenceWritebackBlocked
    || missingWriteTargetCount > 0;
  const applyBlockReason = missingWriteTargetCount > 0
    ? `缺少 ${missingWriteTargetCount} 个可写页面。当前上下文图谱不能直接改源数据；请在 Wiki 图谱中处理，或先沉淀为 Wiki 页面。`
    : !writebackReady
      ? reviewWritebackBlockReason(writeTargets)
      : selectedMergeNodeIds.length === 0 && changedDisambiguationNodes.length === 0
        ? '选择并入节点，或填写至少一条消歧标题/说明。'
        : null;
  const evidenceApplyBlockReason = evidenceRefForApply === null
    ? '先填写 material_id、chunk_id 或证据摘录。'
    : mode === 'node_evidence' && selectedNodeInput === null
      ? '当前节点缺少可写 Wiki 页面，不能自动补证据。'
      : mode === 'relation_evidence' && selectedEdgeInput === null
        ? '当前关系缺少 source_path，不能自动写回关系证据。'
        : null;

  const operationPatch = useMemo(() => {
    if (!activeItem) return '';
    const evidenceRef = evidencePatchFromForm({ materialId, chunkId, page, evidenceText });
    const base: Record<string, unknown> = {
      schema_version: 'scholar-ai-review-operation/v1',
      review_item: {
        key: activeItem.key,
        label: activeItem.label,
        count: activeItem.count,
      },
      target: {
        node_ids: targetNodeIds,
        edge_ids: targetEdgeIds,
        wiki_page_paths: writeTargets,
        frontmatter_fields: frontmatterFields,
      },
      apply_in: 'wiki frontmatter / source import record',
      refresh_after_apply: true,
    };

    if (duplicateReview) {
      base.operation = {
        kind: 'resolve_duplicate_label_group',
        merge_plan: {
          keep_node_id: canonicalNodeId || '<keep_node_id>',
          merge_node_ids: Array.from(mergeNodeIds),
          migrate: ['evidence_refs', 'source_ref', 'relations'],
          remove_or_alias_merged_entries: true,
        },
        disambiguation_plan: {
          nodes: targetNodes.map((entry) => {
            const draft = duplicateDrafts[entry.node.id] ?? { label: '', disambiguation: '' };
            return {
              node_id: entry.node.id,
              current_label: entry.display.title,
              new_label: draft.label.trim() || defaultDisambiguationLabel(entry),
              disambiguation: draft.disambiguation.trim() || '<why this duplicate label is distinct>',
              wiki_page_path: nodePagePath(entry) ?? undefined,
              evidence_preview: entry.display.previewText ?? undefined,
            };
          }),
        },
        user_decision: 'choose merge_plan when nodes are the same concept, or disambiguation_plan when labels collide but concepts differ',
      };
    } else if (mode === 'merge') {
      base.operation = {
        kind: 'merge_duplicate_nodes',
        keep_node_id: canonicalNodeId || '<keep_node_id>',
        merge_node_ids: Array.from(mergeNodeIds),
        migrate: ['evidence_refs', 'source_ref', 'relations'],
        remove_or_alias_merged_entries: true,
      };
    } else if (mode === 'disambiguate') {
      base.operation = {
        kind: 'disambiguate_node',
        node_id: selectedNodeId || '<node_id>',
        label: newLabel.trim() || '<new distinct label>',
        disambiguation: disambiguation.trim() || '<why this node is distinct>',
      };
    } else if (mode === 'node_evidence') {
      base.operation = {
        kind: 'add_node_evidence',
        node_id: selectedNodeId || '<node_id>',
        evidence_refs: [evidenceRef],
        source_ref: evidenceRef,
      };
    } else if (mode === 'relation_evidence') {
      base.operation = {
        kind: 'add_relation_evidence',
        edge_id: selectedEdgeId || '<edge_id>',
        source: selectedEdge?.source ?? '<source_node_id>',
        target: selectedEdge?.target ?? '<target_node_id>',
        relation: selectedEdge?.relation ?? '<relation>',
        evidence_refs: [evidenceRef],
        source_ref: evidenceRef,
      };
    } else if (mode === 'dimension') {
      base.operation = {
        kind: 'set_node_dimension',
        node_id: selectedNodeId || '<node_id>',
        reasoning_dimension: dimension,
        analysis_chain_field: dimension,
      };
    } else if (mode === 'relationship') {
      base.operation = {
        kind: 'upsert_relation',
        source: selectedNodeId || '<source_node_id>',
        target: canonicalNodeId || '<target_node_id>',
        relation,
        evidence_refs: materialId.trim() || evidenceText.trim() ? [evidenceRef] : [],
      };
    } else {
      base.operation = {
        kind: 'inspect_targets',
      };
    }
    return JSON.stringify(base, null, 2);
  }, [
    activeItem,
    canonicalNodeId,
    chunkId,
    dimension,
    duplicateDrafts,
    duplicateReview,
    evidenceText,
    frontmatterFields,
    materialId,
    mergeNodeIds,
    mode,
    newLabel,
    page,
    relation,
    selectedEdge,
    selectedEdgeId,
    selectedNodeId,
    targetEdgeIds,
    targetNodeIds,
    targetNodes,
    writeTargets,
    disambiguation,
  ]);

  const handleCopyPatch = useCallback(() => {
    if (!operationPatch) return;
    void copyTextToClipboard(operationPatch).then((copied) => {
      setCopyState(copied ? 'done' : 'failed');
      window.setTimeout(() => setCopyState('idle'), 3500);
    });
  }, [operationPatch]);
  const handleApplyMerge = useCallback(async () => {
    if (!activeItem || !canApplyMerge) return;
    setApplyState('applying');
    setApplyMessage('正在合并选中节点...');
    try {
      const receipt = await applyWikiGraphReview({
        operation_kind: 'merge_duplicate_nodes',
        review_item_key: activeItem.key,
        keep_node_id: canonicalNodeId,
        merge_node_ids: selectedMergeNodeIds,
        nodes: mergeApplyNodes,
        decided_by: 'graph_console',
      });
      setLastApplyReceipt(receipt);
      setApplyState('applied');
      setApplyMessage(receipt.message || '已合并选中节点。');
      await onReviewApplied?.();
    } catch (err: unknown) {
      setApplyState('failed');
      setApplyMessage(err instanceof Error ? err.message : '合并失败。');
    }
  }, [
    activeItem,
    canApplyMerge,
    canonicalNodeId,
    mergeApplyNodes,
    onReviewApplied,
    selectedMergeNodeIds,
  ]);
  const handleApplyDisambiguation = useCallback(async () => {
    if (!activeItem || !canApplyDisambiguation) return;
    setApplyState('applying');
    setApplyMessage('正在保存消歧...');
    try {
      const receipt = await applyWikiGraphReview({
        operation_kind: 'disambiguate_nodes',
        review_item_key: activeItem.key,
        nodes: changedDisambiguationNodes,
        decided_by: 'graph_console',
      });
      setLastApplyReceipt(receipt);
      setApplyState('applied');
      setApplyMessage(receipt.message || '已保存消歧。');
      await onReviewApplied?.();
    } catch (err: unknown) {
      setApplyState('failed');
      setApplyMessage(err instanceof Error ? err.message : '保存消歧失败。');
    }
  }, [activeItem, canApplyDisambiguation, changedDisambiguationNodes, onReviewApplied]);
  const handleApplyNodeEvidence = useCallback(async () => {
    if (!activeItem || !canApplyNodeEvidence || !selectedNodeInput || !evidenceRefForApply) return;
    setApplyState('applying');
    setApplyMessage('正在补充节点证据...');
    try {
      const receipt = await applyWikiGraphReview({
        operation_kind: 'add_node_evidence',
        review_item_key: activeItem.key,
        nodes: [selectedNodeInput],
        evidence_refs: [evidenceRefForApply],
        decided_by: 'graph_console',
      });
      setLastApplyReceipt(receipt);
      setApplyState('applied');
      setApplyMessage(receipt.message || '已补充节点证据。');
      await onReviewApplied?.();
    } catch (err: unknown) {
      setApplyState('failed');
      setApplyMessage(err instanceof Error ? err.message : '补充节点证据失败。');
    }
  }, [activeItem, canApplyNodeEvidence, evidenceRefForApply, onReviewApplied, selectedNodeInput]);
  const handleApplyRelationEvidence = useCallback(async () => {
    if (!activeItem || !canApplyRelationEvidence || !selectedEdgeInput || !evidenceRefForApply) return;
    setApplyState('applying');
    setApplyMessage('正在补充关系证据...');
    try {
      const receipt = await applyWikiGraphReview({
        operation_kind: 'add_relation_evidence',
        review_item_key: activeItem.key,
        nodes: [],
        edges: [selectedEdgeInput],
        evidence_refs: [evidenceRefForApply],
        decided_by: 'graph_console',
      });
      setLastApplyReceipt(receipt);
      setApplyState('applied');
      setApplyMessage(receipt.message || '已补充关系证据。');
      await onReviewApplied?.();
    } catch (err: unknown) {
      setApplyState('failed');
      setApplyMessage(err instanceof Error ? err.message : '补充关系证据失败。');
    }
  }, [activeItem, canApplyRelationEvidence, evidenceRefForApply, onReviewApplied, selectedEdgeInput]);
  const handleUndoLastApply = useCallback(async () => {
    if (!lastApplyReceipt || lastApplyReceipt.snapshots.length === 0 || !canRunApply) return;
    setApplyState('undoing');
    setApplyMessage('正在撤回上次修改...');
    try {
      const receipt = await undoWikiGraphReview({
        operation_id: lastApplyReceipt.operation_id,
        operation_kind: 'undo_graph_review',
        snapshots: lastApplyReceipt.snapshots,
        decided_by: 'graph_console',
      });
      setApplyState('undone');
      setApplyMessage(receipt.message || '已撤回上次修改。');
      setLastApplyReceipt(null);
      await onReviewApplied?.();
    } catch (err: unknown) {
      setApplyState('failed');
      setApplyMessage(err instanceof Error ? err.message : '撤回失败。');
    }
  }, [canRunApply, lastApplyReceipt, onReviewApplied]);
  const copyFeedbackText = copyState === 'done'
    ? '补丁已复制到剪贴板'
    : copyState === 'failed'
      ? '复制失败，请手动选中 JSON'
      : null;
  const writebackReason = reviewWritebackBlockReason(writeTargets);
  const visibleApplyBlockReason = duplicateReview
    ? applyBlockReason
    : mode === 'node_evidence' || mode === 'relation_evidence'
      ? evidenceApplyBlockReason
      : null;
  const actionLabel = duplicateReview
    ? '合并 / 消歧'
    : mode === 'node_evidence'
      ? '补节点证据'
      : mode === 'relation_evidence'
        ? '补关系证据'
        : mode === 'dimension'
          ? '补维度'
          : mode === 'relationship'
            ? '补关系'
            : '检查';
  const canUndoLastApply = Boolean(lastApplyReceipt) && applyState !== 'applying' && applyState !== 'undoing';
  const actionSummary = duplicateReview
    ? `${selectedMergeNodeIds.length} 个待并入 · ${changedDisambiguationNodes.length} 个待消歧`
    : mode === 'node_evidence'
      ? (canApplyNodeEvidence ? '证据已可应用' : evidenceApplyBlockReason ?? '补齐证据后可应用')
      : mode === 'relation_evidence'
        ? (canApplyRelationEvidence ? '证据已可应用' : evidenceApplyBlockReason ?? '补齐证据后可应用')
        : visibleApplyBlockReason ?? '选择对象后继续处理';
  const writebackStatusText = currentContextReadOnly
    ? '当前图谱只读：没有找到可写的 Wiki 页面或关系来源。请到 Wiki 图谱处理，或先把上下文沉淀成 Wiki 页面后再应用。'
    : `可直接写回 ${writeTargets.length} 个 Wiki 来源，应用后可撤回上次修改。`;
  const activeStep = applyState === 'applied' || applyState === 'undone' ? 3 : activeItem ? 2 : 1;

  const toggleMergeNode = useCallback((nodeId: string) => {
    setMergeNodeIds((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  const updateDuplicateDraft = useCallback((
    nodeId: string,
    field: keyof DuplicateDisambiguationDraft,
    value: string,
  ) => {
    setDuplicateDrafts((current) => ({
      ...current,
      [nodeId]: {
        ...(current[nodeId] ?? { label: '', disambiguation: '' }),
        [field]: value,
      },
    }));
  }, []);

  if (items.length === 0) {
    return (
      <section
        aria-label="复审控制台"
        className="border-l-2 border-emerald-500/45 px-2 py-1.5 text-xs text-emerald-700 dark:text-emerald-300"
      >
        <div className="font-semibold">复审控制台</div>
        <div className="mt-1 text-[11px] leading-relaxed">
          当前图谱没有待处理项。点击节点可查看证据文本、复制证据或打开原文。
        </div>
      </section>
    );
  }

  if (!activeItem) {
    return (
      <section aria-label="复审控制台" className="border-l-2 border-primary/35 px-2 py-1.5 text-xs">
        <div>
          <div className="font-semibold text-foreground">复审控制台</div>
          <div className="mt-0.5 text-[11px] leading-relaxed text-foreground/55">
            先在处理队列选择问题；这里会直接出现合并、消歧、补证据和撤回。
          </div>
        </div>
        <div className="mt-2 grid gap-1">
          {items.slice(0, 4).map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => onFocusReviewTarget(item.target)}
              className={cn(
                'grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-l-2 px-2 py-1.5 text-left transition-colors hover:bg-surface-lowest/70',
                item.tone,
              )}
              aria-label={`处理${item.label}`}
              title={item.title}
            >
              <span className="min-w-0">
                <span className="flex min-w-0 items-center gap-1">
                  <span className="truncate font-medium">{item.label}</span>
                  <span className="shrink-0 tabular-nums">{item.count}</span>
                </span>
                <span className="block truncate text-[10px] opacity-75">{item.action.primary}</span>
              </span>
              <span className={cn('inline-flex shrink-0 items-center gap-0.5 rounded-sm border px-1 py-px text-[9px]', reviewActionTone(item.action.kind))}>
                <ReviewActionIcon kind={item.action.kind} />
                {item.action.badge}
              </span>
            </button>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-2.5 px-1 text-xs" aria-label="复审控制台">
      <div className="sticky top-0 z-20 border-b border-outline-variant/35 bg-surface/95 pb-2 pt-0.5 backdrop-blur-sm">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1 font-semibold text-foreground">
              <Wrench className="h-3.5 w-3.5 text-primary" aria-hidden />
              复审控制台
            </div>
            <div className="mt-0.5 break-words text-[11px] text-foreground/60">{activeItem.label} · {activeItem.count} · {actionLabel}</div>
          </div>
          <button
            type="button"
            onClick={() => onFocusReviewTarget(activeItem.target)}
            className="inline-flex shrink-0 items-center gap-1 rounded-sm border border-primary/35 bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary hover:bg-primary/15"
          >
            <Crosshair className="h-3 w-3" aria-hidden />
            定位
          </button>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-1 text-[10px]" aria-label="复审处理步骤">
          {['选问题', '处理', '应用/撤回'].map((step, index) => {
            const selected = activeStep === index + 1;
            const done = activeStep > index + 1;
            return (
              <div
                key={step}
                className={cn(
                  'min-w-0 border-l-2 px-1.5 py-1',
                  selected
                    ? 'border-primary text-primary'
                    : done
                      ? 'border-emerald-500/45 text-emerald-700 dark:text-emerald-300'
                      : 'border-outline-variant/45 text-foreground/42',
                )}
              >
                <span className="block truncate font-medium">{index + 1}. {step}</span>
              </div>
            );
          })}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {duplicateReview ? (
            <>
              <button
                type="button"
                onClick={() => void handleApplyMerge()}
                disabled={!canApplyMerge}
                className={cn(
                  'inline-flex items-center gap-1 rounded-sm border px-2 py-1 text-[11px] font-medium transition-colors',
                  canApplyMerge
                    ? 'border-primary/45 bg-primary text-primary-foreground hover:bg-primary/90'
                    : 'cursor-not-allowed border-outline-variant/45 bg-surface-low text-foreground/35',
                )}
                title={!canApplyMerge ? applyBlockReason ?? undefined : undefined}
              >
                <GitMerge className="h-3 w-3" aria-hidden />
                {applyState === 'applying' ? '合并中' : '合并选中'}
              </button>
              <button
                type="button"
                onClick={() => void handleApplyDisambiguation()}
                disabled={!canApplyDisambiguation}
                className={cn(
                  'inline-flex items-center gap-1 rounded-sm border px-2 py-1 text-[11px] font-medium transition-colors',
                  canApplyDisambiguation
                    ? 'border-primary/45 bg-primary/10 text-primary hover:bg-primary/15'
                    : 'cursor-not-allowed border-outline-variant/45 bg-surface-low text-foreground/35',
                )}
                title={!canApplyDisambiguation ? applyBlockReason ?? undefined : undefined}
              >
                <CheckCircle2 className="h-3 w-3" aria-hidden />
                {applyState === 'applying' ? '保存中' : '保存消歧'}
              </button>
            </>
          ) : null}
          {!duplicateReview && mode === 'node_evidence' ? (
            <button
              type="button"
              onClick={() => void handleApplyNodeEvidence()}
              disabled={!canApplyNodeEvidence}
              className={cn(
                'inline-flex items-center gap-1 rounded-sm border px-2 py-1 text-[11px] font-medium transition-colors',
                canApplyNodeEvidence
                  ? 'border-primary/45 bg-primary text-primary-foreground hover:bg-primary/90'
                  : 'cursor-not-allowed border-outline-variant/45 bg-surface-low text-foreground/35',
              )}
              title={!canApplyNodeEvidence ? evidenceApplyBlockReason ?? undefined : undefined}
            >
              <CheckCircle2 className="h-3 w-3" aria-hidden />
              {applyState === 'applying' ? '应用中' : '应用补节点证据'}
            </button>
          ) : null}
          {!duplicateReview && mode === 'relation_evidence' ? (
            <button
              type="button"
              onClick={() => void handleApplyRelationEvidence()}
              disabled={!canApplyRelationEvidence}
              className={cn(
                'inline-flex items-center gap-1 rounded-sm border px-2 py-1 text-[11px] font-medium transition-colors',
                canApplyRelationEvidence
                  ? 'border-primary/45 bg-primary text-primary-foreground hover:bg-primary/90'
                  : 'cursor-not-allowed border-outline-variant/45 bg-surface-low text-foreground/35',
              )}
              title={!canApplyRelationEvidence ? evidenceApplyBlockReason ?? undefined : undefined}
            >
              <CheckCircle2 className="h-3 w-3" aria-hidden />
              {applyState === 'applying' ? '应用中' : '应用补关系证据'}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void handleUndoLastApply()}
            disabled={!canUndoLastApply}
            className={cn(
              'inline-flex items-center gap-1 rounded-sm border px-2 py-1 text-[11px] transition-colors',
              canUndoLastApply
                ? 'border-outline-variant/70 bg-surface text-foreground/70 hover:border-primary/35 hover:text-foreground'
                : 'cursor-not-allowed border-outline-variant/40 bg-surface-low text-foreground/30',
            )}
          >
            <X className="h-3 w-3" aria-hidden />
            {applyState === 'undoing' ? '撤回中' : '撤回上次'}
          </button>
        </div>
        <div
          role="status"
          aria-live="polite"
          className={cn(
            'mt-1.5 break-words text-[10px] leading-relaxed',
            applyState === 'failed'
              ? 'text-red-600 dark:text-red-400'
              : applyState === 'applied' || applyState === 'undone'
                ? 'text-emerald-700 dark:text-emerald-300'
                : 'text-foreground/50',
          )}
        >
          {applyMessage ?? actionSummary}
        </div>
        <div
          className={cn(
            'mt-1.5 flex items-start gap-1.5 border-l-2 px-2 py-1 text-[10px] leading-relaxed',
            currentContextReadOnly
              ? 'border-amber-500/55 text-amber-800 dark:text-amber-200'
              : 'border-emerald-500/45 text-emerald-800 dark:text-emerald-200',
          )}
        >
          {currentContextReadOnly ? (
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          ) : (
            <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          )}
          <span className="min-w-0 break-words">{writebackStatusText}</span>
        </div>
      </div>

      {duplicateReview ? (
        <div className="text-[11px] leading-relaxed text-foreground/62">
          <span className="font-semibold text-primary">重复标签同屏处理：</span>
          先看文本，再选择合并为同一概念，或给不同概念补限定标题和说明。
        </div>
      ) : modeOptions.length > 0 ? (
        <div className="flex flex-wrap gap-1" aria-label="复审操作类型">
          {modeOptions.map((option) => (
            <button
              key={option.mode}
              type="button"
              onClick={() => setMode(option.mode)}
              className={cn(
                'rounded-sm border px-2 py-1 text-[11px] transition-colors',
                mode === option.mode
                  ? 'border-primary/50 bg-primary/15 text-primary'
                  : 'border-outline-variant/50 bg-surface-low text-foreground/65 hover:text-foreground',
              )}
              aria-pressed={mode === option.mode}
              title={option.title}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}

      {writeTargets.length > 0 ? (
        <div className="min-w-0 text-[10px] leading-relaxed text-foreground/45">
          <span className="font-medium text-foreground/60">上游：</span>
          {writeTargets.slice(0, 4).map((path, index) => (
            <span key={path} className="font-mono break-all">
              {index > 0 ? ' / ' : ''}
              {compactMiddle(path, 46)}
            </span>
          ))}
        </div>
      ) : null}

      {evidenceDraft && (mode === 'node_evidence' || mode === 'relation_evidence') ? (
        <div className="border-l-2 border-primary/45 px-2 py-1.5 text-[10px] leading-relaxed text-foreground/65">
          <div className="font-semibold text-primary">已填入选中证据</div>
          <div className="mt-0.5 break-words">
            {compactMiddle(evidenceDraft.sourceTitle, 48)}
            {evidenceDraft.materialId ? ` · ${evidenceDraft.materialId}` : ''}
            {evidenceDraft.chunkId ? ` · ${compactMiddle(evidenceDraft.chunkId, 28)}` : ''}
            {evidenceDraft.page ? ` · p.${evidenceDraft.page}` : ''}
          </div>
        </div>
      ) : null}

      {duplicateReview ? (
        <div className="space-y-3">
          <div className="space-y-1">
            <div className="text-[11px] font-semibold text-foreground/70">同名节点</div>
            <div className="divide-y divide-outline-variant/35">
              {targetNodes.map((entry) => (
                <ReviewNodePreview
                  key={entry.node.id}
                  entry={entry}
                  active={selectedNodeId === entry.node.id || canonicalNodeId === entry.node.id}
                  flat
                  onClick={() => {
                    setSelectedNodeId(entry.node.id);
                    onSelectNodeId(entry.node.id);
                  }}
                />
              ))}
            </div>
          </div>

          <div className={REVIEW_PANEL_SECTION_CLASS}>
            <div className="flex items-start gap-1.5">
              <GitMerge className="mt-0.5 h-3.5 w-3.5 text-primary" aria-hidden />
              <div>
                <div className="font-semibold text-foreground/75">同一概念：合并</div>
                <div className="text-[10px] text-foreground/50">选择保留节点，再勾选要并入的节点。</div>
              </div>
            </div>
            <label className="grid gap-1 text-[11px]">
              <span className="font-medium text-foreground/70">保留节点</span>
              <select
                value={canonicalNodeId}
                onChange={(event) => {
                  const nextId = event.target.value;
                  setCanonicalNodeId(nextId);
                  setMergeNodeIds(new Set(targetNodeIds.filter((nodeId) => nodeId !== nextId)));
                  if (nextId) onSelectNodeId(nextId);
                }}
                className={REVIEW_INLINE_CONTROL_CLASS}
              >
                {targetNodes.length > 0 ? (
                  targetNodes.map((entry) => (
                    <option key={entry.node.id} value={entry.node.id}>{compactNodeSelectLabel(entry)}</option>
                  ))
                ) : (
                  <option value="">暂无可选节点</option>
                )}
              </select>
            </label>
            <div className="space-y-1">
              <div className="text-[11px] font-medium text-foreground/70">并入节点</div>
              {targetNodes.filter((entry) => entry.node.id !== canonicalNodeId).map((entry) => (
                <label key={entry.node.id} className="flex min-w-0 cursor-pointer items-start gap-2 border-l-2 border-transparent py-1.5 pl-2 text-[11px] transition-colors hover:border-primary/25 hover:bg-surface-lowest/70">
                  <input
                    aria-label={`并入 ${entry.display.title}`}
                    type="checkbox"
                    checked={mergeNodeIds.has(entry.node.id)}
                    onChange={() => toggleMergeNode(entry.node.id)}
                    className="mt-1"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="break-words font-medium text-foreground/75">{entry.display.title}</div>
                    {entry.display.previewText ? (
                      <div className="mt-0.5 line-clamp-2 break-words text-[10px] leading-relaxed text-foreground/55">
                        {entry.display.previewText}
                      </div>
                    ) : null}
                    <div className={cn('mt-0.5', REVIEW_MUTED_LINE_CLASS)} title={nodeContextSummary(entry)}>
                      {nodeContextSummary(entry)}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          <div className={REVIEW_PANEL_SECTION_CLASS}>
            <div className="flex items-start gap-1.5">
              <Info className="mt-0.5 h-3.5 w-3.5 text-primary" aria-hidden />
              <div>
                <div className="font-semibold text-foreground/75">不同概念：消歧</div>
                <div className="text-[10px] text-foreground/50">只填写需要修改的行，然后一次保存。</div>
              </div>
            </div>
            <div className="divide-y divide-outline-variant/45">
              {targetNodes.map((entry) => {
                const draft = duplicateDrafts[entry.node.id] ?? { label: '', disambiguation: '' };
                const draftChanged = Boolean(draft.label.trim() || draft.disambiguation.trim());
                const expanded = expandedDuplicateId === entry.node.id;
                const panelId = `duplicate-disambiguation-${entry.node.id}`;
                return (
                  <div key={entry.node.id} className="py-1.5">
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedNodeId(entry.node.id);
                        setExpandedDuplicateId((current) => (current === entry.node.id ? null : entry.node.id));
                        onSelectNodeId(entry.node.id);
                      }}
                      className={cn(
                        'flex w-full min-w-0 items-start justify-between gap-2 border-l-2 pl-2 text-left transition-colors hover:border-primary/25 hover:bg-surface-lowest/60',
                        expanded ? 'border-primary/45 bg-primary/5' : 'border-transparent',
                      )}
                      aria-expanded={expanded}
                      aria-controls={panelId}
                    >
                      <span className="min-w-0">
                        <span className="flex min-w-0 items-center gap-1">
                          <ChevronDown
                            className={cn('h-3 w-3 shrink-0 text-foreground/40 transition-transform', expanded && 'rotate-180')}
                            aria-hidden
                          />
                          <span className="truncate text-[11px] font-medium text-foreground/78">{entry.display.title}</span>
                          {draftChanged ? (
                            <span className="shrink-0 rounded-sm border border-primary/35 bg-primary/10 px-1 py-px text-[9px] text-primary">
                              待保存
                            </span>
                          ) : null}
                        </span>
                        <span className="mt-0.5 block line-clamp-2 break-words text-[10px] leading-relaxed text-foreground/52">
                          {entry.display.previewText || '暂无可展示文本，需先补证据摘录。'}
                        </span>
                      </span>
                      <span className="shrink-0 text-[10px] text-foreground/35">{DIMENSION_META[entry.dimension].label}</span>
                    </button>
                    {expanded ? (
                      <div id={panelId} className="mt-2 grid min-w-0 gap-2 pl-5">
                        <TextInput
                          label="新标题"
                          value={draft.label}
                          onChange={(value) => updateDuplicateDraft(entry.node.id, 'label', value)}
                          placeholder={defaultDisambiguationLabel(entry)}
                        />
                        <TextArea
                          label="消歧说明"
                          value={draft.disambiguation}
                          onChange={(value) => updateDuplicateDraft(entry.node.id, 'disambiguation', value)}
                          placeholder="说明它和同名节点的材料、方法、结论或语境差异"
                        />
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}

      {!duplicateReview && mode === 'merge' ? (
        <div className="space-y-2">
          <label className="grid gap-1 text-[11px]">
            <span className="font-medium text-foreground/70">保留节点</span>
            <select
              value={canonicalNodeId}
              onChange={(event) => {
                const nextId = event.target.value;
                setCanonicalNodeId(nextId);
                setMergeNodeIds(new Set(targetNodeIds.filter((nodeId) => nodeId !== nextId)));
                if (nextId) onSelectNodeId(nextId);
              }}
              className={REVIEW_INLINE_CONTROL_CLASS}
            >
              {targetNodes.length > 0 ? (
                targetNodes.map((entry) => (
                  <option key={entry.node.id} value={entry.node.id}>{compactNodeSelectLabel(entry)}</option>
                ))
              ) : (
                <option value="">暂无可选节点</option>
              )}
            </select>
          </label>
          <div className="space-y-1">
            <div className="text-[11px] font-medium text-foreground/70">并入节点</div>
            {targetNodes.filter((entry) => entry.node.id !== canonicalNodeId).map((entry) => (
              <label key={entry.node.id} className="flex min-w-0 cursor-pointer items-center gap-2 border-l-2 border-transparent px-2 py-1 text-[11px] transition-colors hover:border-primary/25 hover:bg-surface-lowest/70">
                <input
                  type="checkbox"
                  checked={mergeNodeIds.has(entry.node.id)}
                  onChange={() => toggleMergeNode(entry.node.id)}
                />
                <span className="min-w-0 truncate" title={compactNodeLabel(entry)}>{compactNodeSelectLabel(entry)}</span>
              </label>
            ))}
          </div>
        </div>
      ) : null}

      {!duplicateReview && mode === 'disambiguate' ? (
        <div className="space-y-2">
          <NodeSelect
            label="消歧节点"
            value={selectedNodeId}
            nodes={targetNodes}
            onChange={(nodeId) => {
              setSelectedNodeId(nodeId);
              if (nodeId) onSelectNodeId(nodeId);
            }}
          />
          <TextInput label="新标题" value={newLabel} onChange={setNewLabel} placeholder="例如：重复诊断节点（机制链）" />
          <TextArea label="消歧说明" value={disambiguation} onChange={setDisambiguation} placeholder="说明它和同名节点的语境差异" />
        </div>
      ) : null}

      {mode === 'node_evidence' ? (
        <div className="space-y-2">
          <NodeSelect
            label="补证据节点"
            value={selectedNodeId}
            nodes={targetNodes}
            onChange={(nodeId) => {
              setSelectedNodeId(nodeId);
              if (nodeId) onSelectNodeId(nodeId);
            }}
          />
          <EvidenceInputs
            materialId={materialId}
            chunkId={chunkId}
            page={page}
            evidenceText={evidenceText}
            onMaterialId={setMaterialId}
            onChunkId={setChunkId}
            onPage={setPage}
            onEvidenceText={setEvidenceText}
          />
        </div>
      ) : null}

      {mode === 'relation_evidence' ? (
        <div className="space-y-2">
          <label className="grid gap-1 text-[11px]">
            <span className="font-medium text-foreground/70">补证据关系</span>
            <select
              value={selectedEdgeId}
              onChange={(event) => setSelectedEdgeId(event.target.value)}
              className={REVIEW_INLINE_CONTROL_CLASS}
            >
              {targetEdges.length > 0 ? (
                targetEdges.map((edge) => (
                  <option key={edge.id} value={edge.id}>{compactEdgeLabel(edge)}</option>
                ))
              ) : (
                <option value="">暂无可选关系</option>
              )}
            </select>
          </label>
          <EvidenceInputs
            materialId={materialId}
            chunkId={chunkId}
            page={page}
            evidenceText={evidenceText}
            onMaterialId={setMaterialId}
            onChunkId={setChunkId}
            onPage={setPage}
            onEvidenceText={setEvidenceText}
          />
        </div>
      ) : null}

      {mode === 'dimension' ? (
        <div className="space-y-2">
          <NodeSelect
            label="标注节点"
            value={selectedNodeId}
            nodes={targetNodes}
            onChange={(nodeId) => {
              setSelectedNodeId(nodeId);
              if (nodeId) onSelectNodeId(nodeId);
            }}
          />
          <label className="grid gap-1 text-[11px]">
            <span className="font-medium text-foreground/70">语义维度</span>
            <select
              value={dimension}
              onChange={(event) => setDimension(event.target.value as ReasoningDimension)}
              className={REVIEW_INLINE_CONTROL_CLASS}
            >
              {DIMENSION_DISPLAY_ORDER.map((item) => (
                <option key={item} value={item}>{DIMENSION_META[item].label}</option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      {mode === 'relationship' ? (
        <div className="space-y-2">
          <label className="grid gap-1 text-[11px]">
            <span className="font-medium text-foreground/70">起点</span>
            <select
              value={selectedNodeId}
              onChange={(event) => {
                setSelectedNodeId(event.target.value);
                if (event.target.value) onSelectNodeId(event.target.value);
              }}
              className={REVIEW_INLINE_CONTROL_CLASS}
            >
              {(targetNodes.length > 0 ? targetNodes.map((entry) => ({ id: entry.node.id, label: compactNodeLabel(entry) })) : allNodeOptions).map((entry) => (
                <option key={entry.id} value={entry.id}>{entry.label}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-[11px]">
            <span className="font-medium text-foreground/70">关系</span>
            <select
              value={relation}
              onChange={(event) => setRelation(event.target.value)}
              className={REVIEW_INLINE_CONTROL_CLASS}
            >
              {['supports', 'contradicts', 'extends', 'uses', 'cites', 'related'].map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-[11px]">
            <span className="font-medium text-foreground/70">终点</span>
            <select
              value={canonicalNodeId}
              onChange={(event) => {
                setCanonicalNodeId(event.target.value);
                if (event.target.value) onSelectNodeId(event.target.value);
              }}
              className={REVIEW_INLINE_CONTROL_CLASS}
            >
              {allNodeOptions.map((entry) => (
                <option key={entry.id} value={entry.id}>{entry.label}</option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      {!duplicateReview ? (
        <details className="border-t border-outline-variant/35 pt-2 text-[10px] text-foreground/55">
          <summary className="cursor-pointer select-none font-medium text-foreground/62">审计补丁</summary>
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className="text-foreground/45">{writebackReason}</span>
            <button
              type="button"
              onClick={handleCopyPatch}
              className={cn(
                'inline-flex shrink-0 items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[10px] transition-colors',
                copyState === 'done'
                  ? 'border-emerald-500/45 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                  : copyState === 'failed'
                    ? 'border-red-500/45 bg-red-500/10 text-red-700 dark:text-red-300'
                    : 'border-outline-variant/60 bg-surface-low text-foreground/65 hover:border-primary/35 hover:text-foreground',
              )}
              aria-label={copyState === 'done' ? '已复制操作补丁' : copyState === 'failed' ? '复制操作补丁失败' : '复制操作补丁'}
            >
              <Copy className="h-3 w-3" aria-hidden />
              {copyState === 'done' ? '已复制' : copyState === 'failed' ? '复制失败' : '复制'}
            </button>
          </div>
          {copyFeedbackText ? (
            <div role="status" aria-live="polite" className="mt-1 text-[10px] text-foreground/55">
              {copyFeedbackText}
            </div>
          ) : null}
          <pre className="mt-2 max-h-44 max-w-full overflow-auto rounded-sm bg-surface-lowest p-2 text-[10px] leading-relaxed text-foreground/65">
            {operationPatch}
          </pre>
        </details>
      ) : null}
    </section>
  );
}

function TextInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid min-w-0 gap-1 text-[11px]">
      <span className="min-w-0 truncate font-medium text-foreground/70">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className={REVIEW_INLINE_CONTROL_CLASS}
      />
    </label>
  );
}

function TextArea({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid min-w-0 gap-1 text-[11px]">
      <span className="min-w-0 truncate font-medium text-foreground/70">{label}</span>
      <textarea
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className={cn(REVIEW_INLINE_CONTROL_CLASS, 'min-h-12 resize-y leading-relaxed')}
      />
    </label>
  );
}

function NodeSelect({
  label,
  value,
  nodes,
  onChange,
}: {
  label: string;
  value: string;
  nodes: DimensionGraphNode[];
  onChange: (nodeId: string) => void;
}) {
  return (
    <label className="grid min-w-0 gap-1 text-[11px]">
      <span className="font-medium text-foreground/70">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={REVIEW_INLINE_CONTROL_CLASS}
      >
        {nodes.length > 0 ? (
          nodes.map((entry) => (
            <option key={entry.node.id} value={entry.node.id}>{compactNodeSelectLabel(entry)}</option>
          ))
        ) : (
          <option value="">暂无可选节点</option>
        )}
      </select>
    </label>
  );
}

function ReviewNodePreview({
  entry,
  active = false,
  flat = false,
  onClick,
}: {
  entry: DimensionGraphNode;
  active?: boolean;
  flat?: boolean;
  onClick?: () => void;
}) {
  const content = (
    <>
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="min-w-0 truncate font-medium text-foreground/80" title={entry.display.title}>{entry.display.title}</span>
        <span className="shrink-0 text-[10px] text-foreground/40">
          {DIMENSION_META[entry.dimension].label}
        </span>
      </div>
      {entry.display.previewText ? (
        <div className="mt-0.5 line-clamp-2 break-words text-[10px] leading-relaxed text-foreground/58">
          {entry.display.previewText}
        </div>
      ) : (
        <div className="mt-0.5 text-[10px] text-amber-600 dark:text-amber-400">暂无可展示文本，需先补证据摘录。</div>
      )}
      <div className={cn('mt-0.5', REVIEW_MUTED_LINE_CLASS)} title={nodeContextSummary(entry)}>{nodeContextSummary(entry)}</div>
    </>
  );

  const className = cn(
    'min-w-0 w-full text-left transition-colors',
    flat
      ? cn(
          'border-l-2 py-1.5 pl-2',
          active
            ? 'border-primary/60 bg-primary/5 text-foreground'
            : 'border-transparent text-foreground/75 hover:border-outline-variant/60 hover:bg-surface-lowest/70 hover:text-foreground',
        )
      : cn(
          'rounded-sm border px-2 py-1.5',
          active
            ? 'border-primary/45 bg-primary/10'
            : 'border-outline-variant/45 bg-surface hover:border-primary/35 hover:bg-surface-high',
        ),
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={className}>
        {content}
      </button>
    );
  }

  return <div className={className}>{content}</div>;
}

function EvidenceInputs({
  materialId,
  chunkId,
  page,
  evidenceText,
  onMaterialId,
  onChunkId,
  onPage,
  onEvidenceText,
}: {
  materialId: string;
  chunkId: string;
  page: string;
  evidenceText: string;
  onMaterialId: (value: string) => void;
  onChunkId: (value: string) => void;
  onPage: (value: string) => void;
  onEvidenceText: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <TextInput label="material_id" value={materialId} onChange={onMaterialId} placeholder="材料 ID" />
      <div className="grid grid-cols-2 gap-2">
        <TextInput label="chunk_id" value={chunkId} onChange={onChunkId} placeholder="chunk ID" />
        <TextInput label="page" value={page} onChange={onPage} placeholder="页码" />
      </div>
      <TextArea label="证据摘录" value={evidenceText} onChange={onEvidenceText} placeholder="粘贴原文片段或证据说明" />
    </div>
  );
}

function LaneHeaders({ lanes, height }: { lanes: DimensionLane[]; height: number }) {
  const { x, y, zoom } = useViewport();
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 z-0"
      style={{
        minWidth: lanes.reduce((max, lane) => Math.max(max, lane.x + lane.width), 0),
        transform: `translate(${x}px, ${y}px) scale(${zoom})`,
        transformOrigin: '0 0',
      }}
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
              className="flex h-11 min-w-0 items-center gap-2 px-1 text-[11px]"
            >
              <span
                className="h-3 w-[3px] shrink-0 rounded-sm"
                style={{ background: meta.accent }}
                aria-hidden
              />
              <span className="min-w-0 truncate font-semibold text-foreground/72">
                {lane.trackTitle ?? meta.label}
              </span>
              <span className="ml-auto shrink-0 tabular-nums text-foreground/42">{lane.title}</span>
            </div>
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
 * - rail：右栏轻量预览，详情走浮层。
 * - explorer：全宽工作台，右侧固定详情栏。
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
  detailPlacement,
  selectedDimensions: controlledDimensions,
  onChangeSelectedDimensions,
  onReviewApplied,
}: DimensionGraphViewerProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [internalDimensions, setInternalDimensions] = useState<Set<ReasoningDimension>>(new Set());
  const [evidenceWeightVisible, setEvidenceWeightVisible] = useState(false);
  const [selectedRouteKinds, setSelectedRouteKinds] = useState<Set<DimensionRouteKind>>(new Set());
  const [reviewFocus, setReviewFocus] = useState<ReviewFocusTarget | null>(null);
  const [reviewEvidenceDraft, setReviewEvidenceDraft] = useState<ReviewEvidenceDraft | null>(null);

  const selectedDimensions = controlledDimensions ?? internalDimensions;
  const setSelectedDimensions = useCallback(
    (next: Set<ReasoningDimension>) => {
      if (onChangeSelectedDimensions) onChangeSelectedDimensions(next);
      else setInternalDimensions(next);
    },
    [onChangeSelectedDimensions],
  );

  const resolvedDetailPlacement: DetailPlacement = detailPlacement ?? (density === 'explorer' ? 'sidebar' : 'panel');

  const dimensionGraph = useMemo(() => (payload ? buildDimensionGraph(payload) : null), [payload]);
  const semanticReviewSpec = useMemo(() => (payload ? buildSemanticReviewSpec(payload) : null), [payload]);
  const routeCounts = useMemo(
    () => (dimensionGraph ? countRouteKinds(dimensionGraph.edges) : emptyRouteCounts()),
    [dimensionGraph],
  );

  const filteredGraph = useMemo(() => {
    if (!dimensionGraph) return null;
    return filterDimensionGraph(dimensionGraph, selectedDimensions, selectedRouteKinds, reviewFocus);
  }, [dimensionGraph, reviewFocus, selectedDimensions, selectedRouteKinds]);

  const paperNetworkMode = useMemo(() => (
    Boolean(dimensionGraph?.nodes.length)
    && dimensionGraph?.nodes.every((entry) => (
      (entry.node.metadata as Record<string, unknown> | undefined)?.graph_presentation === 'paper_network'
    )) === true
  ), [dimensionGraph]);

  const layout = useMemo(
    () => (filteredGraph
      ? layoutDimensionGraph(filteredGraph, {
          hideEmptyLanes,
          presentation: paperNetworkMode ? 'network' : density,
        })
      : null),
    [density, filteredGraph, hideEmptyLanes, paperNetworkMode],
  );

  const selectedEntry = useMemo(() => {
    if (!selectedNodeId || !dimensionGraph) return null;
    return dimensionGraph.nodes.find((candidate) => candidate.node.id === selectedNodeId) ?? null;
  }, [dimensionGraph, selectedNodeId]);
  const reviewItemsForConsole = useMemo(
    () => (semanticReviewSpec ? buildReviewQueueItems(semanticReviewSpec) : []),
    [semanticReviewSpec],
  );
  const activeReviewItemForConsole = useMemo(() => {
    if (!reviewFocus) return null;
    return reviewItemsForConsole.find((item) => item.target.id === reviewFocus.id) ?? null;
  }, [reviewFocus, reviewItemsForConsole]);

  const handleNodeClick = useCallback(
    (entry: DimensionGraphNode) => {
      setSelectedNodeId(entry.node.id);
      onSelectNode?.(entry);
    },
    [onSelectNode],
  );

  const handleSelectNodeIdFromConsole = useCallback((nodeId: string) => {
    if (!dimensionGraph) return;
    const nextEntry = dimensionGraph.nodes.find((entry) => entry.node.id === nodeId) ?? null;
    if (!nextEntry) return;
    setSelectedNodeId(nodeId);
    onSelectNode?.(nextEntry);
  }, [dimensionGraph, onSelectNode]);

  const handleCloseDetail = useCallback(() => {
    setSelectedNodeId(null);
    onSelectNode?.(null);
  }, [onSelectNode]);

  const handleToggleDimension = useCallback(
    (dimension: ReasoningDimension) => {
      setReviewFocus(null);
      const next = new Set(selectedDimensions);
      if (next.has(dimension)) next.delete(dimension);
      else next.add(dimension);
      setSelectedDimensions(next);
    },
    [selectedDimensions, setSelectedDimensions],
  );

  const handleResetFilter = useCallback(() => {
    setSelectedDimensions(new Set());
    setSelectedRouteKinds(new Set());
    setReviewFocus(null);
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
    setReviewFocus(null);
  }, [onlyEvidence, dimensionGraph, setSelectedDimensions]);

  const handleToggleEvidenceWeight = useCallback(() => {
    setEvidenceWeightVisible((value) => !value);
  }, []);

  const handleToggleRouteKind = useCallback((kind: DimensionRouteKind) => {
    setReviewFocus(null);
    setSelectedRouteKinds((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }, []);

  const handleFocusReviewTarget = useCallback((target: ReviewFocusTarget) => {
    setSelectedDimensions(new Set());
    setSelectedRouteKinds(new Set());
    setReviewFocus(target);
    if (!dimensionGraph) {
      handleCloseDetail();
      return;
    }
    const nextNodeId = firstReviewNodeId(target, dimensionGraph);
    if (!nextNodeId) {
      handleCloseDetail();
      return;
    }
    const nextEntry = dimensionGraph.nodes.find((entry) => entry.node.id === nextNodeId) ?? null;
    setSelectedNodeId(nextNodeId);
    onSelectNode?.(nextEntry);
  }, [dimensionGraph, handleCloseDetail, onSelectNode, setSelectedDimensions]);

  const handleUseSelectedEvidence = useCallback((entry: DimensionGraphNode) => {
    const draft = evidenceDraftFromNode(entry, Date.now());
    if (!draft) return;
    setReviewEvidenceDraft(draft);
    if (reviewFocus !== null) return;
    const evidenceItem = reviewItemsForConsole.find((item) => item.key.includes('missing_evidence_refs'))
      ?? reviewItemsForConsole.find((item) => item.key.includes('relations_missing_evidence'))
      ?? reviewItemsForConsole.find((item) => item.key.includes('missing_source_anchor'))
      ?? reviewItemsForConsole.find((item) => item.key.includes('low_confidence') || item.key.includes('source_overlap'));
    if (evidenceItem) {
      handleFocusReviewTarget(evidenceItem.target);
    }
  }, [handleFocusReviewTarget, reviewFocus, reviewItemsForConsole]);

  const handleFocusDimension = useCallback((dimension: ReasoningDimension) => {
    setReviewFocus(null);
    setSelectedRouteKinds(new Set());
    setSelectedDimensions(new Set([dimension]));
  }, [setSelectedDimensions]);

  const handleFocusRelation = useCallback((relation: string) => {
    setReviewFocus(null);
    setSelectedDimensions(new Set());
    setSelectedRouteKinds(new Set([resolveRouteKind(relation)]));
  }, [setSelectedDimensions]);

  const nodes = useMemo(() => (layout ? layout.nodes : []), [layout]);
  const edges = useMemo(() => (layout ? styleEdges(layout.edges) : []), [layout]);
  const performanceMode = nodes.length >= LARGE_GRAPH_NODE_THRESHOLD
    || edges.length >= LARGE_GRAPH_EDGE_THRESHOLD;
  const hasActiveFilter = selectedDimensions.size > 0 || selectedRouteKinds.size > 0 || reviewFocus !== null;

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

  const showReviewConsole = showLegend && density === 'explorer';
  const showSidebar = resolvedDetailPlacement === 'sidebar' && (selectedEntry !== null || showReviewConsole);

  return (
    <div className={cn('relative flex h-full min-h-[280px] w-full gap-2', className)}>
      <div className="flex min-w-0 flex-1 flex-col">
        {showLegend ? (
          <div className="z-10 flex flex-col gap-2 px-2 pt-2">
            <div className="flex items-center gap-2">
              <FilterBar
                counts={dimensionGraph.counts}
                routeCounts={routeCounts}
                selectedDimensions={selectedDimensions}
                onToggleDimension={handleToggleDimension}
                onlyEvidence={onlyEvidence}
                onToggleOnlyEvidence={handleToggleOnlyEvidence}
                evidenceWeightVisible={evidenceWeightVisible}
                onToggleEvidenceWeight={handleToggleEvidenceWeight}
                selectedRouteKinds={selectedRouteKinds}
                onToggleRouteKind={handleToggleRouteKind}
              />
            </div>
            <ActiveFilterStatus
              selectedDimensions={selectedDimensions}
              selectedRouteKinds={selectedRouteKinds}
              reviewFocusLabel={reviewFocus?.label ?? null}
              visibleNodeCount={filteredGraph?.nodes.length ?? 0}
              totalNodeCount={dimensionGraph.nodes.length}
              visibleEdgeCount={filteredGraph?.edges.length ?? 0}
              totalEdgeCount={dimensionGraph.edges.length}
              onResetFilter={handleResetFilter}
            />
            {semanticReviewSpec ? (
              <SemanticReviewPanel
                spec={semanticReviewSpec}
                compact={density === 'rail'}
                collapsed={density === 'explorer' || density === 'rail'}
                selectedDimensions={selectedDimensions}
                selectedRouteKinds={selectedRouteKinds}
                activeReviewFocusId={reviewFocus?.id ?? null}
                onFocusReviewTarget={handleFocusReviewTarget}
                onClearReviewFocus={() => setReviewFocus(null)}
                onFocusDimension={handleFocusDimension}
                onFocusRelation={handleFocusRelation}
              />
            ) : null}
          </div>
        ) : null}
        <div className="relative min-h-0 flex-1 overflow-hidden border-y border-outline-variant/50 bg-surface-lowest">
          {hasActiveFilter && nodes.length === 0 ? (
            <div className="absolute inset-0 z-10 flex items-center justify-center p-6">
              <div className="max-w-sm rounded-md border border-outline-variant/60 bg-surface/95 px-4 py-3 text-center text-xs text-foreground/65 shadow-sm">
                当前筛选没有匹配的节点或关系。
                <button
                  type="button"
                  onClick={handleResetFilter}
                  className="ml-2 rounded-sm border border-primary/35 px-1.5 py-0.5 text-primary hover:bg-primary/10"
                >
                  清除筛选
                </button>
              </div>
            </div>
          ) : null}
          <ReactFlowProvider>
            {layout && layout.lanes.length > 0 ? <LaneHeaders lanes={layout.lanes} height={layout.total.height} /> : null}
            <DimensionFlow
              nodes={nodes}
              edges={edges}
              density={density}
              performanceMode={performanceMode}
              onNodeClick={handleNodeClick}
              detailPlacement={resolvedDetailPlacement}
              selectedEntry={selectedEntry}
              evidenceWeightVisible={evidenceWeightVisible}
              onOpenSource={onOpenSource}
              onUseEvidence={showReviewConsole ? handleUseSelectedEvidence : undefined}
              onCloseDetail={handleCloseDetail}
            />
          </ReactFlowProvider>
        </div>
      </div>
      {showSidebar ? (
        <aside className="h-full w-[22rem] min-w-0 shrink-0 overflow-y-auto overflow-x-hidden border-l border-outline-variant/50 px-2 py-1">
          <div className="space-y-2">
            {showReviewConsole && dimensionGraph ? (
              <ReviewOperationConsole
                items={reviewItemsForConsole}
                activeItem={activeReviewItemForConsole}
                graph={dimensionGraph}
                evidenceDraft={reviewEvidenceDraft}
                onFocusReviewTarget={handleFocusReviewTarget}
                onSelectNodeId={handleSelectNodeIdFromConsole}
                onReviewApplied={onReviewApplied}
              />
            ) : null}
            {showReviewConsole ? (
              <ReviewQueuePanel
                items={reviewItemsForConsole}
                activeReviewFocusId={reviewFocus?.id ?? null}
                onFocusReviewTarget={handleFocusReviewTarget}
                onClearReviewFocus={() => setReviewFocus(null)}
                compact={activeReviewItemForConsole !== null}
              />
            ) : null}
            {selectedEntry ? (
              <SelectionDetail
                entry={selectedEntry}
                onOpenSource={onOpenSource}
                onUseEvidence={showReviewConsole ? handleUseSelectedEvidence : undefined}
                onClose={handleCloseDetail}
              />
            ) : null}
          </div>
        </aside>
      ) : null}
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
  density,
  performanceMode,
  onNodeClick,
  detailPlacement,
  selectedEntry,
  evidenceWeightVisible,
  onOpenSource,
  onUseEvidence,
  onCloseDetail,
}: {
  nodes: Node[];
  edges: Edge[];
  density: GraphDensity;
  performanceMode: boolean;
  onNodeClick: (entry: DimensionGraphNode) => void;
  detailPlacement: DetailPlacement;
  selectedEntry: DimensionGraphNode | null;
  evidenceWeightVisible: boolean;
  onOpenSource?: (entry: DimensionGraphNode) => Promise<boolean> | boolean;
  onUseEvidence?: (entry: DimensionGraphNode) => void;
  onCloseDetail: () => void;
}) {
  const { fitView } = useReactFlow();
  const nodeViewportSignature = useMemo(() => nodes.map((node) => node.id).join('|'), [nodes]);
  const activeNodeId = selectedEntry?.node.id ?? null;
  const interactiveNodes = useMemo(
    () => decorateInteractiveNodes(nodes.map((node) => ({
      ...node,
      data: { ...node.data, performanceMode },
    })), {
      edges,
      activeNodeId,
    }),
    [activeNodeId, edges, nodes, performanceMode],
  );
  const interactiveEdges = useMemo(
    () => decorateInteractiveEdges(edges, {
      activeNodeId,
      evidenceWeightVisible,
    }),
    [activeNodeId, edges, evidenceWeightVisible],
  );

  useEffect(() => {
    if (nodes.length === 0 || density === 'rail') return undefined;
    const timeoutId = window.setTimeout(() => {
      void fitView({
        duration: performanceMode ? 0 : 260,
        maxZoom: nodes.length <= 1 ? 1.25 : 1.08,
        padding: nodes.length <= 1 ? 0.42 : 0.12,
      });
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [density, fitView, nodeViewportSignature, nodes.length, performanceMode]);

  useEffect(() => {
    if (!activeNodeId) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseDetail();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeNodeId, onCloseDetail]);

  const handleFitToNode = useCallback(
    (entry: DimensionGraphNode) => {
      void fitView({ nodes: [{ id: entry.node.id }], duration: 320, maxZoom: 1.4, padding: 0.3 });
    },
    [fitView],
  );
  return (
    <ReactFlow
      nodes={interactiveNodes}
      edges={interactiveEdges}
      nodeTypes={NODE_TYPES}
      edgeTypes={EDGE_TYPES}
      fitView={density === 'explorer'}
      fitViewOptions={{ maxZoom: 1.2, padding: 0.08 }}
      defaultViewport={{ x: 12, y: 12, zoom: 1 }}
      minZoom={density === 'rail' ? 0.7 : 0.55}
      maxZoom={1.6}
      onlyRenderVisibleElements={performanceMode}
      proOptions={{ hideAttribution: true }}
      onNodeClick={(_, node) => {
        const dimensionEntry = (node.data as DimensionNodeData | undefined)?.dimensionEntry;
        if (dimensionEntry) onNodeClick(dimensionEntry);
      }}
      onPaneClick={() => {
        if (activeNodeId) onCloseDetail();
      }}
      nodesConnectable={false}
      nodesDraggable={false}
      elementsSelectable={false}
      nodesFocusable
      edgesFocusable={false}
      selectNodesOnDrag={false}
      panOnScroll
      zoomOnPinch
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={20}
        size={1}
        color="hsl(var(--outline-variant) / 0.42)"
      />
      <Panel position="bottom-left">
        <button
          type="button"
          onClick={() => void fitView({ duration: 260, maxZoom: 1.08, padding: 0.12 })}
          className="inline-flex size-7 items-center justify-center rounded-sm border border-outline-variant/60 bg-surface-lowest/90 text-foreground/62 shadow-sm backdrop-blur-sm transition-colors hover:border-primary/40 hover:text-foreground"
          aria-label="适配视图"
          title="适配视图"
        >
          <Crosshair className="size-3.5" aria-hidden />
        </button>
      </Panel>
      {detailPlacement === 'panel' && selectedEntry ? (
        <Panel position="top-right">
          <SelectionDetail
            entry={selectedEntry}
            onOpenSource={onOpenSource}
            onUseEvidence={onUseEvidence}
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
  onUseEvidence,
  onFitToNode,
  onClose,
  compact = false,
}: {
  entry: DimensionGraphNode;
  onOpenSource?: (entry: DimensionGraphNode) => Promise<boolean> | boolean;
  onUseEvidence?: (entry: DimensionGraphNode) => void;
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
  const canUseEvidence = Boolean(onUseEvidence && (target || evidenceText));

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
              <dd className="min-w-0 break-words font-mono text-[10px] text-foreground/55" title={target.chunk_id}>
                {compactMiddle(target.chunk_id, compact ? 28 : 42)}
              </dd>
            </div>
          )}
        </dl>

        {evidenceText && (
        <div className="border-l-2 border-outline-variant/50 px-2 py-1.5">
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
          {onUseEvidence && (
            <button
              type="button"
              onClick={() => onUseEvidence(entry)}
              disabled={!canUseEvidence}
              className={cn(
                'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition-colors',
                canUseEvidence
                  ? 'border-primary/45 bg-primary/10 text-primary hover:bg-primary/15'
                  : 'cursor-not-allowed border-outline-variant/40 text-foreground/35',
              )}
              title={canUseEvidence ? '把该节点的材料、chunk、页码和摘录填入复审控制台' : '该节点没有可填入的证据信息'}
            >
              <FileSearch className="h-3 w-3" aria-hidden />
              填入证据
            </button>
          )}
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
