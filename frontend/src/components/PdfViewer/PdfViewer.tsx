import { useState, useCallback, useEffect } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Sparkles, Highlighter, PanelRight, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';

import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

// Bundle the pdfjs worker locally so offline use and self-contained installs
// work without reaching unpkg. Vite handles `new URL(..., import.meta.url)`
// by emitting the worker as a hashed asset in production and serving it
// directly in dev.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface PdfViewerProps {
  url: string;
  materialId: string;
  initialPage?: number;
  onAnalyzeText?: (text: string, page: number) => void;
  onAddHighlight?: (highlight: { page: number; text: string; color: string }) => void;
  onDeleteHighlight?: (index: number) => void;
  highlights?: Array<{ page: number; text: string; color: string }>;
  /** Track C F3: when true, the built-in highlight side panel + its
   *  toolbar toggle are not rendered. Used by PdfReaderShell (L2)
   *  which provides its own right-side sidebar. */
  hideHighlightPanel?: boolean;
  /** Track C F6: notify parent every time the page changes. Lets
   *  ReadProgressTracker debounce a /last-page write without forcing
   *  PdfViewer to know about read-progress storage. */
  onPageChange?: (page: number) => void;
  /** Track C F4: selection-anchored note creation. When set, the
   *  floating toolbar exposes a "添加笔记" button. The callback receives
   *  the selected text + current page; the parent (PdfReaderShell)
   *  opens its own popover for body / tags. */
  onAddNote?: (anchorText: string, page: number) => void;
  /** Track C F5: surface the PDF.js outline once the document
   *  resolves. PdfReaderShell consumes this for its OutlineTab. Called
   *  exactly once per loaded document; null when getOutline() returns
   *  null or throws. */
  onOutlineLoaded?: (outline: PdfOutlineEntry[] | null) => void;
  className?: string;
}

export interface PdfOutlineEntry {
  title: string;
  page?: number;
  children?: PdfOutlineEntry[];
}

