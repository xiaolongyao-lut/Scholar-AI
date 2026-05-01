import type { EvidenceReference } from '@/types/writing';

const KNOWN_EVIDENCE_KEYS = new Set(['chunk_id', 'source_id', 'title', 'content', 'quote', 'score']);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const readNonEmptyString = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

const readFiniteNumber = (value: unknown): number | null => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }

  return value;
};

const formatScore = (value: number): string => {
  if (Number.isInteger(value)) {
    return String(value);
  }

  return value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
};

const firstText = (values: Array<string | undefined>): string | null => {
  for (const value of values) {
    const text = readNonEmptyString(value);
    if (text) {
      return text;
    }
  }

  return null;
};

/**
 * Normalizes backend evidence_refs entries before UI rendering.
 *
 * The backend may add provider-specific metadata, so unknown keys are retained
 * while known fields are narrowed to stable display-safe primitive shapes.
 */
export function normalizeEvidenceReference(value: unknown): EvidenceReference | null {
  if (!isRecord(value)) {
    return null;
  }

  const normalized: EvidenceReference = {};

  for (const [key, rawValue] of Object.entries(value)) {
    if (KNOWN_EVIDENCE_KEYS.has(key) || rawValue === undefined || typeof rawValue === 'function') {
      continue;
    }
    normalized[key] = rawValue;
  }

  const chunkId = readNonEmptyString(value.chunk_id);
  if (chunkId) {
    normalized.chunk_id = chunkId;
  }

  const sourceId = readNonEmptyString(value.source_id);
  if (sourceId) {
    normalized.source_id = sourceId;
  }

  const title = readNonEmptyString(value.title);
  if (title) {
    normalized.title = title;
  }

  const content = readNonEmptyString(value.content);
  if (content) {
    normalized.content = content;
  }

  const quote = readNonEmptyString(value.quote);
  if (quote) {
    normalized.quote = quote;
  }

  const score = readFiniteNumber(value.score);
  if (score !== null) {
    normalized.score = score;
  }

  return Object.keys(normalized).length > 0 ? normalized : null;
}

/**
 * Parses an arbitrary backend evidence_refs payload into typed references.
 *
 * Returns an empty array for malformed payloads so job result rendering remains
 * deterministic even when an artifact was produced by an older backend.
 */
export function parseEvidenceReferences(value: unknown): EvidenceReference[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.reduce<EvidenceReference[]>((items, item) => {
    const normalized = normalizeEvidenceReference(item);
    if (normalized) {
      items.push(normalized);
    }
    return items;
  }, []);
}

/**
 * Chooses the primary text body for an evidence reference.
 *
 * The order preserves citation provenance first, then falls back to generic
 * primitive metadata instead of dumping raw JSON into the writing canvas.
 */
export function getEvidenceReferenceBody(reference: EvidenceReference): string | null {
  const directText = firstText([
    reference.content,
    reference.quote,
    reference.title,
    reference.chunk_id,
    reference.source_id,
  ]);

  if (directText) {
    return directText;
  }

  const primitiveMetadata = Object.entries(reference)
    .filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value))
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(' · ');

  return primitiveMetadata.length > 0 ? primitiveMetadata : null;
}

/**
 * Returns the compact title shown above an evidence body.
 */
export function getEvidenceReferenceTitle(reference: EvidenceReference, fallbackLabel: string): string {
  return firstText([reference.title, reference.chunk_id, reference.source_id]) ?? fallbackLabel;
}

/**
 * Builds stable evidence metadata labels for UI chips.
 */
export function getEvidenceReferenceMetaParts(
  reference: EvidenceReference,
  labels: {
    chunk: string;
    source: string;
    score: string;
  },
): string[] {
  const parts: string[] = [];

  if (reference.chunk_id) {
    parts.push(`${labels.chunk}: ${reference.chunk_id}`);
  }

  if (reference.source_id) {
    parts.push(`${labels.source}: ${reference.source_id}`);
  }

  if (typeof reference.score === 'number') {
    parts.push(`${labels.score}: ${formatScore(reference.score)}`);
  }

  return parts;
}
