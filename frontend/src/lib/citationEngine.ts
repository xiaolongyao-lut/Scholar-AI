import CSL, { type Engine } from 'citeproc';
import localeZhCN from '@/assets/csl-locales/locales-zh-CN.xml?raw';
import localeEnUS from '@/assets/csl-locales/locales-en-US.xml?raw';

/**
 * CSL-JSON item (subset). Every item needs a stable `id` and a CSL `type`.
 * See https://citeproc-js.readthedocs.io/en/latest/csl-json/markup.html
 */
export interface CslJsonItem {
  id: string;
  type: string;
  title?: string;
  author?: Array<{ family?: string; given?: string; literal?: string }>;
  issued?: { 'date-parts': number[][] };
  'container-title'?: string;
  publisher?: string;
  volume?: string;
  issue?: string;
  page?: string;
  DOI?: string;
  URL?: string;
  language?: string;
}

export interface CitationRenderResult {
  /** Formatted reference list entries (HTML), in citeproc bibliography order. */
  bibliography: Array<{ id: string; html: string }>;
  /** Per-item in-text preview keyed by item id (style-appropriate form). */
  inText: Record<string, string>;
  errors: string[];
}

export type CitationAuditSeverity = 'error' | 'warning' | 'info';

export interface CitationAuditInputItem {
  id: string;
  title: string;
  authors: string[];
  year?: number | null;
  publication?: string | null;
  doi?: string | null;
  url?: string | null;
  citationCount: number;
  sourceKind?: string;
}

export interface CitationAuditIssue {
  id: string;
  severity: CitationAuditSeverity;
  label: string;
  description: string;
  itemIds: string[];
  action: string;
}

export interface CitationAuditSummary {
  total: number;
  cited: number;
  uncited: number;
  withDoi: number;
  metadataReady: number;
  duplicateGroups: number;
  recentRatio: number;
  issues: CitationAuditIssue[];
}

export interface CitationEvidenceAnchorAuditItem {
  id: string;
  sourceKind?: string | null;
  materialId?: string | null;
  chunkId?: string | null;
  page?: number | null;
  bbox?: number[] | null;
  sourceLabels?: string[] | null;
}

export interface ParsedBibTeXReference {
  key: string;
  cslType: string;
  title: string;
  authors: string[];
  year?: number | null;
  publication?: string | null;
  doi?: string | null;
  url?: string | null;
  publisher?: string | null;
  volume?: string | null;
  issue?: string | null;
  pages?: string | null;
}

// citeproc must always be able to resolve a locale; "us"/en-US is the required
// fallback. GB/T styles declare a zh-CN default-locale, which we honor via the
// engine's forceLang flag below.
function retrieveLocale(lang: string): string {
  return typeof lang === 'string' && lang.toLowerCase().startsWith('zh') ? localeZhCN : localeEnUS;
}

function normalizeEntryIds(entryIds: string[] | string[][] | undefined): string[] {
  if (!Array.isArray(entryIds)) return [];
  return entryIds.map((entry) => (Array.isArray(entry) ? String(entry[0] ?? '') : String(entry)));
}

const GENERATED_CITATION_SOURCE_KINDS = new Set([
  'generated_description',
  'generated_figure_description',
  'generated_table_description',
  'generated_equation_description',
  'figure_description',
  'table_description',
  'equation_description',
]);

/**
 * Render in-text citations + a formatted bibliography for `items` under the
 * given CSL `styleXml` (raw .csl from GET /api/csl-styles/active). Runs the
 * Zotero-grade citeproc-js processor entirely in the browser.
 *
 * Returns empty results (never throws) when the style or items are missing so
 * callers can render a graceful empty state.
 */
