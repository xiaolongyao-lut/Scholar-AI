import { useEffect, useId, useMemo, useRef } from 'react';
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getBezierPath,
  getStraightPath,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type FitViewOptions,
  type Node,
  type NodeProps,
  type XYPosition,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { AlertTriangle, Loader2, RotateCcw } from 'lucide-react';

import { cn } from '@/lib/utils';
import {
  getGraphEdgeGeometry,
  type GraphEdgeDirection,
} from './graphGeometry';
import { layoutWithDagre } from './layoutWithDagre';
import { layoutNetworkGraph } from './networkGraphLayout';

export type GraphViewportDirection = GraphEdgeDirection;
export type GraphViewportLayoutDirection = 'horizontal' | 'vertical';
export type GraphViewportPresentation = 'cards' | 'network';

export interface GraphViewportNode {
  readonly id: string;
  readonly label: string;
  readonly type: string;
  readonly status?: string | null;
  readonly confidence?: number | null;
  /** Optional presentation hint. If every visible node has a valid position, it is preserved. */
  readonly position?: Readonly<XYPosition> | null;
}

export interface GraphViewportEdge {
  readonly id: string;
  readonly source: string;
  readonly target: string;
  readonly relation: string;
  readonly direction: GraphViewportDirection;
  readonly status?: string | null;
  readonly confidence?: number | null;
}

export type GraphViewportSelection =
  | Readonly<{ kind: 'node'; id: string }>
  | Readonly<{ kind: 'edge'; id: string }>
  | null;

/**
 * Empty filter arrays mean “all”, matching the existing Scholar AI graph filter controls.
 * The viewport only applies filters; filter state and reset behavior remain with its controller.
 */
export interface GraphViewportFilters {
  readonly nodeIds?: readonly string[];
  readonly nodeTypes?: readonly string[];
  readonly edgeIds?: readonly string[];
  readonly relations?: readonly string[];
  readonly directions?: readonly GraphViewportDirection[];
  readonly includeIsolatedNodes?: boolean;
}

export interface GraphViewportFit {
  readonly initially?: boolean;
  readonly onDataChange?: boolean;
  readonly requestKey?: string | number;
  readonly padding?: number;
  readonly minZoom?: number;
  readonly maxZoom?: number;
  readonly duration?: number;
}

export interface GraphViewportProps<
  NodeDto extends GraphViewportNode = GraphViewportNode,
  EdgeDto extends GraphViewportEdge = GraphViewportEdge,
> {
  readonly nodes: readonly NodeDto[];
  readonly edges: readonly EdgeDto[];
  readonly selection?: GraphViewportSelection;
  readonly filters?: GraphViewportFilters;
  readonly fit?: GraphViewportFit | false;
  readonly layoutDirection?: GraphViewportLayoutDirection;
  /** Dense Wiki/project graphs use circles; answer/logic graphs keep semantic cards. */
  readonly presentation?: GraphViewportPresentation;
  readonly loading?: boolean;
  readonly error?: string | null;
  readonly className?: string;
  readonly ariaLabel?: string;
  readonly emptyMessage?: string;
  readonly onNodeSelect?: (node: NodeDto) => void;
  readonly onEdgeSelect?: (edge: EdgeDto) => void;
  readonly onSelectionClear?: () => void;
  readonly onResetFilters?: () => void;
  readonly onRetry?: () => void;
}

interface ViewportNodeData extends Record<string, unknown> {
  readonly graphNode: GraphViewportNode;
  readonly presentation: GraphViewportPresentation;
  readonly prominentLabel: boolean;
  readonly dimmed: boolean;
  readonly degree: number;
}

interface ViewportEdgeData extends Record<string, unknown> {
  readonly graphEdge: GraphViewportEdge;
  readonly geometryPath?: string;
}

interface ViewportNodeBox {
  readonly width: number;
  readonly height: number;
  readonly borderRadius: number;
}

type ViewportFlowNode = Node<ViewportNodeData, 'graphViewportNode'>;
type ViewportFlowEdge = Edge<ViewportEdgeData, 'graphViewportEdge'>;

const NODE_MIN_WIDTH = 168;
const NODE_MAX_WIDTH = 304;
const NODE_MIN_HEIGHT = 64;
const NODE_MAX_HEIGHT = 100;
const NODE_HORIZONTAL_PADDING = 28;
const NODE_NON_LABEL_HEIGHT = 46;
const NODE_LABEL_LINE_HEIGHT = 18;
const NODE_MAX_LABEL_LINES = 3;
const NODE_BORDER_RADIUS = 8;
const NODE_METADATA_GAP = 8;
const NODE_STATUS_HORIZONTAL_PADDING = 12;
const NODE_MAX_TYPE_WIDTH = 148;
const NODE_MAX_STATUS_WIDTH = 120;
const NETWORK_NODE_MIN_DIAMETER = 22;
const NETWORK_NODE_MAX_DIAMETER = 46;
const NETWORK_LABEL_LIMIT = 14;
const NETWORK_LARGE_LABEL_LIMIT = 10;
const PERFORMANCE_NODE_THRESHOLD = 150;
const PERFORMANCE_EDGE_THRESHOLD = 600;
const SOURCE_LEFT = 'graph-viewport-source-left';
const SOURCE_RIGHT = 'graph-viewport-source-right';
const SOURCE_TOP = 'graph-viewport-source-top';
const SOURCE_BOTTOM = 'graph-viewport-source-bottom';
const TARGET_LEFT = 'graph-viewport-target-left';
const TARGET_RIGHT = 'graph-viewport-target-right';
const TARGET_TOP = 'graph-viewport-target-top';
const TARGET_BOTTOM = 'graph-viewport-target-bottom';
const HANDLE_CLASS = '!pointer-events-none !size-px !min-h-px !min-w-px !border-0 !bg-transparent !opacity-0';

