import type { Edge, Node } from '@xyflow/react';

import { layoutWithDagre } from './layoutWithDagre';
import {
  DIMENSION_BUS_EDGE_TYPE,
  DIMENSION_SOURCE_BOTTOM_HANDLE,
  DIMENSION_SOURCE_LEFT_HANDLE,
  DIMENSION_SOURCE_RIGHT_HANDLE,
  DIMENSION_TARGET_LEFT_HANDLE,
  DIMENSION_TARGET_RIGHT_HANDLE,
  DIMENSION_TARGET_TOP_HANDLE,
  type DimensionBusEdgeData,
  type DimensionEdgeDensity,
} from './DimensionBusEdge';
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
const COMPACT_COLUMN_THRESHOLD = 6;
const MATRIX_COLUMN_THRESHOLD = 18;
const COMPACT_NODE_HEIGHT = 96;
const MATRIX_NODE_HEIGHT = 86;

export interface DimensionLayoutOptions {
  laneWidth?: number;
  lanePadding?: number;
  nodeWidth?: number;
  nodeHeight?: number;
  verticalGap?: number;
  laneTopPadding?: number;
  /** 隐藏没有节点的泳道，默认开。 */
  hideEmptyLanes?: boolean;
  density?: DimensionEdgeDensity;
}

export interface DimensionLane {
  dimension: ReasoningDimension;
  x: number;
  y?: number;
  width: number;
  height?: number;
  /** 泳道头标签（label + 节点数） */
  title: string;
}