export function renderCitations(styleXml: string, items: CslJsonItem[]): CitationRenderResult {
  if (!styleXml.trim() || items.length === 0) {
    return { bibliography: [], inText: {}, errors: [] };
  }
  const byId = new Map(items.map((item) => [item.id, item]));
  const sys = {
    retrieveLocale,
    retrieveItem: (id: string) => byId.get(id) ?? false,
  };
  let engine: Engine;
  try {
    engine = new CSL.Engine(sys, styleXml, 'zh-CN', true);
  } catch (error) {
    return { bibliography: [], inText: {}, errors: [`citeproc 初始化失败：${String(error)}`] };
  }
  const ids = items.map((item) => item.id);
  engine.updateItems(ids);

  const inText: Record<string, string> = {};
  for (const id of ids) {
    try {
      inText[id] = engine.previewCitationCluster(
        { citationItems: [{ id }], properties: { noteIndex: 0 } },
        [],
        [],
        'text',
      );
    } catch {
      inText[id] = '';
    }
  }

  const [params, entries] = engine.makeBibliography();
  const entryIds = normalizeEntryIds(params.entry_ids);
  const bibliography = entries.map((html, index) => ({
    id: entryIds[index] ?? ids[index] ?? String(index),
    html,
  }));
  return { bibliography, inText, errors: params.bibliography_errors ?? [] };
}

export function auditCitationSources(
  items: CitationAuditInputItem[],
  options: { minReferences?: number; recentYears?: number; recentRatio?: number } = {},
): CitationAuditSummary {
  const minReferences = options.minReferences ?? 15;
  const recentYears = options.recentYears ?? 5;
  const requiredRecentRatio = options.recentRatio ?? 0.5;
  const nowYear = new Date().getFullYear();
  const issues: CitationAuditIssue[] = [];
  const normalizedItems = items.map((item) => ({
    ...item,
    title: item.title.trim(),
    authors: item.authors.map((author) => author.trim()).filter(Boolean),
    doi: normalizeDoi(item.doi),
    publication: item.publication?.trim() || null,
  }));

  for (const item of normalizedItems) {
    const missing: string[] = [];
    if (!item.title || /^未命名文献$/.test(item.title)) missing.push('题名');
    if (item.authors.length === 0 || item.authors.some((author) => /作者待补|unknown|placeholder/i.test(author))) missing.push('作者');
    if (!isValidYear(item.year)) missing.push('年份');
    if (!item.publication && item.sourceKind !== 'manual') missing.push('期刊/出处');
    if (missing.length > 0) {
      issues.push({
        id: `missing:${item.id}`,
        severity: missing.includes('题名') || missing.includes('作者') || missing.includes('年份') ? 'error' : 'warning',
        label: `${item.title || item.id} 缺少 ${missing.join('、')}`,
        description: '缺少核心元数据时，GB/T、IEEE、APA 等样式都会生成不稳定或不完整的参考文献。',
        itemIds: [item.id],
        action: '打开“编辑文献元数据”，补齐题名、作者、年份、出处、DOI。',
      });
    }
    if (!item.doi && !item.url) {
      issues.push({
        id: `locator:${item.id}`,
        severity: 'info',
        label: `${item.title || item.id} 没有 DOI 或 URL`,
        description: '没有可解析定位符时，后续查重、跳转和投稿审查会更弱。',
        itemIds: [item.id],
        action: '能找到 DOI 时优先补 DOI；无 DOI 的资料补 URL 或出版者信息。',
      });
    }
    if (item.citationCount === 0) {
      issues.push({
        id: `uncited:${item.id}`,
        severity: 'info',
        label: `${item.title || item.id} 尚未在正文引用`,
        description: '参考文献表中未被正文引用的条目容易被期刊审稿或格式检查标出。',
        itemIds: [item.id],
        action: '确认是否需要保留；若保留，请在对应论述处插入引用标记。',
      });
    }
  }

  const duplicateGroups = findDuplicateCitationGroups(normalizedItems);
  for (const group of duplicateGroups) {
    issues.push({
      id: `duplicate:${group.join(':')}`,
      severity: 'warning',
      label: `可能重复的文献条目：${group.length} 条`,
      description: 'DOI 相同，或题名和年份高度相似。重复条目会导致正文引用编号和参考文献目录不稳定。',
      itemIds: group,
      action: '保留元数据最完整的一条，合并正文引用后删除重复项。',
    });
  }

  const years = normalizedItems.map((item) => item.year).filter(isValidYear);
  const recentCount = years.filter((year) => nowYear - year <= recentYears).length;
  const recentRatio = normalizedItems.length > 0 ? recentCount / normalizedItems.length : 0;
  if (normalizedItems.length > 0 && normalizedItems.length < minReferences) {
    issues.push({
      id: 'count:min',
      severity: 'warning',
      label: `参考文献数量偏少：${normalizedItems.length}/${minReferences}`,
      description: '多数期刊论文需要足够的背景与对比文献，数量过少会削弱综述和方法对比。',
      itemIds: normalizedItems.map((item) => item.id),
      action: '用智能推荐引用补齐关键背景、方法对比和最新研究。',
    });
  }
  if (normalizedItems.length >= 5 && recentRatio < requiredRecentRatio) {
    issues.push({
      id: 'recency:low',
      severity: 'warning',
      label: `近 ${recentYears} 年文献占比偏低：${Math.round(recentRatio * 100)}%`,
      description: '外部工具的常用检查项会关注近年文献比例，尤其是综述和投稿前自查。',
      itemIds: normalizedItems.filter((item) => isValidYear(item.year) && nowYear - item.year > recentYears).map((item) => item.id),
      action: '补充近年论文，或在目标期刊要求里确认没有近年比例要求。',
    });
  }

  return {
    total: normalizedItems.length,
    cited: normalizedItems.filter((item) => item.citationCount > 0).length,
    uncited: normalizedItems.filter((item) => item.citationCount === 0).length,
    withDoi: normalizedItems.filter((item) => item.doi).length,
    metadataReady: normalizedItems.filter((item) => item.title && item.authors.length > 0 && isValidYear(item.year)).length,
    duplicateGroups: duplicateGroups.length,
    recentRatio,
    issues,
  };
}

