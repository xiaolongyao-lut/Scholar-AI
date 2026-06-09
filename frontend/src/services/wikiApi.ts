import { getApiBaseUrl } from './apiBaseUrl';
import type {
  WikiCompileBudgetCheckModel,
  WikiCompileBudgetSummaryModel,
  WikiCompileDryRunInputModel,
  WikiCompileDryRunModel,
  DoctorSeverity,
  WikiDoctorActionModel,
  WikiDoctorCheckModel,
  WikiDoctorModel,
  WikiDoctorStructuredReportModel,
  WikiGraphEdgeModel,
  WikiManualPageInputModel,
  WikiGraphModel,
  WikiGraphNodeModel,
  WikiGraphStructuredModel,
  WikiPageDetailModel,
  WikiPageListModel,
  WikiPageMutationModel,
  WikiPageSummaryModel,
  WikiSearchEvidenceRefModel,
  WikiSearchModel,
  WikiExportModel,
  WikiReviewDecisionModel,
  WikiReviewItemModel,
  WikiReviewListModel,
  WikiStatusModel,
} from '@/types/wiki';

const BASE = getApiBaseUrl();

export class WikiApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'WikiApiError';
    this.status = status;
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new WikiApiError('Wiki API returned a non-object payload', 500);
  }
  return value as Record<string, unknown>;
}

function readBoolean(record: Record<string, unknown>, key: string): boolean {
  if (typeof record[key] !== 'boolean') {
    throw new WikiApiError(`Wiki payload is missing boolean field: ${key}`, 500);
  }
  return record[key] as boolean;
}

function readNumber(record: Record<string, unknown>, key: string): number {
  if (typeof record[key] !== 'number') {
    throw new WikiApiError(`Wiki payload is missing numeric field: ${key}`, 500);
  }
  return record[key] as number;
}

function readOptionalNumber(record: Record<string, unknown>, key: string, fallback: number = 0): number {
  const value = record[key];
  if (value === undefined || value === null) {
    return fallback;
  }
  if (typeof value !== 'number') {
    throw new WikiApiError(`Wiki payload contains invalid numeric field: ${key}`, 500);
  }
  return value;
}

function readString(record: Record<string, unknown>, key: string): string {
  if (typeof record[key] !== 'string') {
    throw new WikiApiError(`Wiki payload is missing string field: ${key}`, 500);
  }
  return record[key] as string;
}

function readStringArray(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new WikiApiError(`Wiki payload is missing string[] field: ${key}`, 500);
  }
  return value as string[];
}

function readOptionalStringArray(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (value === undefined || value === null) {
    return [];
  }
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new WikiApiError(`Wiki payload contains invalid string[] field: ${key}`, 500);
  }
  return value as string[];
}

function readOptionalRecord(record: Record<string, unknown>, key: string): Record<string, unknown> | null {
  const value = record[key];
  if (value === undefined || value === null) {
    return null;
  }
  return asRecord(value);
}

function readStringRecord(record: Record<string, unknown>, key: string): Record<string, string> {
  const value = asRecord(record[key]);
  for (const item of Object.values(value)) {
    if (typeof item !== 'string') {
      throw new WikiApiError(`Wiki payload contains non-string entries in: ${key}`, 500);
    }
  }
  return value as Record<string, string>;
}

function readNumberRecord(record: Record<string, unknown>, key: string): Record<string, number> {
  const value = asRecord(record[key]);
  for (const item of Object.values(value)) {
    if (typeof item !== 'number') {
      throw new WikiApiError(`Wiki payload contains non-number entries in: ${key}`, 500);
    }
  }
  return value as Record<string, number>;
}

function readArray<T>(record: Record<string, unknown>, key: string, mapper: (item: unknown, index: number) => T): T[] {
  const value = record[key];
  if (!Array.isArray(value)) {
    throw new WikiApiError(`Wiki payload is missing array field: ${key}`, 500);
  }
  return value.map((item, index) => mapper(item, index));
}

