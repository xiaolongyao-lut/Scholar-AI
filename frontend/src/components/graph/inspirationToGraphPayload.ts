/**
 * Convert an inspiration query + spark list into a GraphPayload v0
 * subgraph (Track B E5, D-EVR-6).
 *
 * Mirrors the Workbench adapter shape (claim node + evidence nodes +
 * supports edges) so the Inspiration drawer can reuse the same
 * EvidenceGraphPanel + GraphPayloadViewer rendering. Per D-EVR-6
 * the topology is the simple claim+evidence+supports for v1; richer
 * spark-node typology is deferred to a later slice.
 */
import type { components } from '@/generated/openapi';
import type { InspirationSpark, SparkEvidenceRef } from '@/types/writing';

type GraphPayloadV0 = components['schemas']['GraphPayloadV0'];
type GraphNode = components['schemas']['GraphNode'];
type GraphEdge = components['schemas']['GraphEdge'];

function pickString(v: unknown): string | undefined {
  return typeof v === 'string' && v.length > 0 ? v : undefined;
}

function hashText(text: string): string {
  let h = 0;
  for (let i = 0; i < text.length; i += 1) {
    h = (h * 31 + text.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(16).padStart(8, '0');
}

function evidenceIdOf(ref: SparkEvidenceRef, fallbackIndex: number): string {
  const materialId = pickString(ref.material_id);
  const chunkId = pickString(ref.chunk_id ?? undefined);
  if (materialId && chunkId) return `ev:${materialId}:${chunkId}`;
  if (materialId) return `ev:${materialId}:${fallbackIndex}`;
  // SparkEvidenceRef requires non-empty material_id at the type level,
  // but defensive in case a malformed payload slips through.
  return `ev:fallback:${fallbackIndex}:${hashText(ref.text ?? '')}`;
}

function evidenceLabel(ref: SparkEvidenceRef, index: number): string {
  const text = pickString(ref.text ?? undefined);
  if (text) {
    return text.length > 60 ? `${text.slice(0, 57)}…` : text;
  }
  const materialId = pickString(ref.material_id);
  if (materialId) return `evidence ${materialId}`;
  return `evidence #${index + 1}`;
}

function claimIdOf(query: string): string {
  return `claim:inspiration:${hashText(query)}`;
}

function claimLabel(query: string): string {
  const trimmed = query.trim();
  if (trimmed.length === 0) return '当前灵感主题';
  return trimmed.length > 60 ? `${trimmed.slice(0, 57)}…` : trimmed;
}

/**
 * Build a GraphPayloadV0 from an inspiration query + sparks. The
 * resulting payload renders inside `EvidenceGraphPanel` /
 * `GraphPayloadViewer`; node clicks deep-link to the paper workbench.
 *
 * Topology (D-EVR-6):
 * - one `claim` node = the inspiration query.
 * - one `evidence` node per unique (material_id, chunk_id) found
 *   across all sparks' `evidence_refs`.
 * - `supports` edges from each evidence to the claim.
 *
 * Sparks without `evidence_refs` (LLM-generated, per D-EVR-4 never
 * fabricate) contribute nothing to the graph.
 */
export function inspirationToGraphPayload(
  query: string,
  sparks: ReadonlyArray<InspirationSpark> | null | undefined,
): GraphPayloadV0 {
  const claimNodeId = claimIdOf(query);
  const claimNode: GraphNode = {
    id: claimNodeId,
    label: claimLabel(query),
    type: 'claim',
    metadata: { surface: 'inspiration' },
    material_id: null,
    source_ref: null,
    evidence_refs: null,
    confidence: null,
  };

  const evidenceNodes: GraphNode[] = [];
  const evidenceIds: string[] = [];
  const seen = new Set<string>();

  if (sparks) {
    sparks.forEach((spark) => {
      const refs = spark.evidence_refs;
      if (!refs || refs.length === 0) return;
      refs.forEach((ref, index) => {
        if (!ref || typeof ref.material_id !== 'string' || ref.material_id.length === 0) {
          return;
        }
        const id = evidenceIdOf(ref, index);
        if (seen.has(id)) return;
        seen.add(id);
        evidenceIds.push(id);

        const materialId = pickString(ref.material_id);
        const chunkId = pickString(ref.chunk_id ?? undefined);
        const page = typeof ref.page === 'number' && ref.page > 0 ? ref.page : null;
        const score = typeof ref.score === 'number' && Number.isFinite(ref.score) ? ref.score : null;

        const metadata: Record<string, unknown> = {};
        if (spark.id) metadata.spark_id = spark.id;
        if (spark.spark_type) metadata.spark_type = spark.spark_type;

        evidenceNodes.push({
          id,
          label: evidenceLabel(ref, index),
          type: 'evidence',
          material_id: materialId ?? null,
          source_ref: materialId
            ? {
                material_id: materialId,
                page,
                chunk_id: chunkId ?? null,
                bbox: null,
              }
            : null,
          evidence_refs: null,
          confidence: score,
          metadata: Object.keys(metadata).length > 0 ? metadata : null,
        });
      });
    });
  }

  const edges: GraphEdge[] = evidenceIds.map((evidenceId) => ({
    id: `edge:${evidenceId}->${claimNodeId}`,
    source: evidenceId,
    target: claimNodeId,
    relation: 'supports',
    material_id: null,
    source_ref: null,
    evidence_refs: null,
    confidence: null,
    metadata: null,
  }));

  return {
    version: 'v0',
    scope: {
      kind: 'question',
      ref: query.length > 0 ? query.slice(0, 200) : 'inspiration',
    },
    updated_at: new Date().toISOString(),
    nodes: [claimNode, ...evidenceNodes],
    edges,
  };
}
