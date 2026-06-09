import { AlertTriangle, ExternalLink, Eye, FileSearch, RefreshCw, Tags, TextQuote } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { encodePdfBboxParam, isPdfBboxUnit, readPdfBbox, type PdfBboxUnit } from '@/lib/pdfAnchor';
import { cn } from '@/lib/utils';
import { extractCitationWarnings } from '@/services/wikiApi';
import type { WikiPageDetailModel } from '@/types/wiki';
import { formatWikiError, formatWikiPageLabel, formatWikiWarning, sanitizeWikiVisibleText } from './wikiDisplay';

interface WikiPagePreviewPanelProps {
  selectedPath: string | null;
  page: WikiPageDetailModel | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

interface PageAttributeSummary {
  id: string;
  label: string;
  value: string;
  detail: string;
}

interface WikiPdfAnchor {
  materialId: string;
  page: number | null;
  chunkId: string | null;
  bbox: number[] | null;
  bboxUnit: PdfBboxUnit | null;
}

function scalarText(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === 'boolean') {
    return value ? '是' : '否';
  }
  return null;
}

function wikiKindLabel(value: string | null): string {
  if (!value) return '未标注';
  const labels: Record<string, string> = {
    claim: '断言',
    synthesis: '综合页',
    concept: '概念',
    source: '来源',
    paper: '论文',
    note: '笔记',
    exploration: '探索页',
  };
  return labels[value] ?? value;
}

function wikiStatusLabel(value: string | null): string {
  if (!value) return '未标注';
  const labels: Record<string, string> = {
    draft: '草稿',
    review: '待复审',
    final: '已定稿',
  };
  return labels[value] ?? value;
}

function countFrontmatterValue(value: unknown): number {
  if (Array.isArray(value)) {
    return value.length;
  }
  return scalarText(value) ? 1 : 0;
}

function readFirstScalar(frontmatter: Record<string, unknown>, keys: readonly string[]): string | null {
  for (const key of keys) {
    const value = scalarText(frontmatter[key]);
    if (value) {
      return value;
    }
  }
  return null;
}

function readStringList(frontmatter: Record<string, unknown>, keys: readonly string[]): string[] {
  const values: string[] = [];
  for (const key of keys) {
    const raw = frontmatter[key];
    if (Array.isArray(raw)) {
      for (const item of raw) {
        const text = scalarText(item);
        if (text) {
          values.push(text);
        }
      }
      continue;
    }
    const scalar = scalarText(raw);
    if (scalar) {
      values.push(...scalar.split(/[,，;；、\n]+/).map((part) => part.trim()).filter(Boolean));
    }
  }
  return Array.from(new Set(values)).slice(0, 24);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readPositivePage(value: unknown): number | null {
  if (typeof value === 'number' && Number.isInteger(value) && value > 0) {
    return value;
  }
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) {
    const page = Number(value.trim());
    return page > 0 ? page : null;
  }
  return null;
}

function readPdfAnchorFromRecord(record: Record<string, unknown>): WikiPdfAnchor | null {
  const materialId = scalarText(record.material_id);
  if (!materialId) {
    return null;
  }
  const bbox = readPdfBbox(record.bbox);
  const bboxUnit = record.bbox_unit === undefined || record.bbox_unit === null
    ? null
    : isPdfBboxUnit(record.bbox_unit)
      ? record.bbox_unit
      : null;
  return {
    materialId,
    page: readPositivePage(record.page),
    chunkId: scalarText(record.chunk_id),
    bbox: bbox ? [...bbox] : null,
    bboxUnit,
  };
}

function readPdfAnchors(frontmatter: Record<string, unknown>): WikiPdfAnchor[] {
  const rawRefs = frontmatter.evidence_refs ?? frontmatter.references;
  if (!Array.isArray(rawRefs)) {
    return [];
  }
  const anchors: WikiPdfAnchor[] = [];
  const seen = new Set<string>();
  for (const rawRef of rawRefs) {
    if (!isRecord(rawRef)) {
      continue;
    }
    const anchor = readPdfAnchorFromRecord(rawRef);
    if (!anchor) {
      continue;
    }
    const key = [
      anchor.materialId,
      anchor.page ?? '',
      anchor.chunkId ?? '',
      anchor.bbox?.join(',') ?? '',
    ].join('|');
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    anchors.push(anchor);
  }
  return anchors.slice(0, 12);
}

