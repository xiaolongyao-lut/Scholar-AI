import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';
import type { components } from '@/generated/openapi';

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
  filter?: string;
}

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
  return {
    source_id: readOptionalString(value.source_id, 'source_id'),
    source_vault_id: readOptionalString(value.source_vault_id, 'source_vault_id'),
    chunk_id: readOptionalString(value.chunk_id, 'chunk_id'),
    source_vault_chunk_id: readOptionalString(value.source_vault_chunk_id, 'source_vault_chunk_id'),
    material_id: readOptionalString(value.material_id, 'material_id'),
    page: readOptionalNumber(value.page, 'page'),
    bbox: readBbox(value.bbox),
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
  return {
    id: readString(value.id, 'edge.id'),
    source: readString(value.source, 'edge.source'),
    target: readString(value.target, 'edge.target'),
    relation: value.relation,
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
      ...(query.filter ? { filter: query.filter } : {}),
    },
  });
  return parseEvidenceGraphPayload(data);
}
