/**
 * Convert a Workbench chat answer into a GraphPayload v0 subgraph.
 *
 * KG-1 step 5a (frontend-only). Per remaining-work plan §4.11 the default
 * UX is a collapsible evidence graph panel embedded in the Workbench
 * answer view, reusing the existing React Flow GraphPayloadViewer.
 *
 * Shape:
 *   - one `claim` node = the user query (id: `claim:q:<sha>`).
 *   - one `evidence` node per Source, deduped by material_id+chunk_id
 *     (fallback fingerprint when material_id is missing).
 *   - `supports` edges from each evidence to the claim.
 *
 * Source.page in the Workbench message is a Chinese chunk-index label
 * like `片段 5`, not a real PDF page number; the GraphPayloadViewer node
 * click routes to the paper workbench without a page param when no numeric
 * page is available.
 */
import type { components } from '@/generated/openapi';

type GraphPayloadV0 = components['schemas']['GraphPayloadV0'];
type GraphNode = components['schemas']['GraphNode'];
type GraphEdge = components['schemas']['GraphEdge'];

export interface WorkbenchSource {
  title: string;
  page: string;
  material_id?: string;
  chunk_id?: string;
}

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

function evidenceIdOf(source: WorkbenchSource, fallbackIndex: number): string {
  const materialId = pickString(source.material_id);
  const chunkId = pickString(source.chunk_id);
  if (materialId && chunkId) return `ev:${materialId}:${chunkId}`;
  if (materialId) return `ev:${materialId}:${fallbackIndex}`;
  const title = pickString(source.title) ?? 'unknown';
  const page = pickString(source.page) ?? '';
  return `ev:${title}:${hashText(`${title}|${page}`)}`;
}

function evidenceLabel(source: WorkbenchSource, index: number): string {
  const title = pickString(source.title);
  if (title) {
    const trimmed = title.length > 50 ? `${title.slice(0, 47)}…` : title;
    return source.page ? `${trimmed}｜${source.page}` : trimmed;
  }
  const materialId = pickString(source.material_id);
  if (materialId) return `evidence ${materialId}`;
  return `evidence #${index + 1}`;
}

/**
 * Build a deterministic claim id from the query text. Stable across
 * re-renders so React Flow doesn't tear the node down.
 */
function claimIdOf(query: string): string {
  return `claim:q:${hashText(query)}`;
}

function claimLabel(query: string): string {
  const trimmed = query.trim();
  if (trimmed.length === 0) return '当前问题';
  return trimmed.length > 60 ? `${trimmed.slice(0, 57)}…` : trimmed;
}

/**
 * Convert a (query, sources) pair into GraphPayloadV0. `sources` may be
 * empty / undefined; in that case the payload still carries the claim
 * node so callers can render an "evidence will appear here" panel.
 */
export function workbenchToGraphPayload(
  query: string,
  sources: ReadonlyArray<WorkbenchSource> | null | undefined,
): GraphPayloadV0 {
  const claimNodeId = claimIdOf(query);
  const claimNode: GraphNode = {
    id: claimNodeId,
    label: claimLabel(query),
    type: 'claim',
    metadata: { surface: 'workbench' },
    material_id: null,
    source_ref: null,
    evidence_refs: null,
    confidence: null,
  };

  const evidenceNodes: GraphNode[] = [];
  const evidenceIds: string[] = [];
  const seen = new Set<string>();

  (sources ?? []).forEach((source, index) => {
    const id = evidenceIdOf(source, index);
    if (seen.has(id)) return;
    seen.add(id);
    evidenceIds.push(id);

    const materialId = pickString(source.material_id);
    const chunkId = pickString(source.chunk_id);

    const metadata: Record<string, unknown> = {};
    if (source.page) metadata.page_label = source.page;

    evidenceNodes.push({
      id,
      label: evidenceLabel(source, index),
      type: 'evidence',
      material_id: materialId ?? null,
      // GraphPayloadViewer reads source_ref to build the deep-link;
      // chunk-index style "page" labels are not numeric pages, so we
      // leave page=null and let KnowledgeBase fall back to page 1.
      source_ref: materialId
        ? { material_id: materialId, page: null, chunk_id: chunkId ?? null, bbox: null }
        : null,
      evidence_refs: null,
      confidence: null,
      metadata: Object.keys(metadata).length > 0 ? metadata : null,
    });
  });

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
    scope: { kind: 'question', ref: query.length > 0 ? query.slice(0, 200) : 'workbench' },
    updated_at: new Date().toISOString(),
    nodes: [claimNode, ...evidenceNodes],
    edges,
  };
}