export interface DimensionLayoutResult {
  nodes: Node[];
  edges: Edge[];
  lanes: DimensionLane[];
  total: { width: number; height: number };
  density: DimensionEdgeDensity;
  layoutMode: 'linear' | 'folded';
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
    type: DIMENSION_BUS_EDGE_TYPE,
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

function resolveDensity(
  graph: DimensionGraph,
  value: DimensionEdgeDensity | undefined,
): DimensionEdgeDensity {
  if (value) {
    return value;
  }
  const totalNodes = graph.nodes.length;
  const maxLaneNodes = Math.max(0, ...REASONING_DIMENSIONS.map((dimension) => (
    graph.nodes.filter((entry) => entry.dimension === dimension).length
  )));
  if (totalNodes >= 36 || maxLaneNodes >= MATRIX_COLUMN_THRESHOLD) {
    return 'matrix';
  }
  if (totalNodes >= 15 || maxLaneNodes >= COMPACT_COLUMN_THRESHOLD) {
    return 'compact';
  }
  return 'comfortable';
}

function columnsForLane(count: number, density: DimensionEdgeDensity): number {
  if (count <= 0) {
    return 1;
  }
  if (density === 'matrix') {
    if (count <= 9) {
      return count;
    }
    return Math.max(1, Math.ceil(count / 3));
  }
  if (density === 'compact') {
    return count >= COMPACT_COLUMN_THRESHOLD ? Math.max(2, Math.ceil(count / 3)) : count;
  }
  return count > COMPACT_COLUMN_THRESHOLD ? 1 : count;
}

function nodeHeightForDensity(base: number, density: DimensionEdgeDensity): number {
  if (density === 'matrix') {
    return Math.min(base, MATRIX_NODE_HEIGHT);
  }
  if (density === 'compact') {
    return Math.min(base, COMPACT_NODE_HEIGHT);
  }
  return base;
}

function laneWidthForDensity(
  baseLaneWidth: number,
  nodeWidth: number,
  columns: number,
  lanePadding: number,
): number {
  if (columns <= 1) {
    return baseLaneWidth;
  }
  return Math.max(baseLaneWidth, columns * nodeWidth + Math.max(1, columns - 1) * Math.max(24, lanePadding));
}

function sourceTargetLane(
  lanes: DimensionLane[],
  nodeDimension: Map<string, ReasoningDimension>,
  nodeId: string,
): DimensionLane | undefined {
  const dimension = nodeDimension.get(nodeId);
  return dimension ? lanes.find((lane) => lane.dimension === dimension) : undefined;
}

interface LayoutRect {
  id: string;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function layoutRects(
  positions: Map<string, { x: number; y: number }>,
  nodeWidth: number,
  nodeHeight: number,
): LayoutRect[] {
  return Array.from(positions.entries()).map(([id, position]) => ({
    id,
    left: position.x,
    right: position.x + nodeWidth,
    top: position.y,
    bottom: position.y + nodeHeight,
  }));
}

function rangesOverlap(a1: number, a2: number, b1: number, b2: number): boolean {
  return Math.max(Math.min(a1, a2), Math.min(b1, b2)) < Math.min(Math.max(a1, a2), Math.max(b1, b2));
}

function verticalSegmentHitsRect(x: number, y1: number, y2: number, rect: LayoutRect): boolean {
  return x > rect.left + 3
    && x < rect.right - 3
    && rangesOverlap(y1, y2, rect.top + 3, rect.bottom - 3);
}

function horizontalSegmentHitsRect(y: number, x1: number, x2: number, rect: LayoutRect): boolean {
  return y > rect.top + 3
    && y < rect.bottom - 3
    && rangesOverlap(x1, x2, rect.left + 3, rect.right - 3);
}

function crossLaneCandidateCollides(
  candidateX: number,
  rects: LayoutRect[],
  sourceId: string,
  targetId: string,
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
): boolean {
  for (const rect of rects) {
    if (rect.id === sourceId || rect.id === targetId) {
      continue;
    }
    if (verticalSegmentHitsRect(candidateX, sourceY, targetY, rect)) {
      return true;
    }
    if (horizontalSegmentHitsRect(sourceY, sourceX, candidateX, rect)) {
      return true;
    }
    if (horizontalSegmentHitsRect(targetY, candidateX, targetX, rect)) {
      return true;
    }
  }
  return false;
}

function crossLaneSideCandidateCollides(
  candidateX: number,
  rects: LayoutRect[],
  sourceId: string,
  targetId: string,
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
): boolean {
  for (const rect of rects) {
    if (rect.id === sourceId || rect.id === targetId) {
      continue;
    }
    if (horizontalSegmentHitsRect(sourceY, sourceX, candidateX, rect)) {
      return true;
    }
    if (verticalSegmentHitsRect(candidateX, sourceY, targetY, rect)) {
      return true;
    }
    if (horizontalSegmentHitsRect(targetY, candidateX, targetX, rect)) {
      return true;
    }
  }
  return false;
}

function sameLaneCandidateCollides(
  candidateY: number,
  rects: LayoutRect[],
  sourceId: string,
  targetId: string,
  sourceX: number,
  sourceY: number,
  sourceLeadX: number,
  targetX: number,
  targetY: number,
  targetLeadX: number,
): boolean {
  for (const rect of rects) {
    if (rect.id === sourceId || rect.id === targetId) {
      continue;
    }
    if (horizontalSegmentHitsRect(sourceY, sourceX, sourceLeadX, rect)) {
      return true;
    }
    if (verticalSegmentHitsRect(sourceLeadX, sourceY, candidateY, rect)) {
      return true;
    }
    if (horizontalSegmentHitsRect(candidateY, sourceLeadX, targetLeadX, rect)) {
      return true;
    }
    if (verticalSegmentHitsRect(targetLeadX, candidateY, targetY, rect)) {
      return true;
    }
    if (horizontalSegmentHitsRect(targetY, targetLeadX, targetX, rect)) {
      return true;
    }
  }
  return false;
}

function uniqueCandidates(values: number[]): number[] {
  const seen = new Set<number>();
  const out: number[] = [];
  for (const value of values) {
    if (!Number.isFinite(value)) {
      continue;
    }
    const rounded = Math.round(value * 100) / 100;
    if (seen.has(rounded)) {
      continue;
    }
    seen.add(rounded);
    out.push(rounded);
  }
  return out;
}

function rowCorridorCandidates(rects: LayoutRect[], preferredY: number, nodeHeight: number): number[] {
  const bands = rects
    .map((rect) => ({ top: rect.top, bottom: rect.bottom }))
    .sort((a, b) => a.top - b.top || a.bottom - b.bottom);
  const sameRow = bands.filter((band) => preferredY > band.top + 3 && preferredY < band.bottom - 3);
  const sameRowTop = Math.min(...sameRow.map((band) => band.top));
  const sameRowBottom = Math.max(...sameRow.map((band) => band.bottom));
  const candidates: number[] = [preferredY];
  if (Number.isFinite(sameRowTop) && Number.isFinite(sameRowBottom)) {
    const offset = Math.min(12, nodeHeight / 8);
    candidates.push(sameRowTop - offset);
    candidates.push(sameRowBottom + offset);
  }
  for (let index = 0; index < bands.length - 1; index += 1) {
    const gap = bands[index + 1].top - bands[index].bottom;
    if (gap > 8) {
      candidates.push(bands[index].bottom + gap / 2);
    }
  }
  if (bands.length > 0) {
    const outerOffset = Math.min(24, nodeHeight / 3);
    candidates.push(bands[0].top - outerOffset);
    candidates.push(bands[bands.length - 1].bottom + outerOffset);
  }
  return uniqueCandidates(candidates);
}

function clearSameLaneCorridorY(
  edge: Edge,
  positions: Map<string, { x: number; y: number }>,
  nodeWidth: number,
  nodeHeight: number,
  sourceIsLeft: boolean,
  lead: number,
): number {
  const source = positions.get(edge.source);
  const target = positions.get(edge.target);
  if (!source || !target) {
    return 0;
  }
  const rects = layoutRects(positions, nodeWidth, nodeHeight);
  const sourceX = sourceIsLeft ? source.x + nodeWidth : source.x;
  const targetX = sourceIsLeft ? target.x : target.x + nodeWidth;
  const sourceY = source.y + nodeHeight / 2;
  const targetY = target.y + nodeHeight / 2;
  const sourceLeadX = sourceX + (sourceIsLeft ? lead : -lead);
  const targetLeadX = targetX + (sourceIsLeft ? -lead : lead);
  const ranked = rowCorridorCandidates(rects, sourceY, nodeHeight)
    .map((candidate) => {
      const collides = sameLaneCandidateCollides(
        candidate,
        rects,
        edge.source,
        edge.target,
        sourceX,
        sourceY,
        sourceLeadX,
        targetX,
        targetY,
        targetLeadX,
      );
      const excess = Math.abs(candidate - sourceY) + Math.abs(targetY - candidate) - Math.abs(targetY - sourceY);
      return {
        candidate,
        score: (collides ? 1_000_000 : 0) + Math.max(0, excess) * 10 + Math.abs(candidate - sourceY),
      };
    })
    .sort((a, b) => a.score - b.score);
  return ranked[0]?.candidate ?? sourceY;
}

function clearCrossLaneCorridorX(
  edge: Edge,
  positions: Map<string, { x: number; y: number }>,
  nodeWidth: number,
  nodeHeight: number,
  index: number,
): number {
  const source = positions.get(edge.source);
  const target = positions.get(edge.target);
  if (!source || !target) {
    return 0;
  }
  const rects = layoutRects(positions, nodeWidth, nodeHeight);
  const sourceX = source.x + nodeWidth / 2;
  const sourceY = source.y + nodeHeight;
  const targetX = target.x + nodeWidth / 2;
  const targetY = target.y;
  const sideCandidates = [
    source.x - 1,
    source.x + nodeWidth + 1,
    target.x - 1,
    target.x + nodeWidth + 1,
  ];
  const minX = Math.min(...rects.map((rect) => rect.left));
  const maxX = Math.max(...rects.map((rect) => rect.right));
  const blockers = rects
    .filter((rect) => rect.id !== edge.source && rect.id !== edge.target)
    .filter((rect) => rangesOverlap(sourceY, targetY, rect.top + 3, rect.bottom - 3))
    .sort((a, b) => a.left - b.left);
  const gutterCandidates: number[] = [];
  for (let i = 0; i < blockers.length - 1; i += 1) {
    const gap = blockers[i + 1].left - blockers[i].right;
    if (gap > 10) {
      gutterCandidates.push(blockers[i].right + gap / 2);
    }
  }
  gutterCandidates.push(minX - 24, maxX + 24);
  const spanLeft = Math.min(sourceX, targetX);
  const spanRight = Math.max(sourceX, targetX);
  const fanOffset = ((index % 5) - 2) * 14;
  const candidates = uniqueCandidates([
    targetX + fanOffset,
    targetX,
    sourceX + fanOffset,
    sourceX,
    ...sideCandidates,
    (sourceX + targetX) / 2,
    ...gutterCandidates.filter((candidate) => candidate >= spanLeft && candidate <= spanRight),
    ...gutterCandidates,
  ]);
  const ranked = candidates
    .map((candidate) => {
      const collides = sideCandidates.some((sideCandidate) => Math.abs(sideCandidate - candidate) < 0.01)
        ? crossLaneSideCandidateCollides(
          candidate,
          rects,
          edge.source,
          edge.target,
          sourceX,
          sourceY,
          targetX,
          targetY,
        )
        : crossLaneCandidateCollides(
        candidate,
        rects,
        edge.source,
        edge.target,
        sourceX,
        sourceY,
        targetX,
        targetY,
      );
      const excess = Math.abs(candidate - sourceX) + Math.abs(targetX - candidate) - Math.abs(targetX - sourceX);
      const desired = targetX + fanOffset;
      return {
        candidate,
        score: (collides ? 1_000_000 : 0) + Math.max(0, excess) * 10 + Math.abs(candidate - desired),
      };
    })
    .sort((a, b) => a.score - b.score);
  return ranked[0]?.candidate ?? targetX;
}

function clearBlockedSameColumnCrossLaneRoute(
  edge: Edge,
  positions: Map<string, { x: number; y: number }>,
  nodeWidth: number,
  nodeHeight: number,
): { side: 'left' | 'right'; corridorX: number } | null {
  const source = positions.get(edge.source);
  const target = positions.get(edge.target);
  if (!source || !target) {
    return null;
  }
  const sourceCenterX = source.x + nodeWidth / 2;
  const targetCenterX = target.x + nodeWidth / 2;
  if (Math.abs(sourceCenterX - targetCenterX) > nodeWidth * 0.5) {
    return null;
  }
  const rects = layoutRects(positions, nodeWidth, nodeHeight);
  const sourceBottomY = source.y + nodeHeight;
  const targetTopY = target.y;
  const centerBlocked = crossLaneCandidateCollides(
    sourceCenterX,
    rects,
    edge.source,
    edge.target,
    sourceCenterX,
    sourceBottomY,
    targetCenterX,
    targetTopY,
  );
  if (!centerBlocked) {
    return null;
  }
  const sourceCenterY = source.y + nodeHeight / 2;
  const targetCenterY = target.y + nodeHeight / 2;
  const sideOptions = [
    {
      side: 'right' as const,
      sourceX: source.x + nodeWidth,
      targetX: target.x + nodeWidth,
      corridorX: Math.max(source.x + nodeWidth, target.x + nodeWidth) + 1,
    },
    {
      side: 'left' as const,
      sourceX: source.x,
      targetX: target.x,
      corridorX: Math.min(source.x, target.x) - 1,
    },
  ];
  const ranked = sideOptions
    .map((option) => {
      const collides = crossLaneSideCandidateCollides(
        option.corridorX,
        rects,
        edge.source,
        edge.target,
        option.sourceX,
        sourceCenterY,
        option.targetX,
        targetCenterY,
      );
      const excess = Math.abs(option.corridorX - option.sourceX) + Math.abs(option.targetX - option.corridorX);
      return {
        ...option,
        score: (collides ? 1_000_000 : 0) + excess,
      };
    })
    .sort((a, b) => a.score - b.score);
  const best = ranked[0];
  return best && best.score < 1_000_000 ? { side: best.side, corridorX: best.corridorX } : null;
}

function resolveEdgeRoute(
  edge: Edge,
  positions: Map<string, { x: number; y: number }>,
  lanes: DimensionLane[],
  nodeDimension: Map<string, ReasoningDimension>,
  density: DimensionEdgeDensity,
  index: number,
  nodeWidth: number,
  nodeHeight: number,
): {
  sourceHandle: string;
  targetHandle: string;
  data: DimensionBusEdgeData;
} {
  const source = positions.get(edge.source);
  const target = positions.get(edge.target);
  const sourceLane = sourceTargetLane(lanes, nodeDimension, edge.source);
  const targetLane = sourceTargetLane(lanes, nodeDimension, edge.target);
  const sameLane = sourceLane?.dimension === targetLane?.dimension;
  const sourceCenterX = (source?.x ?? 0) + nodeWidth / 2;
  const targetCenterX = (target?.x ?? 0) + nodeWidth / 2;
  const sourceCenterY = (source?.y ?? 0) + nodeHeight / 2;
  const targetCenterY = (target?.y ?? 0) + nodeHeight / 2;
  const lead = density === 'matrix' ? 1 : 0;

  if (sameLane && source && target) {
    const sameColumn = Math.abs(sourceCenterX - targetCenterX) <= nodeWidth * 0.5;
    if (sameColumn && Math.abs(sourceCenterY - targetCenterY) > nodeHeight * 0.5) {
      const leftNeighborRight = Math.max(
        -Infinity,
        ...Array.from(positions.values())
          .filter((position) => position.x + nodeWidth < source.x)
          .map((position) => position.x + nodeWidth),
      );
      const railX = Number.isFinite(leftNeighborRight)
        ? (leftNeighborRight + source.x) / 2
        : source.x - 24;
      return {
        sourceHandle: DIMENSION_SOURCE_LEFT_HANDLE,
        targetHandle: DIMENSION_TARGET_LEFT_HANDLE,
        data: {
          raw: edge.data && typeof edge.data === 'object' ? (edge.data as Record<string, unknown>).raw : undefined,
          density,
          route: {
            mode: 'sideRail',
            sourceSide: 'left',
            targetSide: 'left',
            lead,
            railX,
          },
        },
      };
    }
    const sourceIsLeft = sourceCenterX <= targetCenterX;
    const corridorY = clearSameLaneCorridorY(edge, positions, nodeWidth, nodeHeight, sourceIsLeft, lead);
    return {
      sourceHandle: sourceIsLeft ? DIMENSION_SOURCE_RIGHT_HANDLE : DIMENSION_SOURCE_LEFT_HANDLE,
      targetHandle: sourceIsLeft ? DIMENSION_TARGET_LEFT_HANDLE : DIMENSION_TARGET_RIGHT_HANDLE,
      data: {
        raw: edge.data && typeof edge.data === 'object' ? (edge.data as Record<string, unknown>).raw : undefined,
        density,
        route: {
          mode: 'corridor',
          sourceSide: sourceIsLeft ? 'right' : 'left',
          targetSide: sourceIsLeft ? 'left' : 'right',
          lead,
          sourceLead: lead,
          targetLead: lead,
          corridorY,
        },
      },
    };
  }

  const blockedSameColumn = source && target
    ? clearBlockedSameColumnCrossLaneRoute(edge, positions, nodeWidth, nodeHeight)
    : null;
  if (blockedSameColumn) {
    return {
      sourceHandle: blockedSameColumn.side === 'right' ? DIMENSION_SOURCE_RIGHT_HANDLE : DIMENSION_SOURCE_LEFT_HANDLE,
      targetHandle: blockedSameColumn.side === 'right' ? DIMENSION_TARGET_RIGHT_HANDLE : DIMENSION_TARGET_LEFT_HANDLE,
      data: {
        raw: edge.data && typeof edge.data === 'object' ? (edge.data as Record<string, unknown>).raw : undefined,
        density,
        route: {
          mode: 'corridor',
          sourceSide: blockedSameColumn.side,
          targetSide: blockedSameColumn.side,
          lead: 1,
          sourceLead: 1,
          targetLead: 1,
          corridorX: blockedSameColumn.corridorX,
        },
      },
    };
  }

  const corridorX = clearCrossLaneCorridorX(edge, positions, nodeWidth, nodeHeight, index);
  return {
    sourceHandle: DIMENSION_SOURCE_BOTTOM_HANDLE,
    targetHandle: DIMENSION_TARGET_TOP_HANDLE,
    data: {
      raw: edge.data && typeof edge.data === 'object' ? (edge.data as Record<string, unknown>).raw : undefined,
      density,
      route: {
        mode: 'corridor',
        sourceSide: 'bottom',
        targetSide: 'top',
        lead: 0,
        sourceLead: 0,
        targetLead: 0,
        corridorX,
      },
    },
  };
}

export function layoutDimensionGraph(
  graph: DimensionGraph,
  options: DimensionLayoutOptions = {},
): DimensionLayoutResult {
  const density = resolveDensity(graph, options.density);
  const laneWidth = options.laneWidth ?? DEFAULT_LANE_WIDTH;
  const lanePadding = options.lanePadding ?? DEFAULT_LANE_PADDING;
  const nodeWidth = options.nodeWidth ?? DEFAULT_NODE_WIDTH;
  const nodeHeight = nodeHeightForDensity(options.nodeHeight ?? DEFAULT_NODE_HEIGHT, density);
  const verticalGap = density === 'matrix'
    ? Math.min(options.verticalGap ?? DEFAULT_NODE_VERTICAL_GAP, 12)
    : options.verticalGap ?? DEFAULT_NODE_VERTICAL_GAP;
  const laneTopPadding = options.laneTopPadding ?? DEFAULT_LANE_TOP_PADDING;
  const hideEmptyLanes = options.hideEmptyLanes ?? true;
  const layoutMode: DimensionLayoutResult['layoutMode'] = density === 'matrix' ? 'folded' : 'linear';

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
  const nodeDimension = new Map(graph.nodes.map((entry) => [entry.node.id, entry.dimension]));
  let maxRight = lanePadding + laneWidth;
  let maxBottom = laneTopPadding;

  const laneInputs = DIMENSION_DISPLAY_ORDER
    .map((dimension) => {
      const laneNodes = nodesByDimension.get(dimension) ?? [];
      const ordered = laidOutOrderForLane(laneNodes, dagrePositions);
      const columns = columnsForLane(ordered.length, density);
      const resolvedLaneWidth = laneWidthForDensity(laneWidth, nodeWidth, columns, lanePadding);
      const rows = Math.max(1, Math.ceil(Math.max(1, ordered.length) / columns));
      const height = Math.max(nodeHeight, rows * nodeHeight + Math.max(0, rows - 1) * verticalGap + laneTopPadding);
      return { dimension, laneNodes, ordered, columns, resolvedLaneWidth, height };
    })
    .filter((item) => !(hideEmptyLanes && item.laneNodes.length === 0));

  const splitIndex = density === 'matrix' ? 3 : Number.POSITIVE_INFINITY;
  const leftTrackWidth = Math.max(
    laneWidth,
    ...laneInputs.slice(0, splitIndex).map((item) => item.resolvedLaneWidth),
  );
  const rightTrackX = lanePadding + leftTrackWidth + lanePadding;
  const trackY = [laneTopPadding, laneTopPadding];

  for (const [laneIndex, item] of laneInputs.entries()) {
    const { dimension, laneNodes, ordered, columns, resolvedLaneWidth, height } = item;
    const track = laneIndex >= splitIndex ? 1 : 0;
    const laneX = density === 'matrix' && track === 1 ? rightTrackX : lanePadding;
    const laneY = trackY[track];
    const meta = DIMENSION_META[dimension];
    const laneTitle = `${meta.label} · ${laneNodes.length}`;
    orderedLanes.push({ dimension, x: laneX, y: laneY, width: resolvedLaneWidth, height, title: laneTitle });

    // 节点按维度水平带排布；同一维度内多节点横排，避免边线穿过节点。
    const columnGap = columns > 1 ? Math.max(24, lanePadding) : 0;
    const gridWidth = columns * nodeWidth + Math.max(0, columns - 1) * columnGap;
    const nodeStartX = laneX + (resolvedLaneWidth - gridWidth) / 2;
    for (const [index, entry] of ordered.entries()) {
      const column = index % columns;
      const row = Math.floor(index / columns);
      const nodeX = nodeStartX + column * (nodeWidth + columnGap);
      const nodeY = laneY + laneTopPadding + row * (nodeHeight + verticalGap);
      positionedNodeIndex.set(entry.node.id, { x: nodeX, y: nodeY });
      maxRight = Math.max(maxRight, nodeX + nodeWidth + lanePadding);
    }
    trackY[track] += height + lanePadding;
    maxRight = Math.max(maxRight, laneX + resolvedLaneWidth + lanePadding);
    maxBottom = Math.max(maxBottom, trackY[track]);
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
    const finalLanes: DimensionLane[] = [];
    let placeholderY = laneTopPadding;
    for (const item of laneInputs.length > 0 ? laneInputs : DIMENSION_DISPLAY_ORDER.map((dimension) => {
      const laneNodes = nodesByDimension.get(dimension) ?? [];
      const columns = columnsForLane(laneNodes.length, density);
      const resolvedLaneWidth = laneWidthForDensity(laneWidth, nodeWidth, columns, lanePadding);
      return { dimension, laneNodes, columns, resolvedLaneWidth, height: nodeHeight + laneTopPadding };
    })) {
      finalLanes.push({
        dimension: item.dimension,
        x: lanePadding,
        y: placeholderY,
        width: item.resolvedLaneWidth,
        height: item.height,
        title: `${DIMENSION_META[item.dimension].label} · ${item.laneNodes.length}`,
      });
      placeholderY += item.height + lanePadding;
    }
    const routedEdges = baseEdges.map((edge, index) => {
      const route = resolveEdgeRoute(edge, positionedNodeIndex, finalLanes, nodeDimension, density, index, nodeWidth, nodeHeight);
      return { ...edge, ...route };
    });
    return {
      nodes: positioned,
      edges: routedEdges,
      lanes: finalLanes,
      total: { width: Math.max(maxRight, lanePadding + laneWidth), height: Math.max(maxBottom + laneTopPadding, 320) },
      density,
      layoutMode,
    };
  }

  const routedEdges = baseEdges.map((edge, index) => {
    const route = resolveEdgeRoute(edge, positionedNodeIndex, orderedLanes, nodeDimension, density, index, nodeWidth, nodeHeight);
    return { ...edge, ...route };
  });

  return {
    nodes: positioned,
    edges: routedEdges,
    lanes: orderedLanes,
    total: { width: Math.max(maxRight, lanePadding + laneWidth), height: Math.max(maxBottom + laneTopPadding, 320) },
    density,
    layoutMode,
  };
}
