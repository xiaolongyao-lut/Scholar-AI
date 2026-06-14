import type { GraphEdge, GraphNode, GraphPayloadV0 } from './payloadToRf';

/**
 * 六维思维角色 + 问题/背景兜底。
 *
 * 这是「论证结构」视角的归一化：用户看图谱不是想看「这个节点叫什么」，
 * 而是想看「这块东西在我的论证里扮演什么角色」。后端会逐步补 metadata
 * 来显式声明维度（slice 4），目前我们用启发式从节点 type / 关系 / 字段
 * 反推，缺失则归到 background。
 */
export type ReasoningDimension =
  | 'question'
  | 'observation'
  | 'mechanism'
  | 'evidence'
  | 'boundary'
  | 'counter_evidence'
  | 'next_action'
  | 'background';

export const REASONING_DIMENSIONS: readonly ReasoningDimension[] = [
  'question',
  'observation',
  'mechanism',
  'evidence',
  'boundary',
  'counter_evidence',
  'next_action',
  'background',
] as const;

/** 默认渲染顺序（从左到右，等价于设计文档里的泳道顺序）。 */
export const DIMENSION_DISPLAY_ORDER: readonly ReasoningDimension[] = [
  'question',
  'observation',
  'mechanism',
  'evidence',
  'boundary',
  'counter_evidence',
  'next_action',
  'background',
] as const;

export interface DimensionMeta {
  /** 中文标签，给泳道头和节点徽标用 */
  label: string;
  /** 一句话说明，给图例 hover 用 */
  description: string;
  /** 主色 (HSL color string fragment，注入到 tailwind/inline style) */
  accent: string;
  /** 辅助色 (淡背景) */
  surface: string;
  /** 边框色 (强调态) */
  border: string;
  /** 单字符徽标（无法用图标时的兜底） */
  glyph: string;
}

export const DIMENSION_META: Record<ReasoningDimension, DimensionMeta> = {
  question: {
    label: '问题',
    description: '当前要解决的问题或主题。',
    accent: 'hsl(220 85% 56%)',
    surface: 'hsl(220 85% 56% / 0.10)',
    border: 'hsl(220 85% 56% / 0.45)',
    glyph: '问',
  },
  observation: {
    label: '观察',
    description: '看到了什么、读到了什么。',
    accent: 'hsl(200 70% 45%)',
    surface: 'hsl(200 70% 45% / 0.10)',
    border: 'hsl(200 70% 45% / 0.45)',
    glyph: '察',
  },
  mechanism: {
    label: '机制',
    description: '为什么发生、怎么发生。',
    accent: 'hsl(265 60% 55%)',
    surface: 'hsl(265 60% 55% / 0.10)',
    border: 'hsl(265 60% 55% / 0.45)',
    glyph: '理',
  },
  evidence: {
    label: '证据',
    description: '哪些原文 / 数据支撑结论。',
    accent: 'hsl(155 55% 38%)',
    surface: 'hsl(155 55% 38% / 0.10)',
    border: 'hsl(155 55% 38% / 0.45)',
    glyph: '据',
  },
  boundary: {
    label: '边界',
    description: '适用范围、前提条件、限制。',
    accent: 'hsl(35 80% 45%)',
    surface: 'hsl(35 80% 45% / 0.10)',
    border: 'hsl(35 80% 45% / 0.45)',
    glyph: '界',
  },
  counter_evidence: {
    label: '反证',
    description: '反例、冲突证据、需要解释的不一致。',
    accent: 'hsl(0 70% 50%)',
    surface: 'hsl(0 70% 50% / 0.10)',
    border: 'hsl(0 70% 50% / 0.50)',
    glyph: '反',
  },
  next_action: {
    label: '下一步',
    description: '读完 / 写完后，下一步该做什么。',
    accent: 'hsl(295 60% 50%)',
    surface: 'hsl(295 60% 50% / 0.10)',
    border: 'hsl(295 60% 50% / 0.45)',
    glyph: '行',
  },
  background: {
    label: '背景',
    description: '尚未归类、视觉上弱化的节点。',
    accent: 'hsl(220 8% 50%)',
    surface: 'hsl(220 8% 50% / 0.08)',
    border: 'hsl(220 8% 50% / 0.32)',
    glyph: '·',
  },
};

const DIMENSION_LOOKUP: ReadonlySet<string> = new Set(REASONING_DIMENSIONS);

function isReasoningDimension(value: unknown): value is ReasoningDimension {
  return typeof value === 'string' && DIMENSION_LOOKUP.has(value);
}

