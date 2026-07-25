import axios from 'axios';
import { getApiBaseUrl } from './apiBaseUrl';

const API_BASE = getApiBaseUrl();

export const ANNOTATION_USE_SCOPES = [
  'project_retrieval',
  'wiki_review',
  'writing_source',
] as const;

export type AnnotationUseScope = (typeof ANNOTATION_USE_SCOPES)[number];

export class AnnotationApiPayloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AnnotationApiPayloadError';
  }
}

export interface HighlightRect {
  /** All four values are normalized to [0, 1] relative to the rendered
   *  PDF page box, so the overlay survives the user changing zoom. */
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Highlight {
  page: number;
  text: string;
  color: string;
  /** 0.1.8.1+: one rect per visual line of the selection. Optional so
   *  highlights persisted before the visual overlay shipped still load. */
  rects?: HighlightRect[];
}

export interface Note {
  note_id: string;
  page: number;
  anchor_text: string;
  body: string;
  tags: string[];
  enabled_scopes: AnnotationUseScope[];
  usage_updated_at: string | null;
  /** Server-derived hash of the normalized full note. Never compute this in the client. */
  content_hash: string;
  created_at: string;
  updated_at: string;
}

export interface AnnotationData {
  material_id: string;
  highlights: Highlight[];
  notes?: Note[];
  last_page?: number | null;
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new AnnotationApiPayloadError(`${label} 不是对象。`);
  }
  return value as Record<string, unknown>;
}

function readString(record: Record<string, unknown>, key: string, label: string): string {
  const value = record[key];
  if (typeof value !== 'string') {
    throw new AnnotationApiPayloadError(`${label} 缺少字符串字段 ${key}。`);
  }
  return value;
}

function readPositiveInteger(record: Record<string, unknown>, key: string, label: string): number {
  const value = record[key];
  if (!Number.isInteger(value) || (value as number) < 1) {
    throw new AnnotationApiPayloadError(`${label} 的 ${key} 无效。`);
  }
  return value as number;
}

function readStringArray(record: Record<string, unknown>, key: string, label: string): string[] {
  const value = record[key];
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new AnnotationApiPayloadError(`${label} 的 ${key} 无效。`);
  }
  return value as string[];
}

function parseHighlightRect(payload: unknown): HighlightRect {
  const record = asRecord(payload, '高亮区域');
  const values = ['x', 'y', 'w', 'h'].map((key) => record[key]);
  if (values.some((value) => typeof value !== 'number' || !Number.isFinite(value))) {
    throw new AnnotationApiPayloadError('高亮区域坐标无效。');
  }
  const [x, y, w, h] = values as number[];
  if (x < 0 || x > 1 || y < 0 || y > 1 || w <= 0 || w > 1 || h <= 0 || h > 1) {
    throw new AnnotationApiPayloadError('高亮区域坐标超出范围。');
  }
  return { x, y, w, h };
}

function parseHighlight(payload: unknown): Highlight {
  const record = asRecord(payload, '高亮');
  const rects = record.rects;
  return {
    page: readPositiveInteger(record, 'page', '高亮'),
    text: readString(record, 'text', '高亮'),
    color: readString(record, 'color', '高亮'),
    ...(rects === undefined || rects === null
      ? {}
      : {
          rects: Array.isArray(rects)
            ? rects.map(parseHighlightRect)
            : (() => { throw new AnnotationApiPayloadError('高亮的 rects 无效。'); })(),
        }),
  };
}

function parseAnnotationUseScopes(payload: unknown): AnnotationUseScope[] {
  if (!Array.isArray(payload)) {
    throw new AnnotationApiPayloadError('笔记的 enabled_scopes 无效。');
  }
  const scopes: AnnotationUseScope[] = [];
  for (const value of payload) {
    if (typeof value !== 'string' || !ANNOTATION_USE_SCOPES.includes(value as AnnotationUseScope)) {
      throw new AnnotationApiPayloadError('笔记包含不支持的使用范围。');
    }
    const scope = value as AnnotationUseScope;
    if (!scopes.includes(scope)) scopes.push(scope);
  }
  return ANNOTATION_USE_SCOPES.filter((scope) => scopes.includes(scope));
}

