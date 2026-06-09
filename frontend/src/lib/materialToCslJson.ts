import type { CitationSourceResource } from '@/types/resources';
import type { CslJsonItem } from '@/lib/citationEngine';

/**
 * Parse a free-form author string into a CSL name part.
 *
 * "Family, Given" → split; otherwise use `literal` so Chinese names and
 * already-formatted Western names render verbatim instead of being mis-split.
 */
function parseAuthor(name: string): { family?: string; given?: string; literal?: string } {
  const trimmed = name.trim();
  const commaIdx = trimmed.indexOf(',');
  if (commaIdx > 0) {
    return {
      family: trimmed.slice(0, commaIdx).trim(),
      given: trimmed.slice(commaIdx + 1).trim(),
    };
  }
  return { literal: trimmed };
}

/**
 * Map a backend citation source (material + persisted bibliographic metadata)
 * to a CSL-JSON item consumable by citeproc-js. The material_id is the stable
 * citation id.
 */
export function citationSourceToCslJson(source: CitationSourceResource): CslJsonItem {
  const item: CslJsonItem = {
    id: source.material_id,
    type: source.csl_type || 'article-journal',
    title: source.title,
    language: 'zh-CN',
  };
  const authors = (source.authors ?? []).map((name) => parseAuthor(name)).filter(
    (a) => a.family || a.literal,
  );
  if (authors.length > 0) item.author = authors;
  if (typeof source.year === 'number') item.issued = { 'date-parts': [[source.year]] };
  if (source.publication) item['container-title'] = source.publication;
  if (source.publisher) item.publisher = source.publisher;
  if (source.volume) item.volume = source.volume;
  if (source.issue) item.issue = source.issue;
  if (source.pages) item.page = source.pages;
  if (source.doi) item.DOI = source.doi;
  if (source.url) item.URL = source.url;
  return item;
}
