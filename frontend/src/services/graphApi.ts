import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import type { components } from '@/generated/openapi';
import { isPdfBboxUnit, PDF_URL_BBOX_UNIT, type PdfBboxUnit } from '@/lib/pdfAnchor';

// Import wire types directly from the generated OpenAPI bindings so the
// service layer stays independent of any UI helper modules.
export type GraphPayloadV0 = components['schemas']['GraphPayloadV0'];

const API_BASE = getApiBaseUrl();

export type EvidenceGraphScopeKind = 'source' | 'knowledge_item' | 'insight' | 'smart_read_session' | 'question' | 'project';
export type EvidenceGraphNodeType =
  | 'source'
  | 'chunk'
  | 'paper'
  | 'concept'
  | 'claim'
  | 'method'
  | 'dataset'
  | 'metric'
  | 'finding'
  | 'limitation'
  | 'insight'
  | 'session'
  | 'agent';
export type EvidenceGraphRelation =
  | 'contains'
  | 'derived_from'
  | 'cites'
  | 'supports'
  | 'contradicts'
  | 'uses_method'
  | 'uses_dataset'
  | 'evaluated_by'
  | 'mentions'
  | 'promoted_to'
  | 'related';
export type EvidenceGraphDirection = 'directed' | 'undirected';
export type EvidenceGraphStatus = 'trusted' | 'candidate' | 'rejected' | 'stale';
export type EvidenceGraphCreatedBy =
  | 'parser'
  | 'wiki_frontmatter'
  | 'llm_extraction'
  | 'user_action'
  | 'migration'
  | 'runtime_capture'
  | 'wiki_graph'
  | 'source_vault';

export interface EvidenceGraphScope {
  kind: EvidenceGraphScopeKind;
  ref: string;
}

export interface EvidenceGraphProvenanceRef {
  source_id?: string | null;
  source_vault_id?: string | null;
  chunk_id?: string | null;
  source_vault_chunk_id?: string | null;
  material_id?: string | null;
  page?: number | null;
  bbox?: number[] | null;
  bbox_unit?: PdfBboxUnit | null;
  text_hash?: string | null;
  quote: string;
}

export interface EvidenceGraphNode {
  id: string;
  label: string;
  type: EvidenceGraphNodeType;
  status: EvidenceGraphStatus;
  confidence?: number | null;
  provenance_refs: EvidenceGraphProvenanceRef[];
  metadata: Record<string, unknown>;
}