const NODE_TYPES = { graphViewportNode: GraphViewportNodeRenderer };
const EDGE_TYPES = { graphViewportEdge: GraphViewportEdgeRenderer };

interface FilteredGraph<NodeDto extends GraphViewportNode, EdgeDto extends GraphViewportEdge> {
  readonly nodes: NodeDto[];
  readonly edges: EdgeDto[];
  readonly hasActiveFilters: boolean;
}

interface ResolvedFit {
  readonly initially: boolean;
  readonly onDataChange: boolean;
  readonly requestKey: string | number | undefined;
  readonly options: FitViewOptions;
}

function normalizeFilter(values: readonly string[] | undefined): ReadonlySet<string> | null {
  if (!values || values.length === 0) return null;
  const normalized = values.map((value) => value.trim()).filter(Boolean);
  return normalized.length > 0 ? new Set(normalized) : null;
}

function uniqueById<T extends { readonly id: string }>(items: readonly T[]): T[] {
  const seen = new Set<string>();
  const unique: T[] = [];
  for (const item of items) {
    const id = item.id.trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    unique.push(item);
  }
  return unique;
}

export function filterGraphViewport<
  NodeDto extends GraphViewportNode,
  EdgeDto extends GraphViewportEdge,
>(
  nodes: readonly NodeDto[],
  edges: readonly EdgeDto[],
  filters: GraphViewportFilters | undefined,
): FilteredGraph<NodeDto, EdgeDto> {
  const nodeIds = normalizeFilter(filters?.nodeIds);
  const nodeTypes = normalizeFilter(filters?.nodeTypes);
  const edgeIds = normalizeFilter(filters?.edgeIds);
  const relations = normalizeFilter(filters?.relations);
  const directions = normalizeFilter(filters?.directions);
  const hasActiveFilters = Boolean(
    nodeIds || nodeTypes || edgeIds || relations || directions || filters?.includeIsolatedNodes === false,
  );

  const candidateNodes = uniqueById(nodes).filter((node) => (
    (!nodeIds || nodeIds.has(node.id)) && (!nodeTypes || nodeTypes.has(node.type))
  ));
  const candidateNodeIds = new Set(candidateNodes.map((node) => node.id));
  const candidateEdges = uniqueById(edges).filter((edge) => (
    candidateNodeIds.has(edge.source)
    && candidateNodeIds.has(edge.target)
    && (!edgeIds || edgeIds.has(edge.id))
    && (!relations || relations.has(edge.relation))
    && (!directions || directions.has(edge.direction))
  ));

  if (filters?.includeIsolatedNodes !== false) {
    return { nodes: candidateNodes, edges: candidateEdges, hasActiveFilters };
  }
  const connectedNodeIds = new Set<string>();
  for (const edge of candidateEdges) {
    connectedNodeIds.add(edge.source);
    connectedNodeIds.add(edge.target);
  }
  return {
    nodes: candidateNodes.filter((node) => connectedNodeIds.has(node.id)),
    edges: candidateEdges,
    hasActiveFilters,
  };
}

function isFinitePosition(value: Readonly<XYPosition> | null | undefined): value is Readonly<XYPosition> {
  return Boolean(value && Number.isFinite(value.x) && Number.isFinite(value.y));
}