function readSha256(record: Record<string, unknown>, key: string, label: string): string {
  const value = readString(record, key, label).toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(value)) {
    throw new AnnotationApiPayloadError(`${label} 的 ${key} 不是有效 SHA-256。`);
  }
  return value;
}

export function parseNote(payload: unknown): Note {
  const record = asRecord(payload, '笔记');
  const usageUpdatedAt = record.usage_updated_at;
  if (usageUpdatedAt !== undefined && usageUpdatedAt !== null && typeof usageUpdatedAt !== 'string') {
    throw new AnnotationApiPayloadError('笔记的 usage_updated_at 无效。');
  }
  return {
    note_id: readString(record, 'note_id', '笔记'),
    page: readPositiveInteger(record, 'page', '笔记'),
    anchor_text: readString(record, 'anchor_text', '笔记'),
    body: readString(record, 'body', '笔记'),
    tags: readStringArray(record, 'tags', '笔记'),
    enabled_scopes: parseAnnotationUseScopes(record.enabled_scopes),
    usage_updated_at: usageUpdatedAt ?? null,
    content_hash: readSha256(record, 'content_hash', '笔记'),
    created_at: readString(record, 'created_at', '笔记'),
    updated_at: readString(record, 'updated_at', '笔记'),
  };
}

export function parseAnnotationData(payload: unknown): AnnotationData {
  const record = asRecord(payload, '批注响应');
  if (!Array.isArray(record.highlights) || !Array.isArray(record.notes)) {
    throw new AnnotationApiPayloadError('批注响应缺少 highlights 或 notes 数组。');
  }
  const lastPage = record.last_page;
  if (lastPage !== undefined && lastPage !== null && (!Number.isInteger(lastPage) || (lastPage as number) < 1)) {
    throw new AnnotationApiPayloadError('批注响应的 last_page 无效。');
  }
  return {
    material_id: readString(record, 'material_id', '批注响应'),
    highlights: record.highlights.map(parseHighlight),
    notes: record.notes.map(parseNote),
    last_page: lastPage === undefined ? null : lastPage as number | null,
  };
}

// ---------------------------------------------------------------------------
// L1 — highlights
// ---------------------------------------------------------------------------

export async function getAnnotations(materialId: string): Promise<AnnotationData> {
  const { data } = await axios.get(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`);
  return parseAnnotationData(data);
}

export async function addHighlight(materialId: string, highlight: Highlight): Promise<AnnotationData> {
  const { data } = await axios.post(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`, {
    material_id: materialId,
    highlight,
  });
  return parseAnnotationData(data);
}

