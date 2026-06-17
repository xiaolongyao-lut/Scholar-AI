import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from '@xyflow/react';

export const DIMENSION_BUS_EDGE_TYPE = 'dimensionBusEdge';
export const DIMENSION_SOURCE_LEFT_HANDLE = 'dimension-source-left';
export const DIMENSION_SOURCE_RIGHT_HANDLE = 'dimension-source-right';
export const DIMENSION_SOURCE_BOTTOM_HANDLE = 'dimension-source-bottom';
export const DIMENSION_TARGET_LEFT_HANDLE = 'dimension-target-left';
export const DIMENSION_TARGET_RIGHT_HANDLE = 'dimension-target-right';
export const DIMENSION_TARGET_TOP_HANDLE = 'dimension-target-top';

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

function pathFromRoute(data: DimensionBusEdgeData | undefined): string | null {
  const route = data?.route;
  if (!route) {
    return null;
  }
  return null;
}

export function DimensionBusEdge(props: EdgeProps) {
  const typedData = props.data as DimensionBusEdgeData | undefined;
  const routedPath = pathFromRoute(typedData);
  const [smoothPath, labelX, labelY] = getSmoothStepPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
    borderRadius: 10,
  });
  const edgePath = routedPath ?? smoothPath;

  return (
    <>
      <BaseEdge
        id={props.id}
        path={edgePath}
        markerEnd={props.markerEnd}
        style={props.style}
      />
      {props.label ? (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-none absolute rounded-sm border border-outline-variant/50 bg-surface-lowest/90 px-1 py-0.5 text-[10px] text-foreground/60 shadow-sm"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
          >
            {props.label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

export default DimensionBusEdge;
