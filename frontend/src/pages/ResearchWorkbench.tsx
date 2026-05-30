import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, BookOpen, CheckCircle2, Hash, Loader2, MessageCircle } from 'lucide-react';
import { WorkbenchShell } from '@/components/workbench/WorkbenchShell';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { PdfTabStrip } from '@/components/PdfViewer/PdfTabStrip';
import { usePdfTabs } from '@/contexts/PdfTabsContext';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import { useWriting } from '@/contexts/WritingContext';
import {
  addHighlight,
  getAnnotations,
  replaceHighlights,
  type AnnotationData,
  type Highlight,
} from '@/services/annotationApi';
import { getWritingBackendService } from '@/services/writingBackend';
import type { WritingMaterialResource } from '@/types/resources';

const PdfReaderShell = lazy(() =>
  import('@/components/PdfViewer/PdfReaderShell').then((m) => ({
    default: m.PdfReaderShell,
  })),
);

const PdfReaderFallback = () => (
  <div className="flex h-full w-full items-center justify-center text-foreground/40">
    <Loader2 className="h-6 w-6 animate-spin" aria-label="Loading PDF reader" />
  </div>
);

function parseBboxSearchParam(value: string | null): number[] | null {
  if (!value) return null;
  const parts = value.split(',').map((part) => Number(part.trim()));
  if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) return null;
  return parts;
}

function bboxToHighlightRect(bbox: number[] | null): { x: number; y: number; w: number; h: number } | null {
  if (!bbox || bbox.length !== 4) return null;
  const [a, b, c, d] = bbox;
  if (![a, b, c, d].every((value) => Number.isFinite(value))) return null;

  if (a >= 0 && b >= 0 && c > 0 && d > 0 && a <= 1 && b <= 1 && a + c <= 1.0001 && b + d <= 1.0001) {
    return { x: a, y: b, w: c, h: d };
  }
  if (a >= 0 && b >= 0 && c > a && d > b && c <= 1 && d <= 1) {
    return { x: a, y: b, w: c - a, h: d - b };
  }
  return null;
}

/**
 * ResearchWorkbench — full-screen PDF reader fallback for a single paper.
 *
 * Route: `/workbench/paper/:materialId`
 * This surface only embeds the reader (highlights, deep-link page/chunk/bbox,
 * annotations). Question answering, multi-agent discussion, and the evidence
 * graph are unified in the SmartRead workbench (`/dialog`); this page links
 * Q&A back there instead of hosting a duplicate chat.
 */
export function ResearchWorkbench() {
  return <ResearchWorkbenchInner />;
}

