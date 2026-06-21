import {
  DIMENSION_META,
  REASONING_DIMENSIONS,
  assignDimension,
  type ReasoningDimension,
} from './dimensionGraph';
import type { GraphEdge, GraphNode, GraphPayloadV0 } from './payloadToRf';

export const REVIEW_DASHBOARD_SPEC_SCHEMA_VERSION = 'scholar-ai-review-dashboard-spec/v1' as const;

export type ReviewBucketStatus = 'ok' | 'review_required';

export interface ReviewCountBucket {
  id: string;
  label: string;
  count: number;
  status: ReviewBucketStatus;
  node_ids: string[];
}

export interface ReviewDimensionBucket {
  dimension: ReasoningDimension;
  label: string;
  node_count: number;
  evidence_ref_count: number;
  missing_anchor_count: number;
}

export interface ReviewRelationBucket {
  relation: string;
  edge_count: number;
  evidence_ref_count: number;
  low_confidence_count: number;
}

export type ReviewDiagnosticSeverity = 'info' | 'warning' | 'critical';
export type ReviewDiagnosticSubject = 'edge' | 'node' | 'material' | 'label';

export interface ReviewDiagnosticBucket {
  id:
    | 'dangling_edges'
    | 'relations_missing_evidence'
    | 'low_confidence_relations'
    | 'source_overlap_relations'
    | 'duplicate_label_groups';
  label: string;
  count: number;
  status: ReviewBucketStatus;
  severity: ReviewDiagnosticSeverity;
  subject: ReviewDiagnosticSubject;
  item_ids: string[];
  message: string;
}

export interface ReviewDuplicateLabelGroup {
  label: string;
  node_ids: string[];
  count: number;
}

export interface ReviewSourceOverlapGroup {
  material_id: string;
  edge_ids: string[];
  node_ids: string[];
  count: number;
}

export interface ReviewDashboardSummary {
  node_count: number;
  edge_count: number;
  dangling_edge_count: number;
  material_count: number;
  evidence_ref_count: number;
  orphan_node_count: number;
  duplicate_label_count: number;
  missing_anchor_count: number;
  relation_without_evidence_count: number;
  source_overlap_relation_count: number;
}

export interface ReviewLargeLibraryHint {
  kind: 'aggregate_by_dimension' | 'group_by_material' | 'filter_orphans' | 'review_duplicates';
  message: string;
  count: number;
}

export interface ReviewDashboardSpecV1 {
  schema_version: typeof REVIEW_DASHBOARD_SPEC_SCHEMA_VERSION;
  source_graph_version: string;
  scope: GraphPayloadV0['scope'] | null;
  generated_at: string | null;
  summary: ReviewDashboardSummary;
  dimensions: ReviewDimensionBucket[];
  relations: ReviewRelationBucket[];
  missing_metadata_buckets: ReviewCountBucket[];
  graph_diagnostics: ReviewDiagnosticBucket[];
  duplicate_label_groups: ReviewDuplicateLabelGroup[];
  source_overlap_groups: ReviewSourceOverlapGroup[];
  large_library_hints: ReviewLargeLibraryHint[];
}

export interface ReviewDashboardSpecOptions {
  generatedAt?: string | null;
  largeNodeThreshold?: number;
  largeMaterialThreshold?: number;
}

