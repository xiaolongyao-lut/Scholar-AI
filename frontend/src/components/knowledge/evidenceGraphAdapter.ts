import type {
  EvidenceGraphEdge,
  EvidenceGraphNode,
  EvidenceGraphPayload,
  EvidenceGraphProvenanceRef,
  EvidenceGraphRelation,
} from '@/services/graphApi';
import type {
  EvidenceRef,
  GraphEdge,
  GraphNode,
  GraphPayloadV0,
  SourceRef,
} from '@/components/graph/payloadToRf';

function materialIdFromRef(ref: EvidenceGraphProvenanceRef): string | null {
  const value = ref.material_id?.trim();
  return value && value.length > 0 ? value : null;
}

function evidenceRefFromProvenance(ref: EvidenceGraphProvenanceRef): EvidenceRef | null {
  const materialId = materialIdFromRef(ref);
  if (!materialId) {
    return null;
  }
  return {
    material_id: materialId,
    page: ref.page ?? null,
    chunk_id: ref.chunk_id ?? ref.source_vault_chunk_id ?? null,
    text: ref.quote || ref.text_hash || '',
    score: null,
    bbox: ref.bbox ?? null,
  };
}

function sourceRefFromProvenance(ref: EvidenceGraphProvenanceRef): SourceRef | null {
  const materialId = materialIdFromRef(ref);
  if (!materialId) {
    return null;
  }
  return {
    material_id: materialId,
    page: ref.page ?? null,
    chunk_id: ref.chunk_id ?? ref.source_vault_chunk_id ?? null,
    bbox: ref.bbox ?? null,
  };
}

function firstMaterialId(refs: EvidenceGraphProvenanceRef[]): string | null {
  for (const ref of refs) {
    const materialId = materialIdFromRef(ref);
    if (materialId) {
      return materialId;
    }
  }
  return null;
}

function firstSourceRef(refs: EvidenceGraphProvenanceRef[]): SourceRef | null {
  for (const ref of refs) {
    const sourceRef = sourceRefFromProvenance(ref);
    if (sourceRef) {
      return sourceRef;
    }
  }
  return null;
}

function evidenceRefs(refs: EvidenceGraphProvenanceRef[]): EvidenceRef[] {
  return refs
    .map(evidenceRefFromProvenance)
    .filter((ref): ref is EvidenceRef => ref !== null);
}

function toV0NodeType(type: EvidenceGraphNode['type']): GraphNode['type'] {
  if (type === 'source' || type === 'paper') return 'material';
  if (type === 'chunk') return 'evidence';
  if (type === 'finding' || type === 'insight') return 'claim';
  if (type === 'session') return 'agent';
  return type;
}

function toV0Relation(relation: EvidenceGraphRelation): GraphEdge['relation'] {
  if (relation === 'uses_method' || relation === 'uses_dataset') return 'uses';
  if (relation === 'supports' || relation === 'contradicts' || relation === 'cites' || relation === 'related') {
    return relation;
  }
  return 'related';
}

function nodeMetadata(node: EvidenceGraphNode): Record<string, unknown> {
  return {
    ...node.metadata,
    evidence_graph_status: node.status,
    evidence_graph_type: node.type,
    evidence_graph_provenance_count: node.provenance_refs.length,
  };
}

function edgeMetadata(edge: EvidenceGraphEdge): Record<string, unknown> {
  return {
    ...edge.metadata,
    evidence_graph_status: edge.status,
    evidence_graph_relation: edge.relation,
    evidence_graph_created_by: edge.created_by,
    evidence_graph_provenance_count: edge.provenance_refs.length,
  };
}

function toV0Node(node: EvidenceGraphNode): GraphNode {
  const materialId = firstMaterialId(node.provenance_refs);
  return {
    id: node.id,
    label: node.label,
    type: toV0NodeType(node.type),
    confidence: node.confidence ?? null,
    material_id: materialId,
    source_ref: firstSourceRef(node.provenance_refs),
    evidence_refs: evidenceRefs(node.provenance_refs),
    metadata: nodeMetadata(node),
  };
}

function toV0Edge(edge: EvidenceGraphEdge): GraphEdge {
  const materialId = firstMaterialId(edge.provenance_refs);
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    relation: toV0Relation(edge.relation),
    confidence: edge.confidence ?? null,
    material_id: materialId,
    source_ref: firstSourceRef(edge.provenance_refs),
    evidence_refs: evidenceRefs(edge.provenance_refs),
    metadata: edgeMetadata(edge),
  };
}

/**
 * Convert Evidence Graph v1 into the existing React Flow viewer envelope.
 *
 * Why:
 * The v1 contract carries trust/provenance semantics, while the current graph
 * viewer already owns fit-view, deep links, hover previews, and canvas behavior.
 */
export function evidenceGraphToGraphPayload(payload: EvidenceGraphPayload): GraphPayloadV0 {
  return {
    version: 'v0',
    scope: {
      kind: payload.scope.kind === 'source' ? 'material' : 'question',
      ref: payload.scope.ref,
    },
    updated_at: payload.updated_at,
    nodes: payload.nodes.map(toV0Node),
    edges: payload.edges.map(toV0Edge),
  };
}