export async function clearAnnotations(materialId: string): Promise<void> {
  await axios.delete(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`);
}

export async function replaceHighlights(materialId: string, highlights: Highlight[]): Promise<AnnotationData> {
  const { data } = await axios.put(`${API_BASE}/api/annotations/${encodeURIComponent(materialId)}`, {
    highlights,
  });
  return parseAnnotationData(data);
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

function parseAddNoteResult(payload: unknown): AddNoteResult {
  const record = asRecord(payload, '笔记写入响应');
  return {
    material_id: readString(record, 'material_id', '笔记写入响应'),
    note: parseNote(record.note),
    annotation: parseAnnotationData(record.annotation),
  };
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
  return parseAddNoteResult(data);
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
  return parseAddNoteResult(data);
}

export async function deleteNote(materialId: string, noteId: string): Promise<{ annotation: AnnotationData }> {
  const { data } = await axios.delete(
    `${API_BASE}/api/annotations/${encodeURIComponent(materialId)}/notes/${encodeURIComponent(noteId)}`,
  );
  const record = asRecord(data, '笔记删除响应');
  return { annotation: parseAnnotationData(record.annotation) };
}

export interface UpdateNoteUsageInput {
  enabled_scopes: AnnotationUseScope[];
  expected_updated_at: string;
}

export interface UpdateNoteUsageResult extends AddNoteResult {
  changed: boolean;
}

export async function updateNoteUsage(
  materialId: string,
  noteId: string,
  input: UpdateNoteUsageInput,
): Promise<UpdateNoteUsageResult> {
  const enabledScopes = parseAnnotationUseScopes(input.enabled_scopes);
  const expectedUpdatedAt = input.expected_updated_at.trim();
  if (!expectedUpdatedAt) {
    throw new AnnotationApiPayloadError('缺少当前笔记版本，无法保存授权。');
  }
  const { data } = await axios.put(
    `${API_BASE}/api/annotations/${encodeURIComponent(materialId)}/notes/${encodeURIComponent(noteId)}/usage`,
    {
      enabled_scopes: enabledScopes,
      expected_updated_at: expectedUpdatedAt,
    },
  );
  const record = asRecord(data, '笔记授权响应');
  if (typeof record.changed !== 'boolean') {
    throw new AnnotationApiPayloadError('笔记授权响应缺少 changed 字段。');
  }
  return {
    ...parseAddNoteResult(record),
    changed: record.changed,
  };
}

export function isAnnotationConflict(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false;
  const response = (error as Record<string, unknown>).response;
  if (typeof response !== 'object' || response === null || Array.isArray(response)) return false;
  return (response as Record<string, unknown>).status === 409;
}

export interface EnqueueAnnotationWikiReviewInput {
  project_id: string;
  material_id: string;
  note_id: string;
  expected_updated_at: string;
  expected_content_hash: string;
  request_id: string;
}

export interface AnnotationWikiReviewSubmission {
  item_id: string;
  item_revision: string;
  status: string;
  target: {
    schema_version: 'scholar-ai-annotation-note-review-target/v1';
    type: 'annotation_note';
    project_id: string;
    material_id: string;
    note_id: string;
    expected_updated_at: string;
    expected_content_hash: string;
    required_scope: 'wiki_review';
  };
}

function requiredInput(value: string, label: string): string {
  const normalized = value.trim();
  if (!normalized) throw new AnnotationApiPayloadError(`${label}不能为空。`);
  return normalized;
}

function parseAnnotationWikiReviewSubmission(payload: unknown): AnnotationWikiReviewSubmission {
  const record = asRecord(payload, 'Wiki 待审响应');
  const target = asRecord(record.target, 'Wiki 待审目标');
  if (
    target.schema_version !== 'scholar-ai-annotation-note-review-target/v1'
    || target.type !== 'annotation_note'
    || target.required_scope !== 'wiki_review'
  ) {
    throw new AnnotationApiPayloadError('Wiki 待审响应的笔记目标无效。');
  }
  return {
    item_id: readString(record, 'item_id', 'Wiki 待审响应'),
    item_revision: readString(record, 'item_revision', 'Wiki 待审响应'),
    status: readString(record, 'status', 'Wiki 待审响应'),
    target: {
      schema_version: target.schema_version,
      type: target.type,
      project_id: readString(target, 'project_id', 'Wiki 待审目标'),
      material_id: readString(target, 'material_id', 'Wiki 待审目标'),
      note_id: readString(target, 'note_id', 'Wiki 待审目标'),
      expected_updated_at: readString(target, 'expected_updated_at', 'Wiki 待审目标'),
      expected_content_hash: readSha256(target, 'expected_content_hash', 'Wiki 待审目标'),
      required_scope: target.required_scope,
    },
  };
}

export async function enqueueAnnotationWikiReview(
  input: EnqueueAnnotationWikiReviewInput,
): Promise<AnnotationWikiReviewSubmission> {
  const expectedContentHash = input.expected_content_hash.trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(expectedContentHash)) {
    throw new AnnotationApiPayloadError('笔记内容哈希无效，请刷新后重试。');
  }
  const body: EnqueueAnnotationWikiReviewInput = {
    project_id: requiredInput(input.project_id, '项目'),
    material_id: requiredInput(input.material_id, '文献'),
    note_id: requiredInput(input.note_id, '笔记'),
    expected_updated_at: requiredInput(input.expected_updated_at, '笔记版本'),
    expected_content_hash: expectedContentHash,
    request_id: requiredInput(input.request_id, '提交请求'),
  };
  const { data } = await axios.post(`${API_BASE}/api/wiki/review/annotations/enqueue`, body);
  return parseAnnotationWikiReviewSubmission(data);
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