export function auditCitationEvidenceAnchors(items: CitationEvidenceAnchorAuditItem[]): CitationAuditIssue[] {
  const issues: CitationAuditIssue[] = [];
  for (const item of items) {
    const sourceKind = normalizeSourceKind(item.sourceKind);
    const hasConcreteAnchor = hasConcreteCitationAnchor(item);
    if (item.bbox && !isPositiveInteger(item.page)) {
      issues.push({
        id: `anchor-page:${item.id}`,
        severity: 'error',
        label: `${item.id} 的 PDF bbox 缺少页码`,
        description: 'bbox 只能在已知 PDF 页码内解释；缺页码会导致引用无法稳定跳回原文。',
        itemIds: [item.id],
        action: '保存 citation anchor 时同时写入 materialId、page 和 bbox。',
      });
      continue;
    }
    if (GENERATED_CITATION_SOURCE_KINDS.has(sourceKind) && !hasConcreteAnchor) {
      issues.push({
        id: `generated-anchor:${item.id}`,
        severity: 'error',
        label: `${item.id} 是生成描述但没有原始 PDF anchor`,
        description: '图表、表格、公式等生成描述不能单独作为可信引用，必须链接到可复核的 PDF 页码、chunk 或 bbox。',
        itemIds: [item.id],
        action: '把生成描述绑定到原始 PDF 证据后再用于正文引用。',
      });
      continue;
    }
    if (!hasConcreteAnchor) {
      issues.push({
        id: `missing-anchor:${item.id}`,
        severity: 'warning',
        label: `${item.id} 缺少可跳转的源锚点`,
        description: '没有 materialId + page/chunk 时，引用只能显示元数据，不能完成 PDF-first 复核。',
        itemIds: [item.id],
        action: '优先从 evidence ref 或 chunk locator 补齐 PDF source anchor。',
      });
    }
  }
  return issues;
}

export function parseBibTeXReferences(input: string): ParsedBibTeXReference[] {
  const text = input.trim();
  if (!text) return [];

  const entries: ParsedBibTeXReference[] = [];
  for (const block of splitBibTeXBlocks(text)) {
    const header = block.match(/^@(\w+)\s*[{(]\s*([^,]+)\s*,/);
    if (!header) continue;
    const entryType = header[1].toLowerCase();
    const key = header[2].trim();
    const fields = parseBibTeXFields(block.slice(header[0].length, -1));
    entries.push({
      key,
      cslType: bibTeXTypeToCslType(entryType),
      title: stripBibTeXBraces(fields.title ?? ''),
      authors: parseBibTeXAuthors(fields.author ?? fields.authors ?? ''),
      year: coerceYear(fields.year),
      publication: stripBibTeXBraces(fields.journal ?? fields.journaltitle ?? fields.booktitle ?? ''),
      doi: stripBibTeXBraces(fields.doi ?? ''),
      url: stripBibTeXBraces(fields.url ?? ''),
      publisher: stripBibTeXBraces(fields.publisher ?? ''),
      volume: stripBibTeXBraces(fields.volume ?? ''),
      issue: stripBibTeXBraces(fields.number ?? fields.issue ?? ''),
      pages: stripBibTeXBraces(fields.pages ?? '').replace(/--/g, '-'),
    });
  }
  return entries;
}

function normalizeDoi(value: string | null | undefined): string | null {
  const text = String(value ?? '').trim();
  if (!text) return null;
  return text.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '').trim().toLowerCase() || null;
}

function isValidYear(value: number | null | undefined): value is number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return false;
  const year = Math.floor(value);
  return year >= 1900 && year <= new Date().getFullYear() + 1;
}

