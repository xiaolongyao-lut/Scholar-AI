import type { Edge, Node } from '@xyflow/react';

import { layoutWithDagre } from './layoutWithDagre';
import {
  DIMENSION_BUS_EDGE_TYPE,
  DIMENSION_SOURCE_BOTTOM_HANDLE,
  DIMENSION_SOURCE_LEFT_HANDLE,
  DIMENSION_SOURCE_RIGHT_HANDLE,
  DIMENSION_SOURCE_TOP_HANDLE,
  DIMENSION_TARGET_BOTTOM_HANDLE,
  DIMENSION_TARGET_LEFT_HANDLE,
  DIMENSION_TARGET_RIGHT_HANDLE,
  DIMENSION_TARGET_TOP_HANDLE,
  type DimensionBusEdgeData,
  type DimensionBusRoute,
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

export type DimensionLayoutPresentation = 'legacy' | 'explorer' | 'rail' | 'network';

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
  /** 生产图谱使用 Evidence Spine；legacy 仅保留既有布局契约与回归覆盖。 */
  presentation?: DimensionLayoutPresentation;
}

export interface DimensionLane {
  dimension: ReasoningDimension;
  x: number;
  y?: number;
  width: number;
  height?: number;
  /** 泳道头标签（label + 节点数） */
  title: string;
  /** Evidence Spine 的列标题，只挂在该列第一条可见分组上。 */
  trackTitle?: string;
  trackKind?: 'support' | 'spine' | 'limits' | 'rail';
}

export interface DimensionLayoutResult {
  nodes: Node[];
  edges: Edge[];
  lanes: DimensionLane[];
  total: { width: number; height: number };
  density: DimensionEdgeDensity;
  layoutMode: 'linear' | 'folded' | 'spine' | 'rail' | 'network';
}