export interface EvidenceGraphEdge {
  id: string;
  source: string;
  target: string;
  relation: EvidenceGraphRelation;
  direction: EvidenceGraphDirection;
  status: EvidenceGraphStatus;
  confidence?: number | null;
  provenance_refs: EvidenceGraphProvenanceRef[];
  created_by: EvidenceGraphCreatedBy;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface EvidenceGraphPayload {
  version: 'v1';
  scope: EvidenceGraphScope;
  updated_at: string;
  nodes: EvidenceGraphNode[];
  edges: EvidenceGraphEdge[];
  warnings: string[];
}

export interface GraphPayloadQuery {
  scope_kind?: 'question' | 'material' | 'concept';
  scope_ref?: string;
  /** Comma-joined node ids to keep. Empty / undefined returns the full snapshot. */
  filter?: string;
}

export interface EvidenceGraphQuery {
  scope_kind?: EvidenceGraphScopeKind;
  scope_ref?: string;
  session_id?: string;
  turn_id?: string;
  filter?: string;
  top_k?: number;
  min_similarity?: number;
}

export interface ProjectEvidenceGraphQuery {
  project_id: string;
  top_k?: number;
  min_similarity?: number;
}

export interface AnswerEvidenceGraphQuery {
  session_id: string;
  turn_id: string;
}

export interface WikiEvidenceGraphQuery {
  scope_kind?: Exclude<EvidenceGraphScopeKind, 'smart_read_session'>;
  scope_ref?: string;
  filter?: string;
}

export const EVIDENCE_GRAPH_DIRECT_NODE_LIMIT = 150;
export const EVIDENCE_GRAPH_DIRECT_EDGE_LIMIT = 600;
export const EVIDENCE_GRAPH_NODE_LIMIT = 300;
export const EVIDENCE_GRAPH_EDGE_LIMIT = 1000;

const EVIDENCE_GRAPH_RELATION_DIRECTIONS: Readonly<Record<EvidenceGraphRelation, EvidenceGraphDirection>> = {
  contains: 'directed',
  derived_from: 'directed',
  cites: 'directed',
  supports: 'directed',
  contradicts: 'directed',
  uses_method: 'directed',
  uses_dataset: 'directed',
  evaluated_by: 'directed',
  mentions: 'directed',
  promoted_to: 'directed',
  related: 'undirected',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isGraphPayloadV0(value: unknown): value is GraphPayloadV0 {
  if (!isRecord(value)) return false;
  return Array.isArray(value.nodes) && Array.isArray(value.edges);
}

function isEvidenceScopeKind(value: unknown): value is EvidenceGraphScopeKind {
  return value === 'source'
    || value === 'knowledge_item'
    || value === 'insight'
    || value === 'smart_read_session'
    || value === 'question'
    || value === 'project';
}

function isEvidenceNodeType(value: unknown): value is EvidenceGraphNodeType {
  return value === 'source'
    || value === 'chunk'
    || value === 'paper'
    || value === 'concept'
    || value === 'claim'
    || value === 'method'
    || value === 'dataset'
    || value === 'metric'
    || value === 'finding'
    || value === 'limitation'
    || value === 'insight'
    || value === 'session'
    || value === 'agent';
}

function isEvidenceRelation(value: unknown): value is EvidenceGraphRelation {
  return value === 'contains'
    || value === 'derived_from'
    || value === 'cites'
    || value === 'supports'
    || value === 'contradicts'
    || value === 'uses_method'
    || value === 'uses_dataset'
    || value === 'evaluated_by'
    || value === 'mentions'
    || value === 'promoted_to'
    || value === 'related';
}

function isEvidenceDirection(value: unknown): value is EvidenceGraphDirection {
  return value === 'directed' || value === 'undirected';
}

function isEvidenceStatus(value: unknown): value is EvidenceGraphStatus {
  return value === 'trusted' || value === 'candidate' || value === 'rejected' || value === 'stale';
}

function isEvidenceCreatedBy(value: unknown): value is EvidenceGraphCreatedBy {
  return value === 'parser'
    || value === 'wiki_frontmatter'
    || value === 'llm_extraction'
    || value === 'user_action'
    || value === 'migration'
    || value === 'runtime_capture'
    || value === 'wiki_graph'
    || value === 'source_vault';
}

function readString(value: unknown, field: string): string {
  if (typeof value !== 'string') {
    throw new Error(`Invalid evidence graph response: ${field} must be a string`);
  }
  return value;
}

function readOptionalNumber(value: unknown, field: string): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid evidence graph response: ${field} must be a finite number or null`);
  }
  return value;
}

function readOptionalString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== 'string') {
    throw new Error(`Invalid evidence graph response: ${field} must be a string or null`);
  }
  return value;
}

function readMetadata(value: unknown, field: string): Record<string, unknown> {
  if (value === undefined || value === null) return {};
  if (!isRecord(value)) {
    throw new Error(`Invalid evidence graph response: ${field} must be an object`);
  }
  return { ...value };
}

function readBbox(value: unknown): number[] | null {
  if (value === null || value === undefined) return null;
  if (!Array.isArray(value) || value.length !== 4) {
    throw new Error('Invalid evidence graph response: bbox must contain four numbers');
  }
  const values = value.map((entry) => {
    if (typeof entry !== 'number' || !Number.isFinite(entry)) {
      throw new Error('Invalid evidence graph response: bbox coordinates must be finite numbers');
    }
    return entry;
  });
  return values;
}

function readBboxUnit(value: unknown, bbox: number[] | null): PdfBboxUnit | null {
  if (value !== null && value !== undefined && !isPdfBboxUnit(value)) {
    throw new Error('Invalid evidence graph response: bbox_unit must be a supported PDF coordinate unit or null');
  }
  if (bbox === null) return null;
  return value ?? PDF_URL_BBOX_UNIT;
}

function parseEvidenceGraphScope(value: unknown): EvidenceGraphScope {
  if (!isRecord(value) || !isEvidenceScopeKind(value.kind)) {
    throw new Error('Invalid evidence graph response: scope is invalid');
  }
  return {
    kind: value.kind,
    ref: readString(value.ref, 'scope.ref'),
  };
}

function parseProvenanceRef(value: unknown): EvidenceGraphProvenanceRef {
  if (!isRecord(value)) {
    throw new Error('Invalid evidence graph response: provenance ref must be an object');
  }
  const bbox = readBbox(value.bbox);
  return {
    source_id: readOptionalString(value.source_id, 'source_id'),
    source_vault_id: readOptionalString(value.source_vault_id, 'source_vault_id'),
    chunk_id: readOptionalString(value.chunk_id, 'chunk_id'),
    source_vault_chunk_id: readOptionalString(value.source_vault_chunk_id, 'source_vault_chunk_id'),
    material_id: readOptionalString(value.material_id, 'material_id'),
    page: readOptionalNumber(value.page, 'page'),
    bbox,
    bbox_unit: readBboxUnit(value.bbox_unit, bbox),
    text_hash: readOptionalString(value.text_hash, 'text_hash'),
    quote: typeof value.quote === 'string' ? value.quote : '',
  };
}

function parseProvenanceRefs(value: unknown): EvidenceGraphProvenanceRef[] {
  if (!Array.isArray(value)) {
    throw new Error('Invalid evidence graph response: provenance_refs must be an array');
  }
  return value.map(parseProvenanceRef);
}

function parseEvidenceNode(value: unknown): EvidenceGraphNode {
  if (!isRecord(value) || !isEvidenceNodeType(value.type) || !isEvidenceStatus(value.status)) {
    throw new Error('Invalid evidence graph response: node is invalid');
  }
  return {
    id: readString(value.id, 'node.id'),
    label: readString(value.label, 'node.label'),
    type: value.type,
    status: value.status,
    confidence: readOptionalNumber(value.confidence, 'node.confidence'),
    provenance_refs: parseProvenanceRefs(value.provenance_refs),
    metadata: readMetadata(value.metadata, 'node.metadata'),
  };
}

function parseEvidenceEdge(value: unknown): EvidenceGraphEdge {
  if (
    !isRecord(value)
    || !isEvidenceRelation(value.relation)
    || !isEvidenceStatus(value.status)
    || !isEvidenceCreatedBy(value.created_by)
  ) {
    throw new Error('Invalid evidence graph response: edge is invalid');
  }
  const expectedDirection = EVIDENCE_GRAPH_RELATION_DIRECTIONS[value.relation];
  const direction = value.direction === undefined
    ? expectedDirection
    : value.direction;
  if (!isEvidenceDirection(direction)) {
    throw new Error('Invalid evidence graph response: edge.direction must be directed or undirected');
  }
  if (direction !== expectedDirection) {
    throw new Error(
      `Invalid evidence graph response: ${value.relation} edges require direction=${expectedDirection}`,
    );
  }
  let source = readString(value.source, 'edge.source');
  let target = readString(value.target, 'edge.target');
  if (direction === 'undirected' && target < source) {
    [source, target] = [target, source];
  }
  return {
    id: readString(value.id, 'edge.id'),
    source,
    target,
    relation: value.relation,
    direction,
    status: value.status,
    confidence: readOptionalNumber(value.confidence, 'edge.confidence'),
    provenance_refs: parseProvenanceRefs(value.provenance_refs),
    created_by: value.created_by,
    updated_at: readString(value.updated_at, 'edge.updated_at'),
    metadata: readMetadata(value.metadata, 'edge.metadata'),
  };
}

export function parseEvidenceGraphPayload(value: unknown): EvidenceGraphPayload {
  if (!isRecord(value) || value.version !== 'v1') {
    throw new Error('Invalid evidence graph response: expected version v1');
  }
  if (!Array.isArray(value.nodes) || !Array.isArray(value.edges) || !Array.isArray(value.warnings)) {
    throw new Error('Invalid evidence graph response: nodes, edges, and warnings must be arrays');
  }
  const warnings = value.warnings.map((entry) => readString(entry, 'warnings[]'));
  return {
    version: 'v1',
    scope: parseEvidenceGraphScope(value.scope),
    updated_at: readString(value.updated_at, 'updated_at'),
    nodes: value.nodes.map(parseEvidenceNode),
    edges: value.edges.map(parseEvidenceEdge),
    warnings,
  };
}

export async function getGraphPayload(query: GraphPayloadQuery = {}): Promise<GraphPayloadV0> {
  const { data } = await axios.get<unknown>(`${API_BASE}/api/graph/payload`, {
    params: {
      scope_kind: query.scope_kind ?? 'question',
      scope_ref: query.scope_ref ?? '',
      ...(query.filter ? { filter: query.filter } : {}),
    },
  });
  if (!isGraphPayloadV0(data)) {
    throw new Error('Invalid graph payload response: expected nodes and edges arrays');
  }
  return data;
}

export async function getEvidenceGraph(query: EvidenceGraphQuery = {}): Promise<EvidenceGraphPayload> {
  const scopeKind = query.scope_kind ?? 'project';
  const scopeRef = query.scope_ref ?? '';
  const { data } = await axios.get<unknown>(`${API_BASE}/api/graph/evidence`, {
    params: {
      scope_kind: scopeKind,
      scope_ref: scopeRef,
      ...(query.session_id ? { session_id: query.session_id } : {}),
      ...(query.turn_id ? { turn_id: query.turn_id } : {}),
      ...(query.filter ? { filter: query.filter } : {}),
      ...(query.top_k !== undefined ? { top_k: query.top_k } : {}),
      ...(query.min_similarity !== undefined ? { min_similarity: query.min_similarity } : {}),
    },
  });
  return boundEvidenceGraphPayload(parseEvidenceGraphPayload(data));
}

function requiredQueryId(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${field} must be a non-empty string`);
  return normalized;
}

