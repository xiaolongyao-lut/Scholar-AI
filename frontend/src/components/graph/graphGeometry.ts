export interface Point2D {
  readonly x: number;
  readonly y: number;
}

export interface RectBounds {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly borderRadius?: number;
}

export type GraphEdgeDirection = 'directed' | 'undirected';
export type GraphEdgePathKind = 'straight' | 'bezier';

export interface GraphEdgeGeometryInput {
  readonly sourceId: string;
  readonly targetId: string;
  readonly sourceRect: RectBounds;
  readonly targetRect: RectBounds;
  readonly direction: GraphEdgeDirection;
  readonly markerEnd?: string;
  readonly markerInset?: number;
  readonly pathKind?: GraphEdgePathKind;
  readonly curvature?: number;
}

export type GraphEdgeGeometryFailureReason =
  | 'self-edge'
  | 'zero-vector'
  | 'overlap'
  | 'invalid-rectangle'
  | 'invalid-options'
  | 'boundary-intersection';

export interface GraphEdgeGeometryRejected {
  readonly ok: false;
  readonly reason: GraphEdgeGeometryFailureReason;
}

export interface GraphEdgeGeometryReady {
  readonly ok: true;
  readonly path: string;
  readonly pathKind: GraphEdgePathKind;
  readonly sourcePoint: Point2D;
  readonly targetPoint: Point2D;
  readonly sourceBoundaryPoint: Point2D;
  readonly targetBoundaryPoint: Point2D;
  readonly controlPoints: readonly [Point2D, Point2D] | null;
  readonly curvature: number;
  readonly markerInset: number;
  readonly markerEnd: string | undefined;
}

export type GraphEdgeGeometryResult =
  | GraphEdgeGeometryReady
  | GraphEdgeGeometryRejected;

const GEOMETRY_EPSILON = 1e-9;
const PATH_PRECISION = 3;
const DEFAULT_BEZIER_CURVATURE = 0.08;
const MAX_BEZIER_CURVATURE = 0.16;
const MAX_MARKER_INSET = 24;

function isFinitePoint(point: Point2D): boolean {
  return Number.isFinite(point.x) && Number.isFinite(point.y);
}

function isValidRect(rect: RectBounds): boolean {
  return Number.isFinite(rect.x)
    && Number.isFinite(rect.y)
    && Number.isFinite(rect.width)
    && Number.isFinite(rect.height)
    && rect.width > GEOMETRY_EPSILON
    && rect.height > GEOMETRY_EPSILON
    && (rect.borderRadius === undefined
      || (Number.isFinite(rect.borderRadius) && rect.borderRadius >= 0));
}