export function PdfViewer({
  url,
  materialId,
  initialPage,
  onAnalyzeText,
  onAddHighlight,
  onDeleteHighlight,
  highlights = [],
  hideHighlightPanel = false,
  onPageChange,
  onAddNote,
  onOutlineLoaded,
  className,
}: PdfViewerProps) {
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(initialPage ?? 1);
  const [scale, setScale] = useState(1.2);
  const [selectedText, setSelectedText] = useState('');
  const [showAIBtn, setShowAIBtn] = useState(false);
  const [btnPos, setBtnPos] = useState({ x: 0, y: 0 });
  const [showPanel, setShowPanel] = useState(false);

  // When the parent passes a new initialPage (e.g. evidence deep-link to
  // a different page in the same PDF), jump to it. Clamped after we know
  // numPages so an out-of-range target falls back to the last page.
  useEffect(() => {
    if (initialPage === undefined) return;
    const target = numPages > 0 ? Math.min(Math.max(1, initialPage), numPages) : Math.max(1, initialPage);
    setPageNumber(target);
  }, [initialPage, numPages]);

  // Track C F6: notify parent on every confirmed page change so the
  // shell can debounce read-progress writes.
  useEffect(() => {
    if (onPageChange) onPageChange(pageNumber);
  }, [pageNumber, onPageChange]);

  const onDocumentLoadSuccess = useCallback(async (pdf: PdfDocumentLike) => {
    setNumPages(pdf.numPages);
    if (!onOutlineLoaded) return;
    if (typeof pdf.getOutline !== 'function') {
      onOutlineLoaded(null);
      return;
    }
    try {
      const raw = await pdf.getOutline();
      const resolved = await resolvePdfOutline(pdf, raw);
      onOutlineLoaded(resolved);
    } catch {
      onOutlineLoaded(null);
    }
  }, [onOutlineLoaded]);

  const handleMouseUp = useCallback(() => {
    const sel = window.getSelection();
    const text = sel?.toString().trim() || '';
    if (text.length > 2) {
      setSelectedText(text);
      const range = sel!.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      setBtnPos({ x: rect.right, y: rect.top });
      setShowAIBtn(true);
    } else {
      setShowAIBtn(false);
      setSelectedText('');
    }
  }, []);

  const handleAnalyze = useCallback(() => {
    if (selectedText && onAnalyzeText) {
      onAnalyzeText(selectedText, pageNumber);
    }
    setShowAIBtn(false);
    window.getSelection()?.removeAllRanges();
  }, [selectedText, pageNumber, onAnalyzeText]);

  const goToPrev = () => setPageNumber(p => Math.max(1, p - 1));
  const goToNext = () => setPageNumber(p => Math.min(numPages, p + 1));

  return (
    <div className={cn('pdf-canvas flex flex-col h-full bg-gray-100', className)}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-outline-variant/60 bg-surface-low">
        <div className="flex items-center gap-2">
          <button onClick={goToPrev} disabled={pageNumber <= 1} className="p-1 rounded hover:bg-surface-high disabled:opacity-30">
            <ChevronLeft size={16} />
          </button>
          <span className="text-xs font-label text-foreground/60">{pageNumber} / {numPages || '—'}</span>
          <button onClick={goToNext} disabled={pageNumber >= numPages} className="p-1 rounded hover:bg-surface-high disabled:opacity-30">
            <ChevronRight size={16} />
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setScale(s => Math.max(0.5, s - 0.2))} className="p-1 rounded hover:bg-surface-high" title="缩小">
            <ZoomOut size={14} />
          </button>
          <span className="text-[10px] font-label text-foreground/50 w-10 text-center">{Math.round(scale * 100)}%</span>
          <button onClick={() => setScale(s => Math.min(3, s + 0.2))} className="p-1 rounded hover:bg-surface-high" title="放大">
            <ZoomIn size={14} />
          </button>
          {!hideHighlightPanel && (
            <button
              onClick={() => setShowPanel(v => !v)}
              className={cn(
                'ml-2 p-1 rounded hover:bg-surface-high transition-colors',
                showPanel && 'bg-amber-100 text-amber-800',
              )}
              title={`标注 (${highlights.length})`}
            >
              <PanelRight size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* PDF pages */}
        <div className="flex-1 overflow-auto flex flex-col items-center py-4 gap-4" onMouseUp={handleMouseUp}>
          <Document
            file={url}
            onLoadSuccess={onDocumentLoadSuccess}
            loading={<div className="text-sm text-foreground/40 py-8">加载 PDF 中...</div>}
            error={<div className="text-sm text-red-500 py-8">PDF 加载失败</div>}
          >
            <Page pageNumber={pageNumber} scale={scale} />
          </Document>
        </div>

        {/* Annotation side panel */}
        {!hideHighlightPanel && showPanel && (
          <div className="w-72 border-l border-outline-variant/60 bg-surface-low flex flex-col">
            <div className="px-3 py-2 border-b border-outline-variant/60 flex items-center justify-between">
              <span className="text-xs font-label text-foreground/70">
                标注 {highlights.length > 0 && <span className="text-foreground/50">({highlights.length})</span>}
              </span>
              <button
                onClick={() => setShowPanel(false)}
                className="text-[10px] text-foreground/50 hover:text-foreground/80"
              >
                收起
              </button>
            </div>
            <div className="flex-1 overflow-auto p-2 space-y-1.5">
              {highlights.length === 0 ? (
                <div className="text-[11px] text-foreground/40 py-4 text-center">
                  选中正文 → 标记，开始添加高亮
                </div>
              ) : (
                highlights.map((h, i) => (
                  <div
                    key={`${h.page}-${i}`}
                    className="group rounded border border-outline-variant/40 bg-amber-50/50 p-2 hover:bg-amber-50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-1 mb-1">
                      <button
                        onClick={() => setPageNumber(h.page)}
                        className="text-[10px] font-label text-blue-700 hover:underline"
                        title="跳到该页"
                      >
                        第 {h.page} 页
                      </button>
                      {onDeleteHighlight && (
                        <button
                          onClick={() => onDeleteHighlight(i)}
                          className="opacity-0 group-hover:opacity-100 text-foreground/40 hover:text-red-600 transition-opacity"
                          title="删除"
                        >
                          <Trash2 size={11} />
                        </button>
                      )}
                    </div>
                    <div className="text-[11px] text-foreground/80 leading-snug line-clamp-3">{h.text}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>

      {/* Floating AI analysis button — appears on text selection */}
      {showAIBtn && selectedText && (
        <div
          className="fixed z-50 flex gap-1"
          style={{ left: btnPos.x + 8, top: btnPos.y - 32 }}
        >
          <button
            onClick={handleAnalyze}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-primary text-primary-foreground shadow-lg text-xs font-label hover:bg-primary/90 transition-all"
          >
            <Sparkles size={12} /> AI 分析选段
          </button>
          <button
            onClick={() => {
              navigator.clipboard.writeText(selectedText);
              setShowAIBtn(false);
            }}
            className="inline-flex items-center gap-1 px-2 py-1.5 rounded-md bg-surface-high border border-outline-variant/60 shadow text-xs font-label hover:bg-surface-container transition-all"
            title="复制选中文本"
          >
            <Highlighter size={12} /> 复制
          </button>
          {onAddHighlight && (
            <button
              onClick={() => {
                onAddHighlight({ page: pageNumber, text: selectedText, color: '#FFEB3B' });
                setShowAIBtn(false);
                window.getSelection()?.removeAllRanges();
              }}
              className="inline-flex items-center gap-1 px-2 py-1.5 rounded-md bg-amber-100 border border-amber-300 shadow text-xs font-label text-amber-800 hover:bg-amber-200 transition-all"
              title="高亮标记选中文本"
            >
              <Highlighter size={12} /> 标记
            </button>
          )}
          {onAddNote && (
            <button
              onClick={() => {
                onAddNote(selectedText, pageNumber);
                setShowAIBtn(false);
                window.getSelection()?.removeAllRanges();
              }}
              className="inline-flex items-center gap-1 px-2 py-1.5 rounded-md bg-blue-50 border border-blue-200 shadow text-xs font-label text-blue-800 hover:bg-blue-100 transition-all"
              title="为选中文本添加笔记"
            >
              <Highlighter size={12} /> 添加笔记
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Track C F5: PDF.js outline → flat-tree resolver.
// ---------------------------------------------------------------------------

interface PdfRef { num: number; gen: number }

interface RawOutlineItem {
  title?: string;
  dest?: string | unknown[] | null;
  items?: RawOutlineItem[];
}

interface PdfDocumentLike {
  numPages: number;
  getOutline?: () => Promise<RawOutlineItem[] | null | undefined>;
  getDestination?: (name: string) => Promise<unknown[] | null>;
  getPageIndex?: (ref: PdfRef) => Promise<number>;
}

async function resolveDestPage(pdf: PdfDocumentLike, dest: string | unknown[] | null | undefined): Promise<number | undefined> {
  if (dest == null) return undefined;
  let resolved: unknown[] | null = null;
  try {
    if (typeof dest === 'string') {
      if (typeof pdf.getDestination === 'function') {
        resolved = await pdf.getDestination(dest);
      }
    } else if (Array.isArray(dest)) {
      resolved = dest;
    }
  } catch {
    return undefined;
  }
  if (!resolved || resolved.length === 0) return undefined;
  const ref = resolved[0] as PdfRef | undefined;
  if (!ref || typeof ref.num !== 'number' || typeof ref.gen !== 'number') return undefined;
  if (typeof pdf.getPageIndex !== 'function') return undefined;
  try {
    const idx = await pdf.getPageIndex(ref);
    if (typeof idx !== 'number' || idx < 0) return undefined;
    return idx + 1; // 1-indexed page number
  } catch {
    return undefined;
  }
}

async function resolvePdfOutline(pdf: PdfDocumentLike, raw: RawOutlineItem[] | null | undefined): Promise<PdfOutlineEntry[] | null> {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const out: PdfOutlineEntry[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const title = typeof item.title === 'string' && item.title.trim().length > 0
      ? item.title.trim()
      : '(untitled)';
    const page = await resolveDestPage(pdf, item.dest);
    const children = await resolvePdfOutline(pdf, item.items ?? null);
    out.push({
      title,
      page,
      children: children ?? undefined,
    });
  }
  return out;
}
