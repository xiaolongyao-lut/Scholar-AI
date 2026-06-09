import { MarkerType, type Edge, type Node } from '@xyflow/react';
import type { components } from '@/generated/openapi';
import { isPdfBboxUnit, readPdfBbox, type PdfBboxUnit } from '@/lib/pdfAnchor';

type GeneratedGraphPayloadV0 = components['schemas']['GraphPayloadV0'];
type GeneratedGraphNode = components['schemas']['GraphNode'];
type GeneratedGraphEdge = components['schemas']['GraphEdge'];
type GeneratedEvidenceRef = components['schemas']['EvidenceRef'];
type GeneratedSourceRef = components['schemas']['SourceRef'];

export interface SourceRef extends Omit<GeneratedSourceRef, 'bbox'> {
  bbox?: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
}

export interface EvidenceRef extends Omit<GeneratedEvidenceRef, 'bbox'> {
  bbox?: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
}

export interface GraphNode extends Omit<GeneratedGraphNode, 'source_ref' | 'evidence_refs'> {
  source_ref?: SourceRef | null;
  evidence_refs?: EvidenceRef[] | null;
}

export interface GraphEdge extends Omit<GeneratedGraphEdge, 'source_ref' | 'evidence_refs'> {
  source_ref?: SourceRef | null;
  evidence_refs?: EvidenceRef[] | null;
}

