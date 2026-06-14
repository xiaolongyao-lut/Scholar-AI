import type { Edge, Node } from '@xyflow/react';

import { layoutWithDagre } from './layoutWithDagre';
import {
  DIMENSION_DISPLAY_ORDER,
  DIMENSION_META,
  REASONING_DIMENSIONS,
  type DimensionGraph,
  type DimensionGraphNode,
  type ReasoningDimension,
} from './dimensionGraph';

const DEFAULT_LANE_WIDTH = 300;
const DEFAULT_LANE_PADDING = 32;
const DEFAULT_NODE_WIDTH = 268;
const DEFAULT_NODE_HEIGHT = 110;
const DEFAULT_NODE_VERTICAL_GAP = 20;
const DEFAULT_LANE_TOP_PADDING = 56;

export interface DimensionLayoutOptions {
  laneWidth?: number;
  lanePadding?: number;
  nodeWidth?: number;
  nodeHeight?: number;
  verticalGap?: number;
  laneTopPadding?: number;
  /** 隐藏没有节点的泳道，默认开。 */
  hideEmptyLanes?: boolean;
}

export interface DimensionLane {
  dimension: ReasoningDimension;
  x: number;
  width: number;
  /** 泳道头标签（label + 节点数） */
  title: string;
}

export interface DimensionLayoutResult {
  nodes: Node[];
  edges: Edge[];
  lanes: DimensionLane[];
  total: { width: number; height: number };
}

interface NodeBoxOpts {
  nodeWidth: number;
  nodeHeight: number;
}

/**
 * 把同一泳道内的节点按拓扑顺序排序：先用 dagre 算出整体的「沿主轴顺序」，
 * 再把每条泳道里的节点 y 坐标按 dagre 输出的相对顺序排列。
 *
 * 输入：维度图 + 每个节点要做的 React Flow Node + 全部 edges。
 * 输出：每个节点的 (x, y) 落在对应泳道里，并附带泳道几何信息供绘制泳道头。
 */
function laidOutOrderForLane(
  laneNodes: DimensionGraphNode[],
  dagrePositions: Map<string, number>,
): DimensionGraphNode[] {
  return [...laneNodes].sort((a, b) => {
    const posA = dagrePositions.get(a.node.id) ?? 0;
    const posB = dagrePositions.get(b.node.id) ?? 0;
    if (posA !== posB) return posA - posB;
    // tie-break 让结果稳定：按 id。
    return a.node.id.localeCompare(b.node.id);
  });
}

function buildBaseNodes(graph: DimensionGraph, box: NodeBoxOpts): Node[] {
  return graph.nodes.map((entry) => ({
    id: entry.node.id,
    position: { x: 0, y: 0 },
    type: 'dimensionNode',
    data: {
      dimensionEntry: entry,
    },
    style: {
      width: box.nodeWidth,
      minHeight: box.nodeHeight,
    },
  }));
}

function buildBaseEdges(graph: DimensionGraph): Edge[] {
  const nodeIds = new Set(graph.nodes.map((entry) => entry.node.id));
  return graph.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)).map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.relation,
    data: { raw: edge },
    type: 'smoothstep',
  }));
}

/**
 * 用 dagre 跑一遍 LR 布局，主要目的是拿到「节点按主轴方向上的顺序」。
 * 我们不直接用 dagre 的坐标，而是用它给的相对位置在泳道里二次排版。
 */
function dagreOrderingMap(nodes: Node[], edges: Edge[]): Map<string, number> {
  const laid = layoutWithDagre(nodes, edges, {
    rankdir: 'LR',
    ranksep: 90,
    nodesep: 32,
    staggerRankSiblings: false,
  });
  const map = new Map<string, number>();
  for (const node of laid.nodes) {
    map.set(node.id, node.position.x);
  }
  return map;
}

export function layoutDimensionGraph(
  graph: DimensionGraph,
  options: DimensionLayoutOptions = {},
): DimensionLayoutResult {
  const laneWidth = options.laneWidth ?? DEFAULT_LANE_WIDTH;
  const lanePadding = options.lanePadding ?? DEFAULT_LANE_PADDING;
  const nodeWidth = options.nodeWidth ?? DEFAULT_NODE_WIDTH;
  const nodeHeight = options.nodeHeight ?? DEFAULT_NODE_HEIGHT;
  const verticalGap = options.verticalGap ?? DEFAULT_NODE_VERTICAL_GAP;
  const laneTopPadding = options.laneTopPadding ?? DEFAULT_LANE_TOP_PADDING;
  const hideEmptyLanes = options.hideEmptyLanes ?? true;

  const baseNodes = buildBaseNodes(graph, { nodeWidth, nodeHeight });
  const baseEdges = buildBaseEdges(graph);

  const dagrePositions = dagreOrderingMap(baseNodes, baseEdges);

  const nodesByDimension = new Map<ReasoningDimension, DimensionGraphNode[]>();
  for (const dimension of REASONING_DIMENSIONS) {
    nodesByDimension.set(dimension, []);
  }
  for (const entry of graph.nodes) {
    nodesByDimension.get(entry.dimension)?.push(entry);
  }

  const orderedLanes: DimensionLane[] = [];
  const positionedNodeIndex = new Map<string, { x: number; y: number }>();
  let cursorX = lanePadding;
  let maxBottom = laneTopPadding;

  for (const dimension of DIMENSION_DISPLAY_ORDER) {
    const laneNodes = nodesByDimension.get(dimension) ?? [];
    if (hideEmptyLanes && laneNodes.length === 0) continue;
    const ordered = laidOutOrderForLane(laneNodes, dagrePositions);
    const laneX = cursorX;
    const meta = DIMENSION_META[dimension];
    const laneTitle = `${meta.label} · ${laneNodes.length}`;
    orderedLanes.push({ dimension, x: laneX, width: laneWidth, title: laneTitle });

    // 节点居中放泳道里，左右各留一点空隙。
    const nodeX = laneX + (laneWidth - nodeWidth) / 2;
    let cursorY = laneTopPadding;
    for (const entry of ordered) {
      positionedNodeIndex.set(entry.node.id, { x: nodeX, y: cursorY });
      cursorY += nodeHeight + verticalGap;
    }
    if (cursorY > maxBottom) maxBottom = cursorY;
    cursorX += laneWidth + lanePadding;
  }

  const positioned: Node[] = baseNodes.map((node) => {
    const pos = positionedNodeIndex.get(node.id);
    if (!pos) {
      // 不应该发生：每个节点一定属于某条泳道。容错走默认位置，避免 React Flow 崩。
      return node;
    }
    return { ...node, position: pos };
  });

  // 给空泳道补一个 placeholder lane（hideEmptyLanes=false 时也展示标题），保持视觉稳定。
  if (!hideEmptyLanes) {
    let lanesCursor = lanePadding;
    const finalLanes: DimensionLane[] = [];
    for (const dimension of DIMENSION_DISPLAY_ORDER) {
      const count = nodesByDimension.get(dimension)?.length ?? 0;
      finalLanes.push({
        dimension,
        x: lanesCursor,
        width: laneWidth,
        title: `${DIMENSION_META[dimension].label} · ${count}`,
      });
      lanesCursor += laneWidth + lanePadding;
    }
    return {
      nodes: positioned,
      edges: baseEdges,
      lanes: finalLanes,
      total: { width: lanesCursor, height: Math.max(maxBottom + laneTopPadding, 320) },
    };
  }

  return {
    nodes: positioned,
    edges: baseEdges,
    lanes: orderedLanes,
    total: { width: cursorX, height: Math.max(maxBottom + laneTopPadding, 320) },
  };
}