function centerOf(rect: RectBounds): Point2D {
  return {
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function roundedRadius(rect: RectBounds): number {
  return clamp(rect.borderRadius ?? 0, 0, Math.min(rect.width, rect.height) / 2);
}

function pointOnRay(center: Point2D, unitX: number, unitY: number, distance: number): Point2D {
  return {
    x: center.x + unitX * distance,
    y: center.y + unitY * distance,
  };
}

/**
 * Finds where a center-origin ray exits an axis-aligned rounded rectangle.
 * CSS-style oversized radii are clamped to half of the shortest side.
 */
export function getRoundedRectRayIntersection(
  rect: RectBounds,
  toward: Point2D,
): Point2D | null {
  if (!isValidRect(rect) || !isFinitePoint(toward)) {
    return null;
  }

  const center = centerOf(rect);
  const deltaX = toward.x - center.x;
  const deltaY = toward.y - center.y;
  const rayLength = Math.hypot(deltaX, deltaY);
  if (!Number.isFinite(rayLength) || rayLength <= GEOMETRY_EPSILON) {
    return null;
  }

  const unitX = deltaX / rayLength;
  const unitY = deltaY / rayLength;
  const absoluteUnitX = Math.abs(unitX);
  const absoluteUnitY = Math.abs(unitY);
  const halfWidth = rect.width / 2;
  const halfHeight = rect.height / 2;
  const radius = roundedRadius(rect);
  const straightHalfWidth = halfWidth - radius;
  const straightHalfHeight = halfHeight - radius;
  const sideDistances: number[] = [];

  if (absoluteUnitX > GEOMETRY_EPSILON) {
    const verticalDistance = halfWidth / absoluteUnitX;
    const verticalOffset = absoluteUnitY * verticalDistance;
    if (verticalOffset <= straightHalfHeight + GEOMETRY_EPSILON) {
      sideDistances.push(verticalDistance);
    }
  }
  if (absoluteUnitY > GEOMETRY_EPSILON) {
    const horizontalDistance = halfHeight / absoluteUnitY;
    const horizontalOffset = absoluteUnitX * horizontalDistance;
    if (horizontalOffset <= straightHalfWidth + GEOMETRY_EPSILON) {
      sideDistances.push(horizontalDistance);
    }
  }

  if (sideDistances.length > 0) {
    return pointOnRay(center, unitX, unitY, Math.min(...sideDistances));
  }

  const cornerProjection = absoluteUnitX * straightHalfWidth
    + absoluteUnitY * straightHalfHeight;
  const cornerConstant = straightHalfWidth * straightHalfWidth
    + straightHalfHeight * straightHalfHeight
    - radius * radius;
  const discriminant = cornerProjection * cornerProjection - cornerConstant;
  const cornerDistance = cornerProjection + Math.sqrt(Math.max(0, discriminant));
  if (!Number.isFinite(cornerDistance) || cornerDistance <= GEOMETRY_EPSILON) {
    return null;
  }
  return pointOnRay(center, unitX, unitY, cornerDistance);
}

function rectsOverlapOrTouch(source: RectBounds, target: RectBounds): boolean {
  const sourceRight = source.x + source.width;
  const sourceBottom = source.y + source.height;
  const targetRight = target.x + target.width;
  const targetBottom = target.y + target.height;
  return source.x <= targetRight + GEOMETRY_EPSILON
    && sourceRight >= target.x - GEOMETRY_EPSILON
    && source.y <= targetBottom + GEOMETRY_EPSILON
    && sourceBottom >= target.y - GEOMETRY_EPSILON;
}

function normalizeMarker(markerEnd: string | undefined): string | undefined {
  return markerEnd && markerEnd.trim().length > 0 ? markerEnd : undefined;
}

function formatCoordinate(value: number): string {
  const rounded = Number(value.toFixed(PATH_PRECISION));
  return Object.is(rounded, -0) ? '0' : rounded.toString();
}

function formatPoint(point: Point2D): string {
  return `${formatCoordinate(point.x)} ${formatCoordinate(point.y)}`;
}

function buildStraightPath(source: Point2D, target: Point2D): string {
  return `M ${formatPoint(source)} L ${formatPoint(target)}`;
}

function buildBezierGeometry(
  source: Point2D,
  target: Point2D,
  curvature: number,
): Pick<GraphEdgeGeometryReady, 'path' | 'controlPoints'> {
  const deltaX = target.x - source.x;
  const deltaY = target.y - source.y;
  const distance = Math.hypot(deltaX, deltaY);
  const normalX = -deltaY / distance;
  const normalY = deltaX / distance;
  const bend = distance * curvature;
  const controlA: Point2D = {
    x: source.x + deltaX / 3 + normalX * bend,
    y: source.y + deltaY / 3 + normalY * bend,
  };
  const controlB: Point2D = {
    x: source.x + (deltaX * 2) / 3 + normalX * bend,
    y: source.y + (deltaY * 2) / 3 + normalY * bend,
  };
  return {
    path: `M ${formatPoint(source)} C ${formatPoint(controlA)} ${formatPoint(controlB)} ${formatPoint(target)}`,
    controlPoints: [controlA, controlB],
  };
}

function rejected(reason: GraphEdgeGeometryFailureReason): GraphEdgeGeometryRejected {
  return { ok: false, reason };
}

/**
 * Builds one boundary-to-boundary SVG path for a read-only React Flow edge.
 * Directed markers land on the target boundary by default; inset is opt-in.
 */
export function getGraphEdgeGeometry(
  input: GraphEdgeGeometryInput,
): GraphEdgeGeometryResult {
  if (input.sourceId === input.targetId) {
    return rejected('self-edge');
  }
  if (!isValidRect(input.sourceRect) || !isValidRect(input.targetRect)) {
    return rejected('invalid-rectangle');
  }

  const sourceCenter = centerOf(input.sourceRect);
  const targetCenter = centerOf(input.targetRect);
  const centerDistance = Math.hypot(
    targetCenter.x - sourceCenter.x,
    targetCenter.y - sourceCenter.y,
  );
  if (!Number.isFinite(centerDistance) || centerDistance <= GEOMETRY_EPSILON) {
    return rejected('zero-vector');
  }
  if (rectsOverlapOrTouch(input.sourceRect, input.targetRect)) {
    return rejected('overlap');
  }

  const pathKind = input.pathKind ?? 'straight';
  const requestedInset = input.markerInset ?? 0;
  const requestedCurvature = input.curvature ?? DEFAULT_BEZIER_CURVATURE;
  if ((pathKind !== 'straight' && pathKind !== 'bezier')
    || !Number.isFinite(requestedInset)
    || requestedInset < 0
    || !Number.isFinite(requestedCurvature)) {
    return rejected('invalid-options');
  }

  const sourceBoundaryPoint = getRoundedRectRayIntersection(
    input.sourceRect,
    targetCenter,
  );
  const targetBoundaryPoint = getRoundedRectRayIntersection(
    input.targetRect,
    sourceCenter,
  );
  if (!sourceBoundaryPoint || !targetBoundaryPoint) {
    return rejected('boundary-intersection');
  }

  const boundaryDeltaX = targetBoundaryPoint.x - sourceBoundaryPoint.x;
  const boundaryDeltaY = targetBoundaryPoint.y - sourceBoundaryPoint.y;
  const boundaryDistance = Math.hypot(boundaryDeltaX, boundaryDeltaY);
  if (!Number.isFinite(boundaryDistance) || boundaryDistance <= GEOMETRY_EPSILON) {
    return rejected('overlap');
  }

  const markerInset = input.direction === 'directed'
    ? Math.min(requestedInset, MAX_MARKER_INSET, boundaryDistance / 2)
    : 0;
  const targetPoint: Point2D = markerInset > 0
    ? {
      x: targetBoundaryPoint.x - (boundaryDeltaX / boundaryDistance) * markerInset,
      y: targetBoundaryPoint.y - (boundaryDeltaY / boundaryDistance) * markerInset,
    }
    : targetBoundaryPoint;
  const sourcePoint = sourceBoundaryPoint;
  const curvature = pathKind === 'bezier'
    ? clamp(requestedCurvature, -MAX_BEZIER_CURVATURE, MAX_BEZIER_CURVATURE)
    : 0;
  const pathGeometry = pathKind === 'bezier'
    ? buildBezierGeometry(sourcePoint, targetPoint, curvature)
    : {
      path: buildStraightPath(sourcePoint, targetPoint),
      controlPoints: null,
    };

  return {
    ok: true,
    path: pathGeometry.path,
    pathKind,
    sourcePoint,
    targetPoint,
    sourceBoundaryPoint,
    targetBoundaryPoint,
    controlPoints: pathGeometry.controlPoints,
    curvature,
    markerInset,
    markerEnd: input.direction === 'directed'
      ? normalizeMarker(input.markerEnd)
      : undefined,
  };
}