function clampNumber(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function isWideCodePoint(codePoint: number): boolean {
  return codePoint >= 0x1100 && (
    codePoint <= 0x115f
    || codePoint === 0x2329
    || codePoint === 0x232a
    || (codePoint >= 0x2e80 && codePoint <= 0xa4cf && codePoint !== 0x303f)
    || (codePoint >= 0xac00 && codePoint <= 0xd7a3)
    || (codePoint >= 0xf900 && codePoint <= 0xfaff)
    || (codePoint >= 0xfe10 && codePoint <= 0xfe19)
    || (codePoint >= 0xfe30 && codePoint <= 0xfe6f)
    || (codePoint >= 0xff00 && codePoint <= 0xff60)
    || (codePoint >= 0xffe0 && codePoint <= 0xffe6)
    || (codePoint >= 0x1f300 && codePoint <= 0x1faff)
    || (codePoint >= 0x20000 && codePoint <= 0x3fffd)
  );
}

function isZeroWidthCodePoint(codePoint: number): boolean {
  return (codePoint >= 0x0300 && codePoint <= 0x036f)
    || (codePoint >= 0x1ab0 && codePoint <= 0x1aff)
    || (codePoint >= 0x1dc0 && codePoint <= 0x1dff)
    || (codePoint >= 0x20d0 && codePoint <= 0x20ff)
    || (codePoint >= 0xfe00 && codePoint <= 0xfe0f)
    || (codePoint >= 0xfe20 && codePoint <= 0xfe2f)
    || codePoint === 0x200d;
}

function estimateTextWidth(text: string, fontSize: number): number {
  let units = 0;
  for (const character of text) {
    const codePoint = character.codePointAt(0);
    if (codePoint === undefined || isZeroWidthCodePoint(codePoint)) continue;
    if (/\s/u.test(character)) {
      units += 0.34;
    } else if (isWideCodePoint(codePoint)) {
      units += 1;
    } else if (/[ilI1|.,'`:;]/u.test(character)) {
      units += 0.38;
    } else if (/[MW@#%&]/u.test(character)) {
      units += 0.92;
    } else {
      units += 0.62;
    }
  }
  return Math.ceil(units * fontSize);
}

function roundUpToEvenPixel(value: number): number {
  return Math.ceil(value / 2) * 2;
}

function normalizedConfidence(value: number | null | undefined): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0;
  return clampNumber(value, 0, 1);
}

function resolveNetworkNodeDiameter(node: GraphViewportNode, degree: number): number {
  const connectivity = Math.log2(Math.max(0, degree) + 1);
  const diameter = NETWORK_NODE_MIN_DIAMETER
    + connectivity * 4.8
    + normalizedConfidence(node.confidence) * 5;
  return roundUpToEvenPixel(clampNumber(
    diameter,
    NETWORK_NODE_MIN_DIAMETER,
    NETWORK_NODE_MAX_DIAMETER,
  ));
}

function resolveNodeBox(
  node: GraphViewportNode,
  presentation: GraphViewportPresentation,
  degree: number,
): ViewportNodeBox {
  if (presentation === 'network') {
    const diameter = resolveNetworkNodeDiameter(node, degree);
    return { width: diameter, height: diameter, borderRadius: diameter / 2 };
  }
  const label = node.label.trim() || '未命名节点';
  const type = node.type.trim() || '节点';
  const status = typeof node.status === 'string' ? node.status.trim() : '';
  const labelWidth = estimateTextWidth(label, 13);
  const typeWidth = Math.min(estimateTextWidth(type, 10), NODE_MAX_TYPE_WIDTH);
  const statusWidth = status
    ? Math.min(
      estimateTextWidth(status, 10) + NODE_STATUS_HORIZONTAL_PADDING,
      NODE_MAX_STATUS_WIDTH,
    )
    : 0;
  const metadataWidth = typeWidth + (statusWidth > 0 ? NODE_METADATA_GAP + statusWidth : 0);
  const minimumContentWidth = NODE_MIN_WIDTH - NODE_HORIZONTAL_PADDING;
  const maximumContentWidth = NODE_MAX_WIDTH - NODE_HORIZONTAL_PADDING;
  const contentWidth = clampNumber(
    Math.max(labelWidth, metadataWidth),
    minimumContentWidth,
    maximumContentWidth,
  );
  const width = clampNumber(
    roundUpToEvenPixel(contentWidth + NODE_HORIZONTAL_PADDING),
    NODE_MIN_WIDTH,
    NODE_MAX_WIDTH,
  );
  const usableLabelWidth = width - NODE_HORIZONTAL_PADDING;
  const labelLines = clampNumber(
    Math.ceil(labelWidth / usableLabelWidth),
    1,
    NODE_MAX_LABEL_LINES,
  );
  const height = clampNumber(
    NODE_NON_LABEL_HEIGHT + labelLines * NODE_LABEL_LINE_HEIGHT,
    NODE_MIN_HEIGHT,
    NODE_MAX_HEIGHT,
  );
  return { width, height, borderRadius: NODE_BORDER_RADIUS };
}

function boxCenter(position: XYPosition, box: ViewportNodeBox): XYPosition {
  return {
    x: position.x + box.width / 2,
    y: position.y + box.height / 2,
  };
}

function handlePair(
  sourcePosition: XYPosition,
  targetPosition: XYPosition,
): Pick<ViewportFlowEdge, 'sourceHandle' | 'targetHandle'> {
  const dx = targetPosition.x - sourcePosition.x;
  const dy = targetPosition.y - sourcePosition.y;
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0
      ? { sourceHandle: SOURCE_RIGHT, targetHandle: TARGET_LEFT }
      : { sourceHandle: SOURCE_LEFT, targetHandle: TARGET_RIGHT };
  }
  return dy >= 0
    ? { sourceHandle: SOURCE_BOTTOM, targetHandle: TARGET_TOP }
    : { sourceHandle: SOURCE_TOP, targetHandle: TARGET_BOTTOM };
}

function edgeStroke(relation: string): string {
  switch (relation) {
    case 'contradicts':
    case 'challenges':
    case 'refutes':
      return 'hsl(0 70% 52% / 0.78)';
    case 'supports':
    case 'supported_by':
      return 'hsl(var(--primary) / 0.76)';
    case 'cites':
      return 'hsl(170 50% 40% / 0.72)';
    case 'uses':
      return 'hsl(265 55% 54% / 0.70)';
    default:
      return 'hsl(var(--outline) / 0.80)';
  }
}

function graphNodeDegrees(
  nodes: readonly GraphViewportNode[],
  edges: readonly GraphViewportEdge[],
): ReadonlyMap<string, number> {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const degrees = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
    degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    if (edge.target !== edge.source) {
      degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
    }
  }
  return degrees;
}

