import { GitBranch } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';

import { PageHeader } from '@/components/common/PageHeader';
import { WikiGraphSegmentedView } from '@/components/graph/WikiGraphSegmentedView';
import type { GraphPayloadV0 } from '@/components/graph/payloadToRf';

const ACCEPTANCE_GRAPH_PAYLOAD: GraphPayloadV0 = {
  version: 'v0',
  scope: { kind: 'concept', ref: 'desktop_acceptance_semantic_review' },
  updated_at: '2026-06-21T00:00:00.000Z',
  nodes: [
    {
      id: 'topic-question',
      type: 'concept',
      label: '研究对象和方法链路',
      confidence: 0.92,
      material_id: null,
      metadata: { reasoning_dimension: 'question' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'claim-observation',
      type: 'claim',
      label: '重复诊断节点',
      confidence: 0.78,
      material_id: 'material-alpha',
      metadata: { reasoning_dimension: 'observation' },
      source_ref: {
        material_id: 'material-alpha',
        chunk_id: 'chunk-alpha-001',
        page: 2,
      },
      evidence_refs: [
        {
          material_id: 'material-alpha',
          chunk_id: 'chunk-alpha-001',
          page: 2,
          score: 0.84,
          text: '作者用对照组建立了主要观察。',
        },
      ],
    },
    {
      id: 'claim-mechanism',
      type: 'claim',
      label: '重复诊断节点',
      confidence: 0.22,
      material_id: 'material-alpha',
      metadata: { reasoning_dimension: 'mechanism' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'evidence-support',
      type: 'evidence',
      label: '关键证据片段',
      confidence: 0.7,
      material_id: 'material-beta',
      metadata: { reasoning_dimension: 'evidence' },
      source_ref: null,
      evidence_refs: [
        {
          material_id: 'material-beta',
          chunk_id: 'chunk-beta-004',
          page: 5,
          score: 0.73,
          text: '补充材料给出了关键证据片段。',
        },
      ],
    },
  ],
  edges: [
    {
      id: 'topic-to-observation',
      source: 'topic-question',
      target: 'claim-observation',
      relation: 'extends',
      confidence: 0.82,
      metadata: { tolf_evidence_score: 0.8 },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'observation-to-mechanism',
      source: 'claim-observation',
      target: 'claim-mechanism',
      relation: 'related',
      confidence: 0.2,
      metadata: {},
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'dangling-diagnostic-edge',
      source: 'claim-mechanism',
      target: 'missing-target-node',
      relation: 'supports',
      confidence: 0.9,
      metadata: {},
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'evidence-to-observation',
      source: 'evidence-support',
      target: 'claim-observation',
      relation: 'supports',
      confidence: 0.74,
      metadata: { tolf_evidence_score: 0.73 },
      source_ref: null,
      evidence_refs: [
        {
          material_id: 'material-beta',
          chunk_id: 'chunk-beta-004',
          page: 5,
          score: 0.73,
          text: '补充材料给出了关键证据片段。',
        },
      ],
    },
  ],
};

const PROJECT_LITERATURE_NODES: GraphPayloadV0['nodes'] = Array.from(
  { length: 24 },
  (_, index) => ({
    id: `project-paper-${index.toString().padStart(2, '0')}`,
    type: 'material',
    label: index === 0
      ? '检索增强生成综述'
      : `文献 ${index.toString().padStart(2, '0')} · ${['方法评估', '证据整合', '领域迁移'][index % 3]}`,
    confidence: Math.max(0.55, 0.98 - index * 0.015),
    material_id: `acceptance-material-${index.toString().padStart(2, '0')}`,
    metadata: {
      graph_scope: 'project_literature',
      publication_year: 2021 + (index % 5),
    },
    source_ref: null,
    evidence_refs: [],
  }),
);

const PROJECT_LITERATURE_EDGES: GraphPayloadV0['edges'] = [
  ...PROJECT_LITERATURE_NODES.map((node, index) => ({
    id: `project-related-${index.toString().padStart(2, '0')}`,
    source: node.id,
    target: PROJECT_LITERATURE_NODES[(index + 1) % PROJECT_LITERATURE_NODES.length].id,
    relation: 'related' as const,
    direction: 'undirected' as const,
    confidence: 0.66 + (index % 4) * 0.05,
    metadata: { graph_scope: 'project_literature' },
    source_ref: null,
    evidence_refs: [],
  })),
  ...PROJECT_LITERATURE_NODES.slice(1).map((node, index) => ({
    id: `project-cites-${(index + 1).toString().padStart(2, '0')}`,
    source: node.id,
    target: PROJECT_LITERATURE_NODES[0].id,
    relation: 'cites' as const,
    direction: 'directed' as const,
    confidence: 0.72 + (index % 5) * 0.04,
    metadata: { graph_scope: 'project_literature' },
    source_ref: null,
    evidence_refs: [],
  })),
];

const PROJECT_LITERATURE_GRAPH_PAYLOAD: GraphPayloadV0 = {
  version: 'v0',
  scope: { kind: 'material', ref: 'desktop_acceptance_project_literature' },
  updated_at: '2026-07-21T00:00:00.000Z',
  nodes: PROJECT_LITERATURE_NODES,
  edges: PROJECT_LITERATURE_EDGES,
};

const ANSWER_GRAPH_PAYLOAD: GraphPayloadV0 = {
  version: 'v0',
  scope: { kind: 'question', ref: 'desktop-acceptance-session:turn-r6' },
  updated_at: '2026-07-21T00:00:00.000Z',
  nodes: [
    {
      id: 'answer-question',
      type: 'concept',
      label: '这些研究如何验证检索增强生成？',
      confidence: 1,
      material_id: null,
      metadata: { reasoning_dimension: 'question', turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-claim-ablation',
      type: 'claim',
      label: '受控消融显示检索贡献',
      confidence: 0.91,
      material_id: null,
      metadata: { reasoning_dimension: 'observation', turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-claim-transfer',
      type: 'claim',
      label: '跨数据集结果保持一致',
      confidence: 0.86,
      material_id: null,
      metadata: { reasoning_dimension: 'mechanism', turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-evidence-ablation',
      type: 'evidence',
      label: '消融后准确率下降 12.4%',
      confidence: 0.94,
      material_id: 'answer-paper-chen',
      metadata: { reasoning_dimension: 'evidence', turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-evidence-transfer',
      type: 'evidence',
      label: '三个数据集均通过显著性检验',
      confidence: 0.89,
      material_id: 'answer-paper-wang',
      metadata: { reasoning_dimension: 'evidence', turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-paper-chen',
      type: 'material',
      label: 'Chen et al. 2025',
      confidence: 0.98,
      material_id: 'answer-paper-chen',
      metadata: { reasoning_dimension: 'background', turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-paper-wang',
      type: 'material',
      label: 'Wang et al. 2024',
      confidence: 0.97,
      material_id: 'answer-paper-wang',
      metadata: { reasoning_dimension: 'background', turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
  ],
  edges: [
    {
      id: 'answer-ablation-to-question',
      source: 'answer-claim-ablation',
      target: 'answer-question',
      relation: 'supports',
      direction: 'directed',
      confidence: 0.92,
      metadata: { turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-transfer-to-question',
      source: 'answer-claim-transfer',
      target: 'answer-question',
      relation: 'supports',
      direction: 'directed',
      confidence: 0.87,
      metadata: { turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-claims-related',
      source: 'answer-claim-ablation',
      target: 'answer-claim-transfer',
      relation: 'related',
      direction: 'undirected',
      confidence: 0.71,
      metadata: { turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-evidence-to-ablation',
      source: 'answer-evidence-ablation',
      target: 'answer-claim-ablation',
      relation: 'supports',
      direction: 'directed',
      confidence: 0.94,
      metadata: { turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-evidence-to-transfer',
      source: 'answer-evidence-transfer',
      target: 'answer-claim-transfer',
      relation: 'supports',
      direction: 'directed',
      confidence: 0.89,
      metadata: { turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-chen-to-evidence',
      source: 'answer-paper-chen',
      target: 'answer-evidence-ablation',
      relation: 'produces',
      direction: 'directed',
      confidence: 0.98,
      metadata: { turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
    {
      id: 'answer-wang-to-evidence',
      source: 'answer-paper-wang',
      target: 'answer-evidence-transfer',
      relation: 'produces',
      direction: 'directed',
      confidence: 0.96,
      metadata: { turn_id: 'turn-r6' },
      source_ref: null,
      evidence_refs: [],
    },
  ],
};

type AcceptanceSurface = 'wiki' | 'project' | 'answer';

function readAcceptanceSurface(value: string | null): AcceptanceSurface {
  if (value === 'project' || value === 'answer') return value;
  return 'wiki';
}

export function DesktopAcceptanceSemanticReview() {
  const [searchParams] = useSearchParams();
  const surface = readAcceptanceSurface(searchParams.get('surface'));
  const title = surface === 'project'
    ? '项目文献网络'
    : surface === 'answer'
      ? '回答论证图'
      : '语义复审';
  const subtitle = surface === 'project'
    ? '本地高密度关系夹具 · 24 篇文献'
    : surface === 'answer'
      ? '单轮只读夹具 · 问题、主张、证据与文献'
      : '本地图谱诊断';

  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden bg-background px-5 py-4"
      data-testid="desktop-acceptance-semantic-review"
      data-acceptance-surface={surface}
    >
      <PageHeader
        icon={<GitBranch size={18} />}
        title={title}
        subtitle={subtitle}
        className="mb-3 shrink-0"
      />
      <div className="min-h-0 flex-1">
        {surface === 'project' ? (
          <WikiGraphSegmentedView
            payload={PROJECT_LITERATURE_GRAPH_PAYLOAD}
            domain="project"
            variant="explorer"
            className="min-h-[620px]"
          />
        ) : surface === 'answer' ? (
          <WikiGraphSegmentedView
            payload={ANSWER_GRAPH_PAYLOAD}
            domain="answer"
            variant="explorer"
            className="min-h-[620px]"
          />
        ) : (
          <WikiGraphSegmentedView
            payload={ACCEPTANCE_GRAPH_PAYLOAD}
            domain="wiki"
            variant="explorer"
            className="min-h-[620px]"
          />
        )}
      </div>
    </div>
  );
}

export default DesktopAcceptanceSemanticReview;