function pdfAnchorHref(anchor: WikiPdfAnchor): string {
  const params = new URLSearchParams();
  if (anchor.page) {
    params.set('page', String(anchor.page));
  }
  if (anchor.chunkId) {
    params.set('chunk', anchor.chunkId);
  }
  const bbox = encodePdfBboxParam(anchor.bbox, anchor.bboxUnit);
  if (bbox) {
    params.set('bbox', bbox);
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return `/workbench/paper/${encodeURIComponent(anchor.materialId)}${suffix}`;
}

function buildPageAttributeSummaries(page: WikiPageDetailModel): PageAttributeSummary[] {
  const frontmatter = page.frontmatter;
  const title = readFirstScalar(frontmatter, ['title']) ?? formatWikiPageLabel(page.path);
  const kind = readFirstScalar(frontmatter, ['kind']);
  const status = readFirstScalar(frontmatter, ['status']);
  const sourceCount = countFrontmatterValue(frontmatter.source_ids) + countFrontmatterValue(frontmatter.source_id);
  const evidenceCount = countFrontmatterValue(frontmatter.evidence_refs) + countFrontmatterValue(frontmatter.references);
  const confidence = readFirstScalar(frontmatter, ['confidence']);
  const updatedAt = readFirstScalar(frontmatter, ['updated_at', 'updated_at_iso', 'created_at', 'created_at_iso']);

  return [
    { id: 'title', label: '标题', value: sanitizeWikiVisibleText(title, 'Wiki 页面'), detail: '页面主标题' },
    { id: 'kind', label: '类型', value: wikiKindLabel(kind), detail: kind ? '已标注类型' : '未标注类型' },
    { id: 'status', label: '状态', value: wikiStatusLabel(status), detail: status ? '已标注状态' : '未标注状态' },
    { id: 'sources', label: '来源', value: `${sourceCount} 项`, detail: '已关联的来源数量' },
    { id: 'evidence', label: '证据', value: `${evidenceCount} 条`, detail: '已关联的证据数量' },
    { id: 'confidence', label: '置信度', value: sanitizeWikiVisibleText(confidence, '未标注'), detail: updatedAt ? '已记录更新时间' : '无更新时间' },
  ];
}

function wikiLinkHref(rawTarget: string, currentPath: string): string {
  const target = rawTarget.split('#', 1)[0].trim().replace(/\\/g, '/');
  const withSuffix = target.endsWith('.md') ? target : `${target}.md`;
  const currentParts = currentPath.split('/');
  const currentParent = currentParts.length > 1 ? currentParts.slice(0, -1).join('/') : '';
  const resolved = withSuffix.includes('/') || !currentParent ? withSuffix : `${currentParent}/${withSuffix}`;
  return `/wiki?${new URLSearchParams({ page: resolved }).toString()}`;
}

function renderableWikiMarkdown(body: string, currentPath: string): string {
  return body.replace(/\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]/g, (_match, rawTarget: string, rawLabel?: string) => {
    const target = rawTarget.trim();
    const label = typeof rawLabel === 'string' && rawLabel.trim() ? rawLabel.trim() : target;
    return `[${label}](${wikiLinkHref(target, currentPath)})`;
  });
}

