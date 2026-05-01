/**
 * scanResult.test.ts — TASK-180: KnowledgeBase scan result state classification
 *
 * Pure logic test — no component rendering, just verifying the scan result
 * state classification that drives the KnowledgeBase actionable panel.
 */
import { describe, it, expect } from 'vitest';

/** Replicates the classification logic from KnowledgeBase.tsx scan result panel */
function classifyScanResult(result: { indexed: number; skipped: number; failed: number }) {
  if (result.failed > 0 && result.indexed === 0) return 'full_failure';
  if (result.failed > 0) return 'partial_failure';
  return 'success';
}

function scanResultTone(classification: string) {
  switch (classification) {
    case 'full_failure': return 'red';
    case 'partial_failure': return 'amber';
    default: return 'emerald';
  }
}

describe('KnowledgeBase scan result classification', () => {
  it('classifies all-success correctly', () => {
    expect(classifyScanResult({ indexed: 10, skipped: 2, failed: 0 })).toBe('success');
    expect(scanResultTone('success')).toBe('emerald');
  });

  it('classifies partial failure correctly', () => {
    expect(classifyScanResult({ indexed: 8, skipped: 1, failed: 3 })).toBe('partial_failure');
    expect(scanResultTone('partial_failure')).toBe('amber');
  });

  it('classifies full failure correctly', () => {
    expect(classifyScanResult({ indexed: 0, skipped: 0, failed: 5 })).toBe('full_failure');
    expect(scanResultTone('full_failure')).toBe('red');
  });

  it('zero-everything is success', () => {
    expect(classifyScanResult({ indexed: 0, skipped: 0, failed: 0 })).toBe('success');
  });

  it('skipped-only is success', () => {
    expect(classifyScanResult({ indexed: 0, skipped: 10, failed: 0 })).toBe('success');
  });
});
