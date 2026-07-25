import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  PDF_QUOTE_MAX_LENGTH,
  buildPdfQuotePageSearchOrder,
  countPdfQuoteOccurrences,
  findUniquePdfQuoteAnchor,
  normalizePdfQuote,
  resolvePdfQuoteAnchor,
} from './pdfQuoteAnchor';

afterEach(() => {
  vi.restoreAllMocks();
});

function createDomRectList(rects: readonly DOMRect[]): DOMRectList {
  return Object.assign([...rects], {
    item(index: number): DOMRect | null {
      return rects[index] ?? null;
    },
  });
}

function installRangeRects(rects: readonly DOMRect[]): Range {
  const range = document.createRange();
  Object.defineProperty(range, 'getClientRects', {
    configurable: true,
    value: () => createDomRectList(rects),
  });
  vi.spyOn(document, 'createRange').mockReturnValue(range);
  return range;
}

describe('normalizePdfQuote', () => {
  it('collapses whitespace, trims the result, and rejects non-text values', () => {
    expect(normalizePdfQuote('  One\n\t two\u00a0three  ')).toBe('One two three');
    expect(normalizePdfQuote(' \n\t ')).toBeNull();
    expect(normalizePdfQuote({ quote: 'not a string' })).toBeNull();
  });

  it('bounds quotes by Unicode characters without splitting a surrogate pair', () => {
    const normalized = normalizePdfQuote(`$${'a'.repeat(PDF_QUOTE_MAX_LENGTH - 1)}\u{1f680}tail`);

    expect(normalized).toBe(`$${'a'.repeat(PDF_QUOTE_MAX_LENGTH - 1)}`);
    expect(Array.from(normalized ?? '')).toHaveLength(PDF_QUOTE_MAX_LENGTH);

    const emojiAtBoundary = normalizePdfQuote(`${'a'.repeat(PDF_QUOTE_MAX_LENGTH - 1)}\u{1f680}tail`);
    expect(emojiAtBoundary?.endsWith('\u{1f680}')).toBe(true);
    expect(Array.from(emojiAtBoundary ?? '')).toHaveLength(PDF_QUOTE_MAX_LENGTH);
  });
});

describe('buildPdfQuotePageSearchOrder', () => {
  it('searches the hinted page first and then alternates bounded neighbours', () => {
    expect(buildPdfQuotePageSearchOrder(5, 12)).toEqual([5, 4, 6, 3, 7]);
    expect(buildPdfQuotePageSearchOrder(1, 12)).toEqual([1, 2, 3]);
    expect(buildPdfQuotePageSearchOrder(12, 12)).toEqual([12, 11, 10]);
  });

  it('returns no pages for invalid or out-of-range boundaries', () => {
    expect(buildPdfQuotePageSearchOrder(undefined, 12)).toEqual([]);
    expect(buildPdfQuotePageSearchOrder(0, 12)).toEqual([]);
    expect(buildPdfQuotePageSearchOrder(13, 12)).toEqual([]);
    expect(buildPdfQuotePageSearchOrder(2.5, 12)).toEqual([]);
    expect(buildPdfQuotePageSearchOrder(1, Number.NaN)).toEqual([]);
  });
});

describe('countPdfQuoteOccurrences', () => {
  it('classifies absent, unique, and repeated normalized page-text matches', () => {
    expect(countPdfQuoteOccurrences('Alpha\n beta', 'alpha beta')).toBe(1);
    expect(countPdfQuoteOccurrences('Alpha beta alpha\tbeta', 'alpha beta')).toBe(2);
    expect(countPdfQuoteOccurrences('Alpha beta', 'missing')).toBe(0);
    expect(countPdfQuoteOccurrences(null, 'alpha')).toBe(0);
  });

  it('treats PDF item-boundary whitespace as layout-only', () => {
    expect(countPdfQuoteOccurrences('Theexactsentence.', 'The exact sentence.')).toBe(1);
    expect(countPdfQuoteOccurrences('The exactsentence. Theexactsentence.', 'The exact sentence.')).toBe(2);
  });
});

