import { describe, expect, it } from 'vitest';

import {
  getEvidenceReferenceBody,
  getEvidenceReferenceMetaParts,
  getEvidenceReferenceTitle,
  normalizeEvidenceReference,
  parseEvidenceReferences,
} from './evidenceReferences';

describe('evidenceReferences', () => {
  it('normalizes known evidence fields while preserving primitive metadata', () => {
    const normalized = normalizeEvidenceReference({
      chunk_id: '  chunk-1  ',
      material_id: 'paper-a',
      source_id: 'source-a',
      title: 'Evidence title',
      content: 'Evidence body',
      text: 'Full RAG text',
      compressed_text: 'Compressed RAG text',
      quote: '',
      label: 'relevant',
      score: 0.875,
      page: 12,
      source: 'paper.pdf',
      source_label: 'dense',
      source_labels: ['bm25', ' dense ', '', null],
      source_hint: 'bm25+dense',
      ignored: undefined,
      callback: () => 'unsafe',
    });

    expect(normalized).toEqual({
      chunk_id: 'chunk-1',
      material_id: 'paper-a',
      source_id: 'source-a',
      title: 'Evidence title',
      content: 'Evidence body',
      text: 'Full RAG text',
      compressed_text: 'Compressed RAG text',
      label: 'relevant',
      score: 0.875,
      page: 12,
      source: 'paper.pdf',
      source_label: 'dense',
      source_labels: ['bm25', 'dense'],
      source_hint: 'bm25+dense',
    });
  });

  it('parses only displayable array entries from backend payloads', () => {
    expect(parseEvidenceReferences(null)).toEqual([]);
    expect(parseEvidenceReferences([{ quote: 'quoted sentence' }, null, {}, 'bad'])).toEqual([
      { quote: 'quoted sentence' },
    ]);
  });

  it('renders titles, bodies, and compact metadata without raw JSON fallback', () => {
    const reference = {
      chunk_id: 'chunk-2',
      source_id: 'source-b',
      score: 1,
      page: 3,
    };

    expect(getEvidenceReferenceTitle(reference, 'Evidence 1')).toBe('chunk-2');
    expect(getEvidenceReferenceBody(reference)).toBe('chunk-2');
    expect(getEvidenceReferenceMetaParts(reference, {
      chunk: 'Chunk',
      source: 'Source',
      score: 'Score',
    })).toEqual(['Chunk: chunk-2', 'Source: source-b', 'Score: 1']);
  });

  it('renders backend RAG evidence text and retrieval source labels', () => {
    const reference = normalizeEvidenceReference({
      chunk_id: 'chunk-3',
      material_id: 'paper-c',
      text: 'Full retrieved passage.',
      compressed_text: 'Compressed retrieved passage.',
      source_labels: ['bm25', 'rerank'],
      score: 0.7712,
    });

    expect(reference).not.toBeNull();
    expect(getEvidenceReferenceTitle(reference!, 'Evidence 3')).toBe('chunk-3');
    expect(getEvidenceReferenceBody(reference!)).toBe('Compressed retrieved passage.');
    expect(getEvidenceReferenceMetaParts(reference!, {
      chunk: 'Chunk',
      source: 'Source',
      score: 'Score',
    })).toEqual(['Chunk: chunk-3', 'Source: paper-c', 'Score: 0.771', 'bm25+rerank']);
  });

  it('falls back to primitive metadata for sparse provider-specific references', () => {
    expect(getEvidenceReferenceTitle({ page: 5 }, 'Evidence 2')).toBe('Evidence 2');
    expect(getEvidenceReferenceBody({ page: 5, verified: true })).toBe('page: 5 · verified: true');
  });
});