function withWarning(payload: EvidenceGraphPayload, warning: string): EvidenceGraphPayload {
  return payload.warnings.includes(warning)
    ? payload
    : { ...payload, warnings: [...payload.warnings, warning] };
}

function boundEvidenceGraphPayload(payload: EvidenceGraphPayload): EvidenceGraphPayload {
  if (payload.nodes.length <= EVIDENCE_GRAPH_NODE_LIMIT && payload.edges.length <= EVIDENCE_GRAPH_EDGE_LIMIT) {
    if (
      payload.nodes.length > EVIDENCE_GRAPH_DIRECT_NODE_LIMIT
      || payload.edges.length > EVIDENCE_GRAPH_DIRECT_EDGE_LIMIT
    ) {
      return withWarning(
        payload,
        `图谱已进入性能模式（超过 ${EVIDENCE_GRAPH_DIRECT_NODE_LIMIT} 个节点或 ${EVIDENCE_GRAPH_DIRECT_EDGE_LIMIT} 条关系）。`,
      );
    }
    return payload;
  }

  const nodes = payload.nodes.slice(0, EVIDENCE_GRAPH_NODE_LIMIT);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = payload.edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .slice(0, EVIDENCE_GRAPH_EDGE_LIMIT);
  const warning = `前端已将图谱限制为 ${EVIDENCE_GRAPH_NODE_LIMIT} 个节点和 ${EVIDENCE_GRAPH_EDGE_LIMIT} 条关系，以保持交互流畅。`;
  return {
    ...payload,
    nodes,
    edges,
    warnings: payload.warnings.includes(warning) ? payload.warnings : [...payload.warnings, warning],
  };
}

