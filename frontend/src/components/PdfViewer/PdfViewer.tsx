import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { ZoomIn, ZoomOut, Sparkles, Highlighter, PanelRight, Trash2 } from 'lucide-react';
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
  /** Multi-tab: when supplied, skip the internal fetch and render these
   *  bytes directly. The LRU cache lives in PdfTabsContext, so the
   *  parent passes a cache hit here and only falls back to URL fetch
   *  when the cache misses. */
  bytes?: Uint8Array;
  /** Multi-tab: notify the parent after a successful fetch so the shell
   *  can park the bytes in the LRU cache for fast tab switches. Fired
   *  exactly once per fetched document. */
  onBytesLoaded?: (bytes: Uint8Array) => void;
  /** Multi-tab: external zoom state. When provided, the toolbar buttons
   *  call onScaleChange instead of mutating local state — lets the
   *  parent persist scale per tab. */
  scale?: number;
  onScaleChange?: (scale: number) => void;
  onAnalyzeText?: (text: string, page: number) => void;
  onAddHighlight?: (highlight: { page: number; text: string; color: string; rects?: Array<{ x: number; y: number; w: number; h: number }> }) => void;
  onDeleteHighlight?: (index: number) => void;
  highlights?: Array<{ page: number; text: string; color: string; rects?: Array<{ x: number; y: number; w: number; h: number }> }>;
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
  bytes,
  onBytesLoaded,
  scale: controlledScale,
  onScaleChange,
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
  const [internalScale, setInternalScale] = useState(controlledScale ?? 1.2);
  const scale = controlledScale ?? internalScale;
  const setScale = useCallback((updater: number | ((s: number) => number)) => {
    const next = typeof updater === 'function' ? (updater as (s: number) => number)(scale) : updater;
    if (onScaleChange) onScaleChange(next);
    else setInternalScale(next);
  }, [scale, onScaleChange]);
  const [selectedText, setSelectedText] = useState('');
  const [showAIBtn, setShowAIBtn] = useState(false);
  const [btnPos, setBtnPos] = useState({ x: 0, y: 0 });
  const [showPanel, setShowPanel] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  // 0.1.8.1: fetch the PDF bytes ourselves and feed them to <Document>
  // instead of letting react-pdf / pdf.js fetch the URL. pdf.js's internal
  // fetch path was misreading CORS preflight responses ("Unexpected server
  // response (204) while retrieving PDF") even when the actual GET returns
  // 200. Owning the fetch also means we see the real HTTP status and JSON
  // error body when the backend says the file isn't there.
  const [pdfData, setPdfData] = useState<Uint8Array | null>(null);

  // When the parent passes a new initialPage we scroll-into-view via the
  // goToPage effect below (defined after pageRefsRef is ready). This
  // earlier set-state path is gone because the continuous-scroll layout
  // takes its current page from the IntersectionObserver, not from a
  // single rendered <Page>.

  // Track C F6: notify parent on every confirmed page change so the
  // shell can debounce read-progress writes.
  useEffect(() => {
    if (onPageChange) onPageChange(pageNumber);
  }, [pageNumber, onPageChange]);

  const onDocumentLoadSuccess = useCallback(async (pdf: PdfDocumentLike) => {
    setLoadError(null);
    setNumPages(pdf.numPages);
    // Stash the doc so internal-link clicks can resolve named dests.
    pdfDocRef.current = pdf;
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

  // react-pdf swallows fetch failures into a generic "load failed" UI;
  // we need the real status/message so users can act ("文件不存在" vs
  // "无原始文件路径记录" vs network) and so devs can grep the browser
  // console.
  const handleLoadError = useCallback((err: Error, status: number | null, detail: string) => {
    if (typeof console !== 'undefined' && typeof console.error === 'function') {
      console.error('[PdfViewer] document load failed', {
        materialId, url, status, detail, errorName: err?.name, errorMessage: err?.message,
      });
    }
    const prefix = status ? `PDF 加载失败（HTTP ${status}）` : 'PDF 加载失败';
    setLoadError(`${prefix}：${detail}`);
  }, [url, materialId]);

  // Own the bytes fetch so pdf.js doesn't (see comment on pdfData state).
  useEffect(() => {
    // Multi-tab fast path: parent's LRU cache already has the bytes.
    if (bytes) {
      setLoadError(null);
      setPdfData(bytes);
      return;
    }
    if (!url) return;
    let cancelled = false;
    setLoadError(null);
    setPdfData(null);
    (async () => {
      try {
        // 0.1.8.1: fetch a base64-encoded JSON envelope instead of the raw
        // binary stream. System-level download managers (FlashGet / 网际快车,
        // IDM, 迅雷, etc.) hook the browser network layer and steal any
        // binary-looking response, returning 204 to the page. JSON looks
        // like an API call to them and gets through untouched.
        const fetchUrl = url.replace(/\/file(\?|$)/, '/file_b64$1');
        const resp = await fetch(fetchUrl, {
          method: 'GET',
          cache: 'no-store',
          headers: { Accept: 'application/json' },
        });
        if (typeof console !== 'undefined') {
          console.info('[PdfViewer] fetch resp', {
            url: fetchUrl,
            status: resp.status,
            ok: resp.ok,
            contentLength: resp.headers.get('content-length'),
            contentType: resp.headers.get('content-type'),
          });
        }
        if (!resp.ok) {
          let detail = `HTTP ${resp.status}`;
          try {
            const body = await resp.clone().json();
            const msg = body?.error?.message || body?.detail;
            if (typeof msg === 'string' && msg.length > 0) detail = msg;
          } catch {
            try {
              const text = await resp.text();
              if (text) detail = text.slice(0, 200);
            } catch { /* ignore */ }
          }
          if (!cancelled) handleLoadError(new Error(detail), resp.status, detail);
          return;
        }
        const payload = await resp.json() as { data?: string; size?: number };
        const b64 = payload?.data;
        if (typeof b64 !== 'string' || b64.length === 0) {
          const detail = '响应体为空（base64 字段缺失）。';
          if (!cancelled) handleLoadError(new Error(detail), resp.status, detail);
          return;
        }
        // atob → Uint8Array. For ~30 MB this stays under 1 s in modern
        // browsers; if it ever becomes a bottleneck, swap in a streaming
        // base64 decoder.
        const bin = atob(b64);
        const decoded = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) decoded[i] = bin.charCodeAt(i);
        if (typeof console !== 'undefined') {
          console.info('[PdfViewer] decoded bytes', decoded.byteLength);
        }
        if (!cancelled) {
          setPdfData(decoded);
          if (onBytesLoaded) onBytesLoaded(decoded);
        }
      } catch (err) {
        if (cancelled) return;
        const e = err instanceof Error ? err : new Error(String(err));
        handleLoadError(e, null, e.message || '网络请求失败');
      }
    })();
    return () => { cancelled = true; };
  }, [url, loadAttempt, handleLoadError, bytes, onBytesLoaded]);

  const handleRetry = useCallback(() => {
    setLoadError(null);
    setLoadAttempt((n) => n + 1);
  }, []);

  // pdf.js's Worker transfers (not copies) the ArrayBuffer we hand it,
  // detaching the master Uint8Array on the main thread. React StrictMode
  // double-invokes effects in dev, and any subsequent re-render of
  // <Document> would try to reuse the now-detached buffer ("ArrayBuffer at
  // index 0 is already detached"). Slicing here produces a fresh copy each
  // time pdfData changes, so the master copy stays intact and any second
  // mount gets its own buffer.
  const documentFile = useMemo(
    () => (pdfData ? { data: pdfData.slice() } : null),
    [pdfData],
  );

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

  const goToPage = useCallback((target: number) => {
    if (!numPages || numPages <= 0) return;
    const clamped = Math.max(1, Math.min(numPages, Math.floor(target)));
    const el = pageRefsRef.current[clamped - 1];
    if (el) {
      el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
    setPageNumber(clamped);
  }, [numPages]);

  // Wraps each rendered <Page> so we can read its bounding rect for the
  // highlight overlay and so IntersectionObserver can track which page
  // is currently visible. Also drives goToPage's scroll-into-view.
  const pageWrapperRef = useRef<HTMLDivElement>(null);
  const pageRefsRef = useRef<Array<HTMLDivElement | null>>([]);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  // Tracks which page has been programmatically scrolled to so the
  // IntersectionObserver doesn't fight the imperative scroll.
  const pendingScrollPageRef = useRef<number | null>(null);
  // Pdf document instance — needed to resolve internal-link annotations
  // (the "[14]" citation references that ship as Link annotations in
  // every modern journal PDF).
  const pdfDocRef = useRef<PdfDocumentLike | null>(null);
  // Flash pulse for the destination page after a link jump so the user
  // notices the scroll actually moved.
  const [flashPage, setFlashPage] = useState<number | null>(null);

  // When the external initialPage / pendingPage changes, scroll to it.
  // Wait for the pages to mount (numPages > 0) before issuing the scroll.
  useEffect(() => {
    if (initialPage === undefined || numPages <= 0) return;
    pendingScrollPageRef.current = initialPage;
    goToPage(initialPage);
    // Release the lock after the scroll settles.
    const t = setTimeout(() => { pendingScrollPageRef.current = null; }, 600);
    return () => clearTimeout(t);
  }, [initialPage, numPages, goToPage]);

  // IntersectionObserver: pick the page whose center is closest to the
  // viewport center. This is the Zotero-style "page-the-user-is-reading"
  // signal — robust under fast scroll and zoom.
  useEffect(() => {
    if (!numPages || !scrollContainerRef.current) return;
    const root = scrollContainerRef.current;
    const observer = new IntersectionObserver(
      (entries) => {
        // Aggregate visibility ratios; pick the page with the largest
        // visible area. This handles edge cases where two pages straddle
        // the viewport boundary equally — the larger half wins.
        let best: { page: number; ratio: number } | null = null;
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const pageAttr = (entry.target as HTMLElement).dataset.pageNumber;
          if (!pageAttr) continue;
          const page = Number(pageAttr);
          if (!Number.isFinite(page) || page < 1) continue;
          if (!best || entry.intersectionRatio > best.ratio) {
            best = { page, ratio: entry.intersectionRatio };
          }
        }
        if (best) {
          // Don't override a programmatic scroll target mid-flight; the
          // observer fires on every layout shift during smooth scroll.
          if (pendingScrollPageRef.current && pendingScrollPageRef.current !== best.page) return;
          setPageNumber((prev) => (prev === best!.page ? prev : best!.page));
        }
      },
      {
        root,
        // Several thresholds so the observer fires reliably as a page
        // crosses the viewport mid-line.
        threshold: [0.1, 0.25, 0.5, 0.75, 1.0],
      },
    );
    for (const el of pageRefsRef.current) {
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [numPages]);

  // Internal-link interception: catch clicks on Link annotations the
  // PDF embeds for in-document jumps (citations `[14]`, "see Fig. 3",
  // outline entries, etc.) and route them through goToPage so the
  // continuous-scroll view glides to the target page instead of
  // opening a new tab or breaking the scroll position.
  //
  // pdf.js renders each Link annotation as
  //   <section class="linkAnnotation"><a href="..."></a></section>
  // Internal links carry either `data-internal-link="true"` + a
  // `data-dest` JSON, or an href starting with `#`. External links
  // (full http URLs) fall through to default browser behaviour.
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const resolveDestToPage = async (dest: unknown): Promise<number | null> => {
      const pdf = pdfDocRef.current;
      if (!pdf) return null;
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
        return null;
      }
      if (!resolved || resolved.length === 0) return null;
      const ref = resolved[0] as PdfRef | undefined;
      if (!ref || typeof ref.num !== 'number' || typeof ref.gen !== 'number') return null;
      if (typeof pdf.getPageIndex !== 'function') return null;
      try {
        const idx = await pdf.getPageIndex(ref);
        if (typeof idx !== 'number' || idx < 0) return null;
        return idx + 1;
      } catch {
        return null;
      }
    };

    const onClick = (e: MouseEvent) => {
      const target = e.target as Element | null;
      if (!target) return;
      const anchor = target.closest('.linkAnnotation a') as HTMLAnchorElement | null;
      if (!anchor) return;

      // Pdf.js marks internal links explicitly. Older versions just put
      // an href starting with "#" — handle both.
      const isInternal =
        anchor.dataset.internalLink === 'true' ||
        anchor.getAttribute('href')?.startsWith('#') === true ||
        Boolean(anchor.dataset.dest);
      if (!isInternal) return; // external http(s) → keep default (new tab)

      e.preventDefault();
      e.stopPropagation();

      // Try the cheapest paths first: href="#page=N" (some viewers
      // serialise dests this way) or data-dest JSON.
      const href = anchor.getAttribute('href') || '';
      const pageMatch = href.match(/[#&]page=(\d+)/i);
      if (pageMatch) {
        const n = Number(pageMatch[1]);
        if (Number.isFinite(n) && n >= 1) {
          goToPage(n);
          setFlashPage(n);
          return;
        }
      }

      const rawDest =
        anchor.dataset.dest ||
        (href.startsWith('#') ? decodeURIComponent(href.slice(1)) : '');
      if (!rawDest) return;

      let parsed: unknown = rawDest;
      // data-dest is JSON-encoded in current pdf.js; fall back to the
      // raw string (a "named destination") if JSON parse fails.
      try { parsed = JSON.parse(rawDest); } catch { /* keep as string */ }

      void resolveDestToPage(parsed).then((page) => {
        if (page) {
          goToPage(page);
          setFlashPage(page);
        }
      });
    };

    container.addEventListener('click', onClick);
    return () => container.removeEventListener('click', onClick);
  }, [goToPage]);

  // Auto-clear the flash highlight after a brief moment.
  useEffect(() => {
    if (flashPage === null) return;
    const t = setTimeout(() => setFlashPage(null), 900);
    return () => clearTimeout(t);
  }, [flashPage]);

  // Compute normalized rects (relative to the page box that contains
  // the selection) for the current selection, plus the page number that
  // selection lives on. Continuous-scroll layout: the selection can land
  // on any of the rendered pages, so we walk up from the anchor node to
  // find its enclosing .react-pdf__Page rather than assuming page 1.
  const computeSelectionRectsAndPage = useCallback((): {
    rects: Array<{ x: number; y: number; w: number; h: number }>;
    page: number;
  } => {
    const sel = window.getSelection();
    const empty = { rects: [], page: pageNumber };
    if (!sel || sel.rangeCount === 0) return empty;
    const range = sel.getRangeAt(0);
    const anchorNode = range.startContainer as Node | null;
    const anchorEl = (anchorNode && anchorNode.nodeType === 1
      ? (anchorNode as Element)
      : anchorNode?.parentElement) ?? null;
    const pageEl = anchorEl?.closest('.react-pdf__Page') as HTMLElement | null;
    if (!pageEl) return empty;
    const pageAttr = pageEl.dataset.pageNumber;
    const page = pageAttr ? Number(pageAttr) : pageNumber;
    const pageRect = pageEl.getBoundingClientRect();
    if (pageRect.width <= 0 || pageRect.height <= 0) return { rects: [], page };
    const raw = Array.from(range.getClientRects()).filter(r => r.width > 0 && r.height > 0);
    const rects = raw.map(r => ({
      x: Math.max(0, Math.min(1, (r.left - pageRect.left) / pageRect.width)),
      y: Math.max(0, Math.min(1, (r.top - pageRect.top) / pageRect.height)),
      w: Math.max(0, Math.min(1, r.width / pageRect.width)),
      h: Math.max(0, Math.min(1, r.height / pageRect.height)),
    }));
    return { rects, page };
  }, [pageNumber]);

  // Group highlights by page once so each page's overlay only sees its
  // own rects — O(N) instead of O(N*pages).
  const highlightsByPage = useMemo(() => {
    const m = new Map<number, typeof highlights>();
    for (const h of highlights ?? []) {
      const list = m.get(h.page);
      if (list) list.push(h);
      else m.set(h.page, [h]);
    }
    return m;
  }, [highlights]);

  return (
    <div className={cn('pdf-canvas flex flex-col h-full bg-gray-100 dark:bg-neutral-900', className)}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-outline-variant/60 bg-surface-low">
        <div className="flex items-center gap-1.5 text-xs font-label text-foreground/80">
          <PageJumpInput
            page={pageNumber}
            numPages={numPages}
            onJump={goToPage}
          />
          <span className="text-foreground/55">/</span>
          <span className="text-foreground/80">{numPages || '—'}</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setScale(s => Math.max(0.5, s - 0.2))}
            className="p-1 rounded text-foreground/80 hover:bg-surface-high hover:text-foreground"
            title="缩小"
          >
            <ZoomOut size={14} />
          </button>
          <span className="text-[10px] font-label text-foreground/75 w-10 text-center">{Math.round(scale * 100)}%</span>
          <button
            onClick={() => setScale(s => Math.min(3, s + 0.2))}
            className="p-1 rounded text-foreground/80 hover:bg-surface-high hover:text-foreground"
            title="放大"
          >
            <ZoomIn size={14} />
          </button>
          {!hideHighlightPanel && (
            <button
              onClick={() => setShowPanel(v => !v)}
              className={cn(
                'ml-2 p-1 rounded text-foreground/80 hover:bg-surface-high hover:text-foreground transition-colors',
                showPanel && 'bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200',
              )}
              title={`标注 (${highlights.length})`}
            >
              <PanelRight size={14} />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* PDF pages — continuous vertical scroll (Zotero-style). */}
        <div
          ref={scrollContainerRef}
          className="flex-1 overflow-auto flex flex-col items-center py-4 gap-4"
          onMouseUp={handleMouseUp}
        >
          {loadError ? (
            <div className="flex flex-col items-center gap-3 py-8 px-4 text-center">
              <div className="text-sm text-red-600 dark:text-red-400 max-w-md break-words">{loadError}</div>
              <button
                type="button"
                onClick={handleRetry}
                className="rounded border border-outline-variant px-3 py-1 text-xs text-foreground/85 hover:bg-surface-high hover:text-foreground"
              >
                重试
              </button>
            </div>
          ) : !documentFile ? (
            <div className="text-sm text-foreground/60 py-8">加载 PDF 中...</div>
          ) : (
            <Document
              key={loadAttempt}
              file={documentFile}
              onLoadSuccess={onDocumentLoadSuccess}
              onLoadError={(err) => handleLoadError(err, null, err?.message || 'PDF 解析失败')}
              loading={<div className="text-sm text-foreground/60 py-8">加载 PDF 中...</div>}
              externalLinkTarget="_blank"
              externalLinkRel="noopener noreferrer"
            >
              <div ref={pageWrapperRef} className="flex flex-col items-center gap-4">
                {Array.from({ length: numPages }, (_, i) => {
                  const pageNo = i + 1;
                  const pageHighlights = highlightsByPage.get(pageNo) ?? [];
                  const isFlashing = flashPage === pageNo;
                  return (
                    <div
                      key={`page-${pageNo}`}
                      ref={(el) => { pageRefsRef.current[i] = el; }}
                      data-page-number={pageNo}
                      className={cn(
                        'relative inline-block shadow-sm transition-shadow',
                        isFlashing && 'ring-2 ring-primary/60 shadow-lg',
                      )}
                    >
                      <Page pageNumber={pageNo} scale={scale} />
                      {pageHighlights.length > 0 && (
                        <div className="pointer-events-none absolute inset-0" aria-hidden>
                          {pageHighlights.flatMap((h, hi) =>
                            (h.rects ?? []).map((r, ri) => (
                              <div
                                key={`${hi}-${ri}`}
                                style={{
                                  position: 'absolute',
                                  left: `${r.x * 100}%`,
                                  top: `${r.y * 100}%`,
                                  width: `${r.w * 100}%`,
                                  height: `${r.h * 100}%`,
                                  backgroundColor: h.color || '#FFEB3B',
                                  opacity: 0.35,
                                  borderRadius: 2,
                                  mixBlendMode: 'multiply',
                                }}
                              />
                            )),
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </Document>
          )}
        </div>

        {/* Annotation side panel */}
        {!hideHighlightPanel && showPanel && (
          <div className="w-72 border-l border-outline-variant/60 bg-surface-low flex flex-col">
            <div className="px-3 py-2 border-b border-outline-variant/60 flex items-center justify-between">
              <span className="text-xs font-label text-foreground/85">
                标注 {highlights.length > 0 && <span className="text-foreground/60">({highlights.length})</span>}
              </span>
              <button
                onClick={() => setShowPanel(false)}
                className="text-[10px] text-foreground/65 hover:text-foreground"
              >
                收起
              </button>
            </div>
            <div className="flex-1 overflow-auto p-2 space-y-1.5">
              {highlights.length === 0 ? (
                <div className="text-[11px] text-foreground/55 py-4 text-center">
                  选中正文 → 标记，开始添加高亮
                </div>
              ) : (
                highlights.map((h, i) => (
                  <div
                    key={`${h.page}-${i}`}
                    className="group rounded border border-outline-variant/40 bg-amber-50/50 dark:bg-amber-500/10 p-2 hover:bg-amber-50 dark:hover:bg-amber-500/20 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-1 mb-1">
                      <button
                        onClick={() => goToPage(h.page)}
                        className="text-[10px] font-label text-blue-700 dark:text-blue-300 hover:underline"
                        title="跳到该页"
                      >
                        第 {h.page} 页
                      </button>
                      {onDeleteHighlight && (
                        <button
                          onClick={() => onDeleteHighlight(i)}
                          className="opacity-0 group-hover:opacity-100 text-foreground/55 hover:text-red-600 dark:hover:text-red-400 transition-opacity"
                          title="删除"
                        >
                          <Trash2 size={11} />
                        </button>
                      )}
                    </div>
                    <div className="text-[11px] text-foreground/85 leading-snug line-clamp-3">{h.text}</div>
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
                const { rects, page } = computeSelectionRectsAndPage();
                onAddHighlight({
                  page,
                  text: selectedText,
                  color: '#FFEB3B',
                  ...(rects.length > 0 ? { rects } : {}),
                });
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
                const { page } = computeSelectionRectsAndPage();
                onAddNote(selectedText, page);
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
// Inline page-jump input. Click to edit, Enter to jump. Lives in the
// toolbar in place of prev/next buttons (continuous scroll makes
// page-stepper buttons redundant — the scroll wheel does the same job).
// ---------------------------------------------------------------------------

function PageJumpInput({
  page,
  numPages,
  onJump,
}: {
  page: number;
  numPages: number;
  onJump: (target: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(page));
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing) setDraft(String(page));
  }, [page, editing]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const commit = () => {
    const n = Number(draft);
    if (Number.isFinite(n) && n >= 1) {
      onJump(Math.min(numPages || n, Math.max(1, Math.floor(n))));
    }
    setEditing(false);
  };

  if (editing) {
    return (
      <input
        ref={inputRef}
        type="number"
        min={1}
        max={numPages || undefined}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') { setDraft(String(page)); setEditing(false); }
        }}
        className="w-12 rounded border border-outline-variant/60 bg-surface-lowest px-1 py-0.5 text-xs text-foreground focus:outline-none focus:border-primary/50 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
      />
    );
  }
  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className="min-w-[2ch] rounded px-1 py-0.5 text-foreground/85 hover:bg-surface-high hover:text-foreground"
      title="跳转到指定页"
    >
      {page || '—'}
    </button>
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
