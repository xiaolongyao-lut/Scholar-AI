import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';

const API_BASE = getApiBaseUrl();

export interface Highlight {
  page: number;
  text: string;
  color: string;
}

export interface Note {
  note_id: string;
  page: number;
  anchor_text: string;
  body: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface AnnotationData {
  material_id: string;
  highlights: Highlight[];
  notes?: Note[];
  last_page?: number | null;
}

// ---------------------------------------------------------------------------
// L1 — highlights
// ---------------------------------------------------------------------------

export async function getAnnotations(materialId: string): Promise<AnnotationData> {
  const { data } = await axios.get(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`);
  return data;
}

export async function addHighlight(materialId: string, highlight: Highlight): Promise<AnnotationData> {
  const { data } = await axios.post(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`, {
    material_id: materialId,
    highlight,
  });
  return data;
}

export async function clearAnnotations(materialId: string): Promise<void> {
  await axios.delete(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`);
}

export async function replaceHighlights(materialId: string, highlights: Highlight[]): Promise<AnnotationData> {
  const { data } = await axios.put(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`, {
    highlights,
  });
  return data;
}

// ---------------------------------------------------------------------------
// L2 — notes (Track C F2)
// ---------------------------------------------------------------------------

export interface AddNoteInput {
  page: number;
  anchor_text?: string;
  body?: string;
  tags?: string[];
}

export interface AddNoteResult {
  material_id: string;
  note: Note;
  annotation: AnnotationData;
}

export async function addNote(materialId: string, input: AddNoteInput): Promise<AddNoteResult> {
  const { data } = await axios.post(
    `${API_BASE}/api/annotations/${encodeURIComponent(materialId)}/notes`,
    {
      page: input.page,
      anchor_text: input.anchor_text ?? '',
      body: input.body ?? '',
      tags: input.tags ?? [],
    },
  );
  return data;
}

export interface UpdateNoteInput {
  body: string;
  tags: string[];
}

export async function updateNote(
  materialId: string,
  noteId: string,
  input: UpdateNoteInput,
): Promise<AddNoteResult> {
  const { data } = await axios.put(
    `${API_BASE}/api/annotations/${encodeURIComponent(materialId)}/notes/${encodeURIComponent(noteId)}`,
    input,
  );
  return data;
}

export async function deleteNote(materialId: string, noteId: string): Promise<{ annotation: AnnotationData }> {
  const { data } = await axios.delete(
    `${API_BASE}/api/annotations/${encodeURIComponent(materialId)}/notes/${encodeURIComponent(noteId)}`,
  );
  return data;
}

// ---------------------------------------------------------------------------
// L2 — last-page (read progress) — Track C F2 + F6
// ---------------------------------------------------------------------------

export interface SetLastPageResult {
  material_id: string;
  last_page: number | null;
  changed: boolean;
}

/**
 * Update read-progress via the primary PUT endpoint.
 *
 * Use this for live page-change debouncing (F6 ReadProgressTracker).
 * For page-unload flushing prefer `setLastPageBeacon` (POST alias) so
 * `navigator.sendBeacon()` can be used — Beacon only supports POST.
 */
export async function setLastPage(
  materialId: string,
  page: number | null,
): Promise<SetLastPageResult> {
  const { data } = await axios.put(
    `${API_BASE}/api/annotations/${encodeURIComponent(materialId)}/last-page`,
    { page },
  );
  return data;
}

/**
 * Best-effort page-unload flush via `navigator.sendBeacon()` against
 * the POST alias of /last-page. Per amendment §0.1 (RFC 9745 / Beacon
 * docs): sendBeacon only sends POST. Returns true when Beacon accepted
 * the request, false when Beacon is unavailable or refused (e.g.
 * payload size limit). The caller can fall back to a keepalive fetch
 * in the false branch.
 */
export function setLastPageBeacon(
  materialId: string,
  page: number | null,
): boolean {
  if (typeof navigator === 'undefined' || typeof navigator.sendBeacon !== 'function') {
    return false;
  }
  const url = `${API_BASE}/api/annotations/${encodeURIComponent(materialId)}/last-page`;
  const body = JSON.stringify({ page });
  const blob = typeof Blob !== 'undefined' ? new Blob([body], { type: 'application/json' }) : body;
  return navigator.sendBeacon(url, blob);
}

/**
 * Unload-safe PUT /last-page via `fetch(..., { keepalive: true })`.
 *
 * Used as the fallback when `setLastPageBeacon` returns false (no
 * Beacon API in this environment). A normal axios request would be
 * dropped by the browser when the page is unloading; `keepalive: true`
 * lets the browser hold the request open after navigation start, with
 * the same ~64 KB payload cap as Beacon.
 *
 * Returns true when the fetch was dispatched (we can't await the
 * server response under unload), false when the call site should give
 * up. Never throws.
 */
export function setLastPageKeepalive(
  materialId: string,
  page: number | null,
): boolean {
  if (typeof fetch !== 'function') return false;
  const url = `${API_BASE}/api/annotations/${encodeURIComponent(materialId)}/last-page`;
  try {
    void fetch(url, {
      method: 'PUT',
      keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page }),
    }).catch(() => undefined);
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// L2 — Markdown export (Track C F2 + F7)
// ---------------------------------------------------------------------------

/**
 * Fetch the Markdown export blob for a material. Per amendment §0.1
 * the frontend fetches the blob first then triggers the download via
 * the existing `downloadBlob` helper; this keeps the routing layer
 * decoupled from the download trigger so downloadBlob's existing
 * filename / cleanup behaviour applies uniformly.
 *
 * Returns the raw Blob; null on network/HTTP error so callers can
 * surface a toast without throwing.
 */
export async function exportMarkdown(materialId: string): Promise<Blob | null> {
  try {
    const { data } = await axios.get<Blob>(
      `${API_BASE}/api/annotations/${encodeURIComponent(materialId)}/export.md`,
      { responseType: 'blob' },
    );
    return data;
  } catch {
    return null;
  }
}
