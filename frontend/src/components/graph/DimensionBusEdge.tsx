import { useId } from 'react';
import {
  BaseEdge,
  getBezierPath,
  type EdgeProps,
} from '@xyflow/react';

export const DIMENSION_BUS_EDGE_TYPE = 'dimensionBusEdge';
export const DIMENSION_SOURCE_LEFT_HANDLE = 'dimension-source-left';
export const DIMENSION_SOURCE_RIGHT_HANDLE = 'dimension-source-right';
export const DIMENSION_SOURCE_TOP_HANDLE = 'dimension-source-top';
export const DIMENSION_SOURCE_BOTTOM_HANDLE = 'dimension-source-bottom';
export const DIMENSION_TARGET_LEFT_HANDLE = 'dimension-target-left';
export const DIMENSION_TARGET_RIGHT_HANDLE = 'dimension-target-right';
export const DIMENSION_TARGET_TOP_HANDLE = 'dimension-target-top';
export const DIMENSION_TARGET_BOTTOM_HANDLE = 'dimension-target-bottom';

export type DimensionEdgeDensity = 'comfortable' | 'compact' | 'matrix';

export interface DimensionBusRoute {
  mode: 'corridor' | 'sideRail';
  sourceSide: 'left' | 'right' | 'top' | 'bottom';
  targetSide: 'left' | 'right' | 'top' | 'bottom';
  lead: number;
  sourceLead?: number;
  targetLead?: number;
  corridorX?: number;
  corridorY?: number;
  railX?: number;
}

export interface DimensionBusEdgeData extends Record<string, unknown> {
  raw?: unknown;
  density?: DimensionEdgeDensity;
  route?: DimensionBusRoute;
}

interface RoutePoint {
  x: number;
  y: number;
}

interface RouteGeometry {
  path: string;
  labelX: number;
  labelY: number;
}

interface RouteVector {
  x: number;
  y: number;
}

function isFinitePoint(point: RoutePoint): boolean {
  return Number.isFinite(point.x) && Number.isFinite(point.y);
}

function formatCoordinate(value: number): string {
  return Number(value.toFixed(3)).toString();
}

function outwardVector(side: DimensionBusRoute['sourceSide']): RouteVector {
  switch (side) {
    case 'left':
      return { x: -1, y: 0 };
    case 'right':
      return { x: 1, y: 0 };
    case 'top':
      return { x: 0, y: -1 };
    case 'bottom':
      return { x: 0, y: 1 };
    default:
      return { x: 0, y: 0 };
  }
}

function offsetPoint(point: RoutePoint, vector: RouteVector, distance: number): RoutePoint {
  return {
    x: point.x + vector.x * distance,
    y: point.y + vector.y * distance,
  };
}

function distanceBetween(a: RoutePoint, b: RoutePoint): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

function curveHandleLength(distance: number): number {
  return Math.min(84, Math.max(12, distance * 0.32));
}

function projectedDistance(from: RoutePoint, to: RoutePoint, vector: RouteVector): number {
  return Math.abs((to.x - from.x) * vector.x + (to.y - from.y) * vector.y);
}

function boundedHandleLength(distance: number, projected: number): number {
  return Math.min(curveHandleLength(distance), Math.max(6, projected * 0.45));
}

function pointCommand(command: 'M' | 'L', point: RoutePoint): string {
  return `${command} ${formatCoordinate(point.x)} ${formatCoordinate(point.y)}`;
}

function cubicCommand(controlA: RoutePoint, controlB: RoutePoint, point: RoutePoint): string {
  return `C ${formatCoordinate(controlA.x)} ${formatCoordinate(controlA.y)} ${formatCoordinate(controlB.x)} ${formatCoordinate(controlB.y)} ${formatCoordinate(point.x)} ${formatCoordinate(point.y)}`;
}