/** 从 GraphNode.metadata 读出后端显式声明的维度（如果有）。 */
function explicitDimensionFromNode(node: GraphNode): DimensionAssignment | null {
  const meta = (node.metadata ?? {}) as Record<string, unknown>;
  const direct = meta.reasoning_dimension;
  if (isReasoningDimension(direct)) {
    return { dimension: direct, reason: 'metadata' };
  }
  const chainField = meta.analysis_chain_field;
  if (typeof chainField !== 'string') return null;
  switch (chainField) {
    case 'question':
      return { dimension: 'question', reason: 'analysis_chain_field' };
    case 'observation':
      return { dimension: 'observation', reason: 'analysis_chain_field' };
    case 'mechanism':
      return { dimension: 'mechanism', reason: 'analysis_chain_field' };
    case 'evidence':
      return { dimension: 'evidence', reason: 'analysis_chain_field' };
    case 'boundary':
      return { dimension: 'boundary', reason: 'analysis_chain_field' };
    case 'counter_evidence':
      return { dimension: 'counter_evidence', reason: 'analysis_chain_field' };
    case 'next_action':
      return { dimension: 'next_action', reason: 'analysis_chain_field' };
    default:
      return null;
  }
}

const CONTRADICT_RELATIONS = new Set(['contradicts', 'challenges', 'refutes']);
const SUPPORT_RELATIONS = new Set(['supports', 'supported_by']);
const DERIVE_RELATIONS = new Set(['derives_from', 'builds_on', 'extends']);

function adjacencyHeuristic(node: GraphNode, edges: GraphEdge[]): ReasoningDimension | null {
  let contradicts = 0;
  let supports = 0;
  let derives = 0;
  for (const edge of edges) {
    const incident = edge.source === node.id || edge.target === node.id;
    if (!incident) continue;
    if (CONTRADICT_RELATIONS.has(edge.relation)) contradicts += 1;
    else if (SUPPORT_RELATIONS.has(edge.relation)) supports += 1;
    else if (DERIVE_RELATIONS.has(edge.relation)) derives += 1;
  }
  if (contradicts > 0 && contradicts >= supports) return 'counter_evidence';
  if (supports > derives && supports > 0) return 'evidence';
  if (derives > 0) return 'mechanism';
  return null;
}

const SOURCE_LIKE_TYPES = new Set(['source', 'material', 'document', 'paper']);
const QUESTION_LIKE_TYPES = new Set(['question', 'topic', 'goal']);
const NEXT_ACTION_TYPES = new Set(['action', 'next_action', 'todo']);
const BOUNDARY_TYPES = new Set(['limitation', 'boundary', 'scope']);

function typeHeuristic(node: GraphNode): ReasoningDimension | null {
  const type = (node.type ?? '').toLowerCase();
  if (QUESTION_LIKE_TYPES.has(type)) return 'question';
  if (SOURCE_LIKE_TYPES.has(type)) return 'evidence';
  if (NEXT_ACTION_TYPES.has(type)) return 'next_action';
  if (BOUNDARY_TYPES.has(type)) return 'boundary';
  if (type === 'claim') return 'observation';
  if (type === 'concept') return 'mechanism';
  if (type === 'evidence') return 'evidence';
  return null;
}

function evidenceAnchorHeuristic(node: GraphNode): ReasoningDimension | null {
  const refs = node.evidence_refs ?? [];
  const hasAnchor = refs.some((ref) => Boolean(ref.material_id) || typeof ref.page === 'number');
  return hasAnchor ? 'evidence' : null;
}

export interface DimensionAssignment {
  dimension: ReasoningDimension;
  /** 哪一步给出的判断，便于 UI 在节点详情里告诉用户为什么被分到这里。 */
  reason:
    | 'metadata'
    | 'analysis_chain_field'
    | 'node_type'
    | 'edge_relations'
    | 'evidence_anchor'
    | 'fallback';
}

/**
 * 给单个节点决定维度。优先信后端 metadata，否则按 type / 关系 / 锚点回退。
 *
 * 输入：GraphNode + 同 payload 内的全部 edges（用来看入边/出边语义）。
 * 输出：维度 + 判断来源；判断来源被透传到节点详情面板里，避免「误判却没办法解释」。
 */
export function assignDimension(node: GraphNode, edges: GraphEdge[]): DimensionAssignment {
  const explicit = explicitDimensionFromNode(node);
  if (explicit) return explicit;
  const fromType = typeHeuristic(node);
  if (fromType) return { dimension: fromType, reason: 'node_type' };
  const fromEdges = adjacencyHeuristic(node, edges);
  if (fromEdges) return { dimension: fromEdges, reason: 'edge_relations' };
  const fromAnchor = evidenceAnchorHeuristic(node);
  if (fromAnchor) return { dimension: fromAnchor, reason: 'evidence_anchor' };
  return { dimension: 'background', reason: 'fallback' };
}

