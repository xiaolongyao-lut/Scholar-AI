import type { PdfHighlightRect } from './pdfAnchor';

export const PDF_QUOTE_MAX_LENGTH = 320;
export const PDF_QUOTE_PAGE_SEARCH_RADIUS = 2;

const PDF_QUOTE_MAX_INPUT_LENGTH = 4096;
const PDF_PAGE_TEXT_MAX_INPUT_LENGTH = 1_000_000;
const SHOW_TEXT = 4;
const TEXT_NODE = 3;
const WHITESPACE_CHARACTER = /\s/u;
const REGEXP_SPECIAL_CHARACTER = /[.*+?^${}()|[\]\\]/g;

interface DomBoundary {
  node: Text;
  offset: number;
}

interface IndexedTextLayer {
  text: string;
  starts: readonly DomBoundary[];
  ends: readonly DomBoundary[];
}

interface UniqueTextMatch {
  index: number;
  length: number;
}

export interface PdfQuoteAnchorMatch {
  quote: string;
  rects: readonly PdfHighlightRect[];
}

export type PdfQuoteAnchorResolution =
  | { status: 'matched'; match: PdfQuoteAnchorMatch }
  | { status: 'not_found' }
  | { status: 'ambiguous' }
  | { status: 'unavailable' };

function trimDanglingHighSurrogate(value: string): string {
  if (!value) return value;
  const finalCodeUnit = value.charCodeAt(value.length - 1);
  return finalCodeUnit >= 0xd800 && finalCodeUnit <= 0xdbff
    ? value.slice(0, -1)
    : value;
}

/**
 * Normalizes an external citation quote into a bounded exact-search value.
 *
 * @param value - Untrusted quote value from an evidence payload.
 * @returns A whitespace-collapsed quote of at most 320 Unicode characters,
 *     or `null` when no searchable text remains.
 */
export function normalizePdfQuote(value: unknown): string | null {
  if (typeof value !== 'string') return null;

  const boundedInput = trimDanglingHighSurrogate(value.slice(0, PDF_QUOTE_MAX_INPUT_LENGTH));
  const normalized = boundedInput.replace(/\s+/gu, ' ').trim();
  if (!normalized) return null;

  const boundedQuote = Array.from(normalized)
    .slice(0, PDF_QUOTE_MAX_LENGTH)
    .join('')
    .trimEnd();
  return boundedQuote || null;
}

/**
 * Builds a small, deterministic set of pages for quote fallback search.
 *
 * @param hintPage - One-based citation page supplied by the evidence locator.
 * @param pageCount - Total one-based PDF page count.
 * @returns Hint page followed by left/right neighbours, limited to five pages.
 */
export function buildPdfQuotePageSearchOrder(
  hintPage: number | null | undefined,
  pageCount: number,
): readonly number[] {
  if (
    !Number.isInteger(hintPage)
    || hintPage === null
    || hintPage === undefined
    || hintPage < 1
    || !Number.isInteger(pageCount)
    || pageCount < 1
    || hintPage > pageCount
  ) {
    return [];
  }

  const pages: number[] = [hintPage];
  for (let distance = 1; distance <= PDF_QUOTE_PAGE_SEARCH_RADIUS; distance += 1) {
    const previousPage = hintPage - distance;
    const nextPage = hintPage + distance;
    if (previousPage >= 1) pages.push(previousPage);
    if (nextPage <= pageCount) pages.push(nextPage);
  }
  return pages;
}

function indexTextLayer(textLayer: HTMLElement): IndexedTextLayer {
  const characters: string[] = [];
  const starts: DomBoundary[] = [];
  const ends: DomBoundary[] = [];
  const walker = textLayer.ownerDocument.createTreeWalker(textLayer, SHOW_TEXT);
  let currentNode = walker.nextNode();

  while (currentNode) {
    if (currentNode.nodeType === TEXT_NODE) {
      const textNode = currentNode as Text;
      for (let offset = 0; offset < textNode.data.length; offset += 1) {
        const character = textNode.data[offset] ?? '';
        if (WHITESPACE_CHARACTER.test(character)) {
          continue;
        }

        characters.push(character);
        starts.push({ node: textNode, offset });
        ends.push({ node: textNode, offset: offset + 1 });
      }
    }
    currentNode = walker.nextNode();
  }

  return { text: characters.join(''), starts, ends };
}

function searchablePdfText(value: string): string {
  return value.replace(/\s+/gu, '');
}

function escapeRegExp(value: string): string {
  return value.replace(REGEXP_SPECIAL_CHARACTER, '\\$&');
}

function findUniqueTextMatch(
  text: string,
  quote: string,
): UniqueTextMatch | 'ambiguous' | null {
  const expression = new RegExp(`(?=(${escapeRegExp(quote)}))`, 'giu');
  let uniqueMatch: UniqueTextMatch | null = null;

  for (const match of text.matchAll(expression)) {
    const matchedText = match[1];
    if (typeof matchedText !== 'string' || matchedText.length === 0) return null;
    if (uniqueMatch) return 'ambiguous';
    uniqueMatch = { index: match.index, length: matchedText.length };
  }

  return uniqueMatch;
}