function normalizeId(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizeLabel(value: unknown): string {
  return typeof value === 'string' ? value.trim().toLowerCase().replace(/\s+/g, ' ') : '';
}

function readMetadata(node: GraphNode): Record<string, unknown> {
  return node.metadata && typeof node.metadata === 'object' ? node.metadata as Record<string, unknown> : {};
}

function readEdgeMetadata(edge: GraphEdge): Record<string, unknown> {
  return edge.metadata && typeof edge.metadata === 'object' ? edge.metadata as Record<string, unknown> : {};
}

function nodeHasSourceAnchor(node: GraphNode): boolean {
  if (node.source_ref?.material_id || node.material_id) return true;
  return (node.evidence_refs ?? []).some((ref) => Boolean(ref.material_id));
}

function nodeEvidenceCount(node: GraphNode): number {
  return (node.evidence_refs ?? []).filter((ref) => Boolean(ref.material_id) || Boolean(ref.text)).length
    + (node.source_ref ? 1 : 0);
}

function edgeEvidenceCount(edge: GraphEdge): number {
  return (edge.evidence_refs ?? []).filter((ref) => Boolean(ref.material_id) || Boolean(ref.text)).length
    + (edge.source_ref ? 1 : 0);
}

function readConfidence(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function uniqueMaterials(nodes: GraphNode[], edges: GraphEdge[]): Set<string> {
  const materialIds = new Set<string>();
  const add = (value: unknown): void => {
    const id = normalizeId(value);
    if (id) materialIds.add(id);
  };
  for (const node of nodes) {
    add(node.material_id);
    add(node.source_ref?.material_id);
    for (const ref of node.evidence_refs ?? []) add(ref.material_id);
  }
  for (const edge of edges) {
    add(edge.material_id);
    add(edge.source_ref?.material_id);
    for (const ref of edge.evidence_refs ?? []) add(ref.material_id);
  }
  return materialIds;
}

function orphanNodeIds(nodes: GraphNode[], edges: GraphEdge[]): Set<string> {
  const connected = new Set<string>();
  for (const edge of edges) {
    connected.add(edge.source);
    connected.add(edge.target);
  }
  return new Set(nodes.filter((node) => !connected.has(node.id)).map((node) => node.id));
}

function duplicateLabelNodeIds(nodes: GraphNode[]): Set<string> {
  const duplicates = new Set<string>();
  for (const group of duplicateLabelGroups(nodes)) {
    for (const id of group.node_ids) duplicates.add(id);
  }
  return duplicates;
}

function duplicateLabelGroups(nodes: GraphNode[]): ReviewDuplicateLabelGroup[] {
  const groupsByLabel = new Map<string, { label: string; node_ids: string[] }>();
  for (const node of nodes) {
    const normalized = normalizeLabel(node.label);
    if (!normalized) continue;
    const existing = groupsByLabel.get(normalized) ?? {
      label: node.label.trim() || normalized,
      node_ids: [],
    };
    existing.node_ids.push(node.id);
    groupsByLabel.set(normalized, existing);
  }
  return Array.from(groupsByLabel.values())
    .filter((group) => group.node_ids.length > 1)
    .map((group) => ({
      label: group.label,
      node_ids: [...group.node_ids].sort(),
      count: group.node_ids.length,
    }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
}

function countStatus(count: number): ReviewBucketStatus {
  return count > 0 ? 'review_required' : 'ok';
}

function buildMissingBuckets(
  nodes: GraphNode[],
  orphanIds: Set<string>,
  duplicateIds: Set<string>,
): ReviewCountBucket[] {
  const missingAnchors = nodes.filter((node) => !nodeHasSourceAnchor(node)).map((node) => node.id);
  const missingDimensionMetadata = nodes
    .filter((node) => {
      const metadata = readMetadata(node);
      return typeof metadata.reasoning_dimension !== 'string' && typeof metadata.analysis_chain_field !== 'string';
    })
    .map((node) => node.id);
  const missingEvidenceRefs = nodes
    .filter((node) => node.type === 'evidence' && nodeEvidenceCount(node) === 0)
    .map((node) => node.id);
  const buckets = [
    { id: 'missing_source_anchor', label: '缺少来源锚点', node_ids: missingAnchors },
    { id: 'missing_dimension_metadata', label: '缺少显式语义维度', node_ids: missingDimensionMetadata },
    { id: 'missing_evidence_refs', label: '证据节点缺少 refs', node_ids: missingEvidenceRefs },
    { id: 'orphan_nodes', label: '孤立节点', node_ids: Array.from(orphanIds) },
    { id: 'duplicate_labels', label: '重复标签', node_ids: Array.from(duplicateIds) },
  ];
  return buckets.map((bucket) => ({
    id: bucket.id,
    label: bucket.label,
    count: bucket.node_ids.length,
    status: countStatus(bucket.node_ids.length),
    node_ids: bucket.node_ids,
  }));
}

function buildDimensionBuckets(nodes: GraphNode[], edges: GraphEdge[]): ReviewDimensionBucket[] {
  return REASONING_DIMENSIONS.map((dimension) => {
    const dimensionNodes = nodes.filter((node) => assignDimension(node, edges).dimension === dimension);
    return {
      dimension,
      label: DIMENSION_META[dimension].label,
      node_count: dimensionNodes.length,
      evidence_ref_count: dimensionNodes.reduce((sum, node) => sum + nodeEvidenceCount(node), 0),
      missing_anchor_count: dimensionNodes.filter((node) => !nodeHasSourceAnchor(node)).length,
    };
  });
}

function buildRelationBuckets(edges: GraphEdge[]): ReviewRelationBucket[] {
  const byRelation = new Map<string, GraphEdge[]>();
  for (const edge of edges) {
    const relation = normalizeId(edge.relation) || 'related';
    const list = byRelation.get(relation) ?? [];
    list.push(edge);
    byRelation.set(relation, list);
  }
  return Array.from(byRelation.entries())
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([relation, relationEdges]) => ({
      relation,
      edge_count: relationEdges.length,
      evidence_ref_count: relationEdges.reduce((sum, edge) => sum + edgeEvidenceCount(edge), 0),
      low_confidence_count: relationEdges.filter((edge) => {
        const confidence = readConfidence(edge.confidence) ?? readConfidence(readEdgeMetadata(edge).confidence);
        return confidence !== null && confidence < 0.5;
      }).length,
    }));
}

function edgeIds(edges: GraphEdge[]): string[] {
  return edges.map((edge) => edge.id).sort();
}

function readMaterialIdsFromRefs(refs: GraphNode['evidence_refs'] | GraphEdge['evidence_refs']): Set<string> {
  const ids = new Set<string>();
  for (const ref of refs ?? []) {
    const id = normalizeId(ref.material_id);
    if (id) ids.add(id);
  }
  return ids;
}

function materialIdsForNode(node: GraphNode): Set<string> {
  const ids = readMaterialIdsFromRefs(node.evidence_refs);
  const materialId = normalizeId(node.material_id);
  if (materialId) ids.add(materialId);
  const sourceMaterialId = normalizeId(node.source_ref?.material_id);
  if (sourceMaterialId) ids.add(sourceMaterialId);
  return ids;
}

function confidenceForEdge(edge: GraphEdge): number | null {
  return readConfidence(edge.confidence) ?? readConfidence(readEdgeMetadata(edge).confidence);
}

function buildSourceOverlapGroups(
  edges: GraphEdge[],
  nodesById: Map<string, GraphNode>,
): ReviewSourceOverlapGroup[] {
  const groups = new Map<string, { edge_ids: Set<string>; node_ids: Set<string> }>();
  for (const edge of edges) {
    const sourceNode = nodesById.get(edge.source);
    const targetNode = nodesById.get(edge.target);
    if (!sourceNode || !targetNode) continue;
    const sourceMaterials = materialIdsForNode(sourceNode);
    const targetMaterials = materialIdsForNode(targetNode);
    for (const materialId of sourceMaterials) {
      if (!targetMaterials.has(materialId)) continue;
      const group = groups.get(materialId) ?? { edge_ids: new Set<string>(), node_ids: new Set<string>() };
      group.edge_ids.add(edge.id);
      group.node_ids.add(sourceNode.id);
      group.node_ids.add(targetNode.id);
      groups.set(materialId, group);
    }
  }
  return Array.from(groups.entries())
    .map(([material_id, group]) => {
      const edge_ids = Array.from(group.edge_ids).sort();
      return {
        material_id,
        edge_ids,
        node_ids: Array.from(group.node_ids).sort(),
        count: edge_ids.length,
      };
    })
    .sort((left, right) => right.count - left.count || left.material_id.localeCompare(right.material_id));
}

function buildGraphDiagnostics({
  danglingEdges,
  validEdges,
  duplicateGroups,
  sourceOverlapGroups,
}: {
  danglingEdges: GraphEdge[];
  validEdges: GraphEdge[];
  duplicateGroups: ReviewDuplicateLabelGroup[];
  sourceOverlapGroups: ReviewSourceOverlapGroup[];
}): ReviewDiagnosticBucket[] {
  const relationsMissingEvidence = validEdges.filter((edge) => edgeEvidenceCount(edge) === 0);
  const lowConfidenceRelations = validEdges.filter((edge) => {
    const confidence = confidenceForEdge(edge);
    return confidence !== null && confidence < 0.5;
  });
  const sourceOverlapEdgeIds = new Set(sourceOverlapGroups.flatMap((group) => group.edge_ids));
  const duplicateNodeIds = duplicateGroups.flatMap((group) => group.node_ids).sort();
  const buckets: ReviewDiagnosticBucket[] = [
    {
      id: 'dangling_edges',
      label: '悬空关系',
      count: danglingEdges.length,
      status: countStatus(danglingEdges.length),
      severity: 'critical',
      subject: 'edge',
      item_ids: edgeIds(danglingEdges),
      message: '存在指向缺失节点的关系，图谱导入或 wiki 编译需要回查来源记录。',
    },
    {
      id: 'relations_missing_evidence',
      label: '关系缺少证据',
      count: relationsMissingEvidence.length,
      status: countStatus(relationsMissingEvidence.length),
      severity: 'warning',
      subject: 'edge',
      item_ids: edgeIds(relationsMissingEvidence),
      message: '存在没有 source_ref 或 evidence_refs 的关系，回答引用前应补证据锚点。',
    },
    {
      id: 'low_confidence_relations',
      label: '低置信关系',
      count: lowConfidenceRelations.length,
      status: countStatus(lowConfidenceRelations.length),
      severity: 'warning',
      subject: 'edge',
      item_ids: edgeIds(lowConfidenceRelations),
      message: '存在置信度低于 0.5 的关系，建议进入 review queue 后再用于写作。',
    },
    {
      id: 'source_overlap_relations',
      label: '同源关系',
      count: sourceOverlapEdgeIds.size,
      status: countStatus(sourceOverlapEdgeIds.size),
      severity: 'info',
      subject: 'material',
      item_ids: Array.from(sourceOverlapEdgeIds).sort(),
      message: '关系两端复用了相同材料，适合检查是否为同一证据的重复解释或 citation overlap。',
    },
    {
      id: 'duplicate_label_groups',
      label: '重复标签组',
      count: duplicateGroups.length,
      status: countStatus(duplicateGroups.length),
      severity: 'warning',
      subject: 'label',
      item_ids: duplicateNodeIds,
      message: '存在同名节点组，建议合并同义节点或补充 disambiguation metadata。',
    },
  ];
  return buckets;
}

function buildLargeLibraryHints(
  summary: ReviewDashboardSummary,
  options: Required<Pick<ReviewDashboardSpecOptions, 'largeNodeThreshold' | 'largeMaterialThreshold'>>,
): ReviewLargeLibraryHint[] {
  const hints: ReviewLargeLibraryHint[] = [];
  if (summary.node_count >= options.largeNodeThreshold) {
    hints.push({
      kind: 'aggregate_by_dimension',
      message: '节点较多，优先按语义维度聚合后再审阅。',
      count: summary.node_count,
    });
  }
  if (summary.material_count >= options.largeMaterialThreshold) {
    hints.push({
      kind: 'group_by_material',
      message: '材料数量较多，优先按文献/材料分组检查证据来源。',
      count: summary.material_count,
    });
  }
  if (summary.orphan_node_count > 0) {
    hints.push({
      kind: 'filter_orphans',
      message: '存在孤立节点，建议先筛出并补关系或移出图谱。',
      count: summary.orphan_node_count,
    });
  }
  if (summary.duplicate_label_count > 0) {
    hints.push({
      kind: 'review_duplicates',
      message: '存在重复标签，建议合并同义节点或补充 disambiguation metadata。',
      count: summary.duplicate_label_count,
    });
  }
  return hints;
}

/**
 * Build a deterministic semantic review/dashboard specification from
 * GraphPayloadV0. The spec is renderer-neutral so React views, backend
 * artifacts, and MCP agents can review the same buckets without copying UI
 * state.
 */
export function buildSemanticReviewSpec(
  payload: GraphPayloadV0,
  options: ReviewDashboardSpecOptions = {},
): ReviewDashboardSpecV1 {
  const nodeIds = new Set(payload.nodes.map((node) => node.id));
  const nodesById = new Map(payload.nodes.map((node) => [node.id, node] as const));
  const edges = payload.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const danglingEdges = payload.edges.filter((edge) => !nodeIds.has(edge.source) || !nodeIds.has(edge.target));
  const materialIds = uniqueMaterials(payload.nodes, edges);
  const orphanIds = orphanNodeIds(payload.nodes, edges);
  const duplicateGroups = duplicateLabelGroups(payload.nodes);
  const duplicateIds = duplicateLabelNodeIds(payload.nodes);
  const sourceOverlapGroups = buildSourceOverlapGroups(edges, nodesById);
  const evidenceRefCount = payload.nodes.reduce((sum, node) => sum + nodeEvidenceCount(node), 0)
    + edges.reduce((sum, edge) => sum + edgeEvidenceCount(edge), 0);
  const missingAnchorCount = payload.nodes.filter((node) => !nodeHasSourceAnchor(node)).length;
  const relationWithoutEvidenceCount = edges.filter((edge) => edgeEvidenceCount(edge) === 0).length;
  const summary: ReviewDashboardSummary = {
    node_count: payload.nodes.length,
    edge_count: edges.length,
    dangling_edge_count: danglingEdges.length,
    material_count: materialIds.size,
    evidence_ref_count: evidenceRefCount,
    orphan_node_count: orphanIds.size,
    duplicate_label_count: duplicateIds.size,
    missing_anchor_count: missingAnchorCount,
    relation_without_evidence_count: relationWithoutEvidenceCount,
    source_overlap_relation_count: sourceOverlapGroups.reduce((sum, group) => sum + group.count, 0),
  };
  const thresholds = {
    largeNodeThreshold: options.largeNodeThreshold ?? 200,
    largeMaterialThreshold: options.largeMaterialThreshold ?? 50,
  };
  return {
    schema_version: REVIEW_DASHBOARD_SPEC_SCHEMA_VERSION,
    source_graph_version: payload.version,
    scope: payload.scope ?? null,
    generated_at: options.generatedAt ?? payload.updated_at ?? null,
    summary,
    dimensions: buildDimensionBuckets(payload.nodes, edges),
    relations: buildRelationBuckets(edges),
    missing_metadata_buckets: buildMissingBuckets(payload.nodes, orphanIds, duplicateIds),
    graph_diagnostics: buildGraphDiagnostics({
      danglingEdges,
      validEdges: edges,
      duplicateGroups,
      sourceOverlapGroups,
    }),
    duplicate_label_groups: duplicateGroups,
    source_overlap_groups: sourceOverlapGroups,
    large_library_hints: buildLargeLibraryHints(summary, thresholds),
  };
}