export interface DimensionGraphNode {
  node: GraphNode;
  dimension: ReasoningDimension;
  reason: DimensionAssignment['reason'];
  /**
   * 用于节点底部元信息的总览：来源标签 + 证据数。
   * 这些字段都已在节点上有原始数据，只是预先归一化好给视图层用。
   */
  display: {
    title: string;
    typeLabel: string;
    sourceLabel?: string;
    evidenceCount: number;
    confidence: number | null;
    status?: string | null;
  };
}

export interface DimensionGraph {
  nodes: DimensionGraphNode[];
  edges: GraphEdge[];
  counts: Record<ReasoningDimension, number>;
}

const TYPE_DISPLAY: Record<string, string> = {
  claim: '断言',
  concept: '概念',
  evidence: '证据',
  source: '文献',
  material: '文献',
  paper: '论文',
  agent: '智能体',
  question: '问题',
  action: '动作',
  next_action: '动作',
  todo: '动作',
  limitation: '局限',
  boundary: '边界',
  topic: '主题',
  goal: '目标',
  document: '文档',
};

function readSourceLabel(node: GraphNode): string | undefined {
  const meta = (node.metadata ?? {}) as Record<string, unknown>;
  if (typeof meta.source_label === 'string') return meta.source_label;
  if (typeof meta.source_title === 'string') return meta.source_title;
  const sourceRef = node.source_ref;
  if (sourceRef && typeof sourceRef.material_id === 'string') {
    const page = typeof sourceRef.page === 'number' && sourceRef.page > 0 ? ` p.${sourceRef.page}` : '';
    return `${sourceRef.material_id}${page}`;
  }
  const firstEvidence = (node.evidence_refs ?? []).find((ref) => Boolean(ref.material_id));
  if (firstEvidence) {
    const page = typeof firstEvidence.page === 'number' && firstEvidence.page > 0 ? ` p.${firstEvidence.page}` : '';
    return `${firstEvidence.material_id}${page}`;
  }
  return undefined;
}

function readConfidence(node: GraphNode): number | null {
  if (typeof node.confidence === 'number' && Number.isFinite(node.confidence)) return node.confidence;
  const refs = node.evidence_refs ?? [];
  const scores = refs.map((ref) => ref.score).filter((s): s is number => typeof s === 'number' && Number.isFinite(s));
  if (scores.length === 0) return null;
  return scores.reduce((sum, s) => sum + s, 0) / scores.length;
}

function readStatus(node: GraphNode): string | null {
  const meta = (node.metadata ?? {}) as Record<string, unknown>;
  if (typeof meta.status === 'string') return meta.status;
  return null;
}

const MAX_TITLE_LENGTH = 72;

function truncateTitle(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '未命名节点';
  if (trimmed.length <= MAX_TITLE_LENGTH) return trimmed;
  return `${trimmed.slice(0, MAX_TITLE_LENGTH - 1)}…`;
}

/**
 * 把 GraphPayloadV0 整体投影到「维度图谱」：每个节点带上维度 + 显示元信息，
 * 边保持原样（颜色由 viewer 决定）。
 */
export function buildDimensionGraph(payload: GraphPayloadV0): DimensionGraph {
  const nodeIds = new Set(payload.nodes.map((node) => node.id));
  const edges = payload.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const counts: Record<ReasoningDimension, number> = {
    question: 0,
    observation: 0,
    mechanism: 0,
    evidence: 0,
    boundary: 0,
    counter_evidence: 0,
    next_action: 0,
    background: 0,
  };
  const nodes: DimensionGraphNode[] = payload.nodes.map((node) => {
    const assignment = assignDimension(node, edges);
    counts[assignment.dimension] += 1;
    const typeLabel = TYPE_DISPLAY[(node.type ?? '').toLowerCase()] ?? (node.type ?? '节点');
    return {
      node,
      dimension: assignment.dimension,
      reason: assignment.reason,
      display: {
        title: truncateTitle(node.label),
        typeLabel,
        sourceLabel: readSourceLabel(node),
        evidenceCount: (node.evidence_refs?.length ?? 0) + (node.source_ref ? 1 : 0),
        confidence: readConfidence(node),
        status: readStatus(node),
      },
    };
  });
  return { nodes, edges, counts };
}

/**
 * 给「未归类」的节点视觉弱化用：在 viewer 里降低不透明度。
 */
export function isBackgroundDimension(dimension: ReasoningDimension): boolean {
  return dimension === 'background';
}
