/**
 * Convert a Workbench chat answer into a GraphPayload v0 subgraph.
 *
 * Frontend-only default graph panel for Workbench answers. The default
 * UX is a collapsible evidence graph panel embedded in the Workbench
 * answer view, reusing the existing React Flow GraphPayloadViewer.
 *
 * Shape:
 *   - one `claim` node = the user query (id: `claim:q:<sha>`).
 *   - one `evidence` node per Source, deduped by material_id+chunk_id
 *     (fallback fingerprint when material_id is missing).
 *   - `supports` edges from each evidence to the claim.
 *   - **2026-06-14 dimension overlay**: when an AnalysisChain is provided,
 *     each non-empty field becomes an additional node tagged with
 *     `analysis_chain_field` so DimensionGraphViewer projects the answer
 *     into the six reasoning lanes. Original claim/evidence shape is
 *     preserved so the relations view still renders cleanly.
 *
 * Source.page in the Workbench message is a Chinese chunk-index label
 * like `片段 5`, not a real PDF page number; the GraphPayloadViewer node
 * click routes to the paper workbench without a page param when no numeric
 * page is available.
 */
import type { components } from '@/generated/openapi';
import type { AnalysisChainPayload } from '@/services/discussionApi';

type GraphPayloadV0 = components['schemas']['GraphPayloadV0'];
type GraphNode = components['schemas']['GraphNode'];
type GraphEdge = components['schemas']['GraphEdge'];

export interface WorkbenchSource {
  title: string;
  page: string;
  material_id?: string;
  chunk_id?: string;
  excerpt?: string;
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
 *
 * When ``analysisChain`` is provided, every non-empty field is added as
 * a typed node so DimensionGraphViewer can place it in the matching lane.
 */
export function workbenchToGraphPayload(
  query: string,
  sources: ReadonlyArray<WorkbenchSource> | null | undefined,
  analysisChain?: AnalysisChainPayload | null,
): GraphPayloadV0 {
  const claimNodeId = claimIdOf(query);
  const claimNode: GraphNode = {
    id: claimNodeId,
    label: claimLabel(query),
    type: 'claim',
    metadata: { surface: 'workbench', reasoning_dimension: 'question', analysis_chain_field: 'question' },
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
    if (source.excerpt && source.excerpt.trim()) {
      metadata.evidence_text = source.excerpt.trim();
    }

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
      evidence_refs: materialId && source.excerpt
        ? [{
            material_id: materialId,
            page: null,
            chunk_id: chunkId ?? null,
            text: source.excerpt,
            score: null,
          }]
        : null,
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

  // Mark every dedup'd evidence node with reasoning_dimension=evidence so
  // DimensionGraphViewer routes them into the evidence lane regardless of
  // upstream heuristics.
  for (const node of evidenceNodes) {
    const existingMeta = (node.metadata as Record<string, unknown> | null | undefined) ?? {};
    node.metadata = { ...existingMeta, reasoning_dimension: 'evidence', analysis_chain_field: 'evidence' };
  }

  const chainNodes = analysisChain ? buildAnalysisChainNodes(claimNodeId, analysisChain) : [];
  for (const entry of chainNodes) {
    edges.push(entry.edge);
  }
  const chainNodeList = chainNodes.map((entry) => entry.node);

  return {
    version: 'v0',
    scope: { kind: 'question', ref: query.length > 0 ? query.slice(0, 200) : 'workbench' },
    updated_at: new Date().toISOString(),
    nodes: [claimNode, ...evidenceNodes, ...chainNodeList],
    edges,
  };
}

interface AnalysisChainNodeEntry {
  node: GraphNode;
  edge: GraphEdge;
}

/**
 * Project an AnalysisChainPayload onto typed nodes. Each non-empty field
 * yields one node connected to the claim with a relation that suggests
 * its argumentative role (supports / contradicts / derives_from).
 */
function buildAnalysisChainNodes(
  claimNodeId: string,
  chain: AnalysisChainPayload,
): AnalysisChainNodeEntry[] {
  const entries: AnalysisChainNodeEntry[] = [];

  const pushTextNode = (
    field: 'observation' | 'mechanism' | 'boundary' | 'next_action',
    text: string | undefined,
    type: GraphNode['type'],
    relation: GraphEdge['relation'],
  ) => {
    const trimmed = (text ?? '').trim();
    if (!trimmed) return;
    const id = `chain:${field}:${hashText(trimmed)}`;
    const node: GraphNode = {
      id,
      label: trimmed.length > 60 ? `${trimmed.slice(0, 57)}…` : trimmed,
      type,
      metadata: { analysis_chain_field: field, reasoning_dimension: field },
      material_id: null,
      source_ref: null,
      evidence_refs: null,
      confidence: null,
    };
    const edge: GraphEdge = {
      id: `edge:${id}->${claimNodeId}`,
      source: id,
      target: claimNodeId,
      relation,
      material_id: null,
      source_ref: null,
      evidence_refs: null,
      confidence: null,
      metadata: { via: 'analysis_chain', field },
    };
    entries.push({ node, edge });
  };

  pushTextNode('observation', chain.observation, 'claim', 'extends');
  pushTextNode('mechanism', chain.mechanism, 'concept', 'extends');
  pushTextNode('boundary', chain.boundary, 'limitation', 'supports');
  pushTextNode('next_action', chain.next_action, 'agent', 'related');

  const pushListNodes = (
    field: 'evidence' | 'counter_evidence',
    list: string[] | undefined,
    type: GraphNode['type'],
    relation: GraphEdge['relation'],
  ) => {
    const items = (list ?? []).map((item) => item.trim()).filter((item) => item.length > 0);
    items.forEach((text, index) => {
      const id = `chain:${field}:${index}:${hashText(text)}`;
      const node: GraphNode = {
        id,
        label: text.length > 60 ? `${text.slice(0, 57)}…` : text,
        type,
        metadata: { analysis_chain_field: field, reasoning_dimension: field },
        material_id: null,
        source_ref: null,
        evidence_refs: null,
        confidence: null,
      };
      const edge: GraphEdge = {
        id: `edge:${id}->${claimNodeId}`,
        source: id,
        target: claimNodeId,
        relation,
        material_id: null,
        source_ref: null,
        evidence_refs: null,
        confidence: null,
        metadata: { via: 'analysis_chain', field },
      };
      entries.push({ node, edge });
    });
  };

  pushListNodes('evidence', chain.evidence, 'evidence', 'supports');
  pushListNodes('counter_evidence', chain.counter_evidence, 'evidence', 'contradicts');

  return entries;
}