function prominentNetworkNodeIds(
  nodes: readonly GraphViewportNode[],
  degrees: ReadonlyMap<string, number>,
): ReadonlySet<string> {
  if (nodes.length <= 18) return new Set(nodes.map((node) => node.id));
  const limit = nodes.length > 80 ? NETWORK_LARGE_LABEL_LIMIT : NETWORK_LABEL_LIMIT;
  const ranked = [...nodes].sort((left, right) => {
    const degreeDifference = (degrees.get(right.id) ?? 0) - (degrees.get(left.id) ?? 0);
    if (degreeDifference !== 0) return degreeDifference;
    const confidenceDifference = normalizedConfidence(right.confidence)
      - normalizedConfidence(left.confidence);
    if (confidenceDifference !== 0) return confidenceDifference;
    return left.id.localeCompare(right.id);
  });
  return new Set(ranked.slice(0, limit).map((node) => node.id));
}

function selectedNodeNeighbourIds(
  selection: GraphViewportSelection | undefined,
  edges: readonly GraphViewportEdge[],
): ReadonlySet<string> | null {
  if (selection?.kind !== 'node') return null;
  const neighbours = new Set<string>([selection.id]);
  for (const edge of edges) {
    if (edge.source === selection.id) neighbours.add(edge.target);
    if (edge.target === selection.id) neighbours.add(edge.source);
  }
  return neighbours;
}

function resolveNetworkPositions<
  NodeDto extends GraphViewportNode,
  EdgeDto extends GraphViewportEdge,
>(
  nodes: readonly NodeDto[],
  edges: readonly EdgeDto[],
  presentation: GraphViewportPresentation,
): ReadonlyMap<string, XYPosition> | null {
  if (
    presentation !== 'network'
    || nodes.length === 0
    || nodes.every((node) => isFinitePosition(node.position))
  ) {
    return null;
  }
  const degrees = graphNodeDegrees(nodes, edges);
  return layoutNetworkGraph(
    nodes.map((node) => {
      const diameter = resolveNetworkNodeDiameter(node, degrees.get(node.id) ?? 0);
      return { id: node.id, width: diameter, height: diameter };
    }),
    edges,
  );
}

