import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, BookOpen, CheckCircle2, Hash } from 'lucide-react';
import { WorkbenchShell } from '@/components/workbench/WorkbenchShell';
import {
  ResearchWorkbenchInspector,
  ResearchWorkbenchEvidenceDrawer,
} from '@/components/workbench/ResearchWorkbenchInspector';
import { PdfReaderShell } from '@/components/PdfViewer/PdfReaderShell';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import { useWriting } from '@/contexts/WritingContext';
import {
  getAnnotations,
  type AnnotationData,
  type Highlight,
} from '@/services/annotationApi';
import { getWritingBackendService } from '@/services/writingBackend';
import type { WritingMaterialResource } from '@/types/resources';
import type { ChatMessageData } from '@/components/chat/Message';
import type { EvidenceRefLike } from '@/components/evidence/EvidencePill';

/**
 * Phase 2 / Slice 3 — ResearchWorkbench surface (Paper object only).
 *
 * Route: `/workbench/paper/:materialId`
 * v1 invariants (R7 / R5 / L9 / L10):
 *   - exactly one active object canvas, no tab strip
 *   - object header carries title + status chip only, no second row
 *   - PDF canvas keeps a light background (Zotero rule, index.css)
 *   - inherited_context is packaged on the client but not sent to a
 *     backend that does not accept the field yet (Q1=a strict)
 */
export function ResearchWorkbench() {
  return <ResearchWorkbenchInner />;
}

function ResearchWorkbenchInner() {
  const { materialId = '' } = useParams<{ materialId: string }>();
  const [searchParams] = useSearchParams();
  const initialPageRaw = searchParams.get('page');
  const initialPage = initialPageRaw ? Math.max(1, Number(initialPageRaw)) : undefined;
  const navigate = useNavigate();
  const { activeProjectId } = useWriting();

  const [material, setMaterial] = useState<WritingMaterialResource | null>(null);
  const [annotation, setAnnotation] = useState<AnnotationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const pdfUrl = useMemo(
    () => (materialId ? `${getApiBaseUrl()}/resources/document/${materialId}/file` : ''),
    [materialId],
  );

  // Load material + annotations. Failure mode: friendly Chinese error,
  // never raw API path or error.toString().
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

  const handleAddHighlight = useCallback(
    async (h: Highlight) => {
      try {
        const { addHighlight } = await import('@/services/annotationApi');
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
        const { replaceHighlights } = await import('@/services/annotationApi');
        const updated = await replaceHighlights(materialId, next);
        setAnnotation(updated);
      } catch {
        setLoadError('删除高亮失败，请稍后重试。');
      }
    },
    [annotation, materialId],
  );

  const handleAnalyzeText = useCallback(
    (text: string, page: number) => {
      // K1 → K2 bridge: selection text becomes a Smart Read user message.
      setMessages((prev) => [
        ...prev,
        {
          id: `u-${Date.now()}`,
          role: 'user',
          content: text,
          timestamp: new Date().toISOString(),
        },
        {
          id: `a-${Date.now()}-pending`,
          role: 'assistant',
          content: '正在结合本页内容生成回答…',
          status: 'streaming',
          timestamp: new Date().toISOString(),
        },
      ]);
      // For Slice 3 we do NOT call backend here — Smart Read backend
      // wiring is preserved unchanged via the existing /dialog route.
      // The bridge is a UX scaffold proving K1→K2→K3 flow.
      void page;
    },
    [],
  );

  const handleSend = useCallback((text: string) => {
    setMessages((prev) => [
      ...prev,
      { id: `u-${Date.now()}`, role: 'user', content: text, timestamp: new Date().toISOString() },
    ]);
  }, []);

  const drawerEvidence: EvidenceRefLike[] = useMemo(() => {
    const fromMessages = messages.flatMap((m) => m.evidence ?? []);
    return fromMessages;
  }, [messages]);

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
      drawerTitle={`证据抽屉（${drawerEvidence.length}）`}
      header={
        <>
          <button
            type="button"
            onClick={() => navigate('/library')}
            className="flex shrink-0 items-center gap-1 rounded p-1 text-foreground/60 hover:bg-surface-high hover:text-foreground"
            title="返回文献库"
            aria-label="返回文献库"
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
        </>
      }
      canvas={
        <ErrorBoundary fallbackTitle="PDF 阅读器暂时无法显示">
          <PdfReaderShell
            url={pdfUrl}
            materialId={materialId}
            initialPage={initialPage}
            highlights={annotation?.highlights ?? []}
            notes={annotation?.notes ?? []}
            lastPage={annotation?.last_page ?? null}
            onAnalyzeText={handleAnalyzeText}
            onAddHighlight={(h) => void handleAddHighlight(h)}
            onDeleteHighlight={(i) => void handleDeleteHighlight(i)}
            onAnnotationUpdate={setAnnotation}
          />
        </ErrorBoundary>
      }
      inspector={
        <ErrorBoundary fallbackTitle="检视面板暂时无法显示">
          <ResearchWorkbenchInspector
            projectId={activeProjectId ?? null}
            messages={messages}
            onSend={handleSend}
            selectedEvidenceId={selectedEvidenceId}
            onSelectEvidence={(ev) => setSelectedEvidenceId(ev.evidence_id ?? ev.chunk_id ?? null)}
          />
        </ErrorBoundary>
      }
      drawer={
        <ErrorBoundary fallbackTitle="证据抽屉暂时无法显示">
          <ResearchWorkbenchEvidenceDrawer
            evidence={drawerEvidence}
            projectId={activeProjectId ?? null}
            selectedEvidenceId={selectedEvidenceId}
            onSelectEvidence={(ev) => setSelectedEvidenceId(ev.evidence_id ?? ev.chunk_id ?? null)}
          />
        </ErrorBoundary>
      }
    />
  );
}

export default ResearchWorkbench;
