/**
 * Settings page section ids and URL compatibility normalization.
 *
 * Standalone embedding/rerank routes now share the semantic routing surface,
 * and standalone sampling routes now share the chat surface. Old bookmarks
 * remain valid through normalization here.
 */

export type SectionId =
  | 'api'
  | 'chat'
  | 'embedding'
  | 'rerank'
  | 'semantic-routing'
  | 'workspace'
  | 'sampling'
  | 'skills'
  | 'credentials'
  | 'mcp'
  | 'discussion'
  | 'citation-styles'
  | 'experimental'
  | 'logs';

export const SECTION_IDS: readonly SectionId[] = [
  'api',
  'chat',
  'embedding',
  'rerank',
  'semantic-routing',
  'workspace',
  'sampling',
  'skills',
  'credentials',
  'mcp',
  'discussion',
  'citation-styles',
  'experimental',
  'logs',
];

export function isSectionId(value: string | null): value is SectionId {
  return typeof value === 'string' && (SECTION_IDS as readonly string[]).includes(value);
}

/**
 * Map legacy SectionId values to the current settings surface.
 */
export function normalizeSection(value: SectionId): SectionId {
  if (value === 'embedding' || value === 'rerank') {
    return 'semantic-routing';
  }
  if (value === 'sampling') {
    return 'chat';
  }
  return value;
}

/**
 * Resolve the initial active section from `?section=` in window.location,
 * applying back-compat normalization. Falls back to `'api'` when the
 * param is absent, unrecognized, or the env has no `window`.
 *
 * Inputs:
 * - search: optional override for `window.location.search`. Useful for
 *   tests; production callers can omit and let the function read window.
 *
 * Output:
 * - SectionId, never null.
 */
export function resolveInitialSection(search?: string): SectionId {
  let raw: string | null = null;
  if (typeof search === 'string') {
    raw = new URLSearchParams(search).get('section');
  } else if (typeof window !== 'undefined') {
    raw = new URLSearchParams(window.location.search).get('section');
  }
  return isSectionId(raw) ? normalizeSection(raw) : 'api';
}

export function buildSettingsSectionPath(section: SectionId): string {
  return `/settings?section=${encodeURIComponent(normalizeSection(section))}`;
}