export interface GraphPayloadV0 extends Omit<GeneratedGraphPayloadV0, 'nodes' | 'edges'> {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

const NODE_TYPE_STYLE: Record<string, { background: string; border: string }> = {
  claim: {
    background: 'hsl(var(--primary) / 0.12)',
    border: 'hsl(var(--primary) / 0.55)',
  },
  material: {
    background: 'hsl(170 50% 38% / 0.16)',
    border: 'hsl(170 50% 38% / 0.42)',
  },
  evidence: {
    background: 'hsl(var(--surface-lowest))',
    border: 'hsl(var(--outline-variant) / 0.8)',
  },
  agent: {
    background: 'hsl(260 55% 50% / 0.16)',
    border: 'hsl(260 55% 50% / 0.42)',
  },
};

/**
 * Resolve the (material_id, page) target that a node click should
 * navigate to, or null if no material backing is available.
 *
 * Rule (agreed with user):
 *   1. node.material_id wins. page/chunk come from source_ref *only if*
 *      source_ref.material_id matches node.material_id — otherwise the
 *      source_ref points at a different paper and we'd deep-link page N
 *      of the wrong PDF. Fall back to the first matching evidence_ref
 *      for page/chunk in that case; otherwise drop page/chunk and just
 *      open the material at default page 1.
 *   2. otherwise, the first evidence_refs[i] that has a material_id.
 *   3. otherwise, null — caller opens the detail panel instead.
 */
export interface MaterialTarget {
  material_id: string;
  page?: number;
  chunk_id?: string;
  bbox?: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
}

function readGraphBbox(value: unknown): number[] | null {
  const bbox = readPdfBbox(value);
  return bbox ? [...bbox] : null;
}

function readGraphBboxUnit(value: unknown): PdfBboxUnit | null {
  return isPdfBboxUnit(value) ? value : null;
}

function targetFromSourceRef(ref: SourceRef): MaterialTarget {
  const target: MaterialTarget = {
    material_id: ref.material_id,
  };
  if (typeof ref.page === 'number' && ref.page > 0) {
    target.page = ref.page;
  }
  if (ref.chunk_id) {
    target.chunk_id = ref.chunk_id;
  }
  const bbox = readGraphBbox(ref.bbox);
  if (bbox) {
    target.bbox = bbox;
    target.bbox_unit = readGraphBboxUnit(ref.bbox_unit);
  }
  return target;
}

function targetFromEvidenceRef(ref: EvidenceRef): MaterialTarget {
  const target: MaterialTarget = {
    material_id: ref.material_id,
  };
  if (typeof ref.page === 'number' && ref.page > 0) {
    target.page = ref.page;
  }
  if (ref.chunk_id) {
    target.chunk_id = ref.chunk_id;
  }
  const bbox = readGraphBbox(ref.bbox);
  if (bbox) {
    target.bbox = bbox;
    target.bbox_unit = readGraphBboxUnit(ref.bbox_unit);
  }
  return target;
}

export function resolveMaterialTarget(node: GraphNode): MaterialTarget | null {
  if (node.material_id) {
    const materialId = node.material_id;
    const refs = node.evidence_refs ?? [];
    // Prefer source_ref when it matches; otherwise scan evidence_refs
    // for a ref that *does* match; otherwise drop precision.
    if (node.source_ref && node.source_ref.material_id === materialId) {
      return targetFromSourceRef(node.source_ref);
    }
    const matchingRef = refs.find((r) => r.material_id === materialId);
    if (matchingRef) {
      return targetFromEvidenceRef(matchingRef);
    }
    return { material_id: materialId };
  }
  const firstRef = (node.evidence_refs ?? []).find((r) => !!r.material_id);
  if (firstRef) {
    return targetFromEvidenceRef(firstRef);
  }
  return null;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function nodeDegree(nodeId: string, edges: GraphEdge[]): number {
  return edges.reduce((count, edge) => (
    edge.source === nodeId || edge.target === nodeId ? count + 1 : count
  ), 0);
}

function averageEvidenceScore(node: GraphNode): number | null {
  const scores = (node.evidence_refs ?? [])
    .map((ref) => ref.score)
    .filter((score): score is number => typeof score === 'number' && Number.isFinite(score));
  if (scores.length === 0) return null;
  return scores.reduce((sum, score) => sum + score, 0) / scores.length;
}

function nodeWeight(node: GraphNode, edges: GraphEdge[]): number {
  const confidence = typeof node.confidence === 'number' && Number.isFinite(node.confidence)
    ? node.confidence
    : averageEvidenceScore(node) ?? 0;
  const evidenceCount = node.evidence_refs?.length ?? (node.source_ref ? 1 : 0);
  const degree = nodeDegree(node.id, edges);
  return clamp(1 + evidenceCount * 0.45 + degree * 0.35 + confidence * 1.8, 1, 5);
}

function nodeLabel(node: GraphNode): string {
  const raw = node.label.trim() || '知识节点';
  const maxLength = node.type === 'claim' ? 72 : 58;
  return raw.length > maxLength ? `${raw.slice(0, maxLength - 1)}…` : raw;
}

function graphNodeStyle(node: GraphNode, weight: number): Node['style'] {
  const typeStyle = NODE_TYPE_STYLE[node.type] ?? {
    background: 'hsl(var(--surface-low))',
    border: 'hsl(var(--outline-variant) / 0.75)',
  };
  const width = Math.round(142 + weight * 18);
  const minHeight = Math.round(42 + weight * 5);
  const fontSize = node.type === 'claim' ? 12 : 11;
  return {
    width,
    minHeight,
    borderRadius: 8,
    border: `1px solid ${typeStyle.border}`,
    background: typeStyle.background,
    color: 'hsl(var(--foreground))',
    boxShadow: weight >= 3.6 ? '0 8px 22px hsl(var(--foreground) / 0.08)' : '0 2px 8px hsl(var(--foreground) / 0.05)',
    padding: '8px 10px',
    fontSize,
    lineHeight: 1.25,
    whiteSpace: 'normal',
    overflowWrap: 'anywhere',
  };
}

function edgeStroke(relation: GraphEdge['relation']): string {
  if (relation === 'contradicts') return 'hsl(0 70% 55% / 0.78)';
  if (relation === 'supports') return 'hsl(var(--primary) / 0.72)';
  if (relation === 'cites') return 'hsl(170 50% 40% / 0.66)';
  if (relation === 'uses') return 'hsl(260 55% 55% / 0.66)';
  return 'hsl(var(--outline) / 0.82)';
}

/**
 * Map a GraphPayload v0 into the shape React Flow consumes. dagre
 * runs separately (layoutWithDagre) so this stays free of side effects
 * and is trivially unit-testable.
 */
export function payloadToRf(payload: GraphPayloadV0): { nodes: Node[]; edges: Edge[] } {
  const edges: Edge[] = payload.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.relation,
    data: { raw: e },
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
    style: {
      stroke: edgeStroke(e.relation),
      strokeWidth: e.relation === 'supports' ? 1.8 : 1.3,
    },
    labelStyle: {
      fill: 'hsl(var(--foreground) / 0.62)',
      fontSize: 10,
      fontWeight: 500,
    },
    labelBgStyle: {
      fill: 'hsl(var(--surface-lowest) / 0.85)',
    },
    // Subtle styling — emphasise supports/contradicts visually.
    animated: e.relation === 'supports' || e.relation === 'contradicts',
  }));

  const nodes: Node[] = payload.nodes.map((n) => {
    const weight = nodeWeight(n, payload.edges);
    return {
      id: n.id,
      // dagre will overwrite position; keep a placeholder so React Flow
      // doesn't crash before layout runs.
      position: { x: 0, y: 0 },
      data: {
        label: nodeLabel(n),
        type: n.type,
        raw: n,
        weight,
      },
      style: graphNodeStyle(n, weight),
      type: 'default',
    };
  });

  return { nodes, edges };
}