function readSeverity(value: unknown, fieldName: string): DoctorSeverity {
  if (value === 'ok' || value === 'warning' || value === 'error') {
    return value;
  }
  throw new WikiApiError(`Wiki doctor payload contains invalid severity in: ${fieldName}`, 500);
}

function readNullableString(record: Record<string, unknown>, key: string): string | null {
  if (record[key] === null || record[key] === undefined || record[key] === '') {
    return null;
  }
  if (typeof record[key] !== 'string') {
    throw new WikiApiError(`Wiki payload contains invalid nullable string field: ${key}`, 500);
  }
  return record[key] as string;
}

function buildAbortSignal(timeoutMs: number, signals: Array<AbortSignal | null | undefined>): {
  signal: AbortSignal;
  cleanup: () => void;
} {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new WikiApiError('Wiki 请求超时时间配置无效。', 500);
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  const listeners: Array<{ signal: AbortSignal; listener: () => void }> = [];

  for (const signal of signals) {
    if (!signal) {
      continue;
    }
    if (signal.aborted) {
      controller.abort();
      continue;
    }
    const listener = () => controller.abort();
    signal.addEventListener('abort', listener, { once: true });
    listeners.push({ signal, listener });
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timeoutId);
      for (const { signal, listener } of listeners) {
        signal.removeEventListener('abort', listener);
      }
    },
  };
}

async function fetchWikiJson(
  path: string,
  timeoutMs: number,
  init?: RequestInit,
  signal?: AbortSignal,
): Promise<unknown> {
  const headers = new Headers(init?.headers);
  headers.set('Accept', 'application/json');
  if (init?.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const abort = buildAbortSignal(timeoutMs, [init?.signal, signal]);

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: 'GET',
      ...init,
      headers,
      signal: abort.signal,
    });
  } finally {
    abort.cleanup();
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
      ? (payload as { detail?: unknown }).detail
      : undefined;
    const message = typeof detail === 'string' ? detail : response.statusText || 'Wiki request failed';
    throw new WikiApiError(message, response.status);
  }

  return response.json();
}

function encodeWikiPagePath(pagePath: string): string {
  return pagePath
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/');
}

function parseWikiPageSummary(payload: unknown): WikiPageSummaryModel {
  const record = asRecord(payload);
  return {
    path: readString(record, 'path'),
    title: readString(record, 'title'),
    kind: readString(record, 'kind'),
    status: readString(record, 'status'),
  } satisfies WikiPageSummaryModel;
}

function parseWikiDoctorAction(payload: unknown): WikiDoctorActionModel {
  const record = asRecord(payload);
  return {
    command: readString(record, 'command'),
    description: readString(record, 'description'),
    safe_auto_repair: readBoolean(record, 'safe_auto_repair'),
  };
}

function parseWikiDoctorCheck(payload: unknown): WikiDoctorCheckModel {
  const record = asRecord(payload);
  return {
    id: readString(record, 'id'),
    label: readString(record, 'label'),
    status: readSeverity(record.status, 'status'),
    summary: readString(record, 'summary'),
    detail: typeof record.detail === 'string' ? record.detail : '',
    metrics: 'metrics' in record ? asRecord(record.metrics) : {},
    actions: 'actions' in record ? readArray(record, 'actions', parseWikiDoctorAction) : [],
  };
}

function parseStructuredDoctorReport(report: Record<string, unknown>): WikiDoctorStructuredReportModel | null {
  try {
    return {
      ok: readBoolean(report, 'ok'),
      status: readSeverity(report.status, 'status'),
      counts: readNumberRecord(report, 'counts'),
      checks: readArray(report, 'checks', parseWikiDoctorCheck),
    };
  } catch {
    return null;
  }
}

function parseWikiReviewDecision(payload: unknown): WikiReviewDecisionModel {
  const record = asRecord(payload);
  return {
    status: readString(record, 'status'),
    reason: readString(record, 'reason'),
    decided_at: readString(record, 'decided_at'),
    decided_by: readString(record, 'decided_by'),
  };
}