function toFlowGraph<NodeDto extends GraphViewportNode, EdgeDto extends GraphViewportEdge>(
  nodes: readonly NodeDto[],
  edges: readonly EdgeDto[],
  selection: GraphViewportSelection | undefined,
  layoutDirection: GraphViewportLayoutDirection,
  presentation: GraphViewportPresentation,
  networkPositions: ReadonlyMap<string, XYPosition> | null,
): { nodes: ViewportFlowNode[]; edges: ViewportFlowEdge[] } {
  const preservePositions = nodes.length > 0 && nodes.every((node) => (
    isFinitePosition(node.position) || networkPositions?.has(node.id) === true
  ));
  const nodeLabels = new Map(nodes.map((node) => [node.id, node.label.trim() || '未命名节点']));
  const degrees = graphNodeDegrees(nodes, edges);
  const prominentNodeIds = prominentNetworkNodeIds(nodes, degrees);
  const selectedNeighbourIds = selectedNodeNeighbourIds(selection, edges);
  const nodeBoxes = new Map<string, ViewportNodeBox>();
  const baseNodes: ViewportFlowNode[] = nodes.map((node) => {
    const degree = degrees.get(node.id) ?? 0;
    const box = resolveNodeBox(node, presentation, degree);
    const resolvedPosition = isFinitePosition(node.position)
      ? node.position
      : networkPositions?.get(node.id);
    nodeBoxes.set(node.id, box);
    return {
      id: node.id,
      type: 'graphViewportNode',
      position: resolvedPosition
        ? { x: resolvedPosition.x, y: resolvedPosition.y }
        : { x: 0, y: 0 },
      data: {
        graphNode: node,
        presentation,
        prominentLabel: presentation === 'network' && prominentNodeIds.has(node.id),
        dimmed: presentation === 'network'
          && selectedNeighbourIds !== null
          && !selectedNeighbourIds.has(node.id),
        degree,
      },
      selected: selection?.kind === 'node' && selection.id === node.id,
      draggable: false,
      connectable: false,
      selectable: true,
      deletable: false,
      focusable: true,
      ariaRole: 'button',
      ariaLabel: `${node.type || '节点'}：${node.label || '未命名节点'}`,
      style: { width: box.width, height: box.height },
    };
  });
  const provisionalEdges: ViewportFlowEdge[] = edges.map((edge) => {
    const edgeSelected = selection?.kind === 'edge' && selection.id === edge.id;
    const touchesSelectedNode = selection?.kind === 'node'
      && (edge.source === selection.id || edge.target === selection.id);
    const networkOpacity = selection
      ? edgeSelected || touchesSelectedNode ? 0.94 : 0.13
      : 0.68;
    const networkWidth = edgeSelected ? 2.2 : touchesSelectedNode ? 1.7 : 1.05;
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'graphViewportEdge',
      data: { graphEdge: edge },
      selected: edgeSelected,
      selectable: true,
      deletable: false,
      reconnectable: false,
      focusable: true,
      ariaRole: 'button',
      ariaLabel: `${nodeLabels.get(edge.source) ?? edge.source} ${edge.relation || '关联'} ${nodeLabels.get(edge.target) ?? edge.target}`,
      style: {
        stroke: edgeStroke(edge.relation),
        strokeWidth: presentation === 'network'
          ? networkWidth
          : edgeSelected ? 2.2 : 1.35,
        opacity: presentation === 'network'
          ? networkOpacity
          : selection && !edgeSelected ? 0.42 : 0.9,
      },
    };
  });
  const positioned = preservePositions
    ? { nodes: baseNodes, edges: provisionalEdges }
    : layoutWithDagre(baseNodes, provisionalEdges, {
        nodeWidth: NODE_MIN_WIDTH,
        nodeHeight: NODE_MIN_HEIGHT,
        rankdir: layoutDirection === 'horizontal' ? 'LR' : 'TB',
        ranksep: layoutDirection === 'horizontal' ? 104 : 86,
        nodesep: 42,
        staggerRankSiblings: false,
      });
  const nodePositions = new Map(positioned.nodes.map((node) => [node.id, node.position]));
  const routedEdges = provisionalEdges.map((edge) => {
    const sourcePosition = nodePositions.get(edge.source);
    const targetPosition = nodePositions.get(edge.target);
    const sourceBox = nodeBoxes.get(edge.source);
    const targetBox = nodeBoxes.get(edge.target);
    if (!sourcePosition || !targetPosition || !sourceBox || !targetBox) return edge;
    const graphEdge = edge.data?.graphEdge;
    if (!graphEdge) return edge;
    const direction = graphEdge.direction;
    const geometry = getGraphEdgeGeometry({
      sourceId: edge.source,
      targetId: edge.target,
      sourceRect: {
        x: sourcePosition.x,
        y: sourcePosition.y,
        width: sourceBox.width,
        height: sourceBox.height,
        borderRadius: sourceBox.borderRadius,
      },
      targetRect: {
        x: targetPosition.x,
        y: targetPosition.y,
        width: targetBox.width,
        height: targetBox.height,
        borderRadius: targetBox.borderRadius,
      },
      direction,
      pathKind: 'straight',
    });
    return {
      ...edge,
      ...handlePair(
        boxCenter(sourcePosition, sourceBox),
        boxCenter(targetPosition, targetBox),
      ),
      data: {
        graphEdge,
        geometryPath: geometry.ok ? geometry.path : undefined,
      },
    };
  });
  return { nodes: positioned.nodes as ViewportFlowNode[], edges: routedEdges };
}

interface NetworkNodeTone {
  readonly background: string;
  readonly border: string;
  readonly core: string;
}

function networkNodeTone(type: string): NetworkNodeTone {
  switch (type) {
    case 'paper':
    case 'material':
    case 'source':
    case 'evidence':
      return {
        background: 'hsl(170 50% 40% / 0.20)',
        border: 'hsl(170 50% 40% / 0.76)',
        core: 'hsl(170 50% 34% / 0.92)',
      };
    case 'claim':
    case 'finding':
    case 'insight':
    case 'concept':
      return {
        background: 'hsl(var(--primary) / 0.18)',
        border: 'hsl(var(--primary) / 0.76)',
        core: 'hsl(var(--primary) / 0.94)',
      };
    case 'method':
    case 'dataset':
    case 'metric':
      return {
        background: 'hsl(38 70% 50% / 0.17)',
        border: 'hsl(38 70% 46% / 0.70)',
        core: 'hsl(38 68% 42% / 0.92)',
      };
    default:
      return {
        background: 'hsl(var(--foreground) / 0.10)',
        border: 'hsl(var(--outline) / 0.78)',
        core: 'hsl(var(--foreground) / 0.72)',
      };
  }
}

