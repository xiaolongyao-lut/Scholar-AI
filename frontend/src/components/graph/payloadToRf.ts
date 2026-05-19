import type { Edge, Node } from '@xyflow/react';
import type { components } from '@/generated/openapi';

export type GraphPayloadV0 = components['schemas']['GraphPayloadV0'];
export type GraphNode = components['schemas']['GraphNode'];
export type GraphEdge = components['schemas']['GraphEdge'];
export type EvidenceRef = components['schemas']['EvidenceRef'];

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
}

export function resolveMaterialTarget(node: GraphNode): MaterialTarget | null {
  if (node.material_id) {
    const materialId = node.material_id;
    const refs = node.evidence_refs ?? [];
    // Prefer source_ref when it matches; otherwise scan evidence_refs
    // for a ref that *does* match; otherwise drop precision.
    if (node.source_ref && node.source_ref.material_id === materialId) {
      return {
        material_id: materialId,
        page: node.source_ref.page ?? undefined,
        chunk_id: node.source_ref.chunk_id ?? undefined,
      };
    }
    const matchingRef = refs.find((r) => r.material_id === materialId);
    if (matchingRef) {
      return {
        material_id: materialId,
        page: matchingRef.page ?? undefined,
        chunk_id: matchingRef.chunk_id ?? undefined,
      };
    }
    return { material_id: materialId };
  }
  const firstRef = (node.evidence_refs ?? []).find((r) => !!r.material_id);
  if (firstRef) {
    return {
      material_id: firstRef.material_id,
      page: firstRef.page ?? undefined,
      chunk_id: firstRef.chunk_id ?? undefined,
    };
  }
  return null;
}

/**
 * Map a GraphPayload v0 into the shape React Flow consumes. dagre
 * runs separately (layoutWithDagre) so this stays free of side effects
 * and is trivially unit-testable.
 */
export function payloadToRf(payload: GraphPayloadV0): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = payload.nodes.map((n) => ({
    id: n.id,
    // dagre will overwrite position; keep a placeholder so React Flow
    // doesn't crash before layout runs.
    position: { x: 0, y: 0 },
    data: {
      label: n.label,
      type: n.type,
      raw: n,
    },
    type: 'default',
  }));

  const edges: Edge[] = payload.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.relation,
    data: { raw: e },
    // Subtle styling — emphasise supports/contradicts visually.
    animated: e.relation === 'supports' || e.relation === 'contradicts',
  }));

  return { nodes, edges };
}