function parseWikiReviewItem(payload: unknown): WikiReviewItemModel {
  const record = asRecord(payload);
  return {
    item_id: readString(record, 'item_id'),
    kind: readString(record, 'kind'),
    title: readString(record, 'title'),
    page_path: readString(record, 'page_path'),
    summary: typeof record.summary === 'string' ? record.summary : '',
    status: readString(record, 'status'),
    created_at: readString(record, 'created_at'),
    source: readString(record, 'source'),
    metadata: 'metadata' in record ? asRecord(record.metadata) : {},
    decision: record.decision && typeof record.decision === 'object' ? parseWikiReviewDecision(record.decision) : null,
  };
}

function parseWikiGraphNode(payload: unknown): WikiGraphNodeModel {
  const record = asRecord(payload);
  return {
    node_id: readString(record, 'node_id'),
    page_path: readString(record, 'page_path'),
    kind: readString(record, 'kind'),
    title: readString(record, 'title'),
    status: readString(record, 'status'),
    content_hash: readString(record, 'content_hash'),
    frontmatter_id: readNullableString(record, 'frontmatter_id'),
    metadata: 'metadata' in record ? asRecord(record.metadata) : {},
  };
}

function parseWikiGraphEdge(payload: unknown): WikiGraphEdgeModel {
  const record = asRecord(payload);
  return {
    edge_id: readString(record, 'edge_id'),
    source_id: readString(record, 'source_id'),
    target_id: readString(record, 'target_id'),
    edge_type: readString(record, 'edge_type'),
    weight: readNumber(record, 'weight'),
    confidence: readString(record, 'confidence'),
    evidence: readString(record, 'evidence'),
    source_path: readString(record, 'source_path'),
    target_path: readNullableString(record, 'target_path'),
    metadata: 'metadata' in record ? asRecord(record.metadata) : {},
  };
}

function parseStructuredGraph(graph: Record<string, unknown>): WikiGraphStructuredModel | null {
  try {
    return {
      schema_version: readNumber(graph, 'schema_version'),
      updated_at: readString(graph, 'updated_at'),
      node_count: readNumber(graph, 'node_count'),
      edge_count: readNumber(graph, 'edge_count'),
      nodes: readArray(graph, 'nodes', parseWikiGraphNode),
      edges: readArray(graph, 'edges', parseWikiGraphEdge),
    };
  } catch {
    return null;
  }
}

function parseWikiSearchEvidenceRef(payload: unknown): WikiSearchEvidenceRefModel {
  const record = asRecord(payload);
  return {
    ...record,
    page_path: typeof record.page_path === 'string' ? record.page_path : undefined,
    title: typeof record.title === 'string' ? record.title : undefined,
    score: typeof record.score === 'number' ? record.score : undefined,
    snippet: typeof record.snippet === 'string' ? record.snippet : undefined,
    source: typeof record.source === 'string' ? record.source : undefined,
    source_labels: Array.isArray(record.source_labels) && record.source_labels.every((item) => typeof item === 'string')
      ? record.source_labels
      : undefined,
  };
}

function parseWikiCompileBudgetSummary(payload: unknown): WikiCompileBudgetSummaryModel {
  if (payload === undefined || payload === null) {
    return {
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      input_cost_usd: 0,
      output_cost_usd: 0,
      estimated_cost_usd: 0,
      pricing_configured: false,
      pricing_source: 'not_configured',
      currency: 'USD',
    };
  }
  const record = asRecord(payload);
  return {
    input_tokens: readNumber(record, 'input_tokens'),
    output_tokens: readNumber(record, 'output_tokens'),
    total_tokens: readNumber(record, 'total_tokens'),
    input_cost_usd: readNumber(record, 'input_cost_usd'),
    output_cost_usd: readNumber(record, 'output_cost_usd'),
    estimated_cost_usd: readNumber(record, 'estimated_cost_usd'),
    pricing_configured: readBoolean(record, 'pricing_configured'),
    pricing_source: readString(record, 'pricing_source'),
    currency: readString(record, 'currency'),
  };
}