describe('findUniquePdfQuoteAnchor', () => {
  it('matches case-insensitively across text nodes and maps range rects to the page', () => {
    const layer = document.createElement('div');
    layer.innerHTML = '<span>Alpha   </span><span>BETA\n gamma</span>';
    vi.spyOn(layer, 'getBoundingClientRect').mockReturnValue(new DOMRect(100, 200, 400, 800));
    const range = installRangeRects([
      new DOMRect(120, 240, 200, 40),
      new DOMRect(100, 300, 160, 32),
    ]);

    expect(findUniquePdfQuoteAnchor(layer, ' alpha beta\tGAMMA ')).toEqual({
      quote: 'alpha beta GAMMA',
      rects: [
        { x: 0.05, y: 0.05, w: 0.5, h: 0.05 },
        { x: 0, y: 0.125, w: 0.4, h: 0.04 },
      ],
    });
    expect(range.startContainer).toBe(layer.querySelector('span')?.firstChild);
    expect(range.startOffset).toBe(0);
    expect(range.endContainer).toBe(layer.querySelectorAll('span')[1]?.firstChild);
    expect(range.endOffset).toBe('BETA\n gamma'.length);
  });

  it('matches a spaced quote across PDF.js item spans without literal DOM spaces', () => {
    const layer = document.createElement('div');
    layer.innerHTML = '<span>The</span><span>exact</span><span>sentence.</span>';
    vi.spyOn(layer, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 400, 800));
    const range = installRangeRects([new DOMRect(20, 40, 240, 24)]);

    expect(findUniquePdfQuoteAnchor(layer, 'The exact sentence.')).toEqual({
      quote: 'The exact sentence.',
      rects: [{ x: 0.05, y: 0.05, w: 0.6, h: 0.03 }],
    });
    expect(range.startContainer).toBe(layer.querySelectorAll('span')[0]?.firstChild);
    expect(range.endContainer).toBe(layer.querySelectorAll('span')[2]?.firstChild);
  });

  it('clips client rects to the page before normalizing them', () => {
    const layer = document.createElement('div');
    layer.textContent = 'Exact quote';
    vi.spyOn(layer, 'getBoundingClientRect').mockReturnValue(new DOMRect(100, 200, 400, 800));
    installRangeRects([new DOMRect(80, 180, 500, 100)]);

    expect(findUniquePdfQuoteAnchor(layer, 'exact quote')?.rects).toEqual([
      { x: 0, y: 0, w: 1, h: 0.1 },
    ]);
  });

  it('returns no anchor when the exact quote is duplicated, including overlaps', () => {
    const duplicated = document.createElement('div');
    duplicated.textContent = 'Target and target';
    const createRangeSpy = vi.spyOn(document, 'createRange');

    expect(findUniquePdfQuoteAnchor(duplicated, 'TARGET')).toBeNull();
    expect(createRangeSpy).not.toHaveBeenCalled();

    const overlapping = document.createElement('div');
    overlapping.textContent = 'aaaa';
    expect(findUniquePdfQuoteAnchor(overlapping, 'aaa')).toBeNull();
    expect(resolvePdfQuoteAnchor(overlapping, 'aaa')).toEqual({ status: 'ambiguous' });
  });

  it('degrades safely when geometry is unavailable or a DOM range operation fails', () => {
    const zeroSizedLayer = document.createElement('div');
    zeroSizedLayer.textContent = 'Unique sentence';
    vi.spyOn(zeroSizedLayer, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 0, 0));
    expect(findUniquePdfQuoteAnchor(zeroSizedLayer, 'Unique sentence')).toBeNull();

    const throwingLayer = document.createElement('div');
    throwingLayer.textContent = 'Unique sentence';
    vi.spyOn(throwingLayer, 'getBoundingClientRect').mockImplementation(() => {
      throw new Error('detached text layer');
    });
    expect(findUniquePdfQuoteAnchor(throwingLayer, 'Unique sentence')).toBeNull();
    expect(findUniquePdfQuoteAnchor(throwingLayer, null)).toBeNull();
  });
});