async function fetchEvidenceGraph(
  path: string,
  params: Readonly<Record<string, string | number>>,
): Promise<EvidenceGraphPayload> {
  const { data } = await axios.get<unknown>(`${API_BASE}${path}`, { params });
  return boundEvidenceGraphPayload(parseEvidenceGraphPayload(data));
}

/** Read only the project graph domain; this endpoint cannot access Wiki or answer state. */
export async function getProjectEvidenceGraph(
  query: ProjectEvidenceGraphQuery,
): Promise<EvidenceGraphPayload> {
  const projectId = requiredQueryId(query.project_id, 'project_id');
  return fetchEvidenceGraph('/api/graph/evidence/project', {
    project_id: projectId,
    ...(query.top_k !== undefined ? { top_k: query.top_k } : {}),
    ...(query.min_similarity !== undefined ? { min_similarity: query.min_similarity } : {}),
  });
}

/** Read exactly one persisted answer turn; question text is never accepted as a key. */
export async function getAnswerEvidenceGraph(
  query: AnswerEvidenceGraphQuery,
): Promise<EvidenceGraphPayload> {
  return fetchEvidenceGraph('/api/graph/evidence/answer', {
    session_id: requiredQueryId(query.session_id, 'session_id'),
    turn_id: requiredQueryId(query.turn_id, 'turn_id'),
  });
}

/** Read only the Wiki graph domain; this endpoint cannot access project citation or answer stores. */
export async function getWikiEvidenceGraph(
  query: WikiEvidenceGraphQuery = {},
): Promise<EvidenceGraphPayload> {
  return fetchEvidenceGraph('/api/graph/evidence/wiki', {
    scope_kind: query.scope_kind ?? 'project',
    scope_ref: query.scope_ref ?? '',
    ...(query.filter ? { filter: query.filter } : {}),
  });
}