function smoothRoutePath({
  source,
  target,
  sourceLead,
  targetLead,
  guide,
  guideAxis,
  sourceSide,
  targetSide,
}: {
  source: RoutePoint;
  target: RoutePoint;
  sourceLead: RoutePoint;
  targetLead: RoutePoint;
  guide: RoutePoint;
  guideAxis: 'horizontal' | 'vertical';
  sourceSide: DimensionBusRoute['sourceSide'];
  targetSide: DimensionBusRoute['targetSide'];
}): string | null {
  const points = [source, sourceLead, guide, targetLead, target];
  if (points.some((point) => !isFinitePoint(point))) {
    return null;
  }

  const sourceOutward = outwardVector(sourceSide);
  const targetOutward = outwardVector(targetSide);
  const guideDirection = guideAxis === 'horizontal'
    ? { x: Math.sign(targetLead.x - sourceLead.x) || 1, y: 0 }
    : { x: 0, y: Math.sign(targetLead.y - sourceLead.y) || 1 };
  const sourceDistance = distanceBetween(sourceLead, guide);
  const targetDistance = distanceBetween(guide, targetLead);
  const sourceHandle = boundedHandleLength(
    sourceDistance,
    projectedDistance(sourceLead, guide, sourceOutward),
  );
  const targetHandle = boundedHandleLength(
    targetDistance,
    projectedDistance(targetLead, guide, targetOutward),
  );
  const guideSourceHandle = boundedHandleLength(
    sourceDistance,
    projectedDistance(sourceLead, guide, guideDirection),
  );
  const guideTargetHandle = boundedHandleLength(
    targetDistance,
    projectedDistance(guide, targetLead, guideDirection),
  );
  const commands = [pointCommand('M', source)];

  if (source.x !== sourceLead.x || source.y !== sourceLead.y) {
    commands.push(pointCommand('L', sourceLead));
  }
  commands.push(cubicCommand(
    offsetPoint(sourceLead, sourceOutward, sourceHandle),
    offsetPoint(guide, guideDirection, -guideSourceHandle),
    guide,
  ));
  commands.push(cubicCommand(
    offsetPoint(guide, guideDirection, guideTargetHandle),
    offsetPoint(targetLead, targetOutward, targetHandle),
    targetLead,
  ));
  if (target.x !== targetLead.x || target.y !== targetLead.y) {
    commands.push(pointCommand('L', target));
  }
  return commands.join(' ');
}

export function buildDimensionBusRoutePath({
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
}: {
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  data: DimensionBusEdgeData | undefined;
}): RouteGeometry | null {
  const route = data?.route;
  if (!route) {
    return null;
  }
  const source = { x: sourceX, y: sourceY };
  const target = { x: targetX, y: targetY };
  const sourceLeadDistance = route.sourceLead ?? route.lead;
  const targetLeadDistance = route.targetLead ?? route.lead;
  const sourceLead = offsetPoint(source, outwardVector(route.sourceSide), sourceLeadDistance);
  const targetLead = offsetPoint(target, outwardVector(route.targetSide), targetLeadDistance);
  let guide: RoutePoint | null = null;
  let guideAxis: 'horizontal' | 'vertical' = 'vertical';

  if (route.mode === 'sideRail' && typeof route.railX === 'number') {
    guide = { x: route.railX, y: (sourceLead.y + targetLead.y) / 2 };
  } else if (route.mode === 'corridor' && typeof route.corridorY === 'number') {
    guide = { x: (sourceLead.x + targetLead.x) / 2, y: route.corridorY };
    guideAxis = 'horizontal';
  } else if (route.mode === 'corridor' && typeof route.corridorX === 'number') {
    guide = { x: route.corridorX, y: (sourceLead.y + targetLead.y) / 2 };
  }

  if (!guide) {
    return null;
  }
  const path = smoothRoutePath({
    source,
    target,
    sourceLead,
    targetLead,
    guide,
    guideAxis,
    sourceSide: route.sourceSide,
    targetSide: route.targetSide,
  });
  if (!path) {
    return null;
  }
  return {
    path,
    labelX: guide.x,
    labelY: guide.y,
  };
}

export function DimensionBusEdge(props: EdgeProps) {
  const reactId = useId();
  const edgeData = props.data as DimensionBusEdgeData | undefined;
  const raw = edgeData?.raw as { direction?: unknown; relation?: unknown } | undefined;
  const directed = raw?.direction === 'undirected' || raw?.relation === 'related'
    ? false
    : true;
  const [directPath] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
    curvature: 0.12,
  });
  const markerId = `dimension-arrow-${reactId.replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const markerColor = typeof props.style?.stroke === 'string'
    ? props.style.stroke
    : 'hsl(var(--outline))';
  const markerOpacity = typeof props.style?.opacity === 'number' ? props.style.opacity : 1;

  return (
    <>
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
          <path d="M 0 0 L 8 4 L 0 8 Z" fill={markerColor} opacity={markerOpacity} />
        </marker>
      </defs>
      <BaseEdge
        id={props.id}
        path={directPath}
        markerEnd={directed ? `url(#${markerId})` : undefined}
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

export default DimensionBusEdge;