function findDuplicateCitationGroups(items: Array<CitationAuditInputItem & { doi: string | null }>): string[][] {
  const groups = new Map<string, string[]>();
  for (const item of items) {
    const key = item.doi
      ? `doi:${item.doi}`
      : `title:${normalizeTitleForDuplicateCheck(item.title)}:${item.year ?? ''}`;
    if (key === 'title::') continue;
    const next = groups.get(key) ?? [];
    next.push(item.id);
    groups.set(key, next);
  }
  return [...groups.values()].filter((group) => group.length > 1);
}

function normalizeSourceKind(value: string | null | undefined): string {
  return String(value ?? 'local').trim().toLowerCase() || 'local';
}

function hasConcreteCitationAnchor(item: CitationEvidenceAnchorAuditItem): boolean {
  const materialId = String(item.materialId ?? '').trim();
  if (!materialId) return false;
  if (String(item.chunkId ?? '').trim()) return true;
  if (isPositiveInteger(item.page)) return true;
  return false;
}

function isPositiveInteger(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

function normalizeTitleForDuplicateCheck(value: string): string {
  return value
    .toLowerCase()
    .replace(/[{}[\]().,，。:：;；"'“”‘’\s_-]+/g, '')
    .slice(0, 96);
}

function splitBibTeXBlocks(text: string): string[] {
  const blocks: string[] = [];
  let start = -1;
  let depth = 0;
  let opened = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '@' && depth === 0) {
      start = index;
      opened = false;
    }
    if (start < 0) continue;
    if (char === '{' || char === '(') {
      depth += 1;
      opened = true;
    }
    if (char === '}' || char === ')') depth -= 1;
    if (start >= 0 && opened && depth === 0 && index > start) {
      blocks.push(text.slice(start, index + 1));
      start = -1;
      opened = false;
    }
  }
  return blocks;
}

function parseBibTeXFields(text: string): Record<string, string> {
  const fields: Record<string, string> = {};
  const fieldPattern = /(\w+)\s*=\s*(?:\{([\s\S]*?)\}|"([\s\S]*?)")\s*,?/g;
  let match: RegExpExecArray | null;
  while ((match = fieldPattern.exec(text)) !== null) {
    fields[match[1].toLowerCase()] = stripBibTeXBraces(match[2] ?? match[3] ?? '');
  }
  return fields;
}

function stripBibTeXBraces(value: string): string {
  return value.replace(/[{}]/g, '').replace(/\s+/g, ' ').trim();
}

function parseBibTeXAuthors(value: string): string[] {
  return stripBibTeXBraces(value)
    .split(/\s+and\s+/i)
    .map((author) => {
      const parts = author.split(',').map((part) => part.trim()).filter(Boolean);
      return parts.length >= 2 ? `${parts[1]} ${parts[0]}` : author.trim();
    })
    .filter(Boolean);
}

function coerceYear(value: string | undefined): number | null {
  const match = String(value ?? '').match(/\d{4}/);
  if (!match) return null;
  const year = Number(match[0]);
  return Number.isFinite(year) ? year : null;
}

function bibTeXTypeToCslType(value: string): string {
  const map: Record<string, string> = {
    article: 'article-journal',
    inproceedings: 'paper-conference',
    proceedings: 'paper-conference',
    conference: 'paper-conference',
    book: 'book',
    incollection: 'chapter',
    phdthesis: 'thesis',
    mastersthesis: 'thesis',
    techreport: 'report',
    dataset: 'dataset',
    online: 'webpage',
    misc: 'webpage',
  };
  return map[value] ?? 'article-journal';
}