function NetworkGraphNodeRenderer({ data, selected }: NodeProps<ViewportFlowNode>) {
  const entry = data.graphNode;
  const tone = networkNodeTone(entry.type);
  const status = typeof entry.status === 'string' ? entry.status.trim() : '';
  const label = entry.label.trim() || '未命名节点';
  const labelVisible = selected || data.prominentLabel;
  return (
    <div
      className={cn(
        'nodrag nopan group relative flex h-full w-full cursor-pointer items-center justify-center rounded-full border-2 transition-[border-color,box-shadow,opacity,transform] duration-150 motion-reduce:transition-none',
        selected
          ? 'z-20 scale-110 ring-2 ring-primary/25 ring-offset-2 ring-offset-surface-lowest'
          : 'hover:z-20 hover:scale-110 hover:shadow-md',
        data.dimmed ? 'opacity-20' : 'opacity-100',
      )}
      style={{
        background: tone.background,
        borderColor: tone.border,
        boxShadow: selected ? `0 0 0 1px ${tone.border}, 0 8px 24px hsl(var(--foreground) / 0.12)` : undefined,
      }}
      data-graph-node-id={entry.id}
      data-graph-node-type={entry.type}
      data-graph-node-presentation="network"
      data-network-degree={data.degree}
      data-network-prominent-label={data.prominentLabel ? 'true' : 'false'}
      data-selected={selected ? 'true' : 'false'}
      data-dimmed={data.dimmed ? 'true' : 'false'}
      title={`${entry.type || '节点'}：${label}`}
    >
      <GraphViewportHandles />
      <span
        aria-hidden
        className="size-[28%] min-h-1 min-w-1 rounded-full"
        style={{ background: tone.core }}
      />
      <span
        className={cn(
          'pointer-events-none absolute left-1/2 top-[calc(100%+0.35rem)] z-30 w-max max-w-[15rem] -translate-x-1/2 rounded-md border border-outline-variant/55 bg-surface-lowest/95 px-2 py-1 text-center text-[11px] leading-4 text-foreground shadow-sm backdrop-blur-sm transition-opacity duration-150 motion-reduce:transition-none',
          labelVisible ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
        )}
      >
        <span className="line-clamp-2 block break-words font-medium">{label}</span>
        {selected ? (
          <span className="mt-0.5 block text-[9px] text-foreground/48">
            {entry.type || '节点'}{status ? ` · ${status}` : ''}
          </span>
        ) : null}
      </span>
    </div>
  );
}

function GraphViewportNodeRenderer(props: NodeProps<ViewportFlowNode>) {
  if (props.data.presentation === 'network') {
    return <NetworkGraphNodeRenderer {...props} />;
  }
  const { data, selected } = props;
  const entry = data.graphNode;
  const status = typeof entry.status === 'string' ? entry.status.trim() : '';
  return (
    <div
      className={cn(
        'nodrag nopan relative flex h-full w-full min-w-0 flex-col justify-center overflow-hidden rounded-lg border bg-surface-lowest px-3.5 py-2.5 text-foreground shadow-sm transition-[border-color,box-shadow,opacity] duration-150',
        selected
          ? 'border-primary shadow-md ring-2 ring-primary/20'
          : 'border-outline-variant/80 hover:border-outline hover:shadow-md',
      )}
      data-graph-node-id={entry.id}
      data-graph-node-type={entry.type}
      data-selected={selected ? 'true' : 'false'}
    >
      <GraphViewportHandles />
      <div className="flex min-w-0 items-center gap-2 text-[10px] font-medium text-foreground/52">
        <span className="min-w-0 truncate">{entry.type || '节点'}</span>
        {status ? (
          <span className="ml-auto max-w-[7.5rem] shrink-0 truncate rounded-sm bg-surface-high px-1.5 py-0.5 text-foreground/60">
            {status}
          </span>
        ) : null}
      </div>
      <div className="mt-1 line-clamp-3 min-w-0 break-words text-[13px] font-medium leading-[18px] text-foreground">
        {entry.label.trim() || '未命名节点'}
      </div>
    </div>
  );
}

function GraphViewportHandles() {
  return (
    <>
      <Handle id={TARGET_LEFT} type="target" position={Position.Left} className={HANDLE_CLASS} />
      <Handle id={SOURCE_LEFT} type="source" position={Position.Left} className={HANDLE_CLASS} />
      <Handle id={TARGET_RIGHT} type="target" position={Position.Right} className={HANDLE_CLASS} />
      <Handle id={SOURCE_RIGHT} type="source" position={Position.Right} className={HANDLE_CLASS} />
      <Handle id={TARGET_TOP} type="target" position={Position.Top} className={HANDLE_CLASS} />
      <Handle id={SOURCE_TOP} type="source" position={Position.Top} className={HANDLE_CLASS} />
      <Handle id={TARGET_BOTTOM} type="target" position={Position.Bottom} className={HANDLE_CLASS} />
      <Handle id={SOURCE_BOTTOM} type="source" position={Position.Bottom} className={HANDLE_CLASS} />
    </>
  );
}