function parseWikiCompileBudgetCheck(payload: unknown): WikiCompileBudgetCheckModel {
  const record = asRecord(payload);
  return {
    source_id: readString(record, 'source_id'),
    source_chunks: readNumber(record, 'source_chunks'),
    total_chunk_chars: readNumber(record, 'total_chunk_chars'),
    estimated_tokens: readNumber(record, 'estimated_tokens'),
    over_budget: readBoolean(record, 'over_budget'),
    reason: readString(record, 'reason'),
  };
}

export function parseWikiStatus(payload: unknown): WikiStatusModel {
  const record = asRecord(payload);
  return {
    enabled: readBoolean(record, 'enabled'),
    page_count: readNumber(record, 'page_count'),
    stale: readBoolean(record, 'stale'),
    graph_json_exists: readBoolean(record, 'graph_json_exists'),
    graph_db_exists: readBoolean(record, 'graph_db_exists'),
    query_index_exists: readBoolean(record, 'query_index_exists'),
    review_queue_exists: readBoolean(record, 'review_queue_exists'),
    paths: readStringRecord(record, 'paths'),
    warnings: readStringArray(record, 'warnings'),
  } satisfies WikiStatusModel;
}

export function parseWikiPageList(payload: unknown): WikiPageListModel {
  const record = asRecord(payload);
  return {
    enabled: readBoolean(record, 'enabled'),
    pages: readArray(record, 'pages', parseWikiPageSummary),
  } satisfies WikiPageListModel;
}

export function parseWikiDoctor(payload: unknown): WikiDoctorModel {
  const record = asRecord(payload);
  const report = asRecord(record.report);
  const warnings = Array.isArray(report.warnings) && report.warnings.every((item) => typeof item === 'string')
    ? (report.warnings as string[])
    : [];
  return {
    enabled: readBoolean(record, 'enabled'),
    report,
    warnings,
    structuredReport: parseStructuredDoctorReport(report),
  } satisfies WikiDoctorModel;
}

export function parseWikiReviewList(payload: unknown): WikiReviewListModel {
  const record = asRecord(payload);
  return {
    enabled: readBoolean(record, 'enabled'),
    items: readArray(record, 'items', parseWikiReviewItem),
  } satisfies WikiReviewListModel;
}

export function parseWikiGraph(payload: unknown): WikiGraphModel {
  const record = asRecord(payload);
  const graph = asRecord(record.graph);
  return {
    enabled: readBoolean(record, 'enabled'),
    graph,
    structuredGraph: parseStructuredGraph(graph),
  } satisfies WikiGraphModel;
}

export function parseWikiPageDetail(payload: unknown): WikiPageDetailModel {
  const record = asRecord(payload);
  return {
    enabled: readBoolean(record, 'enabled'),
    path: readString(record, 'path'),
    frontmatter: 'frontmatter' in record && record.frontmatter !== undefined && record.frontmatter !== null
      ? asRecord(record.frontmatter)
      : {},
    body: readString(record, 'body'),
  } satisfies WikiPageDetailModel;
}

export function parseWikiCompileDryRun(payload: unknown): WikiCompileDryRunModel {
  const record = asRecord(payload);
  return {
    enabled: readBoolean(record, 'enabled'),
    dry_run: readBoolean(record, 'dry_run'),
    created: readOptionalNumber(record, 'created'),
    updated: readOptionalNumber(record, 'updated'),
    skipped: readOptionalNumber(record, 'skipped'),
    planned_paths: readOptionalStringArray(record, 'planned_paths'),
    written_paths: readOptionalStringArray(record, 'written_paths'),
    budget_summary: parseWikiCompileBudgetSummary(readOptionalRecord(record, 'budget_summary')),
    budget_checks: Array.isArray(record.budget_checks)
      ? record.budget_checks.map(parseWikiCompileBudgetCheck)
      : [],
    errors: readOptionalStringArray(record, 'errors'),
    warnings: readOptionalStringArray(record, 'warnings'),
  } satisfies WikiCompileDryRunModel;
}