export function WikiPagePreviewPanel({ selectedPath, page, isLoading, error, onRefresh }: WikiPagePreviewPanelProps) {
  const pageAttributes = page ? buildPageAttributeSummaries(page) : [];
  const pageTags = page ? readStringList(page.frontmatter, ['tags', 'labels', 'categories', 'category']) : [];
  const pdfAnchors = page ? readPdfAnchors(page.frontmatter) : [];
  const citationWarnings = page ? extractCitationWarnings(page) : [];

  return (
    <section data-testid="wiki-page-preview-panel" className="glass-card rounded-2xl border border-outline-variant/40 p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="font-label text-[11px] uppercase tracking-[0.22em] text-foreground/35">页面预览</div>
          <h2 className="mt-2 font-display text-2xl font-semibold text-foreground">页面预览</h2>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={!selectedPath || isLoading}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-xs font-label text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          刷新预览
        </button>
      </div>

      {error ? (
        <div className="mt-5 rounded-xl border border-red-200/80 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {formatWikiError(error, '读取 Wiki 页面预览失败，请稍后重试。')}
        </div>
      ) : null}

      {!selectedPath ? (
        <div className="mt-5 rounded-2xl border border-dashed border-outline-variant/40 bg-surface-lowest/70 px-5 py-10 text-center text-sm text-foreground/50">
          <FileSearch size={20} className="mx-auto text-primary/55" />
          <div className="mt-3 font-medium text-foreground/70">请先在左侧页面列表中选中一个页面</div>
          <p className="mt-2 text-xs leading-6 text-foreground/45">
            选中后，这里会展示页面属性、正文内容与引用状态。
          </p>
        </div>
      ) : isLoading ? (
        <div className="mt-5 rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-5 py-10 text-center text-sm text-foreground/50">
          正在读取页面预览…
        </div>
      ) : page ? (
        <>
          <div className="mt-5 rounded-2xl border border-outline-variant/30 bg-surface-lowest/75 px-4 py-4">
            <div className="font-label text-[11px] tracking-[0.14em] text-foreground/35">当前页面</div>
            <div className="mt-2 text-[13px] leading-5 text-foreground/75">{formatWikiPageLabel(page.path)}</div>
          </div>

          {citationWarnings.length > 0 && (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-700/40 dark:bg-amber-500/15">
              <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300">
                <AlertTriangle size={16} />
                <h3 className="font-headline text-sm font-semibold">文内引用与证据预警</h3>
              </div>
              <ul className="mt-3 list-inside list-disc space-y-2 text-sm text-amber-900/80 dark:text-amber-300">
                {citationWarnings.map((warning, index) => (
                  <li key={index} className="leading-6">{formatWikiWarning(warning)}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div data-testid="wiki-page-attribute-summary" className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/75 p-4">
              <div className="flex items-center gap-2 text-foreground">
                <Eye size={16} className="text-primary/65" />
                <h3 className="font-headline text-sm font-semibold">页面属性</h3>
              </div>

              {pageAttributes.length ? (
                <div className="mt-4 space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    {pageAttributes.map((attribute) => (
                      <div key={attribute.id} className="min-w-0 rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                        <div className="font-label text-[10px] tracking-[0.14em] text-foreground/35">{attribute.label}</div>
                        <div className="mt-1 truncate text-sm font-medium text-foreground/80">{attribute.value}</div>
                        <div className="mt-1 truncate text-[10px] text-foreground/40">{attribute.detail}</div>
                      </div>
                    ))}
                  </div>

                  <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                    <div className="flex items-center gap-2 font-label text-[10px] tracking-[0.14em] text-foreground/35">
                      <Tags size={12} className="text-primary/55" />
                      标签
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2" aria-label="Wiki 页面标签">
                      {pageTags.length > 0 ? pageTags.map((tag) => (
                        <span
                          key={tag}
                          className="max-w-full truncate rounded-full border border-primary/20 bg-primary/8 px-2.5 py-1 text-[11px] font-medium text-primary/80"
                          title={tag}
                        >
                          {tag}
                        </span>
                      )) : (
                        <span className="rounded-full border border-outline-variant/30 bg-surface-lowest px-2.5 py-1 text-[11px] text-foreground/45">
                          未标注
                        </span>
                      )}
                    </div>
                  </div>

                  {pdfAnchors.length > 0 ? (
                    <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                      <div className="flex items-center gap-2 font-label text-[10px] tracking-[0.14em] text-foreground/35">
                        <ExternalLink size={12} className="text-primary/55" />
                        PDF 证据定位
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2" aria-label="PDF 证据定位">
                        {pdfAnchors.map((anchor, index) => (
                          <a
                            key={`${anchor.materialId}-${anchor.page ?? 'p'}-${anchor.chunkId ?? index}`}
                            href={pdfAnchorHref(anchor)}
                            className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-primary/25 bg-primary/8 px-2.5 py-1 text-[11px] font-medium text-primary/80 transition-colors hover:border-primary/45 hover:bg-primary/12"
                          >
                            <ExternalLink size={11} className="shrink-0" aria-hidden />
                            <span className="truncate">
                              {anchor.page ? `打开原文 p.${anchor.page}` : '打开原文'}
                            </span>
                          </a>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="mt-4 rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-5 text-sm text-foreground/45">
                  当前页面没有结构化属性，或者后端返回的是空对象。
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/75 p-4">
              <div className="flex items-center gap-2 text-foreground">
                <TextQuote size={16} className="text-primary/65" />
                <h3 className="font-headline text-sm font-semibold">正文内容</h3>
              </div>

              {page.body.trim() ? (
                <div className="mt-4 max-h-[34rem] overflow-auto rounded-xl border border-outline-variant/30 bg-surface-high/70 px-4 py-4">
                  <div className="prose prose-sm max-w-none break-words text-foreground prose-headings:font-headline prose-headings:text-foreground prose-p:leading-7 prose-a:text-primary prose-strong:text-foreground prose-code:before:content-none prose-code:after:content-none prose-pre:border prose-pre:border-outline-variant/30 prose-pre:bg-surface-lowest prose-blockquote:border-primary/35 prose-blockquote:text-foreground/65 dark:prose-invert">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        a: ({ href, children }) => (
                          <a
                            href={href}
                            className="font-medium text-primary underline-offset-2 hover:underline"
                          >
                            {children}
                          </a>
                        ),
                        code: ({ children }) => (
                          <code className="rounded bg-surface-lowest px-1 py-0.5 font-mono text-[0.9em] text-foreground/80">
                            {children}
                          </code>
                        ),
                      }}
                    >
                      {renderableWikiMarkdown(page.body, page.path)}
                    </ReactMarkdown>
                  </div>
                </div>
              ) : (
                <div className="mt-4 rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-5 text-sm text-foreground/45">
                  当前页面正文为空，仍然保留路径与页面属性供人工判断。
                </div>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="mt-5 rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 px-5 py-10 text-center text-sm text-foreground/50">
          页面预览尚未加载。
        </div>
      )}
    </section>
  );
}
