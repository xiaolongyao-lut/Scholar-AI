import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  BookMarked,
  BookOpen,
  Calendar,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileText,
  Inbox,
  Link2,
  ListChecks,
  Loader2,
  Pencil,
  Plus,
  Quote,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Square,
  User,
  X,
} from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import axios from 'axios';
import DOMPurify from 'dompurify';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { PageHeader } from '@/components/common/PageHeader';
import { EmptyState } from '@/components/common/EmptyState';
import { useWriting } from '@/contexts/WritingContext';
import { sanitizeRuntimeVisibleText } from '@/components/writing/writingRuntimeDisplay';
import { getWritingBackendService } from '@/services/writingBackend';
import { locateChunk, type ChunkLocator } from '@/services/resourcesApi';
import { getActiveCslStyle } from '@/services/cslStylesApi';
import { auditCitationSources, parseBibTeXReferences, renderCitations, type CitationAuditSummary } from '@/lib/citationEngine';
import { citationSourceToCslJson } from '@/lib/materialToCslJson';
import { encodePdfBboxParam, normalizePdfUrlBbox } from '@/lib/pdfAnchor';
import type {
  CitationSourceResource,
  CitationSourceUpdate,
  CitationSuggestionResource,
  WritingMaterialResource,
} from '@/types/resources';

interface Reference {
  id: string;
  materialId: string;
  sourceId: string;
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
  cslType?: string;
  cited: boolean;
  citationCount: number;
  tags: string[];
  chunkCount: number;
  firstChunkId?: string | null;
  firstPage?: number | null;
  firstBbox?: number[] | null;
  sourceKind: 'metadata' | 'material' | 'manual';
}

export interface FirstChunkLocator {
  chunkId: string | null;
  page: number | null;
  bbox: number[] | null;
}

const MAX_SOURCE_LOCATOR_UPGRADES = 48;
const CITATION_BIBLIOGRAPHY_ALLOWED_TAGS = [
  'a',
  'b',
  'br',
  'div',
  'em',
  'i',
  'p',
  'span',
  'strong',
  'sub',
  'sup',
] as const;
const CITATION_BIBLIOGRAPHY_ALLOWED_ATTR = ['class', 'href', 'title'] as const;

export function sanitizeCitationBibliographyHtml(html: unknown): string {
  if (typeof html !== 'string' || !html.trim()) return '';
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [...CITATION_BIBLIOGRAPHY_ALLOWED_TAGS],
    ALLOWED_ATTR: [...CITATION_BIBLIOGRAPHY_ALLOWED_ATTR],
    ALLOW_DATA_ATTR: false,
    SAFE_FOR_TEMPLATES: true,
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'form', 'input', 'button'],
    FORBID_ATTR: ['style'],
  });
}

function isRequestCanceled(error: unknown): boolean {
  return (error instanceof DOMException && error.name === 'AbortError')
    || (axios.isAxiosError(error) && error.code === 'ERR_CANCELED');
}

const WRITING_SOURCE_INTERNAL_ID_PATTERN = /^(?:mat|material|chunk|source|paper|doc|cite)[-_][a-z0-9][a-z0-9_-]*$/i;

export function formatWritingSourceVisibleText(value: unknown, fallback: string): string {
  const visible = sanitizeRuntimeVisibleText(value, fallback);
  if (visible === fallback) return visible;
  return WRITING_SOURCE_INTERNAL_ID_PATTERN.test(visible.trim()) ? fallback : visible;
}

export function formatWritingSourceTitle(value: unknown, fallback = '未命名文献'): string {
  return formatWritingSourceVisibleText(value, fallback);
}

export function formatWritingSourceTag(value: unknown): string | null {
  const label = formatWritingSourceVisibleText(value, '');
  return label || null;
}

export function formatWritingSourceError(error: unknown): string {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  return formatWritingSourceVisibleText(message, '来源加载失败，请稍后重试。');
}

function formatMaterialTypeLabel(value: unknown): string {
  const raw = typeof value === 'string' ? value.trim().toLowerCase() : '';
  const labels: Record<string, string> = {
    paper: '论文',
    pdf: 'PDF 文献',
    book: '书籍',
    article: '文章',
    report: '报告',
    dataset: '数据集',
  };
  return labels[raw] ?? formatWritingSourceVisibleText(value, '文献资料');
}

function formatOptionalSourceText(value: unknown): string | null {
  const visible = formatWritingSourceVisibleText(value, '');
  return visible || null;
}