interface NodeBoxOpts {
  nodeWidth: number;
  nodeHeight: number;
  density: DimensionEdgeDensity;
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
      density: box.density,
    },
    style: {
      width: box.nodeWidth,
      height: box.nodeHeight,
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

type RouteSide = DimensionBusRoute['sourceSide'];

interface LayoutRect {
  id: string;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

interface LayoutPoint {
  x: number;
  y: number;
}

interface RouteCandidate {
  sourceHandle: string;
  targetHandle: string;
  data: DimensionBusEdgeData;
  points: LayoutPoint[];
  priority: number;
}

const ROUTE_INSET = 3;
const ROUTE_COLLISION_PENALTY = 1_000_000;

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
  return x > rect.left + ROUTE_INSET
    && x < rect.right - ROUTE_INSET
    && rangesOverlap(y1, y2, rect.top + ROUTE_INSET, rect.bottom - ROUTE_INSET);
}

function horizontalSegmentHitsRect(y: number, x1: number, x2: number, rect: LayoutRect): boolean {
  return y > rect.top + ROUTE_INSET
    && y < rect.bottom - ROUTE_INSET
    && rangesOverlap(x1, x2, rect.left + ROUTE_INSET, rect.right - ROUTE_INSET);
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

function sideSign(side: RouteSide): number {
  return side === 'right' || side === 'bottom' ? 1 : -1;
}

function isHorizontalSide(side: RouteSide): boolean {
  return side === 'left' || side === 'right';
}

function rectCenter(rect: LayoutRect): LayoutPoint {
  return {
    x: (rect.left + rect.right) / 2,
    y: (rect.top + rect.bottom) / 2,
  };
}

function pointForSide(rect: LayoutRect, side: RouteSide): LayoutPoint {
  switch (side) {
    case 'left':
      return { x: rect.left, y: (rect.top + rect.bottom) / 2 };
    case 'right':
      return { x: rect.right, y: (rect.top + rect.bottom) / 2 };
    case 'top':
      return { x: (rect.left + rect.right) / 2, y: rect.top };
    case 'bottom':
      return { x: (rect.left + rect.right) / 2, y: rect.bottom };
    default:
      return rectCenter(rect);
  }
}

function sourceHandleForSide(side: RouteSide): string {
  switch (side) {
    case 'left':
      return DIMENSION_SOURCE_LEFT_HANDLE;
    case 'right':
      return DIMENSION_SOURCE_RIGHT_HANDLE;
    case 'top':
      return DIMENSION_SOURCE_TOP_HANDLE;
    case 'bottom':
      return DIMENSION_SOURCE_BOTTOM_HANDLE;
    default:
      return DIMENSION_SOURCE_BOTTOM_HANDLE;
  }
}

function targetHandleForSide(side: RouteSide): string {
  switch (side) {
    case 'left':
      return DIMENSION_TARGET_LEFT_HANDLE;
    case 'right':
      return DIMENSION_TARGET_RIGHT_HANDLE;
    case 'top':
      return DIMENSION_TARGET_TOP_HANDLE;
    case 'bottom':
      return DIMENSION_TARGET_BOTTOM_HANDLE;
    default:
      return DIMENSION_TARGET_TOP_HANDLE;
  }
}

function leadForDensity(density: DimensionEdgeDensity): number {
  void density;
  return 12;
}

function edgeFanOffset(index: number, step: number): number {
  return (((index + 2) % 5) - 2) * step;
}

function rawEdgeData(edge: Edge): unknown {
  return edge.data && typeof edge.data === 'object'
    ? (edge.data as Record<string, unknown>).raw
    : undefined;
}

function cleanPoints(points: LayoutPoint[]): LayoutPoint[] {
  return points.filter((point, index) => (
    index === 0 || point.x !== points[index - 1].x || point.y !== points[index - 1].y
  ));
}

function pointsForRoute(source: LayoutPoint, target: LayoutPoint, route: DimensionBusRoute): LayoutPoint[] {
  if (route.mode === 'sideRail' && typeof route.railX === 'number') {
    return cleanPoints([
      source,
      { x: route.railX, y: source.y },
      { x: route.railX, y: target.y },
      target,
    ]);
  }
  if (route.mode === 'corridor' && typeof route.corridorY === 'number') {
    const sourceLead = route.sourceLead ?? route.lead;
    const targetLead = route.targetLead ?? route.lead;
    const sourceLeadX = source.x + sideSign(route.sourceSide) * sourceLead;
    const targetLeadX = target.x + sideSign(route.targetSide) * targetLead;
    return cleanPoints([
      source,
      { x: sourceLeadX, y: source.y },
      { x: sourceLeadX, y: route.corridorY },
      { x: targetLeadX, y: route.corridorY },
      { x: targetLeadX, y: target.y },
      target,
    ]);
  }
  if (route.mode === 'corridor' && typeof route.corridorX === 'number') {
    const sourceLead = route.sourceLead ?? route.lead;
    const targetLead = route.targetLead ?? route.lead;
    if (isHorizontalSide(route.sourceSide) || isHorizontalSide(route.targetSide)) {
      const sourceLeadX = source.x + sideSign(route.sourceSide) * sourceLead;
      const targetLeadX = target.x + sideSign(route.targetSide) * targetLead;
      return cleanPoints([
        source,
        { x: sourceLeadX, y: source.y },
        { x: route.corridorX, y: source.y },
        { x: route.corridorX, y: target.y },
        { x: targetLeadX, y: target.y },
        target,
      ]);
    }
    const sourceLeadY = source.y + sideSign(route.sourceSide) * sourceLead;
    const targetLeadY = target.y + sideSign(route.targetSide) * targetLead;
    return cleanPoints([
      source,
      { x: source.x, y: sourceLeadY },
      { x: route.corridorX, y: sourceLeadY },
      { x: route.corridorX, y: targetLeadY },
      { x: target.x, y: targetLeadY },
      target,
    ]);
  }
  return [];
}

function routeLength(points: LayoutPoint[]): number {
  let length = 0;
  for (let index = 1; index < points.length; index += 1) {
    length += Math.abs(points[index].x - points[index - 1].x) + Math.abs(points[index].y - points[index - 1].y);
  }
  return length;
}

function endpointDistance(points: LayoutPoint[]): number {
  if (points.length < 2) {
    return 0;
  }
  const source = points[0];
  const target = points[points.length - 1];
  return Math.abs(source.x - target.x) + Math.abs(source.y - target.y);
}

function segmentHitsRect(a: LayoutPoint, b: LayoutPoint, rect: LayoutRect): boolean {
  if (a.x === b.x) {
    return verticalSegmentHitsRect(a.x, a.y, b.y, rect);
  }
  if (a.y === b.y) {
    return horizontalSegmentHitsRect(a.y, a.x, b.x, rect);
  }
  return false;
}

function routeCollides(points: LayoutPoint[], rects: LayoutRect[], sourceId: string, targetId: string): boolean {
  for (let index = 1; index < points.length; index += 1) {
    for (const rect of rects) {
      if (rect.id === sourceId || rect.id === targetId) {
        continue;
      }
      if (segmentHitsRect(points[index - 1], points[index], rect)) {
        return true;
      }
    }
  }
  return false;
}

function corridorXCandidates(
  rects: LayoutRect[],
  sourceId: string,
  targetId: string,
  y1: number,
  y2: number,
  preferred: number[],
  pad: number,
): number[] {
  const blockers = rects
    .filter((rect) => rect.id !== sourceId && rect.id !== targetId)
    .filter((rect) => rangesOverlap(y1, y2, rect.top + ROUTE_INSET, rect.bottom - ROUTE_INSET))
    .sort((a, b) => a.left - b.left || a.right - b.right);
  const candidates: number[] = [...preferred];
  for (let index = 0; index < blockers.length - 1; index += 1) {
    const gap = blockers[index + 1].left - blockers[index].right;
    if (gap > pad * 2) {
      candidates.push(blockers[index].right + gap / 2);
    }
  }
  for (const blocker of blockers) {
    candidates.push(blocker.left - pad);
    candidates.push(blocker.right + pad);
  }
  if (rects.length > 0) {
    candidates.push(Math.min(...rects.map((rect) => rect.left)) - pad * 2);
    candidates.push(Math.max(...rects.map((rect) => rect.right)) + pad * 2);
  }
  return uniqueCandidates(candidates);
}

function corridorYCandidates(
  rects: LayoutRect[],
  sourceId: string,
  targetId: string,
  x1: number,
  x2: number,
  preferred: number[],
  pad: number,
): number[] {
  const blockers = rects
    .filter((rect) => rect.id !== sourceId && rect.id !== targetId)
    .filter((rect) => rangesOverlap(x1, x2, rect.left + ROUTE_INSET, rect.right - ROUTE_INSET))
    .sort((a, b) => a.top - b.top || a.bottom - b.bottom);
  const candidates: number[] = [...preferred];
  for (let index = 0; index < blockers.length - 1; index += 1) {
    const gap = blockers[index + 1].top - blockers[index].bottom;
    if (gap > pad * 2) {
      candidates.push(blockers[index].bottom + gap / 2);
    }
  }
  for (const blocker of blockers) {
    candidates.push(blocker.top - pad);
    candidates.push(blocker.bottom + pad);
  }
  if (rects.length > 0) {
    candidates.push(Math.min(...rects.map((rect) => rect.top)) - pad * 2);
    candidates.push(Math.max(...rects.map((rect) => rect.bottom)) + pad * 2);
  }
  return uniqueCandidates(candidates);
}

function makeRouteCandidate({
  edge,
  density,
  sourceRect,
  targetRect,
  sourceSide,
  targetSide,
  priority,
  corridorX,
  corridorY,
}: {
  edge: Edge;
  density: DimensionEdgeDensity;
  sourceRect: LayoutRect;
  targetRect: LayoutRect;
  sourceSide: RouteSide;
  targetSide: RouteSide;
  priority: number;
  corridorX?: number;
  corridorY?: number;
}): RouteCandidate | null {
  const lead = leadForDensity(density);
  const route: DimensionBusRoute = {
    mode: 'corridor',
    sourceSide,
    targetSide,
    lead,
    sourceLead: lead,
    targetLead: lead,
    corridorX,
    corridorY,
  };
  const sourcePoint = pointForSide(sourceRect, sourceSide);
  const targetPoint = pointForSide(targetRect, targetSide);
  const points = pointsForRoute(sourcePoint, targetPoint, route);
  if (points.length < 2) {
    return null;
  }
  return {
    sourceHandle: sourceHandleForSide(sourceSide),
    targetHandle: targetHandleForSide(targetSide),
    data: {
      raw: rawEdgeData(edge),
      density,
      route,
    },
    points,
    priority,
  };
}

function addRouteCandidate(
  candidates: RouteCandidate[],
  value: RouteCandidate | null,
): void {
  if (value) {
    candidates.push(value);
  }
}

function resolveEdgeRoute(
  edge: Edge,
  positions: Map<string, { x: number; y: number }>,
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
  if (!source || !target) {
    return {
      sourceHandle: DIMENSION_SOURCE_BOTTOM_HANDLE,
      targetHandle: DIMENSION_TARGET_TOP_HANDLE,
      data: { raw: rawEdgeData(edge), density },
    };
  }

  const rects = layoutRects(positions, nodeWidth, nodeHeight);
  const sourceRect: LayoutRect = {
    id: edge.source,
    left: source.x,
    right: source.x + nodeWidth,
    top: source.y,
    bottom: source.y + nodeHeight,
  };
  const targetRect: LayoutRect = {
    id: edge.target,
    left: target.x,
    right: target.x + nodeWidth,
    top: target.y,
    bottom: target.y + nodeHeight,
  };
  const sourceCenter = rectCenter(sourceRect);
  const targetCenter = rectCenter(targetRect);
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;
  const verticalMajor = Math.abs(dy) >= Math.abs(dx) * 0.72;
  const horizontalMajor = Math.abs(dx) >= Math.abs(dy) * 0.72;
  const fanX = edgeFanOffset(index, density === 'matrix' ? 10 : 14);
  const fanY = edgeFanOffset(index, density === 'matrix' ? 8 : 12);
  const lead = leadForDensity(density);
  const pad = lead + 8;
  const candidates: RouteCandidate[] = [];

  const verticalSourceSide: RouteSide = dy >= 0 ? 'bottom' : 'top';
  const verticalTargetSide: RouteSide = dy >= 0 ? 'top' : 'bottom';
  const verticalSourcePoint = pointForSide(sourceRect, verticalSourceSide);
  const verticalTargetPoint = pointForSide(targetRect, verticalTargetSide);
  const verticalSourceLeadY = verticalSourcePoint.y + sideSign(verticalSourceSide) * lead;
  const verticalTargetLeadY = verticalTargetPoint.y + sideSign(verticalTargetSide) * lead;
  for (const corridorX of corridorXCandidates(
    rects,
    edge.source,
    edge.target,
    verticalSourceLeadY,
    verticalTargetLeadY,
    [
      verticalTargetPoint.x + fanX,
      verticalTargetPoint.x,
      verticalSourcePoint.x + fanX,
      verticalSourcePoint.x,
      (verticalSourcePoint.x + verticalTargetPoint.x) / 2,
      sourceRect.left - pad,
      sourceRect.right + pad,
      targetRect.left - pad,
      targetRect.right + pad,
    ],
    pad,
  )) {
    addRouteCandidate(candidates, makeRouteCandidate({
      edge,
      density,
      sourceRect,
      targetRect,
      sourceSide: verticalSourceSide,
      targetSide: verticalTargetSide,
      priority: verticalMajor ? 0 : 38,
      corridorX,
    }));
  }

  const horizontalSourceSide: RouteSide = dx >= 0 ? 'right' : 'left';
  const horizontalTargetSide: RouteSide = dx >= 0 ? 'left' : 'right';
  const horizontalSourcePoint = pointForSide(sourceRect, horizontalSourceSide);
  const horizontalTargetPoint = pointForSide(targetRect, horizontalTargetSide);
  const horizontalSourceLeadX = horizontalSourcePoint.x + sideSign(horizontalSourceSide) * lead;
  const horizontalTargetLeadX = horizontalTargetPoint.x + sideSign(horizontalTargetSide) * lead;
  for (const corridorY of corridorYCandidates(
    rects,
    edge.source,
    edge.target,
    horizontalSourceLeadX,
    horizontalTargetLeadX,
    [
      horizontalSourcePoint.y + fanY,
      horizontalSourcePoint.y,
      horizontalTargetPoint.y + fanY,
      horizontalTargetPoint.y,
      (horizontalSourcePoint.y + horizontalTargetPoint.y) / 2,
      sourceRect.top - pad,
      sourceRect.bottom + pad,
      targetRect.top - pad,
      targetRect.bottom + pad,
    ],
    pad,
  )) {
    addRouteCandidate(candidates, makeRouteCandidate({
      edge,
      density,
      sourceRect,
      targetRect,
      sourceSide: horizontalSourceSide,
      targetSide: horizontalTargetSide,
      priority: horizontalMajor ? 0 : 34,
      corridorY,
    }));
  }

  for (const corridorX of corridorXCandidates(
    rects,
    edge.source,
    edge.target,
    horizontalSourcePoint.y,
    horizontalTargetPoint.y,
    [
      (horizontalSourcePoint.x + horizontalTargetPoint.x) / 2,
      horizontalSourceLeadX,
      horizontalTargetLeadX,
      horizontalTargetPoint.x + fanX,
      horizontalSourcePoint.x + fanX,
    ],
    pad,
  )) {
    addRouteCandidate(candidates, makeRouteCandidate({
      edge,
      density,
      sourceRect,
      targetRect,
      sourceSide: horizontalSourceSide,
      targetSide: horizontalTargetSide,
      priority: horizontalMajor ? 8 : 22,
      corridorX,
    }));
  }

  const outerSides: RouteSide[] = ['left', 'right'];
  for (const side of outerSides) {
    const sourcePoint = pointForSide(sourceRect, side);
    const targetPoint = pointForSide(targetRect, side);
    const outsideX = side === 'left'
      ? Math.min(sourceRect.left, targetRect.left) - pad
      : Math.max(sourceRect.right, targetRect.right) + pad;
    for (const corridorX of corridorXCandidates(
      rects,
      edge.source,
      edge.target,
      sourcePoint.y,
      targetPoint.y,
      [outsideX, outsideX + fanX, sourcePoint.x + sideSign(side) * pad, targetPoint.x + sideSign(side) * pad],
      pad,
    )) {
      addRouteCandidate(candidates, makeRouteCandidate({
        edge,
        density,
        sourceRect,
        targetRect,
        sourceSide: side,
        targetSide: side,
        priority: verticalMajor ? 16 : 28,
        corridorX,
      }));
    }
  }

  const ranked = candidates
    .map((candidate) => {
      const length = routeLength(candidate.points);
      const excess = Math.max(0, length - endpointDistance(candidate.points));
      const collides = routeCollides(candidate.points, rects, edge.source, edge.target);
      return {
        candidate,
        score: (collides ? ROUTE_COLLISION_PENALTY : 0) + length + excess * 0.25 + candidate.priority,
      };
    })
    .sort((a, b) => a.score - b.score);

  const best = ranked[0]?.candidate;
  if (best) {
    return {
      sourceHandle: best.sourceHandle,
      targetHandle: best.targetHandle,
      data: best.data,
    };
  }

  return {
    sourceHandle: DIMENSION_SOURCE_BOTTOM_HANDLE,
    targetHandle: DIMENSION_TARGET_TOP_HANDLE,
    data: { raw: rawEdgeData(edge), density },
  };
}

interface EvidenceSpineTrack {
  kind: NonNullable<DimensionLane['trackKind']>;
  title: string;
  dimensions: readonly ReasoningDimension[];
  maxColumns: number;
}

const EXPLORER_SPINE_TRACKS: readonly EvidenceSpineTrack[] = [
  {
    kind: 'support',
    title: '材料与支持证据',
    dimensions: ['evidence', 'background'],
    maxColumns: 2,
  },
  {
    kind: 'spine',
    title: '论证主轴',
    dimensions: ['question', 'observation', 'mechanism', 'next_action'],
    maxColumns: 1,
  },
  {
    kind: 'limits',
    title: '边界与反证',
    dimensions: ['boundary', 'counter_evidence'],
    maxColumns: 1,
  },
] as const;

const RAIL_SPINE_TRACKS: readonly EvidenceSpineTrack[] = [
  {
    kind: 'rail',
    title: '证据脉络',
    dimensions: [
      'question',
      'observation',
      'mechanism',
      'next_action',
      'evidence',
      'boundary',
      'counter_evidence',
      'background',
    ],
    maxColumns: 1,
  },
] as const;

function columnsForSpineTrack(
  track: EvidenceSpineTrack,
  nodesByDimension: Map<ReasoningDimension, DimensionGraphNode[]>,
  presentation: 'explorer' | 'rail',
): number {
  if (presentation === 'rail') return 1;
  const largestGroup = Math.max(
    0,
    ...track.dimensions.map((dimension) => nodesByDimension.get(dimension)?.length ?? 0),
  );
  return largestGroup >= 5 ? track.maxColumns : 1;
}

function layoutEvidenceSpineGraph(
  graph: DimensionGraph,
  options: DimensionLayoutOptions,
  presentation: 'explorer' | 'rail',
): DimensionLayoutResult {
  const density = presentation === 'rail'
    ? 'compact'
    : resolveDensity(graph, options.density);
  const nodeWidth = options.nodeWidth ?? (presentation === 'rail' ? 220 : 248);
  const nodeHeight = nodeHeightForDensity(
    options.nodeHeight ?? (presentation === 'rail' ? 76 : 84),
    density,
  );
  const outerPadding = options.lanePadding ?? (presentation === 'rail' ? 20 : 28);
  const nodeGap = presentation === 'rail' ? 16 : 20;
  const trackGap = presentation === 'rail' ? 0 : 72;
  const laneHeaderHeight = options.laneTopPadding ?? 44;
  const laneGap = presentation === 'rail' ? 18 : 24;
  const hideEmptyLanes = options.hideEmptyLanes ?? true;
  const tracks = presentation === 'rail' ? RAIL_SPINE_TRACKS : EXPLORER_SPINE_TRACKS;
  const baseEdges = buildBaseEdges(graph);
  const baseNodes = buildBaseNodes(graph, { nodeWidth, nodeHeight, density });
  const dagrePositions = dagreOrderingMap(baseNodes, baseEdges);

  const nodesByDimension = new Map<ReasoningDimension, DimensionGraphNode[]>();
  for (const dimension of REASONING_DIMENSIONS) {
    nodesByDimension.set(dimension, []);
  }
  for (const entry of graph.nodes) {
    nodesByDimension.get(entry.dimension)?.push(entry);
  }

  const trackGeometry = tracks.map((track) => {
    const columns = columnsForSpineTrack(track, nodesByDimension, presentation);
    return {
      ...track,
      columns,
      width: columns * nodeWidth + Math.max(0, columns - 1) * nodeGap,
    };
  });

  let nextTrackX = outerPadding;
  const trackX = new Map<EvidenceSpineTrack['kind'], number>();
  for (const track of trackGeometry) {
    trackX.set(track.kind, nextTrackX);
    nextTrackX += track.width + trackGap;
  }

  const lanes: DimensionLane[] = [];
  const positionedNodeIndex = new Map<string, { x: number; y: number }>();
  let maxBottom = outerPadding;

  for (const track of trackGeometry) {
    const x = trackX.get(track.kind) ?? outerPadding;
    let y = outerPadding;
    let renderedTrackTitle = false;
    for (const dimension of track.dimensions) {
      const entries = laidOutOrderForLane(nodesByDimension.get(dimension) ?? [], dagrePositions);
      if (hideEmptyLanes && entries.length === 0) continue;
      const columns = Math.max(1, Math.min(track.columns, Math.max(1, entries.length)));
      const rows = Math.max(1, Math.ceil(Math.max(1, entries.length) / columns));
      const laneHeight = laneHeaderHeight
        + rows * nodeHeight
        + Math.max(0, rows - 1) * nodeGap
        + 12;
      const meta = DIMENSION_META[dimension];
      lanes.push({
        dimension,
        x,
        y,
        width: track.width,
        height: laneHeight,
        title: `${meta.label} · ${entries.length}`,
        trackTitle: renderedTrackTitle ? undefined : track.title,
        trackKind: track.kind,
      });
      renderedTrackTitle = true;

      const gridWidth = columns * nodeWidth + Math.max(0, columns - 1) * nodeGap;
      const nodeStartX = x + (track.width - gridWidth) / 2;
      for (const [index, entry] of entries.entries()) {
        const column = index % columns;
        const row = Math.floor(index / columns);
        positionedNodeIndex.set(entry.node.id, {
          x: nodeStartX + column * (nodeWidth + nodeGap),
          y: y + laneHeaderHeight + row * (nodeHeight + nodeGap),
        });
      }
      y += laneHeight + laneGap;
    }
    maxBottom = Math.max(maxBottom, y);
  }

  const positioned = baseNodes.map((node) => {
    const position = positionedNodeIndex.get(node.id);
    return position ? { ...node, position } : node;
  });
  const routedEdges = baseEdges.map((edge, index) => {
    const route = resolveEdgeRoute(
      edge,
      positionedNodeIndex,
      density,
      index,
      nodeWidth,
      nodeHeight,
    );
    return { ...edge, ...route };
  });

  return {
    nodes: positioned,
    edges: routedEdges,
    lanes,
    total: {
      width: Math.max(nextTrackX - trackGap + outerPadding, nodeWidth + outerPadding * 2),
      height: Math.max(maxBottom + outerPadding - laneGap, 320),
    },
    density,
    layoutMode: presentation === 'rail' ? 'rail' : 'spine',
  };
}

function layoutPaperNetworkGraph(
  graph: DimensionGraph,
  options: DimensionLayoutOptions,
): DimensionLayoutResult {
  const density = resolveDensity(graph, options.density);
  const nodeWidth = options.nodeWidth ?? 236;
  const nodeHeight = nodeHeightForDensity(options.nodeHeight ?? 82, density);
  const padding = options.lanePadding ?? 36;
  const baseNodes = buildBaseNodes(graph, { nodeWidth, nodeHeight, density });
  const baseEdges = buildBaseEdges(graph);
  const dagre = layoutWithDagre(baseNodes, baseEdges, {
    rankdir: 'LR',
    ranksep: density === 'matrix' ? 72 : 96,
    nodesep: density === 'matrix' ? 22 : 34,
    staggerRankSiblings: false,
  });
  const minX = Math.min(0, ...dagre.nodes.map((node) => node.position.x));
  const minY = Math.min(0, ...dagre.nodes.map((node) => node.position.y));
  const positioned = dagre.nodes.map((node) => ({
    ...node,
    position: {
      x: node.position.x - minX + padding,
      y: node.position.y - minY + padding,
    },
  }));
  const positionedNodeIndex = new Map(positioned.map((node) => [node.id, node.position]));
  const routedEdges = baseEdges.map((edge) => {
    const source = positionedNodeIndex.get(edge.source);
    const target = positionedNodeIndex.get(edge.target);
    if (!source || !target) return edge;
    const sourceCenter = { x: source.x + nodeWidth / 2, y: source.y + nodeHeight / 2 };
    const targetCenter = { x: target.x + nodeWidth / 2, y: target.y + nodeHeight / 2 };
    const horizontal = Math.abs(targetCenter.x - sourceCenter.x) >= Math.abs(targetCenter.y - sourceCenter.y);
    const sourceSide: RouteSide = horizontal
      ? (targetCenter.x >= sourceCenter.x ? 'right' : 'left')
      : (targetCenter.y >= sourceCenter.y ? 'bottom' : 'top');
    const targetSide: RouteSide = horizontal
      ? (targetCenter.x >= sourceCenter.x ? 'left' : 'right')
      : (targetCenter.y >= sourceCenter.y ? 'top' : 'bottom');
    return {
      ...edge,
      sourceHandle: sourceHandleForSide(sourceSide),
      targetHandle: targetHandleForSide(targetSide),
      data: { raw: rawEdgeData(edge), density } satisfies DimensionBusEdgeData,
    };
  });
  const maxRight = Math.max(nodeWidth, ...positioned.map((node) => node.position.x + nodeWidth));
  const maxBottom = Math.max(nodeHeight, ...positioned.map((node) => node.position.y + nodeHeight));
  return {
    nodes: positioned,
    edges: routedEdges,
    lanes: [],
    total: {
      width: maxRight + padding,
      height: Math.max(maxBottom + padding, 320),
    },
    density,
    layoutMode: 'network',
  };
}

export function layoutDimensionGraph(
  graph: DimensionGraph,
  options: DimensionLayoutOptions = {},
): DimensionLayoutResult {
  const presentation = options.presentation ?? 'legacy';
  if (presentation === 'network') {
    return layoutPaperNetworkGraph(graph, options);
  }
  if (presentation === 'explorer' || presentation === 'rail') {
    return layoutEvidenceSpineGraph(graph, options, presentation);
  }
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

  const baseNodes = buildBaseNodes(graph, { nodeWidth, nodeHeight, density });
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
      const route = resolveEdgeRoute(edge, positionedNodeIndex, density, index, nodeWidth, nodeHeight);
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
    const route = resolveEdgeRoute(edge, positionedNodeIndex, density, index, nodeWidth, nodeHeight);
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