function ResearchWorkbenchInner() {
  const { materialId = '' } = useParams<{ materialId: string }>();
  const [searchParams] = useSearchParams();
  const initialPageRaw = searchParams.get('page');
  const initialPage = initialPageRaw ? Math.max(1, Number(initialPageRaw)) : undefined;
  const deepLinkKey = `${initialPageRaw ?? ''}:${searchParams.get('chunk') ?? ''}:${searchParams.get('bbox') ?? ''}`;
  const targetBbox = useMemo(
    () => bboxToHighlightRect(parseBboxSearchParam(searchParams.get('bbox'))),
    [searchParams],
  );
  const navigate = useNavigate();
  const { activeProjectId } = useWriting();
  const {
    openTab,
    activeId,
    setTitle,
    getView,
    updateView,
    getCachedBytes,
    setCachedBytes,
  } = usePdfTabs();

  const [material, setMaterial] = useState<WritingMaterialResource | null>(null);
  const [annotation, setAnnotation] = useState<AnnotationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Bump this when the active tab changes so PdfReaderShell sees a new bytes
  // prop reference and re-mounts cleanly between PDFs.
  const [bytesNonce, setBytesNonce] = useState(0);
  const pdfUrl = useMemo(
    () => (materialId ? `${getApiBaseUrl()}/resources/document/${materialId}/file` : ''),
    [materialId],
  );

  // URL → tab store: any nav into /workbench/paper/:id opens (or re-activates)
  // the tab.
  useEffect(() => {
    if (!materialId) return;
    openTab({ materialId, title: materialId }, { activate: true });
  }, [materialId, openTab]);

  useEffect(() => {
    setBytesNonce((n) => n + 1);
  }, [activeId]);

  const cachedBytes = useMemo(
    () => (materialId ? getCachedBytes(materialId) : undefined),
    // bytesNonce is the trigger; getCachedBytes itself is stable.
    [materialId, bytesNonce, getCachedBytes],
  );

  const handleBytesLoaded = useCallback((bytes: Uint8Array) => {
    if (materialId) setCachedBytes(materialId, bytes);
  }, [materialId, setCachedBytes]);

  const persistedView = materialId ? getView(materialId) : undefined;
  const handleScaleChange = useCallback((scale: number) => {
    if (materialId) updateView(materialId, { scale });
  }, [materialId, updateView]);
  const handleTabPageChange = useCallback((page: number) => {
    if (materialId) updateView(materialId, { page });
  }, [materialId, updateView]);
  const deepLinkedHighlights = useMemo<Highlight[]>(() => {
    if (!initialPage || !targetBbox) return [];
    return [{
      page: initialPage,
      text: '当前跳转证据位置',
      color: '#60A5FA',
      rects: [targetBbox],
    }];
  }, [initialPage, targetBbox]);
  const readerHighlights = useMemo(
    () => [...deepLinkedHighlights, ...(annotation?.highlights ?? [])],
    [deepLinkedHighlights, annotation?.highlights],
  );

  const handleTabStripActivate = useCallback((nextId: string) => {
    if (nextId === materialId) return;
    navigate(`/workbench/paper/${encodeURIComponent(nextId)}`);
  }, [navigate, materialId]);

  const handleTabStripEmpty = useCallback(() => {
    navigate('/knowledge');
  }, [navigate]);

  // Load material + annotations. Failure mode: friendly Chinese error,
  // never raw endpoint path or error.toString().
  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!materialId) return;
      setLoading(true);
      setLoadError(null);
      try {
        const ann = await getAnnotations(materialId);
        if (cancelled) return;
        setAnnotation(ann);

        const svc = getWritingBackendService();
        const projects = await svc.listProjects();
        if (cancelled) return;
        const projectIds = [
          ...(activeProjectId ? [activeProjectId] : []),
          ...projects
            .map((project) => project.project_id)
            .filter((projectId) => projectId !== activeProjectId),
        ];
        for (const projectId of projectIds) {
          const all = await svc.listMaterials(projectId);
          if (cancelled) return;
          const hit = all.find((m) => m.material_id === materialId) ?? null;
          if (hit) {
            setMaterial(hit);
            return;
          }
        }
        setMaterial(null);
      } catch {
        if (cancelled) return;
        setLoadError('文献加载失败，请稍后重试。');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [materialId, activeProjectId]);

  // Replace the strip label with the real title once we know it.
  useEffect(() => {
    if (materialId && material?.title) {
      setTitle(materialId, material.title);
    }
  }, [materialId, material?.title, setTitle]);

  const handleAddHighlight = useCallback(
    async (h: Highlight) => {
      try {
        const updated = await addHighlight(materialId, h);
        setAnnotation(updated);
      } catch {
        setLoadError('保存高亮失败，请稍后重试。');
      }
    },
    [materialId],
  );

  const handleDeleteHighlight = useCallback(
    async (index: number) => {
      if (!annotation) return;
      const next = (annotation.highlights ?? []).slice();
      next.splice(index, 1);
      try {
        const updated = await replaceHighlights(materialId, next);
        setAnnotation(updated);
      } catch {
        setLoadError('删除高亮失败，请稍后重试。');
      }
    },
    [annotation, materialId],
  );

  const openInSmartRead = useCallback(() => {
    const params = new URLSearchParams();
    params.set('scope', 'paper');
    params.set('material_id', materialId);
    if (activeProjectId) params.set('project_id', activeProjectId);
    if (material?.title) params.set('material_title', material.title);
    navigate(`/dialog?${params.toString()}`);
  }, [navigate, materialId, activeProjectId, material?.title]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-background">
        <p className="text-sm text-foreground/55">正在载入文献…</p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-background px-6 text-center">
        <p className="text-sm text-foreground/70">{loadError}</p>
        <button
          type="button"
          onClick={() => navigate('/knowledge')}
          className="rounded-md border border-outline-variant px-3 py-1.5 text-xs text-foreground/70 hover:bg-surface-high hover:text-foreground"
        >
          返回文献库
        </button>
      </div>
    );
  }

  const title = material?.title || 'PDF 文献';

  return (
    <WorkbenchShell
      drawerTitle="阅读说明"
      header={
        <>
          <button
            type="button"
            onClick={() => navigate('/knowledge')}
            className="flex shrink-0 items-center gap-1 rounded p-1 text-foreground/60 hover:bg-surface-high hover:text-foreground"
            title="返回知识库"
            aria-label="返回知识库"
          >
            <ArrowLeft size={14} />
          </button>
          <BookOpen size={14} className="shrink-0 text-primary/60" aria-hidden />
          <span className="truncate text-sm font-medium text-foreground">{title}</span>
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-emerald-300/60 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
            <CheckCircle2 size={10} aria-hidden /> 已索引
          </span>
          {initialPage && (
            <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-outline-variant bg-surface-low px-1.5 py-0.5 text-[10px] font-medium text-foreground/65">
              <Hash size={10} aria-hidden /> 第 {initialPage} 页
            </span>
          )}
          <button
            type="button"
            onClick={openInSmartRead}
            className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary/15"
            title="在智能研读里围绕本文献提问与讨论"
          >
            <MessageCircle size={12} aria-hidden /> 智能研读
          </button>
        </>
      }
      canvas={
        <div className="flex h-full min-h-0 flex-col">
          <PdfTabStrip onActivate={handleTabStripActivate} onEmpty={handleTabStripEmpty} />
          <div className="min-h-0 flex-1">
            <ErrorBoundary fallbackTitle="PDF 阅读器暂时无法显示">
              <Suspense fallback={<PdfReaderFallback />}>
                <PdfReaderShell
                  key={`${materialId}:${deepLinkKey}`}
                  url={pdfUrl}
                  materialId={materialId}
                  initialPage={initialPage ?? persistedView?.page}
                  bytes={cachedBytes}
                  onBytesLoaded={handleBytesLoaded}
                  scale={persistedView?.scale}
                  onScaleChange={handleScaleChange}
                  highlights={readerHighlights}
                  notes={annotation?.notes ?? []}
                  lastPage={annotation?.last_page ?? null}
                  onAddHighlight={(h) => void handleAddHighlight(h)}
                  onDeleteHighlight={(i) => void handleDeleteHighlight(i)}
                  onAnnotationUpdate={setAnnotation}
                  onPageChange={handleTabPageChange}
                />
              </Suspense>
            </ErrorBoundary>
          </div>
        </div>
      }
      inspector={
        <div className="flex h-full min-h-0 flex-col gap-3 p-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">在智能研读里继续</h3>
            <p className="mt-1 text-xs leading-relaxed text-foreground/60">
              本页是全屏阅读器。围绕本文献的提问、多智能体讨论和证据图谱已统一到智能研读工作台。
            </p>
          </div>
          <button
            type="button"
            onClick={openInSmartRead}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <MessageCircle size={13} aria-hidden /> 去智能研读提问
          </button>
          <button
            type="button"
            onClick={() => navigate('/knowledge')}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-3 py-2 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
          >
            <ArrowLeft size={13} aria-hidden /> 返回知识库
          </button>
        </div>
      }
      drawer={
        <p className="text-xs leading-relaxed text-foreground/55">
          证据、笔记与图谱已统一到智能研读工作台；在上方「智能研读」入口围绕本文献提问即可看到对应证据定位。
        </p>
      }
    />
  );
}

export default ResearchWorkbench;
