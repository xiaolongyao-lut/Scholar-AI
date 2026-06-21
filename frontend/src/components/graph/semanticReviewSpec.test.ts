import { describe, expect, it } from 'vitest';

import type { GraphPayloadV0 } from './payloadToRf';
import {
  REVIEW_DASHBOARD_SPEC_SCHEMA_VERSION,
  buildSemanticReviewSpec,
} from './semanticReviewSpec';

describe('buildSemanticReviewSpec', () => {
  it('builds a renderer-neutral review spec from GraphPayloadV0', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      scope: { kind: 'question', ref: 'fatigue evidence' },
      updated_at: '2026-06-21T00:00:00Z',
      nodes: [
        {
          id: 'claim',
          type: 'claim',
          label: 'Fatigue claim',
          metadata: { reasoning_dimension: 'question' },
          material_id: null,
          source_ref: null,
          evidence_refs: null,
          confidence: 0.8,
        },
        {
          id: 'ev',
          type: 'evidence',
          label: 'Evidence chunk',
          metadata: { reasoning_dimension: 'evidence' },
          material_id: 'm1',
          source_ref: { material_id: 'm1', page: 3, chunk_id: 'c1', bbox: null },
          evidence_refs: [{ material_id: 'm1', page: 3, chunk_id: 'c1', text: 'evidence', score: 0.9 }],
          confidence: 0.9,
        },
      ],
      edges: [
        {
          id: 'ev-claim',
          source: 'ev',
          target: 'claim',
          relation: 'supports',
          material_id: 'm1',
          source_ref: null,
          evidence_refs: [{ material_id: 'm1', page: 3, chunk_id: 'c1', text: 'evidence', score: 0.9 }],
          confidence: 0.9,
          metadata: null,
        },
      ],
    } as GraphPayloadV0;

    const spec = buildSemanticReviewSpec(payload);

    expect(spec.schema_version).toBe(REVIEW_DASHBOARD_SPEC_SCHEMA_VERSION);
    expect(spec.source_graph_version).toBe('v0');
    expect(spec.generated_at).toBe('2026-06-21T00:00:00Z');
    expect(spec.summary.node_count).toBe(2);
    expect(spec.summary.edge_count).toBe(1);
    expect(spec.summary.dangling_edge_count).toBe(0);
    expect(spec.summary.material_count).toBe(1);
    expect(spec.summary.evidence_ref_count).toBe(3);
    expect(spec.summary.relation_without_evidence_count).toBe(0);
    expect(spec.dimensions.find((item) => item.dimension === 'evidence')?.node_count).toBe(1);
    expect(spec.relations).toEqual([
      {
        relation: 'supports',
        edge_count: 1,
        evidence_ref_count: 1,
        low_confidence_count: 0,
      },
    ]);
  });

  it('reports missing metadata buckets and duplicate labels', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'a',
          type: 'evidence',
          label: 'Same label',
          metadata: null,
          material_id: null,
          source_ref: null,
          evidence_refs: [],
          confidence: null,
        },
        {
          id: 'b',
          type: 'evidence',
          label: 'Same label',
          metadata: null,
          material_id: null,
          source_ref: null,
          evidence_refs: [],
          confidence: null,
        },
      ],
      edges: [],
    } as unknown as GraphPayloadV0;

    const spec = buildSemanticReviewSpec(payload);
    const missingRefs = spec.missing_metadata_buckets.find((item) => item.id === 'missing_evidence_refs');
    const duplicates = spec.missing_metadata_buckets.find((item) => item.id === 'duplicate_labels');

    expect(spec.summary.orphan_node_count).toBe(2);
    expect(spec.summary.duplicate_label_count).toBe(2);
    expect(spec.duplicate_label_groups).toEqual([
      { label: 'Same label', node_ids: ['a', 'b'], count: 2 },
    ]);
    expect(missingRefs?.status).toBe('review_required');
    expect(missingRefs?.node_ids).toEqual(['a', 'b']);
    expect(duplicates?.node_ids).toEqual(['a', 'b']);
  });

  it('filters dangling edges before relation and large-library analysis', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'a',
          type: 'topic',
          label: 'Topic',
          metadata: { reasoning_dimension: 'question' },
          material_id: null,
          source_ref: null,
          evidence_refs: null,
          confidence: null,
        },
      ],
      edges: [
        {
          id: 'dangling',
          source: 'a',
          target: 'missing',
          relation: 'supports',
          material_id: null,
          source_ref: null,
          evidence_refs: null,
          confidence: 0.2,
          metadata: null,
        },
      ],
    } as unknown as GraphPayloadV0;

    const spec = buildSemanticReviewSpec(payload, { largeNodeThreshold: 1, generatedAt: null });

    expect(spec.generated_at).toBeNull();
    expect(spec.summary.edge_count).toBe(0);
    expect(spec.summary.dangling_edge_count).toBe(1);
    expect(spec.relations).toEqual([]);
    expect(spec.graph_diagnostics.find((item) => item.id === 'dangling_edges')).toMatchObject({
      count: 1,
      status: 'review_required',
      item_ids: ['dangling'],
    });
    expect(spec.large_library_hints.map((hint) => hint.kind)).toContain('aggregate_by_dimension');
    expect(spec.large_library_hints.map((hint) => hint.kind)).toContain('filter_orphans');
  });

  it('reports weak relations and source-overlap hints as graph diagnostics', () => {
    const payload: GraphPayloadV0 = {
      version: 'v0',
      nodes: [
        {
          id: 'claim-a',
          type: 'claim',
          label: 'Claim A',
          metadata: { reasoning_dimension: 'observation' },
          material_id: 'm-shared',
          source_ref: null,
          evidence_refs: [],
          confidence: 0.8,
        },
        {
          id: 'claim-b',
          type: 'claim',
          label: 'Claim B',
          metadata: { reasoning_dimension: 'mechanism' },
          material_id: 'm-shared',
          source_ref: null,
          evidence_refs: [],
          confidence: 0.7,
        },
      ],
      edges: [
        {
          id: 'weak-overlap',
          source: 'claim-a',
          target: 'claim-b',
          relation: 'supports',
          material_id: null,
          source_ref: null,
          evidence_refs: [],
          confidence: 0.2,
          metadata: null,
        },
      ],
    } as unknown as GraphPayloadV0;

    const spec = buildSemanticReviewSpec(payload);

    expect(spec.summary.relation_without_evidence_count).toBe(1);
    expect(spec.summary.source_overlap_relation_count).toBe(1);
    expect(spec.graph_diagnostics.find((item) => item.id === 'relations_missing_evidence')).toMatchObject({
      count: 1,
      severity: 'warning',
      item_ids: ['weak-overlap'],
    });
    expect(spec.graph_diagnostics.find((item) => item.id === 'low_confidence_relations')).toMatchObject({
      count: 1,
      severity: 'warning',
      item_ids: ['weak-overlap'],
    });
    expect(spec.graph_diagnostics.find((item) => item.id === 'source_overlap_relations')).toMatchObject({
      count: 1,
      severity: 'info',
      item_ids: ['weak-overlap'],
    });
    expect(spec.source_overlap_groups).toEqual([
      {
        material_id: 'm-shared',
        edge_ids: ['weak-overlap'],
        node_ids: ['claim-a', 'claim-b'],
        count: 1,
      },
    ]);
  });
});
