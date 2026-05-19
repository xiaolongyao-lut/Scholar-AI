/**
 * Settings page section ids + URL back-compat normalization.
 *
 * After Settings S5 (commit `d39f89a5`) the standalone `embedding` and
 * `rerank` sections were merged into `semantic-routing`. To keep old
 * bookmarks and deep links working, the URL `?section=embedding` and
 * `?section=rerank` are normalized to `semantic-routing` at parse time.
 *
 * This module is the single source of truth for the SectionId vocabulary
 * and the normalization rule. Settings.tsx imports both.
 */

export type SectionId =
  | 'chat'
  | 'embedding'
  | 'rerank'
  | 'semantic-routing'
  | 'workspace'
  | 'sampling'
  | 'skills'
  | 'credentials'
  | 'mcp'
  | 'discussion';

export const SECTION_IDS: readonly SectionId[] = [
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
];

export function isSectionId(value: string | null): value is SectionId {
  return typeof value === 'string' && (SECTION_IDS as readonly string[]).includes(value);
}

/**
 * Map legacy SectionId values to the post-S5 surface. `embedding` and
 * `rerank` collapse into `semantic-routing`; every other id maps to
 * itself.
 */
export function normalizeSection(value: SectionId): SectionId {
  return value === 'embedding' || value === 'rerank' ? 'semantic-routing' : value;
}

/**
 * Resolve the initial active section from `?section=` in window.location,
 * applying back-compat normalization. Falls back to `'chat'` when the
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
  return isSectionId(raw) ? normalizeSection(raw) : 'chat';
}
