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
      source_id: 'source-a',
      title: 'Evidence title',
      content: 'Evidence body',
      quote: '',
      score: 0.875,
      page: 12,
      ignored: undefined,
      callback: () => 'unsafe',
    });

    expect(normalized).toEqual({
      page: 12,
      chunk_id: 'chunk-1',
      source_id: 'source-a',
      title: 'Evidence title',
      content: 'Evidence body',
      score: 0.875,
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

  it('falls back to primitive metadata for sparse provider-specific references', () => {
    expect(getEvidenceReferenceTitle({ page: 5 }, 'Evidence 2')).toBe('Evidence 2');
    expect(getEvidenceReferenceBody({ page: 5, verified: true })).toBe('page: 5 · verified: true');
  });
});
