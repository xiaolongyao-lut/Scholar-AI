import type { GraphEdgeDirection } from '@/components/graph/graphGeometry';

export interface WikiGraphRelationPresentation {
  readonly relation: string;
  readonly direction: GraphEdgeDirection;
  readonly label: string;
}
const RELATED: WikiGraphRelationPresentation = {
  relation: 'related',
  direction: 'undirected',
  label: '相关',
};

const WIKI_GRAPH_RELATIONS: Readonly<Record<string, WikiGraphRelationPresentation>> = {
  supports: { relation: 'supports', direction: 'directed', label: '支持' },
  contradicts: { relation: 'contradicts', direction: 'directed', label: '冲突' },
  challenges: { relation: 'contradicts', direction: 'directed', label: '质疑' },
  critiques_concept: { relation: 'contradicts', direction: 'directed', label: '批评概念' },
  derived_from: { relation: 'derived_from', direction: 'directed', label: '源自' },
  derives_from: { relation: 'derived_from', direction: 'directed', label: '源自' },
  extends: { relation: 'derived_from', direction: 'directed', label: '扩展' },
  extends_concept: { relation: 'derived_from', direction: 'directed', label: '扩展概念' },
  improves_on: { relation: 'derived_from', direction: 'directed', label: '改进' },
  builds_on: { relation: 'derived_from', direction: 'directed', label: '建立于' },
  introduces_concept: { relation: 'derived_from', direction: 'directed', label: '提出概念' },
  uses_concept: { relation: 'mentions', direction: 'directed', label: '使用概念' },
  depends_on: { relation: 'mentions', direction: 'directed', label: '依赖' },
  cites: { relation: 'cites', direction: 'directed', label: '引用' },
  surveys: { relation: 'cites', direction: 'directed', label: '综述' },
  compares_against: { relation: 'related', direction: 'undirected', label: '比较' },
  same_problem_as: { relation: 'related', direction: 'undirected', label: '同类问题' },
  similar_method_to: { relation: 'related', direction: 'undirected', label: '相似方法' },
  complementary_to: { relation: 'related', direction: 'undirected', label: '互补' },
  related_to: RELATED,
  wikilink: { relation: 'related', direction: 'undirected', label: '页面链接' },
};

/**
 * Collapse the Wiki edge ontology into the shared read-only graph contract.
 * Unknown relations stay conservative: an unrecognized edge must not gain an
 * arrow and imply a direction that the source contract never established.
 */
export function resolveWikiGraphRelation(edgeType: string): WikiGraphRelationPresentation {
  const normalized = edgeType.trim().toLowerCase();
  return WIKI_GRAPH_RELATIONS[normalized] ?? RELATED;
}
