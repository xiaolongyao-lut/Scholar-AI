import { GitBranch } from 'lucide-react';

import { PageHeader } from '@/components/common/PageHeader';
import { DimensionGraphViewer } from '@/components/graph/DimensionGraphViewer';
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
      relation: 'supports',
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

export function DesktopAcceptanceSemanticReview() {
  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden bg-background px-5 py-4"
      data-testid="desktop-acceptance-semantic-review"
    >
      <PageHeader
        icon={<GitBranch size={18} />}
        title="语义复审"
        subtitle="本地图谱诊断"
        className="mb-3 shrink-0"
      />
      <div className="min-h-0 flex-1">
        <DimensionGraphViewer
          payload={ACCEPTANCE_GRAPH_PAYLOAD}
          density="explorer"
          detailPlacement="sidebar"
          className="min-h-[620px]"
        />
      </div>
    </div>
  );
}

export default DesktopAcceptanceSemanticReview;