export function parseWikiSearch(payload: unknown): WikiSearchModel {
  const record = asRecord(payload);
  return {
    enabled: readBoolean(record, 'enabled'),
    fallback_required: readBoolean(record, 'fallback_required'),
    answer: typeof record.answer === 'string' ? record.answer : '',
    evidence_refs: readArray(record, 'evidence_refs', parseWikiSearchEvidenceRef),
    warnings: readOptionalStringArray(record, 'warnings'),
  } satisfies WikiSearchModel;
}

export function parseWikiExport(payload: unknown): WikiExportModel {
  const record = asRecord(payload);
  return {
    success: readBoolean(record, 'success'),
    page_count: readNumber(record, 'page_count'),
    output_path: readString(record, 'output_path'),
    errors: readOptionalStringArray(record, 'errors'),
  } satisfies WikiExportModel;
}

export function parseWikiPageMutation(payload: unknown): WikiPageMutationModel {
  const record = asRecord(payload);
  return {
    success: readBoolean(record, 'success'),
    slug: readString(record, 'slug'),
    message: readString(record, 'message'),
  } satisfies WikiPageMutationModel;
}

export async function getWikiStatus(timeoutMs: number = 15000): Promise<WikiStatusModel> {
  return parseWikiStatus(await fetchWikiJson('/api/wiki/status', timeoutMs));
}

export async function getWikiPages(timeoutMs: number = 15000): Promise<WikiPageListModel> {
  return parseWikiPageList(await fetchWikiJson('/api/wiki/pages', timeoutMs));
}

export async function getWikiPageDetail(pagePath: string, timeoutMs: number = 15000): Promise<WikiPageDetailModel> {
  return parseWikiPageDetail(await fetchWikiJson(`/api/wiki/pages/${encodeWikiPagePath(pagePath)}`, timeoutMs));
}

export async function searchWiki(
  query: string,
  timeoutMs: number = 15000,
  options: { signal?: AbortSignal } = {},
): Promise<WikiSearchModel> {
  return parseWikiSearch(
    await fetchWikiJson('/api/wiki/search', timeoutMs, {
      method: 'POST',
      body: JSON.stringify({ query }),
    }, options.signal),
  );
}

export async function getWikiDoctor(timeoutMs: number = 15000): Promise<WikiDoctorModel> {
  return parseWikiDoctor(await fetchWikiJson('/api/wiki/doctor', timeoutMs));
}

export async function getWikiReview(timeoutMs: number = 15000): Promise<WikiReviewListModel> {
  return parseWikiReviewList(await fetchWikiJson('/api/wiki/review', timeoutMs));
}

export async function getWikiGraph(timeoutMs: number = 15000): Promise<WikiGraphModel> {
  return parseWikiGraph(await fetchWikiJson('/api/wiki/graph', timeoutMs));
}

export async function runWikiCompileDryRun(
  input: WikiCompileDryRunInputModel = {},
  timeoutMs: number = 15000,
  options: { signal?: AbortSignal } = {},
): Promise<WikiCompileDryRunModel> {
  const allowWrite = input.allow_write === true;
  const payload = {
    dry_run: !allowWrite,
    allow_write: allowWrite,
    ...(input.source_id ? { source_id: input.source_id } : {}),
    ...(input.project_id ? { project_id: input.project_id } : {}),
  };

  return parseWikiCompileDryRun(
    await fetchWikiJson('/api/wiki/compile', timeoutMs, {
      method: 'POST',
      body: JSON.stringify(payload),
    }, options.signal)
  );
}

export async function createWikiManualPage(
  input: WikiManualPageInputModel,
  timeoutMs: number = 15000,
  options: { signal?: AbortSignal } = {},
): Promise<WikiPageMutationModel> {
  const title = input.title.trim();
  const body = input.body.trim();
  if (!title || !body) {
    throw new WikiApiError('标题和正文不能为空。', 400);
  }
  return parseWikiPageMutation(
    await fetchWikiJson('/api/wiki/pages', timeoutMs, {
      method: 'POST',
      body: JSON.stringify({
        title,
        kind: input.kind,
        body,
        status: input.status,
        evidence_refs: [],
        source_hashes: [],
        extra: { entry_source: 'manual_frontend' },
      }),
    }, options.signal),
  );
}