function GraphViewportEdgeRenderer(props: EdgeProps<ViewportFlowEdge>) {
  const reactId = useId();
  const direction = props.data?.graphEdge.direction ?? 'directed';
  const nearlyAligned = Math.abs(props.sourceX - props.targetX) <= 2
    || Math.abs(props.sourceY - props.targetY) <= 2;
  const [fallbackPath] = nearlyAligned
    ? getStraightPath({
      sourceX: props.sourceX,
      sourceY: props.sourceY,
      targetX: props.targetX,
      targetY: props.targetY,
    })
    : getBezierPath({
      sourceX: props.sourceX,
      sourceY: props.sourceY,
      sourcePosition: props.sourcePosition,
      targetX: props.targetX,
      targetY: props.targetY,
      targetPosition: props.targetPosition,
      curvature: 0.12,
    });
  const path = props.data?.geometryPath ?? fallbackPath;
  const markerId = `graph-viewport-arrow-${reactId.replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const markerColor = typeof props.style?.stroke === 'string'
    ? props.style.stroke
    : 'hsl(var(--outline))';

  return (
    <>
      {direction === 'directed' ? (
        <defs>
          <marker
            id={markerId}
            viewBox="0 0 8 8"
            markerWidth="8"
            markerHeight="8"
            refX="8"
            refY="4"
            markerUnits="userSpaceOnUse"
            orient="auto-start-reverse"
            overflow="visible"
          >
            <path d="M 0 0 L 8 4 L 0 8 Z" fill={markerColor} />
          </marker>
        </defs>
      ) : null}
      <BaseEdge
        id={props.id}
        path={path}
        markerEnd={direction === 'directed' ? `url(#${markerId})` : undefined}
        interactionWidth={20}
        style={{
          strokeLinecap: 'round',
          strokeLinejoin: 'round',
          vectorEffect: 'non-scaling-stroke',
          ...props.style,
        }}
      />
    </>
  );
}