/**
 * Counts exact quote occurrences in extracted page text, capped at two.
 *
 * The cap is intentional: callers only need to distinguish no match, one
 * unique match, and ambiguity without retaining an unbounded match list.
 *
 * @param pageTextValue - Untrusted text extracted from one PDF page.
 * @param quoteValue - Untrusted citation quote.
 * @returns `0` for absent, `1` for unique, or `2` for multiple matches.
 */
export function countPdfQuoteOccurrences(
  pageTextValue: unknown,
  quoteValue: unknown,
): 0 | 1 | 2 {
  if (typeof pageTextValue !== 'string') return 0;
  const quote = normalizePdfQuote(quoteValue);
  if (!quote) return 0;
  const pageText = searchablePdfText(pageTextValue.slice(0, PDF_PAGE_TEXT_MAX_INPUT_LENGTH));
  const match = findUniqueTextMatch(pageText, searchablePdfText(quote));
  if (match === 'ambiguous') return 2;
  return match ? 1 : 0;
}

function isFiniteRect(rect: DOMRect): boolean {
  return Number.isFinite(rect.left)
    && Number.isFinite(rect.top)
    && Number.isFinite(rect.width)
    && Number.isFinite(rect.height);
}

function normalizeClientRect(rect: DOMRect, pageRect: DOMRect): PdfHighlightRect | null {
  if (!isFiniteRect(rect) || rect.width <= 0 || rect.height <= 0) return null;

  const left = Math.max(rect.left, pageRect.left);
  const top = Math.max(rect.top, pageRect.top);
  const right = Math.min(rect.left + rect.width, pageRect.left + pageRect.width);
  const bottom = Math.min(rect.top + rect.height, pageRect.top + pageRect.height);
  if (right <= left || bottom <= top) return null;

  return {
    x: (left - pageRect.left) / pageRect.width,
    y: (top - pageRect.top) / pageRect.height,
    w: (right - left) / pageRect.width,
    h: (bottom - top) / pageRect.height,
  };
}

/**
 * Locates one exact quote in a rendered PDF.js text layer.
 *
 * The match is case-insensitive and ignores PDF layout whitespace. Ambiguous matches,
 * detached DOM, invalid geometry, and Range failures intentionally return
 * `null` so the caller can retain document/page-only navigation.
 *
 * @param textLayer - Rendered text-layer element whose bounds represent a page.
 * @param quoteValue - Untrusted quote value from the citation target.
 * @returns The normalized quote and page-relative highlight rectangles, or
 *     `null` when a unique, measurable exact match cannot be proven.
 */
export function findUniquePdfQuoteAnchor(
  textLayer: HTMLElement,
  quoteValue: unknown,
): PdfQuoteAnchorMatch | null {
  const resolution = resolvePdfQuoteAnchor(textLayer, quoteValue);
  return resolution.status === 'matched' ? resolution.match : null;
}

/**
 * Classifies exact quote resolution so callers can reject ambiguity across
 * several candidate pages instead of silently accepting the first match.
 *
 * @param textLayer - Rendered PDF.js text-layer element for one page.
 * @param quoteValue - Untrusted quote value from the citation target.
 * @returns A matched anchor or an explicit safe-degradation reason.
 */
export function resolvePdfQuoteAnchor(
  textLayer: HTMLElement,
  quoteValue: unknown,
): PdfQuoteAnchorResolution {
  const quote = normalizePdfQuote(quoteValue);
  if (!quote || !textLayer || typeof textLayer.getBoundingClientRect !== 'function') {
    return { status: 'unavailable' };
  }

  try {
    const indexedLayer = indexTextLayer(textLayer);
    const match = findUniqueTextMatch(indexedLayer.text, searchablePdfText(quote));
    if (match === 'ambiguous') return { status: 'ambiguous' };
    if (!match) return { status: 'not_found' };

    const start = indexedLayer.starts[match.index];
    const end = indexedLayer.ends[match.index + match.length - 1];
    if (!start || !end) return { status: 'unavailable' };

    const pageRect = textLayer.getBoundingClientRect();
    if (!isFiniteRect(pageRect) || pageRect.width <= 0 || pageRect.height <= 0) {
      return { status: 'unavailable' };
    }

    const range = textLayer.ownerDocument.createRange();
    range.setStart(start.node, start.offset);
    range.setEnd(end.node, end.offset);

    const rectList = range.getClientRects();
    const rects: PdfHighlightRect[] = [];
    for (let index = 0; index < rectList.length; index += 1) {
      const rect = rectList.item(index);
      if (!rect) continue;
      const normalizedRect = normalizeClientRect(rect, pageRect);
      if (normalizedRect) rects.push(normalizedRect);
    }

    return rects.length > 0
      ? { status: 'matched', match: { quote, rects } }
      : { status: 'unavailable' };
  } catch {
    // Text layers can detach between render and citation activation.
    return { status: 'unavailable' };
  }
}