export async function exportWikiMarkdown(
  timeoutMs: number = 30000,
  options: { signal?: AbortSignal } = {},
): Promise<WikiExportModel> {
  return parseWikiExport(
    await fetchWikiJson('/api/wiki/export', timeoutMs, {
      method: 'POST',
    }, options.signal),
  );
}

const EVIDENCE_BEARING_KINDS = new Set(['claim', 'claims', 'synthesis', 'exploration']);
const EVIDENCE_ID_FIELDS = ['chunk_id', 'source_id', 'material_id', 'citation_target', 'page_store_path'];
const EVIDENCE_TEXT_FIELDS = ['quote', 'compressed_text', 'text', 'content'];

function readTrimmedText(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function isLooseEvidenceRef(value: unknown): boolean {
  return readTrimmedText(value) !== null;
}

function hasAnyTextField(record: Record<string, unknown>, fields: string[]): boolean {
  return fields.some((field) => readTrimmedText(record[field]) !== null);
}

function getRawEvidenceRefs(frontmatter: Record<string, unknown>): unknown[] {
  const rawRefs = frontmatter.evidence_refs ?? frontmatter.references;
  return Array.isArray(rawRefs) ? rawRefs : [];
}

function hasStandaloneBracketCitation(body: string): boolean {
  return /(^|[^\[])\[[^\]\n]{1,80}\](?!\])/.test(body);
}

function hasInlineCitationMarker(body: string): boolean {
  return /@cite(?:\(|\[|:|\s+)/i.test(body) || hasStandaloneBracketCitation(body) || /来源|出处/.test(body);
}

function hasQuoteContext(body: string): boolean {
  return /^\s*>\s+\S/m.test(body) || /^##\s+Evidence\b/im.test(body);
}

function evidenceRefLooksUsable(rawRef: unknown): boolean {
  if (isLooseEvidenceRef(rawRef)) {
    return true;
  }
  if (typeof rawRef !== 'object' || rawRef === null || Array.isArray(rawRef)) {
    return false;
  }
  const record = rawRef as Record<string, unknown>;
  return hasAnyTextField(record, EVIDENCE_ID_FIELDS) && hasAnyTextField(record, EVIDENCE_TEXT_FIELDS);
}

export function extractCitationWarnings(detail: WikiPageDetailModel): string[] {
  const warnings: string[] = [];
  const { frontmatter, body } = detail;
  const normalizedBody = body.trim();
  const status = readTrimmedText(frontmatter.status);
  const kind = readTrimmedText(frontmatter.kind);
  const evidenceRefs = getRawEvidenceRefs(frontmatter);
  const hasEvidenceRefs = evidenceRefs.length > 0;
  const hasWikilinks = /\[\[[^\]\n]+\]\]/.test(body);
  const hasInlineCitation = hasInlineCitationMarker(body);
  const evidenceBearing = Boolean(kind && EVIDENCE_BEARING_KINDS.has(kind)) || status === 'final';

  if (!normalizedBody) {
    warnings.push('页面正文为空，无法核验证据引用。');
    return warnings;
  }

  if (status === 'draft' && !hasInlineCitation && !hasWikilinks && !hasEvidenceRefs) {
    warnings.push('草稿内容缺乏基础引用或证据链接。');
  }

  if (evidenceBearing && !hasEvidenceRefs) {
    warnings.push('证据型页面缺少 evidence_refs，不能进入 final/claim 可信链路。');
  }

  if (hasInlineCitation && !hasEvidenceRefs) {
    warnings.push('正文包含引用标记，但 Frontmatter 缺少 evidence_refs/references，无法做跳转或后续审计。');
  }

  if (hasEvidenceRefs && evidenceRefs.some((ref) => !evidenceRefLooksUsable(ref))) {
    warnings.push('部分 evidence_refs 缺少 chunk_id/source_id/material_id 或 quote/text，引用跳转可能不可用。');
  }

  if (kind === 'claim' && !hasQuoteContext(body)) {
    warnings.push('这是一个 Claim，但正文中未找到 `> 引述` 或 `## Evidence` 证据上下文。');
  }

  return warnings;
}