export function SourcesCitations() {
  const { t } = useI18n();
  const { activeProjectId, activeSectionId } = useWriting();
  const [search, setSearch] = useState('');
  const [showCitedOnly, setShowCitedOnly] = useState(false);
  const [contextText, setContextText] = useState('');
  const [suggestions, setSuggestions] = useState<CitationSuggestionResource[]>([]);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [suggestAttempted, setSuggestAttempted] = useState(false);
  const [suggestStopped, setSuggestStopped] = useState(false);
  const [suggestDraftId, setSuggestDraftId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const suggestAbortControllerRef = useRef<AbortController | null>(null);
  const suggestStopRequestedRef = useRef(false);

  const [refs, setRefs] = useState<Reference[]>([]);
  const [manualRefs, setManualRefs] = useState<Reference[]>([]);
  const [sources, setSources] = useState<CitationSourceResource[]>([]);
  const [activeStyleXml, setActiveStyleXml] = useState('');
  const [activeStyleTitle, setActiveStyleTitle] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const style = await getActiveCslStyle();
        if (!cancelled) {
          setActiveStyleXml(typeof style.csl_xml === 'string' ? style.csl_xml : '');
          setActiveStyleTitle(typeof style.title === 'string' ? style.title : '');
        }
      } catch {
        if (!cancelled) {
          setActiveStyleXml('');
          setActiveStyleTitle('');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadProjectRefs = useCallback(async () => {
    if (!activeProjectId) {
      setRefs(manualRefs);
      setSources([]);
      setSuggestDraftId(null);
      setSuggestions([]);
      setSuggestAttempted(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const svc = getWritingBackendService();
      const [citationSources, materials, chunks, drafts] = await Promise.all([
        svc.listCitationSources(activeProjectId).catch(() => [] as CitationSourceResource[]),
        svc.listMaterials(activeProjectId),
        svc.listProjectChunks(activeProjectId).catch(() => ({ project_id: activeProjectId, total_chunks: 0, chunks: [] })),
        svc.listDrafts(activeProjectId, activeSectionId || undefined).catch(() => []),
      ]);
      setSuggestDraftId(drafts[0]?.draft_id ?? null);
      setSources(citationSources);
      const chunkCounts = new Map<string, number>();
      const firstChunkByMaterial = new Map<string, FirstChunkLocator>();
      for (const chunk of chunks.chunks) {
        const materialId = typeof chunk.material_id === 'string' ? chunk.material_id : '';
        if (!materialId) continue;
        chunkCounts.set(materialId, (chunkCounts.get(materialId) ?? 0) + 1);
        if (!firstChunkByMaterial.has(materialId)) {
          firstChunkByMaterial.set(materialId, {
            chunkId: typeof chunk.chunk_id === 'string' && chunk.chunk_id.trim() ? chunk.chunk_id : null,
            page: coercePositivePage(chunk.page),
            bbox: coerceNormalizedBbox(chunk.bbox),
          });
        }
      }
      const enrichedFirstChunkByMaterial = await enrichFirstChunkLocators(activeProjectId, firstChunkByMaterial);
      const sourceByMaterialId = new Map(citationSources.map((source) => [source.material_id, source] as const));
      const materialRefs = materials.map((material) => {
        const source = sourceByMaterialId.get(material.material_id);
        const firstChunk = enrichedFirstChunkByMaterial.get(material.material_id);
        return source
          ? citationSourceToReference(source, chunkCounts.get(material.material_id) ?? 0, firstChunk)
          : materialToReference(material, chunkCounts.get(material.material_id) ?? 0, firstChunk);
      });
      const extraSourceRefs = citationSources
        .filter((source) => !materials.some((material) => material.material_id === source.material_id))
        .map((source) => citationSourceToReference(
          source,
          chunkCounts.get(source.material_id) ?? 0,
          enrichedFirstChunkByMaterial.get(source.material_id),
        ));
      setRefs([...materialRefs, ...extraSourceRefs, ...manualRefs]);
    } catch (err) {
      setError(formatWritingSourceError(err));
      setRefs(manualRefs);
      setSuggestDraftId(null);
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, activeSectionId, manualRefs]);

  useEffect(() => {
    void loadProjectRefs();
  }, [loadProjectRefs]);

  useEffect(() => {
    return () => {
      suggestAbortControllerRef.current?.abort();
    };
  }, []);

  const stats = useMemo(() => ({
    total: refs.length,
    cited: refs.filter((ref) => ref.citationCount > 0 || ref.cited).length,
    withMetadata: refs.filter((ref) => ref.sourceKind === 'metadata').length,
    missingMetadata: refs.filter((ref) => ref.sourceKind !== 'metadata').length,
  }), [refs]);
  const audit = useMemo(() => auditCitationSources(refs), [refs]);

  const filtered = useMemo(() => refs.filter((ref) => {
    if (showCitedOnly && !(ref.citationCount > 0 || ref.cited)) return false;
    if (!search.trim()) return true;
    const haystack = [
      ref.title,
      ref.authors.join(' '),
      ref.publication,
      ref.doi,
      ref.materialId,
      ref.tags.join(' '),
    ].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(search.trim().toLowerCase());
  }), [refs, search, showCitedOnly]);

  const handleImport = () => {
    fileInputRef.current?.click();
  };

  const handleFileImport = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files) return;
    void importReferenceFiles(Array.from(files), t('sources.author_placeholder'))
      .then((nextRefs) => {
        if (nextRefs.length > 0) {
          setManualRefs((prev) => [...nextRefs, ...prev]);
        }
      })
      .catch(() => undefined);
    event.target.value = '';
  };

  const handleSuggest = async () => {
    if (!activeProjectId || !suggestDraftId || !contextText.trim()) return;
    const abortController = new AbortController();
    suggestAbortControllerRef.current = abortController;
    suggestStopRequestedRef.current = false;
    setSuggestLoading(true);
    setError(null);
    setSuggestAttempted(true);
    setSuggestStopped(false);
    try {
      const result = await getWritingBackendService().suggestCitations({
        project_id: activeProjectId,
        draft_id: suggestDraftId,
        context: contextText.trim(),
        max_suggestions: 5,
      }, { signal: abortController.signal });
      setSuggestions(result);
    } catch (err) {
      if (isRequestCanceled(err)) {
        if (suggestStopRequestedRef.current) {
          setSuggestStopped(true);
          setSuggestAttempted(false);
          setSuggestions([]);
        }
        return;
      }
      setError(formatWritingSourceError(err));
      setSuggestions([]);
    } finally {
      if (suggestAbortControllerRef.current === abortController) {
        suggestAbortControllerRef.current = null;
        setSuggestLoading(false);
      }
    }
  };

  const stopSuggest = () => {
    const abortController = suggestAbortControllerRef.current;
    if (!abortController) return;
    suggestStopRequestedRef.current = true;
    abortController.abort();
    setSuggestLoading(false);
    setSuggestStopped(true);
    setSuggestAttempted(false);
    setSuggestions([]);
  };

  const handleCopyCitationToken = async (ref: Reference) => {
    try {
      await navigator.clipboard.writeText(`[^cite:${ref.materialId}]`);
      setCopiedId(ref.id);
      window.setTimeout(() => setCopiedId(null), 1800);
    } catch {
      setCopiedId(null);
    }
  };

  const handleCopySuggestionToken = async (suggestion: CitationSuggestionResource) => {
    try {
      await navigator.clipboard.writeText(`[^cite:${suggestion.material_id}]`);
      setCopiedId(`suggestion-${suggestion.material_id}`);
      window.setTimeout(() => setCopiedId(null), 1800);
    } catch {
      setCopiedId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<BookMarked size={18} />}
          title={t('writing.sources.title')}
          subtitle={t('writing.sources.subtitle', { total: stats.total, cited: stats.cited })}
          className="mb-0"
          actions={
            <>
              <button
                type="button"
                onClick={() => void loadProjectRefs()}
                disabled={loading}
                className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-60"
              >
                {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                刷新
              </button>
              <button
                type="button"
                onClick={handleImport}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                <Plus size={13} />
                {t('writing.sources.import')}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".bib,.ris,.enw,.pdf"
                multiple
                className="hidden"
                aria-label={t('writing.sources.import')}
                title={t('writing.sources.import')}
                onChange={handleFileImport}
              />
            </>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-auto px-6 py-5">
        {error ? (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
            {error}
          </div>
        ) : null}

        <section className="mb-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(340px,420px)]">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="来源" value={stats.total} icon={<FileText size={14} />} />
            <Metric label="已引用" value={stats.cited} icon={<Quote size={14} />} />
            <Metric label="有元数据" value={stats.withMetadata} icon={<CheckCircle2 size={14} />} />
            <Metric label="需处理问题" value={audit.issues.filter((issue) => issue.severity !== 'info').length} icon={<AlertTriangle size={14} />} />
          </div>
          <div className="rounded-md border border-outline-variant/60 bg-surface-lowest p-4">
            <div className="flex items-start gap-3">
              <ListChecks size={16} className="mt-0.5 shrink-0 text-primary/70" />
              <div className="space-y-1 text-xs leading-5 text-foreground/58">
                <div><span className="font-medium text-foreground/78">引用检查：</span>检查未引用条目、缺失元数据、重复 DOI/题名和近年文献占比。</div>
                <div><span className="font-medium text-foreground/78">样式格式：</span>参考文献表由当前 CSL 样式实时生成，支持 GB/T、IEEE、APA 等样式。</div>
                <div><span className="font-medium text-foreground/78">导入方式：</span>BibTeX 会先进入本页临时条目；保存到项目元数据需要在条目里补齐并保存。</div>
              </div>
            </div>
          </div>
        </section>

        <section className="mb-5 grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
          <div className="flex items-center gap-3">
            <div className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-outline-variant/50 bg-surface-lowest px-3 py-2 focus-within:border-primary/40">
              <Search size={15} className="shrink-0 text-foreground/30" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t('writing.sources.search_placeholder')}
                className="min-w-0 flex-1 bg-transparent text-sm font-label text-foreground placeholder:text-foreground/30 focus:outline-none"
              />
            </div>
            <button
              type="button"
              onClick={() => setShowCitedOnly(!showCitedOnly)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs font-label font-medium transition-all',
                showCitedOnly ? 'border-primary bg-primary/10 text-primary' : 'border-outline-variant bg-surface-high text-foreground/45 hover:text-foreground',
              )}
            >
              <Quote size={13} />
              {t('writing.sources.cited_only')}
            </button>
          </div>
          <CitationSuggestionPanel
            contextText={contextText}
            suggestions={suggestions}
            loading={suggestLoading}
            attempted={suggestAttempted}
            stopped={suggestStopped}
            disabled={!activeProjectId || !suggestDraftId || !contextText.trim()}
            draftReady={Boolean(suggestDraftId)}
            copiedSuggestionId={copiedId}
            onContextChange={setContextText}
            onSuggest={() => void handleSuggest()}
            onStopSuggest={stopSuggest}
            onCopySuggestion={(suggestion) => void handleCopySuggestionToken(suggestion)}
          />
        </section>

        {loading ? (
          <div className="flex items-center justify-center gap-2 rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-10 text-sm text-foreground/50">
            <Loader2 size={16} className="animate-spin" />
            正在加载来源
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            title={activeProjectId ? '没有匹配的来源' : '未激活项目'}
            description={activeProjectId ? '项目上传的文献会在这里显示，并同步展示引用次数、切块数量和元数据完整度。' : '先选择项目，或临时导入 Bib/RIS/PDF 作为本页来源。'}
            icon={<Inbox size={40} />}
          />
        ) : (
          <div className="space-y-3">
            <CitationAuditPanel audit={audit} />
            <AnimatePresence>
              {filtered.map((ref, index) => (
                <motion.div
                  key={ref.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: -10 }}
                  transition={{ delay: index * 0.03 }}
                  className="group rounded-md border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm transition-colors hover:border-primary/30"
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-surface-high">
                      <FileText size={16} className={ref.citationCount > 0 || ref.cited ? 'text-primary' : 'text-foreground/25'} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                        <StatusLabel refItem={ref} />
                        {ref.citationCount > 0 ? (
                          <span className="rounded bg-primary/10 px-1.5 py-0.5 font-label text-[9px] font-medium text-primary">
                            {ref.citationCount} 个引用标记
                          </span>
                        ) : null}
                      </div>
                      <h4 className="line-clamp-2 font-headline text-sm font-medium leading-snug text-foreground">{ref.title}</h4>
                      <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] font-label text-foreground/42">
                        <span className="flex items-center gap-1"><User size={10} /> {formatAuthors(ref.authors)}</span>
                        <span className="flex items-center gap-1"><Calendar size={10} /> {ref.year ?? '年份待补'}</span>
                        <span>{ref.chunkCount} 个切块</span>
                        {ref.publication ? <span className="truncate">{ref.publication}</span> : null}
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        {ref.tags.map((tag) => (
                          <span key={tag} className="rounded bg-surface-high px-1.5 py-0.5 font-label text-[9px] text-foreground/40">{tag}</span>
                        ))}
                        {ref.doi ? (
                          <span className="rounded bg-surface-high px-1.5 py-0.5 font-label text-[9px] text-foreground/40">DOI {ref.doi}</span>
                        ) : (
                          <span className="rounded border border-amber-200/70 bg-amber-50 px-1.5 py-0.5 font-label text-[9px] text-amber-700 dark:border-amber-700/40 dark:bg-amber-500/10 dark:text-amber-300">DOI 待补</span>
                        )}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {ref.sourceKind !== 'manual' ? (
                        <Link
                          to={buildWorkbenchPath(ref)}
                          title="在 PDF Reader 中打开文献"
                          aria-label={`在 PDF Reader 中打开 ${ref.title}`}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-low text-foreground/45 transition-colors hover:border-primary/35 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <BookOpen size={14} />
                        </Link>
                      ) : null}
                      {ref.sourceKind !== 'manual' ? (
                        <button
                          type="button"
                          onClick={() => setEditingId(editingId === ref.materialId ? null : ref.materialId)}
                          title="编辑文献元数据"
                          aria-label={`编辑 ${ref.title} 的文献元数据`}
                          aria-pressed={editingId === ref.materialId}
                          className={cn(
                            'inline-flex h-8 w-8 items-center justify-center rounded-md border transition-colors',
                            editingId === ref.materialId
                              ? 'border-primary/45 bg-primary/10 text-primary'
                              : 'border-outline-variant/60 bg-surface-low text-foreground/45 hover:border-primary/35 hover:text-primary',
                          )}
                        >
                          <Pencil size={14} />
                        </button>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => void handleCopyCitationToken(ref)}
                        title={copiedId === ref.id ? '已复制' : '复制引用标记'}
                        aria-label={copiedId === ref.id ? '已复制' : '复制引用标记'}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-low text-foreground/45 transition-colors hover:border-primary/35 hover:text-primary"
                      >
                        {copiedId === ref.id ? <CheckCircle2 size={14} /> : <Copy size={14} />}
                      </button>
                      {(ref.doi || ref.url) ? (
                        <a
                          href={ref.doi ? `https://doi.org/${ref.doi}` : (ref.url?.match(/^https?:\/\//i) ? ref.url : undefined)}
                          target="_blank"
                          rel="noopener noreferrer"
                          title={ref.doi ? `DOI: ${ref.doi}` : ref.url ?? ''}
                          aria-label={ref.doi ? `DOI: ${ref.doi}` : ref.url ?? ''}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-foreground/25 transition-colors hover:bg-surface-high hover:text-primary"
                        >
                          <ExternalLink size={14} />
                        </a>
                      ) : null}
                    </div>
                  </div>
                  {editingId === ref.materialId ? (
                    <SourceMetadataEditor
                      reference={ref}
                      onCancel={() => setEditingId(null)}
                      onSaved={() => {
                        setEditingId(null);
                        void loadProjectRefs();
                      }}
                    />
                  ) : null}
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}

        <CitationBibliographySection
          sources={sources}
          styleXml={activeStyleXml}
          styleTitle={activeStyleTitle}
        />
      </div>
    </div>
  );
}

async function importReferenceFiles(files: File[], authorFallback: string): Promise<Reference[]> {
  const timestamp = Date.now();
  const imported: Reference[] = [];
  for (let fileIndex = 0; fileIndex < files.length; fileIndex += 1) {
    const file = files[fileIndex];
    const lowerName = file.name.toLowerCase();
    if (lowerName.endsWith('.bib')) {
      const entries = parseBibTeXReferences(await file.text());
      entries.forEach((entry, entryIndex) => {
        const id = `manual-${timestamp}-${fileIndex}-${entryIndex}`;
        imported.push({
          id,
          materialId: id,
          sourceId: id,
          title: formatWritingSourceTitle(entry.title || entry.key, '临时条目'),
          authors: entry.authors.length > 0 ? entry.authors : [authorFallback],
          year: entry.year ?? null,
          publication: formatOptionalSourceText(entry.publication),
          doi: entry.doi ?? null,
          url: entry.url ?? null,
          publisher: entry.publisher ?? null,
          volume: entry.volume ?? null,
          issue: entry.issue ?? null,
          pages: entry.pages ?? null,
          cslType: entry.cslType,
          cited: false,
          citationCount: 0,
          tags: ['BibTeX 临时导入', entry.cslType],
          chunkCount: 0,
          sourceKind: 'manual',
        });
      });
      continue;
    }

    const id = `manual-${timestamp}-${fileIndex}`;
    imported.push({
      id,
      materialId: id,
      sourceId: id,
      title: formatWritingSourceTitle(file.name.replace(/\.[^.]+$/, ''), '临时条目'),
      authors: [authorFallback],
      year: new Date().getFullYear(),
      publication: '',
      cited: false,
      citationCount: 0,
      tags: ['临时导入'],
      chunkCount: 0,
      sourceKind: 'manual',
    });
  }
  return imported;
}

function CitationAuditPanel({ audit }: { audit: CitationAuditSummary }) {
  const blockingIssues = audit.issues.filter((issue) => issue.severity !== 'info');
  const visibleIssues = audit.issues.slice(0, 8);
  const readyRatio = audit.total > 0 ? Math.round((audit.metadataReady / audit.total) * 100) : 0;
  return (
    <section className="rounded-md border border-outline-variant/60 bg-surface-lowest p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ListChecks size={15} className="text-primary/70" />
          <h3 className="font-headline text-sm font-semibold text-foreground">引用整理检查</h3>
          <span className={cn(
            'rounded px-1.5 py-0.5 font-label text-[10px] font-medium',
            blockingIssues.length === 0 ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
          )}>
            {blockingIssues.length === 0 ? '没有阻断问题' : `${blockingIssues.length} 个需处理问题`}
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5 font-label text-[10px] text-foreground/45">
          <span className="rounded bg-surface-high px-1.5 py-0.5">元数据完整 {readyRatio}%</span>
          <span className="rounded bg-surface-high px-1.5 py-0.5">DOI {audit.withDoi}/{audit.total}</span>
          <span className="rounded bg-surface-high px-1.5 py-0.5">近年 {Math.round(audit.recentRatio * 100)}%</span>
          <span className="rounded bg-surface-high px-1.5 py-0.5">重复组 {audit.duplicateGroups}</span>
        </div>
      </div>
      {audit.total === 0 ? (
        <p className="text-xs leading-5 text-foreground/45">还没有可检查的文献来源。</p>
      ) : visibleIssues.length === 0 ? (
        <p className="text-xs leading-5 text-foreground/55">当前引用元数据、重复项和引用覆盖没有明显问题。</p>
      ) : (
        <div className="grid gap-2 lg:grid-cols-2">
          {visibleIssues.map((issue) => (
            <div
              key={issue.id}
              className={cn(
                'rounded-md border px-3 py-2',
                issue.severity === 'error'
                  ? 'border-red-200 bg-red-50/70 text-red-800 dark:border-red-700/40 dark:bg-red-500/10 dark:text-red-200'
                  : issue.severity === 'warning'
                    ? 'border-amber-200 bg-amber-50/70 text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/10 dark:text-amber-200'
                    : 'border-outline-variant/60 bg-surface-low text-foreground/58',
              )}
            >
              <div className="flex items-start gap-2">
                {issue.severity === 'error' ? <AlertTriangle size={13} className="mt-0.5 shrink-0" /> : issue.severity === 'warning' ? <AlertTriangle size={13} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={13} className="mt-0.5 shrink-0" />}
                <div className="min-w-0">
                  <div className="line-clamp-1 font-label text-[11px] font-semibold">{issue.label}</div>
                  <p className="mt-1 line-clamp-2 text-[10px] leading-4 opacity-80">{issue.description}</p>
                  <p className="mt-1 text-[10px] leading-4 opacity-70">{issue.action}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {audit.issues.length > visibleIssues.length ? (
        <p className="mt-2 font-label text-[10px] text-foreground/40">还有 {audit.issues.length - visibleIssues.length} 个较低优先级提示，优先处理上面的问题。</p>
      ) : null}
    </section>
  );
}

function CitationBibliographySection({
  sources,
  styleXml,
  styleTitle,
}: {
  sources: CitationSourceResource[];
  styleXml: string;
  styleTitle: string;
}) {
  const safeStyleXml = typeof styleXml === 'string' ? styleXml : '';
  const safeStyleTitle = typeof styleTitle === 'string' ? styleTitle : '';
  const result = useMemo(() => {
    if (!safeStyleXml.trim() || sources.length === 0) return null;
    return renderCitations(safeStyleXml, sources.map(citationSourceToCslJson));
  }, [sources, safeStyleXml]);

  return (
    <section className="mt-6 rounded-md border border-outline-variant/60 bg-surface-lowest p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <BookMarked size={15} className="text-primary/70" />
          <h3 className="font-headline text-sm font-semibold text-foreground">参考文献表</h3>
          <span className="font-label text-[10px] text-foreground/40">按当前 CSL 样式实时生成</span>
        </div>
        <div className="flex items-center gap-2 font-label text-[10px] text-foreground/45">
          <span className="rounded bg-surface-high px-1.5 py-0.5 text-foreground/60">{safeStyleTitle || '默认样式'}</span>
          <Link to="/settings?section=citation-styles" className="inline-flex items-center gap-1 transition-colors hover:text-primary">
            <Pencil size={10} /> 切换样式
          </Link>
        </div>
      </div>
      {!safeStyleXml.trim() ? (
        <p className="text-xs leading-5 text-foreground/45">样式未就绪；请在「设置 · 文献样式」中确认当前 CSL 样式。</p>
      ) : sources.length === 0 ? (
        <p className="text-xs leading-5 text-foreground/45">本项目暂无文献来源；上传或导入文献后将按当前样式生成参考文献表。</p>
      ) : result && result.bibliography.length > 0 ? (
        <div className="space-y-2 text-xs leading-relaxed text-foreground/80">
          {result.bibliography.map((entry) => (
            <div
              key={entry.id}
              className="[&_.csl-left-margin]:inline [&_.csl-right-inline]:inline [&_a]:text-primary [&_a]:underline"
              dangerouslySetInnerHTML={{ __html: sanitizeCitationBibliographyHtml(entry.html) }}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs leading-5 text-foreground/45">尚无法生成条目；为文献补全作者、年份、题名、期刊等元数据后即可按样式格式化。</p>
      )}
      {result && result.errors.length > 0 ? (
        <p className="mt-2 font-label text-[10px] text-amber-600 dark:text-amber-400">{result.errors.length} 个条目存在格式化告警（多为元数据缺失）。</p>
      ) : null}
    </section>
  );
}

const CSL_TYPE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'article-journal', label: '期刊论文' },
  { value: 'paper-conference', label: '会议论文' },
  { value: 'book', label: '专著' },
  { value: 'chapter', label: '专著章节' },
  { value: 'thesis', label: '学位论文' },
  { value: 'report', label: '报告/标准' },
  { value: 'webpage', label: '网页' },
  { value: 'dataset', label: '数据集' },
];

function SourceMetadataEditor({
  reference,
  onCancel,
  onSaved,
}: {
  reference: Reference;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [authors, setAuthors] = useState(reference.authors.join('\n'));
  const [year, setYear] = useState(reference.year ? String(reference.year) : '');
  const [publication, setPublication] = useState(reference.publication ?? '');
  const [publisher, setPublisher] = useState(reference.publisher ?? '');
  const [volume, setVolume] = useState(reference.volume ?? '');
  const [issue, setIssue] = useState(reference.issue ?? '');
  const [pages, setPages] = useState(reference.pages ?? '');
  const [doi, setDoi] = useState(reference.doi ?? '');
  const [url, setUrl] = useState(reference.url ?? '');
  const [cslType, setCslType] = useState(reference.cslType ?? 'article-journal');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    const trimmedYear = year.trim();
    const yearNum = trimmedYear ? Number(trimmedYear) : null;
    const update: CitationSourceUpdate = {
      authors: authors.split('\n').map((a) => a.trim()).filter(Boolean),
      year: yearNum !== null && Number.isFinite(yearNum) ? yearNum : null,
      publication: publication.trim() || null,
      publisher: publisher.trim() || null,
      volume: volume.trim() || null,
      issue: issue.trim() || null,
      pages: pages.trim() || null,
      doi: doi.trim() || null,
      url: url.trim() || null,
      csl_type: cslType,
    };
    try {
      await getWritingBackendService().updateCitationSource(reference.sourceId, update);
      onSaved();
    } catch (err) {
      setSaveError(formatWritingSourceError(err));
    } finally {
      setSaving(false);
    }
  };

  const inputClass = 'w-full rounded-md border border-outline-variant/50 bg-surface-low px-2.5 py-1.5 text-xs text-foreground outline-none placeholder:text-foreground/30 focus:border-primary/40';

  return (
    <div className="mt-3 rounded-md border border-primary/25 bg-surface-low p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-headline text-[11px] font-semibold text-foreground/80">文献元数据</span>
        <span className="font-label text-[10px] text-foreground/40">用于参考文献表与导出</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="sm:col-span-2 flex flex-col gap-1">
          <span className="font-label text-[10px] text-foreground/50">作者（每行一位，或用「姓, 名」）</span>
          <textarea
            value={authors}
            onChange={(e) => setAuthors(e.target.value)}
            rows={2}
            placeholder={'张三\n李四'}
            className={cn(inputClass, 'resize-y')}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-label text-[10px] text-foreground/50">类型</span>
          <select value={cslType} onChange={(e) => setCslType(e.target.value)} className={inputClass}>
            {CSL_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-label text-[10px] text-foreground/50">年份</span>
          <input value={year} onChange={(e) => setYear(e.target.value)} inputMode="numeric" placeholder="2024" className={inputClass} />
        </label>
        <label className="sm:col-span-2 flex flex-col gap-1">
          <span className="font-label text-[10px] text-foreground/50">期刊 / 出处（container-title）</span>
          <input value={publication} onChange={(e) => setPublication(e.target.value)} placeholder="如：机械工程学报" className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-label text-[10px] text-foreground/50">出版者</span>
          <input value={publisher} onChange={(e) => setPublisher(e.target.value)} placeholder="如：科学出版社" className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-label text-[10px] text-foreground/50">卷 / 期 / 页</span>
          <div className="grid grid-cols-3 gap-1">
            <input value={volume} onChange={(e) => setVolume(e.target.value)} placeholder="卷" className={inputClass} />
            <input value={issue} onChange={(e) => setIssue(e.target.value)} placeholder="期" className={inputClass} />
            <input value={pages} onChange={(e) => setPages(e.target.value)} placeholder="页" className={inputClass} />
          </div>
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-label text-[10px] text-foreground/50">DOI</span>
          <input value={doi} onChange={(e) => setDoi(e.target.value)} placeholder="10.xxxx/xxxx" className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-label text-[10px] text-foreground/50">URL</span>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" className={inputClass} />
        </label>
      </div>
      {saveError ? <p className="mt-2 text-[10px] text-red-600 dark:text-red-300">{saveError}</p> : null}
      <div className="mt-3 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-[11px] font-medium text-foreground/60 transition-colors hover:text-foreground disabled:opacity-50"
        >
          <X size={12} /> 取消
        </button>
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving}
          className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 font-label text-[11px] font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          保存元数据
        </button>
      </div>
    </div>
  );
}

function CitationSuggestionPanel({
  contextText,
  suggestions,
  loading,
  attempted,
  stopped,
  disabled,
  draftReady,
  copiedSuggestionId,
  onContextChange,
  onSuggest,
  onStopSuggest,
  onCopySuggestion,
}: {
  contextText: string;
  suggestions: CitationSuggestionResource[];
  loading: boolean;
  attempted: boolean;
  stopped: boolean;
  disabled: boolean;
  draftReady: boolean;
  copiedSuggestionId: string | null;
  onContextChange: (value: string) => void;
  onSuggest: () => void;
  onStopSuggest: () => void;
  onCopySuggestion: (suggestion: CitationSuggestionResource) => void;
}) {
  return (
    <div className="rounded-md border border-outline-variant/60 bg-surface-lowest p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-primary/70" />
          <span className="font-headline text-xs font-semibold text-foreground">智能推荐引用</span>
        </div>
        <button
          type="button"
          onClick={loading ? onStopSuggest : onSuggest}
          disabled={!loading && disabled}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 font-label text-[11px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45',
            loading
              ? 'border-red-200 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300'
              : 'border-outline-variant/60 bg-surface-low text-foreground/55 hover:border-primary/35 hover:text-primary',
          )}
        >
          {loading ? <Square size={12} /> : <Sparkles size={12} />}
          {loading ? '停止' : '推荐'}
        </button>
      </div>
      <textarea
        value={contextText}
        onChange={(event) => onContextChange(event.target.value)}
        rows={2}
        placeholder="粘贴一段草稿上下文，用已有文献切块推荐可引用来源"
        className="min-h-[64px] w-full resize-y rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2 text-xs leading-5 text-foreground outline-none placeholder:text-foreground/30 focus:border-primary/40"
      />
      {!draftReady ? (
        <p className="mt-2 text-[10px] leading-4 text-foreground/42">
          当前项目还没有可用于推荐的草稿；先在手稿页面创建或保存草稿后再请求推荐。
        </p>
      ) : null}
      {stopped ? (
        <p className="mt-2 rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2 text-[10px] leading-4 text-foreground/42">
          已停止推荐引用。
        </p>
      ) : null}
      {suggestions.length > 0 ? (
        <div className="mt-3 space-y-2">
          {suggestions.map((suggestion) => {
            const safeTitle = formatWritingSourceTitle(suggestion.title, '推荐来源');
            const safeExcerpt = formatWritingSourceVisibleText(suggestion.excerpt, '证据摘要已隐藏，避免显示内部路径或系统字段。');
            const safeRationale = formatWritingSourceVisibleText(suggestion.rationale, '已根据当前草稿上下文匹配到该来源。');
            return (
              <div key={`${suggestion.material_id}-${suggestion.title}`} className="rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-headline text-[11px] font-semibold text-foreground">{safeTitle}</span>
                  <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 font-label text-[9px] text-primary">
                    {Math.round(suggestion.relevance_score * 100)}%
                  </span>
                </div>
                <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-foreground/50">{safeExcerpt}</p>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate font-label text-[10px] text-foreground/38">{safeRationale}</span>
                  <button
                    type="button"
                    onClick={() => onCopySuggestion(suggestion)}
                    className="inline-flex shrink-0 items-center gap-1 rounded border border-outline-variant/50 px-2 py-1 font-label text-[10px] text-foreground/50 transition-colors hover:border-primary/35 hover:text-primary"
                  >
                    {copiedSuggestionId === `suggestion-${suggestion.material_id}` ? <CheckCircle2 size={11} /> : <Copy size={11} />}
                    {copiedSuggestionId === `suggestion-${suggestion.material_id}` ? '已复制' : '引用'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : attempted && !loading ? (
        <p className="mt-2 rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2 text-[10px] leading-4 text-foreground/42">
          当前上下文没有匹配到可推荐来源；可换一段包含关键词、机制或实验对象的草稿上下文再试。
        </p>
      ) : null}
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <div className="rounded-md border border-outline-variant/60 bg-surface-lowest p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-label text-[11px] text-foreground/45">{label}</span>
        <span className="text-primary/60">{icon}</span>
      </div>
      <div className="mt-2 font-headline text-xl font-semibold text-foreground">{value}</div>
    </div>
  );
}

function StatusLabel({ refItem }: { refItem: Reference }) {
  if (refItem.sourceKind === 'metadata') {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 font-label text-[9px] font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
        <CheckCircle2 size={10} />
        元数据
      </span>
    );
  }
  if (refItem.sourceKind === 'manual') {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-surface-high px-1.5 py-0.5 font-label text-[9px] font-medium text-foreground/45">
        <Link2 size={10} />
        临时条目
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded border border-amber-200/70 bg-amber-50 px-1.5 py-0.5 font-label text-[9px] font-medium text-amber-700 dark:border-amber-700/40 dark:bg-amber-500/10 dark:text-amber-300">
      <AlertTriangle size={10} />
      待补元数据
    </span>
  );
}

export function mergeFirstChunkLocator(
  materialId: string,
  firstChunk: FirstChunkLocator,
  locator: ChunkLocator | null,
): FirstChunkLocator {
  if (locator?.material_id !== materialId || locator.chunk_id !== firstChunk.chunkId) {
    return firstChunk;
  }
  return {
    chunkId: firstChunk.chunkId,
    page: firstChunk.page ?? coercePositivePage(locator.page),
    bbox: firstChunk.bbox ?? coerceNormalizedBbox(locator.bbox),
  };
}

async function enrichFirstChunkLocators(
  projectId: string,
  firstChunkByMaterial: Map<string, FirstChunkLocator>,
): Promise<Map<string, FirstChunkLocator>> {
  const normalizedProjectId = projectId.trim();
  if (!normalizedProjectId || firstChunkByMaterial.size === 0) {
    return firstChunkByMaterial;
  }
  const next = new Map(firstChunkByMaterial);
  const pending = Array.from(next.entries())
    .filter(([, firstChunk]) => Boolean(firstChunk.chunkId) && (!firstChunk.page || !firstChunk.bbox))
    .slice(0, MAX_SOURCE_LOCATOR_UPGRADES);

  const settled = await Promise.allSettled(
    pending.map(async ([materialId, firstChunk]) => {
      if (!firstChunk.chunkId) return null;
      const locator = await locateChunk(firstChunk.chunkId, normalizedProjectId);
      return { materialId, firstChunk, locator };
    }),
  );

  for (const result of settled) {
    if (result.status !== 'fulfilled' || result.value === null) continue;
    const { materialId, firstChunk, locator } = result.value;
    next.set(materialId, mergeFirstChunkLocator(materialId, firstChunk, locator));
  }
  return next;
}

function citationSourceToReference(
  source: CitationSourceResource,
  chunkCount: number,
  firstChunk?: FirstChunkLocator,
): Reference {
  return {
    id: source.source_id,
    materialId: source.material_id,
    sourceId: source.source_id,
    title: formatWritingSourceTitle(source.title, '未命名文献'),
    authors: source.authors ?? [],
    year: source.year ?? null,
    publication: formatOptionalSourceText(source.publication),
    doi: source.doi ?? null,
    url: source.url ?? null,
    publisher: source.publisher ?? null,
    volume: source.volume ?? null,
    issue: source.issue ?? null,
    pages: source.pages ?? null,
    cslType: source.csl_type ?? 'article-journal',
    cited: source.citation_count > 0,
    citationCount: source.citation_count,
    tags: ['元数据来源'],
    chunkCount,
    firstChunkId: firstChunk?.chunkId ?? null,
    firstPage: firstChunk?.page ?? null,
    firstBbox: firstChunk?.bbox ?? null,
    sourceKind: 'metadata',
  };
}

function materialToReference(
  material: WritingMaterialResource,
  chunkCount: number,
  firstChunk?: FirstChunkLocator,
): Reference {
  const title = formatWritingSourceTitle(material.title || material.title_en, '未命名文献');
  return {
    id: material.material_id,
    materialId: material.material_id,
    sourceId: material.material_id,
    title,
    authors: material.type ? [formatMaterialTypeLabel(material.type)] : [],
    year: safeYear(material.created_at),
    publication: formatOptionalSourceText(material.summary || material.summary_en),
    cited: false,
    citationCount: 0,
    tags: [
      formatMaterialTypeLabel(material.type),
      ...(material.focus_points ?? []).slice(0, 2),
    ].map(formatWritingSourceTag).filter((tag): tag is string => Boolean(tag)),
    chunkCount,
    firstChunkId: firstChunk?.chunkId ?? null,
    firstPage: firstChunk?.page ?? null,
    firstBbox: firstChunk?.bbox ?? null,
    sourceKind: 'material',
  };
}

function formatAuthors(authors: string[]): string {
  const cleaned = authors.map((author) => formatWritingSourceVisibleText(author, '')).filter(Boolean);
  if (cleaned.length === 0) return '作者待补';
  if (cleaned.length <= 3) return cleaned.join('，');
  return `${cleaned.slice(0, 3).join('，')} 等`;
}

function safeYear(value: string): number {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return new Date().getFullYear();
  return date.getFullYear();
}

function coercePositivePage(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 1) {
    return Math.floor(value);
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed >= 1) {
      return Math.floor(parsed);
    }
  }
  return null;
}

function coerceNormalizedBbox(value: unknown): number[] | null {
  const bbox = normalizePdfUrlBbox(value);
  return bbox ? [...bbox] : null;
}

function buildWorkbenchPath(ref: Reference): string {
  const params = new URLSearchParams();
  if (ref.firstPage && ref.firstPage > 0) {
    params.set('page', String(ref.firstPage));
  }
  if (ref.firstChunkId) {
    params.set('chunk', ref.firstChunkId);
  }
  const bbox = coerceNormalizedBbox(ref.firstBbox);
  if (bbox) {
    const bboxParam = encodePdfBboxParam(bbox);
    if (bboxParam) params.set('bbox', bboxParam);
  }
  const query = params.toString();
  return `/workbench/paper/${encodeURIComponent(ref.materialId)}${query ? `?${query}` : ''}`;
}