function clamp(value: number | undefined, min: number, max: number, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

function resolveFit(fit: GraphViewportFit | false | undefined): ResolvedFit | null {
  if (fit === false) return null;
  const minZoom = clamp(fit?.minZoom, 0.05, 1.8, 0.22);
  const maxZoom = Math.max(minZoom, clamp(fit?.maxZoom, minZoom, 2, 1.12));
  const reduceMotion = typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
  return {
    initially: fit?.initially ?? true,
    onDataChange: fit?.onDataChange ?? true,
    requestKey: fit?.requestKey,
    options: {
      padding: clamp(fit?.padding, 0, 1, 0.16),
      minZoom,
      maxZoom,
      duration: reduceMotion ? 0 : clamp(fit?.duration, 0, 2_000, 220),
    },
  };
}

function FitViewController({
  signature,
  fit,
}: {
  signature: string;
  fit: ResolvedFit;
}) {
  const { fitView } = useReactFlow();
  const previousSignature = useRef(signature);
  const previousRequestKey = useRef<string | number | undefined>(undefined);

  useEffect(() => {
    const dataChanged = previousSignature.current !== signature;
    const requestChanged = fit.requestKey !== undefined
      && previousRequestKey.current !== fit.requestKey;
    previousSignature.current = signature;
    previousRequestKey.current = fit.requestKey;
    if ((!fit.onDataChange || !dataChanged) && !requestChanged) return undefined;
    const timeoutId = window.setTimeout(() => {
      void fitView(fit.options);
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [fit, fitView, signature]);

  return null;
}

function StateShell({
  className,
  role,
  children,
}: {
  className?: string;
  role: 'alert' | 'status';
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        'flex h-full min-h-[280px] w-full items-center justify-center rounded-md border border-dashed border-outline-variant/60 bg-surface-low p-6 text-center text-sm text-foreground/58',
        className,
      )}
      role={role}
      aria-live={role === 'alert' ? 'assertive' : 'polite'}
    >
      {children}
    </div>
  );
}

/**
 * Shared read-only graph canvas. It owns presentation only: no Wiki API, review hook,
 * mutation command, or domain projector is imported here.
 */
export function GraphViewport<
  NodeDto extends GraphViewportNode = GraphViewportNode,
  EdgeDto extends GraphViewportEdge = GraphViewportEdge,
>({
  nodes,
  edges,
  selection,
  filters,
  fit,
  layoutDirection = 'horizontal',
  presentation = 'cards',
  loading = false,
  error = null,
  className,
  ariaLabel = '只读知识图谱',
  emptyMessage = '暂无可显示的图谱数据。',
  onNodeSelect,
  onEdgeSelect,
  onSelectionClear,
  onResetFilters,
  onRetry,
}: GraphViewportProps<NodeDto, EdgeDto>) {
  const filtered = useMemo(
    () => filterGraphViewport(nodes, edges, filters),
    [edges, filters, nodes],
  );
  const networkPositions = useMemo(
    () => resolveNetworkPositions(filtered.nodes, filtered.edges, presentation),
    [filtered.edges, filtered.nodes, presentation],
  );
  const flowGraph = useMemo(
    () => toFlowGraph(
      filtered.nodes,
      filtered.edges,
      selection,
      layoutDirection,
      presentation,
      networkPositions,
    ),
    [filtered.edges, filtered.nodes, layoutDirection, networkPositions, presentation, selection],
  );
  const resolvedFit = useMemo(() => resolveFit(fit), [fit]);
  const signature = useMemo(
    () => `${flowGraph.nodes.map((node) => (
      `${node.id}@${node.position.x},${node.position.y}:${String(node.style?.width)}x${String(node.style?.height)}`
    )).join('|')}::${flowGraph.edges.map((edge) => `${edge.id}:${edge.source}>${edge.target}`).join('|')}`,
    [flowGraph.edges, flowGraph.nodes],
  );
  const performanceMode = flowGraph.nodes.length > PERFORMANCE_NODE_THRESHOLD
    || flowGraph.edges.length > PERFORMANCE_EDGE_THRESHOLD;
  const visibleNodesById = useMemo(
    () => new Map(filtered.nodes.map((node) => [node.id, node])),
    [filtered.nodes],
  );
  const visibleEdgesById = useMemo(
    () => new Map(filtered.edges.map((edge) => [edge.id, edge])),
    [filtered.edges],
  );

  if (error) {
    return (
      <StateShell className={className} role="alert">
        <div className="flex max-w-md flex-col items-center gap-2">
          <AlertTriangle className="size-5 text-red-500/80" aria-hidden />
          <span>{error}</span>
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="mt-1 inline-flex min-h-8 items-center gap-1.5 rounded-md border border-outline-variant/70 bg-surface-lowest px-3 text-xs text-foreground/72 transition-colors hover:border-primary/45 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
            >
              <RotateCcw className="size-3.5" aria-hidden />
              重新加载
            </button>
          ) : null}
        </div>
      </StateShell>
    );
  }

  if (loading) {
    return (
      <StateShell className={className} role="status">
        <div className="flex items-center gap-2">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
          <span>正在加载图谱…</span>
        </div>
      </StateShell>
    );
  }

  if (flowGraph.nodes.length === 0) {
    const filteredEmpty = filtered.hasActiveFilters && nodes.length > 0;
    return (
      <StateShell className={className} role="status">
        <div className="flex max-w-md flex-col items-center gap-2">
          <span>{filteredEmpty ? '当前筛选没有匹配的节点或关系。' : emptyMessage}</span>
          {filteredEmpty && onResetFilters ? (
            <button
              type="button"
              onClick={onResetFilters}
              className="inline-flex min-h-8 items-center rounded-md border border-outline-variant/70 bg-surface-lowest px-3 text-xs text-foreground/72 transition-colors hover:border-primary/45 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35"
            >
              清除筛选
            </button>
          ) : null}
        </div>
      </StateShell>
    );
  }

  return (
    <div className={cn('relative h-full min-h-[280px] w-full overflow-hidden bg-surface-lowest', className)}>
      <ReactFlowProvider>
        <ReactFlow<ViewportFlowNode, ViewportFlowEdge>
          aria-label={ariaLabel}
          nodes={flowGraph.nodes}
          edges={flowGraph.edges}
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          fitView={resolvedFit?.initially ?? false}
          fitViewOptions={resolvedFit?.options}
          minZoom={0.18}
          maxZoom={1.8}
          onlyRenderVisibleElements={performanceMode}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesReconnectable={false}
          elementsSelectable
          nodesFocusable
          edgesFocusable
          disableKeyboardA11y={false}
          selectNodesOnDrag={false}
          selectionOnDrag={false}
          connectOnClick={false}
          deleteKeyCode={null}
          panOnDrag
          panOnScroll
          zoomOnPinch
          zoomOnDoubleClick
          proOptions={{ hideAttribution: true }}
          onNodeClick={(_, node) => {
            const raw = node.data.graphNode as NodeDto;
            onNodeSelect?.(raw);
          }}
          onEdgeClick={(_, edge) => {
            const raw = edge.data?.graphEdge as EdgeDto | undefined;
            if (raw) onEdgeSelect?.(raw);
          }}
          onPaneClick={() => onSelectionClear?.()}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              onSelectionClear?.();
              return;
            }
            if (event.key !== 'Enter' && event.key !== ' ') return;
            const target = event.target;
            if (!(target instanceof Element)) return;
            const nodeId = target.closest<HTMLElement>('.react-flow__node')?.dataset.id;
            if (nodeId) {
              const node = visibleNodesById.get(nodeId);
              if (node) {
                event.preventDefault();
                onNodeSelect?.(node);
              }
              return;
            }
            const edgeId = target.closest<SVGGElement>('.react-flow__edge')?.dataset.id;
            if (!edgeId) return;
            const edge = visibleEdgesById.get(edgeId);
            if (edge) {
              event.preventDefault();
              onEdgeSelect?.(edge);
            }
          }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={20}
            size={1}
            color="hsl(var(--outline-variant) / 0.42)"
          />
          {resolvedFit ? <FitViewController signature={signature} fit={resolvedFit} /> : null}
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}

export default GraphViewport;
