import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { ChevronLeft, ChevronRight, Download, Maximize2, Printer, Search, ZoomIn, ZoomOut, Sparkles, Highlighter, PanelRight, Trash2 } from 'lucide-react';
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
  onAnalyzeText?: (text: string, page: number, anchor?: PdfSelectionAnchor) => void;
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

export interface PdfSelectionAnchor {
  page: number;
  rects: Array<{ x: number; y: number; w: number; h: number }>;
}

type SearchStatus = 'idle' | 'searching' | 'done' | 'error';

interface PdfSearchResult {
  page: number;
}

interface SelectionRangeRect {
  right: number;
  top: number;
}

interface SelectionToolbarPosition {
  x: number;
  y: number;
}

const PDF_LOAD_DETAIL_FALLBACK = 'PDF 文件读取失败，请稍后重试。';
const PDF_LOAD_INTERNAL_DETAIL_PATTERN =
  /(?:env=|env_refs|capability_[a-z0-9_]*|api[_\s-]?key|base[_\s-]?url|authorization|bearer|token|secret|https?:\/\/|\/api\/[^\s"'<>，。；,;)]*|\/runtime\/[^\s"'<>，。；,;)]*|\/resources\/[^\s"'<>，。；,;)]*|[A-Za-z]:\\[^\s"'<>]*|[{}[\]"`]|[A-Za-z0-9+/]{32,}={0,2})/i;
const SELECTION_TOOLBAR_MARGIN_PX = 8;
const SELECTION_TOOLBAR_ESTIMATED_WIDTH_PX = 336;
const SELECTION_TOOLBAR_ESTIMATED_HEIGHT_PX = 40;
const PDF_VIRTUALIZATION_THRESHOLD = 12;
const PDF_PAGE_OVERSCAN = 3;
const PDF_DEFAULT_PAGE_HEIGHT_PX = 1120;
const PDF_RENDER_OPTIONS = {
  isEvalSupported: false,
} as const;

function sanitizePdfLoadDetail(detail: unknown): string {
  const raw = typeof detail === 'string' ? detail.replace(/\s+/g, ' ').trim() : '';
  if (!raw || raw.length > 180 || PDF_LOAD_INTERNAL_DETAIL_PATTERN.test(raw)) {
    return PDF_LOAD_DETAIL_FALLBACK;
  }
  return raw;
}

function blobToBase64(blob: Blob): Promise<string> {
  if (!(blob instanceof Blob)) {
    throw new TypeError('blob must be a Blob');
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Failed to read PDF bytes'));
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== 'string') {
        reject(new Error('PDF reader returned a non-string payload'));
        return;
      }
      const [, base64 = ''] = result.split(',', 2);
      if (!base64) {
        reject(new Error('PDF reader returned empty base64 content'));
        return;
      }
      resolve(base64);
    };
    reader.readAsDataURL(blob);
  });
}

export function formatPdfLoadError(status: number | null, detail: unknown): string {
  const prefix = status ? `PDF 加载失败（HTTP ${status}）` : 'PDF 加载失败';
  return `${prefix}：${sanitizePdfLoadDetail(detail)}`;
}

function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (max < min) return min;
  return Math.max(min, Math.min(max, value));
}

function resolveSelectionToolbarPosition(
  rangeRect: SelectionRangeRect,
  viewportWidth: number,
  viewportHeight: number,
): SelectionToolbarPosition {
  const maxLeft = viewportWidth - SELECTION_TOOLBAR_ESTIMATED_WIDTH_PX - SELECTION_TOOLBAR_MARGIN_PX;
  const maxTop = viewportHeight - SELECTION_TOOLBAR_ESTIMATED_HEIGHT_PX - SELECTION_TOOLBAR_MARGIN_PX;
  return {
    x: clampNumber(rangeRect.right + SELECTION_TOOLBAR_MARGIN_PX, SELECTION_TOOLBAR_MARGIN_PX, maxLeft),
    y: clampNumber(rangeRect.top - 32, SELECTION_TOOLBAR_MARGIN_PX, maxTop),
  };
}

function selectionAnchorElement(selection: Selection): Element | null {
  const node = selection.anchorNode ?? selection.focusNode;
  if (!node) return null;
  if (node.nodeType === Node.ELEMENT_NODE) return node as Element;
  return node.parentElement;
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
  const [searchQuery, setSearchQuery] = useState('');
  const [searchStatus, setSearchStatus] = useState<SearchStatus>('idle');
  const [searchResults, setSearchResults] = useState<PdfSearchResult[]>([]);
  const [activeSearchIndex, setActiveSearchIndex] = useState(-1);
  const [visiblePageWindow, setVisiblePageWindow] = useState<{ first: number; last: number }>(() => {
    const initialWindowPage = initialPage ?? 1;
    return { first: initialWindowPage, last: initialWindowPage };
  });
  const [measuredPageHeights, setMeasuredPageHeights] = useState<Record<number, number>>({});
  const viewerRootRef = useRef<HTMLDivElement | null>(null);
  const onPageChangeRef = useRef(onPageChange);
  const [fullscreenAvailable, setFullscreenAvailable] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
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

  useEffect(() => {
    onPageChangeRef.current = onPageChange;
  }, [onPageChange]);

  useEffect(() => {
    const syncFullscreenState = () => {
      const root = viewerRootRef.current;
      const canRequestFullscreen = Boolean(
        root
        && document.fullscreenEnabled
        && typeof root.requestFullscreen === 'function'
        && typeof document.exitFullscreen === 'function',
      );
      setFullscreenAvailable(canRequestFullscreen);
      setIsFullscreen(Boolean(root && document.fullscreenElement === root));
    };

    syncFullscreenState();
    document.addEventListener('fullscreenchange', syncFullscreenState);
    document.addEventListener('fullscreenerror', syncFullscreenState);
    return () => {
      document.removeEventListener('fullscreenchange', syncFullscreenState);
      document.removeEventListener('fullscreenerror', syncFullscreenState);
    };
  }, []);

  // Track C F6: notify parent on confirmed page-number changes only.
  useEffect(() => {
    onPageChangeRef.current?.(pageNumber);
  }, [pageNumber]);

  const onDocumentLoadSuccess = useCallback(async (pdf: PdfDocumentLike) => {
    setLoadError(null);
    setNumPages(pdf.numPages);
    // Stash the doc so internal-link clicks can resolve named dests.
    pdfDocRef.current = pdf;
    setSearchStatus('idle');
    setSearchResults([]);
    setActiveSearchIndex(-1);
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
    const visibleMessage = formatPdfLoadError(status, detail || err?.message);
    if (typeof console !== 'undefined' && typeof console.error === 'function') {
      console.error('[PdfViewer] document load failed', {
        status,
        errorName: err?.name,
      });
    }
    setLoadError(visibleMessage);
  }, []);

  // Own the bytes fetch so pdf.js doesn't (see comment on pdfData state).
  //
  // 0.1.8.4 PDF-fetch-hardening (bug: source-dev mode 204 No Content):
  //   Browser download-manager extensions (IDM / 迅雷 / FlashGet / etc.) and
  //   some service-worker shells intercept large binary GETs and replace the
  //   real response with 204 — body, Content-Type, Content-Length all gone.
  //   The original `?as=bin` + application/octet-stream trick (0.1.8.1) no
  //   longer escapes them. Layered defence here:
  //     1. `?as=raw1` selects a private vendor MIME on the backend
  //        (application/vnd.litassist.encoded). Download managers don't
  //        sniff it as PDF and ignore.
  //     2. Custom `X-LitAssist-Pdf-Stream: 1` header forces a CORS preflight,
  //        which most download-manager extensions don't intercept.
  //     3. If we still get 204 / 0-byte / null content-type, retry once
  //        with XHR + responseType='arraybuffer' (XHR uses a different
  //        code path than fetch in many extensions).
  //     4. If XHR also returns empty, fall back to the natural PDF MIME
  //        (no `as=` flag) — works for users without an aggressive
  //        download manager.
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

    const buildUrl = (flag: 'raw1' | 'bin' | null): string => {
      if (!flag) return url;
      const sep = url.includes('?') ? '&' : '?';
      return `${url}${sep}as=${flag}`;
    };

    const isEmptyResponse = (status: number, byteLength: number): boolean => {
      // 204 / 205 are explicitly bodiless. A 200 with 0 bytes means an
      // interceptor (extension / SW) swallowed the body.
      if (status === 204 || status === 205) return true;
      if (status >= 200 && status < 300 && byteLength === 0) return true;
      return false;
    };

    type FetchOk = { kind: 'ok'; bytes: Uint8Array; via: string };
    type FetchEmpty = { kind: 'empty'; status: number; via: string };
    type FetchHttpErr = { kind: 'http_err'; status: number; detail: string; via: string };
    type FetchNetErr = { kind: 'net_err'; detail: string; via: string };
    type FetchOutcome = FetchOk | FetchEmpty | FetchHttpErr | FetchNetErr;

    const fetchViaFetch = async (fetchUrl: string, via: string): Promise<FetchOutcome> => {
      try {
        const resp = await fetch(fetchUrl, {
          method: 'GET',
          cache: 'no-store',
          headers: {
            Accept: 'application/vnd.litassist.encoded,application/octet-stream,application/pdf;q=0.9,*/*;q=0.1',
            // Non-simple header → forces CORS preflight, which most
            // download-manager extensions don't intercept.
            'X-LitAssist-Pdf-Stream': '1',
          },
        });
        if (typeof console !== 'undefined') {
          console.info('[PdfViewer] fetch resp', {
            via,
            url: fetchUrl,
            status: resp.status,
            ok: resp.ok,
            contentLength: resp.headers.get('content-length'),
            contentType: resp.headers.get('content-type'),
          });
        }
        if (!resp.ok && !isEmptyResponse(resp.status, 0)) {
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
          return { kind: 'http_err', status: resp.status, detail, via };
        }
        const decoded = new Uint8Array(await resp.arrayBuffer());
        if (isEmptyResponse(resp.status, decoded.byteLength)) {
          return { kind: 'empty', status: resp.status, via };
        }
        return { kind: 'ok', bytes: decoded, via };
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        return { kind: 'net_err', detail: e.message || '网络请求失败', via };
      }
    };

    const fetchViaXhr = (fetchUrl: string, via: string): Promise<FetchOutcome> => {
      return new Promise((resolve) => {
        try {
          const xhr = new XMLHttpRequest();
          xhr.open('GET', fetchUrl, true);
          xhr.responseType = 'arraybuffer';
          xhr.setRequestHeader(
            'Accept',
            'application/vnd.litassist.encoded,application/octet-stream,application/pdf;q=0.9,*/*;q=0.1',
          );
          xhr.setRequestHeader('X-LitAssist-Pdf-Stream', '1');
          xhr.setRequestHeader('Cache-Control', 'no-store');
          xhr.onload = () => {
            const status = xhr.status || 0;
            const ab = xhr.response instanceof ArrayBuffer ? xhr.response : null;
            const byteLength = ab ? ab.byteLength : 0;
            if (typeof console !== 'undefined') {
              console.info('[PdfViewer] xhr resp', {
                via,
                url: fetchUrl,
                status,
                byteLength,
                contentType: xhr.getResponseHeader('content-type'),
                contentLength: xhr.getResponseHeader('content-length'),
              });
            }
            if (status >= 400) {
              const detail = xhr.responseText ? xhr.responseText.slice(0, 200) : `HTTP ${status}`;
              resolve({ kind: 'http_err', status, detail, via });
              return;
            }
            if (!ab || isEmptyResponse(status, byteLength)) {
              resolve({ kind: 'empty', status, via });
              return;
            }
            resolve({ kind: 'ok', bytes: new Uint8Array(ab), via });
          };
          xhr.onerror = () => {
            resolve({ kind: 'net_err', detail: 'XHR network error', via });
          };
          xhr.send();
        } catch (err) {
          const e = err instanceof Error ? err : new Error(String(err));
          resolve({ kind: 'net_err', detail: e.message || 'XHR setup failed', via });
        }
      });
    };

    (async () => {
      // Stage 1: fetch + vendor MIME (?as=raw1). Most users land here.
      let outcome = await fetchViaFetch(buildUrl('raw1'), 'fetch:raw1');
      // Stage 2: XHR + vendor MIME — different transport, sometimes
      // escapes interceptors that swallow fetch().
      if (outcome.kind === 'empty' || outcome.kind === 'net_err') {
        const fallback = await fetchViaXhr(buildUrl('raw1'), 'xhr:raw1');
        if (fallback.kind === 'ok') outcome = fallback;
        else if (outcome.kind === 'empty') outcome = fallback;
      }
      // Stage 3: natural PDF MIME (no flag). Works for users without
      // aggressive download manager extensions; loses the octet-stream
      // disguise but at least the doc opens.
      if (outcome.kind === 'empty') {
        const fallback = await fetchViaFetch(buildUrl(null), 'fetch:plain');
        if (fallback.kind === 'ok') outcome = fallback;
      }
      if (cancelled) return;
      if (outcome.kind === 'ok') {
        if (typeof console !== 'undefined') {
          console.info('[PdfViewer] decoded bytes', outcome.bytes.byteLength, 'via', outcome.via);
        }
        setPdfData(outcome.bytes);
        if (onBytesLoaded) onBytesLoaded(outcome.bytes);
        return;
      }
      if (outcome.kind === 'http_err') {
        handleLoadError(new Error(outcome.detail), outcome.status, outcome.detail);
        return;
      }
      if (outcome.kind === 'empty') {
        const detail = '响应体为空（可能被浏览器扩展或下载管理器拦截，请暂时禁用 IDM/迅雷/FDM 类扩展后重试）。';
        handleLoadError(new Error(detail), outcome.status, detail);
        return;
      }
      handleLoadError(new Error(outcome.detail), null, outcome.detail);
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
  const pdfFileName = useMemo(() => {
    const safeName = materialId
      .trim()
      .replace(/[\\/:*?"<>|]+/g, '_')
      .replace(/\s+/g, '_')
      .replace(/^_+|_+$/g, '');
    const baseName = safeName.length > 0 ? safeName : 'document';
    return baseName.toLowerCase().endsWith('.pdf') ? baseName : `${baseName}.pdf`;
  }, [materialId]);
  const createPdfBlob = useCallback((): Blob | null => {
    if (!pdfData || pdfData.byteLength === 0) return null;
    return new Blob([pdfData.slice()], { type: 'application/pdf' });
  }, [pdfData]);
  const handleDownloadPdf = useCallback(() => {
    const blob = createPdfBlob();
    if (!blob) return;
    const nativeSaveBytes = window.pywebview?.api?.save_bytes;
    if (nativeSaveBytes) {
      void blobToBase64(blob)
        .then((contentBase64) => nativeSaveBytes(pdfFileName, contentBase64))
        .catch(() => undefined);
      return;
    }
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = pdfFileName;
    anchor.rel = 'noopener';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }, [createPdfBlob, pdfFileName]);
  const handlePrintPdf = useCallback(() => {
    const blob = createPdfBlob();
    if (!blob) {
      window.print();
      return;
    }
    const objectUrl = URL.createObjectURL(blob);
    const printWindow = window.open(objectUrl, '_blank', 'noopener,noreferrer');
    if (!printWindow) {
      URL.revokeObjectURL(objectUrl);
      window.print();
      return;
    }
    let printed = false;
    const printNow = () => {
      if (printed) return;
      printed = true;
      try {
        printWindow.focus();
        printWindow.print();
      } finally {
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
      }
    };
    printWindow.addEventListener('load', printNow, { once: true });
    window.setTimeout(printNow, 400);
  }, [createPdfBlob]);
  const handleToggleFullscreen = useCallback(() => {
    const root = viewerRootRef.current;
    if (!root || !fullscreenAvailable) return;
    if (document.fullscreenElement === root) {
      void document.exitFullscreen().catch(() => undefined);
      return;
    }
    void root.requestFullscreen().catch(() => undefined);
  }, [fullscreenAvailable]);

  const handleMouseUp = useCallback(() => {
    const sel = window.getSelection();
    const text = sel?.toString().trim() || '';
    if (text.length > 2 && sel && sel.rangeCount > 0) {
      const anchorEl = selectionAnchorElement(sel);
      const pageEl = anchorEl?.closest('.react-pdf__Page') ?? null;
      if (!pageEl || !scrollContainerRef.current?.contains(pageEl)) {
        setShowAIBtn(false);
        setSelectedText('');
        return;
      }
      setSelectedText(text);
      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      setBtnPos(resolveSelectionToolbarPosition(rect, window.innerWidth, window.innerHeight));
      setShowAIBtn(true);
    } else {
      setShowAIBtn(false);
      setSelectedText('');
    }
  }, []);

  const computeSelectionRectsAndPage = useCallback((): PdfSelectionAnchor => {
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

  const handleAnalyze = useCallback(() => {
    if (selectedText && onAnalyzeText) {
      const anchor = computeSelectionRectsAndPage();
      onAnalyzeText(selectedText, anchor.page, anchor);
    }
    setShowAIBtn(false);
    window.getSelection()?.removeAllRanges();
  }, [computeSelectionRectsAndPage, selectedText, onAnalyzeText]);

  const goToPage = useCallback((target: number) => {
    if (!numPages || numPages <= 0) return;
    const clamped = Math.max(1, Math.min(numPages, Math.floor(target)));
    const el = pageRefsRef.current[clamped - 1];
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
    setPageNumber(clamped);
  }, [numPages]);
  const canGoPrevious = numPages > 0 && pageNumber > 1;
  const canGoNext = numPages > 0 && pageNumber < numPages;
  const canSearchPdf = searchQuery.trim().length > 0 && searchStatus !== 'searching' && numPages > 0;
  const jumpByPage = useCallback((delta: -1 | 1) => {
    goToPage(pageNumber + delta);
  }, [goToPage, pageNumber]);
  const activateSearchResult = useCallback((index: number) => {
    if (searchResults.length === 0) return;
    const normalizedIndex = ((index % searchResults.length) + searchResults.length) % searchResults.length;
    const result = searchResults[normalizedIndex];
    if (!result) return;
    setActiveSearchIndex(normalizedIndex);
    goToPage(result.page);
    setFlashPage(result.page);
  }, [goToPage, searchResults]);
  const runPdfSearch = useCallback(async () => {
    const query = searchQuery.trim();
    const pdf = pdfDocRef.current;
    if (!query) {
      setSearchStatus('idle');
      setSearchResults([]);
      setActiveSearchIndex(-1);
      return;
    }
    if (!pdf || typeof pdf.getPage !== 'function' || !numPages || numPages <= 0) {
      setSearchStatus('error');
      setSearchResults([]);
      setActiveSearchIndex(-1);
      return;
    }

    setSearchStatus('searching');
    const needle = query.toLocaleLowerCase();
    const nextResults: PdfSearchResult[] = [];
    try {
      for (let page = 1; page <= numPages; page += 1) {
        const pdfPage = await pdf.getPage(page);
        if (!pdfPage || typeof pdfPage.getTextContent !== 'function') continue;
        const text = extractPdfTextContent(await pdfPage.getTextContent());
        if (text.toLocaleLowerCase().includes(needle)) {
          nextResults.push({ page });
        }
      }
      setSearchResults(nextResults);
      setSearchStatus('done');
      if (nextResults.length > 0) {
        setActiveSearchIndex(0);
        goToPage(nextResults[0].page);
        setFlashPage(nextResults[0].page);
      } else {
        setActiveSearchIndex(-1);
      }
    } catch {
      setSearchResults([]);
      setActiveSearchIndex(-1);
      setSearchStatus('error');
    }
  }, [goToPage, numPages, searchQuery]);

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

  useEffect(() => {
    const handleDocumentMouseUp = () => {
      window.setTimeout(handleMouseUp, 0);
    };
    document.addEventListener('mouseup', handleDocumentMouseUp);
    return () => document.removeEventListener('mouseup', handleDocumentMouseUp);
  }, [handleMouseUp]);

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
    if (typeof IntersectionObserver === 'undefined') return;
    const root = scrollContainerRef.current;
    const observer = new IntersectionObserver(
      (entries) => {
        // Aggregate visibility ratios; pick the page with the largest
        // visible area. This handles edge cases where two pages straddle
        // the viewport boundary equally — the larger half wins.
        let best: { page: number; ratio: number } | null = null;
        const visiblePages: number[] = [];
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const pageAttr = (entry.target as HTMLElement).dataset.pageNumber;
          if (!pageAttr) continue;
          const page = Number(pageAttr);
          if (!Number.isFinite(page) || page < 1) continue;
          visiblePages.push(page);
          if (!best || entry.intersectionRatio > best.ratio) {
            best = { page, ratio: entry.intersectionRatio };
          }
        }
        if (visiblePages.length > 0) {
          setVisiblePageWindow({
            first: Math.min(...visiblePages),
            last: Math.max(...visiblePages),
          });
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
  const heavyPageWindow = useMemo(() => {
    if (!numPages || numPages <= 0) {
      return { first: 1, last: 0 };
    }
    if (numPages <= PDF_VIRTUALIZATION_THRESHOLD) {
      return { first: 1, last: numPages };
    }
    const pageOutsideVisibleWindow = (
      pageNumber < visiblePageWindow.first - PDF_PAGE_OVERSCAN
      || pageNumber > visiblePageWindow.last + PDF_PAGE_OVERSCAN
    );
    const baseFirst = pageOutsideVisibleWindow ? pageNumber : Math.min(pageNumber, visiblePageWindow.first);
    const baseLast = pageOutsideVisibleWindow ? pageNumber : Math.max(pageNumber, visiblePageWindow.last);
    const first = clampNumber(baseFirst - PDF_PAGE_OVERSCAN, 1, numPages);
    const last = clampNumber(baseLast + PDF_PAGE_OVERSCAN, 1, numPages);
    return { first, last };
  }, [numPages, pageNumber, visiblePageWindow.first, visiblePageWindow.last]);
  const forcedHeavyPages = useMemo(() => {
    const pages = new Set<number>();
    if (numPages > 0) {
      pages.add(clampNumber(pageNumber, 1, numPages));
      if (flashPage !== null) pages.add(clampNumber(flashPage, 1, numPages));
      for (const page of highlightsByPage.keys()) {
        if (page >= 1 && page <= numPages) pages.add(page);
      }
    }
    return pages;
  }, [flashPage, highlightsByPage, numPages, pageNumber]);
  const shouldRenderPdfPage = useCallback((pageNo: number): boolean => {
    if (!numPages || numPages <= PDF_VIRTUALIZATION_THRESHOLD) return true;
    return (
      forcedHeavyPages.has(pageNo)
      || (pageNo >= heavyPageWindow.first && pageNo <= heavyPageWindow.last)
    );
  }, [forcedHeavyPages, heavyPageWindow.first, heavyPageWindow.last, numPages]);
  const updateMeasuredPageHeight = useCallback((pageNo: number, element: HTMLDivElement | null): void => {
    if (!element) return;
    const nextHeight = Math.ceil(element.getBoundingClientRect().height);
    if (!Number.isFinite(nextHeight) || nextHeight <= 0) return;
    setMeasuredPageHeights((current) => {
      if (current[pageNo] === nextHeight) return current;
      return { ...current, [pageNo]: nextHeight };
    });
  }, []);

  return (
    <div
      ref={viewerRootRef}
      className={cn(
        'pdf-canvas flex flex-col h-full bg-gray-100 dark:bg-neutral-900',
        isFullscreen && 'h-screen w-screen',
        className,
      )}
    >
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-outline-variant/60 bg-surface-low">
        <div className="flex items-center gap-1.5 text-xs font-label text-foreground/80">
          <button
            type="button"
            onClick={() => jumpByPage(-1)}
            disabled={!canGoPrevious}
            className="inline-flex h-6 w-6 items-center justify-center rounded text-foreground/75 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent"
            aria-label="上一页"
            title="上一页"
          >
            <ChevronLeft size={14} aria-hidden />
          </button>
          <PageJumpInput
            page={pageNumber}
            numPages={numPages}
            onJump={goToPage}
          />
          <span className="text-foreground/55">/</span>
          <span className="text-foreground/80">{numPages || '—'}</span>
          <button
            type="button"
            onClick={() => jumpByPage(1)}
            disabled={!canGoNext}
            className="inline-flex h-6 w-6 items-center justify-center rounded text-foreground/75 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent"
            aria-label="下一页"
            title="下一页"
          >
            <ChevronRight size={14} aria-hidden />
          </button>
        </div>
        <form
          className="mx-2 hidden min-w-[190px] max-w-[320px] flex-1 items-center justify-center gap-1 sm:flex"
          onSubmit={(event) => {
            event.preventDefault();
            void runPdfSearch();
          }}
        >
          <div className="flex min-w-0 flex-1 items-center rounded border border-outline-variant/50 bg-surface-lowest px-1.5 py-0.5 focus-within:border-primary/45">
            <Search size={12} className="mr-1 shrink-0 text-foreground/40" aria-hidden />
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none placeholder:text-foreground/35"
              aria-label="搜索 PDF 文本"
              placeholder="搜索 PDF 文本"
            />
            <button
              type="submit"
              disabled={!canSearchPdf}
              className="ml-1 rounded px-1.5 py-0.5 text-[10px] font-label text-foreground/70 hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35"
              aria-label="搜索 PDF"
              title="搜索 PDF"
            >
              搜索
            </button>
          </div>
          <button
            type="button"
            onClick={() => activateSearchResult(activeSearchIndex - 1)}
            disabled={searchResults.length <= 1 || activeSearchIndex < 0}
            className="inline-flex h-6 w-6 items-center justify-center rounded text-foreground/70 hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent"
            aria-label="上一个搜索结果"
            title="上一个搜索结果"
          >
            <ChevronLeft size={13} aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => activateSearchResult(activeSearchIndex + 1)}
            disabled={searchResults.length <= 1 || activeSearchIndex < 0}
            className="inline-flex h-6 w-6 items-center justify-center rounded text-foreground/70 hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent"
            aria-label="下一个搜索结果"
            title="下一个搜索结果"
          >
            <ChevronRight size={13} aria-hidden />
          </button>
          <span
            className="w-10 text-center text-[10px] font-label text-foreground/55"
            aria-live="polite"
            title={searchStatus === 'error' ? 'PDF 文本搜索失败' : undefined}
          >
            {searchStatus === 'searching'
              ? '...'
              : searchStatus === 'done'
                ? `${activeSearchIndex >= 0 ? activeSearchIndex + 1 : 0}/${searchResults.length}`
                : searchStatus === 'error'
                  ? '错误'
                  : ''}
          </span>
        </form>
        <div className="flex items-center gap-1">
          <button
            onClick={handleDownloadPdf}
            disabled={!pdfData}
            className="p-1 rounded text-foreground/80 hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent"
            aria-label="下载 PDF"
            title="下载 PDF"
          >
            <Download size={14} aria-hidden />
          </button>
          <button
            onClick={handlePrintPdf}
            disabled={!pdfData}
            className="p-1 rounded text-foreground/80 hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent"
            aria-label="打印 PDF"
            title="打印 PDF"
          >
            <Printer size={14} aria-hidden />
          </button>
          <button
            type="button"
            onClick={handleToggleFullscreen}
            disabled={!fullscreenAvailable}
            className="p-1 rounded text-foreground/80 hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent"
            aria-label={isFullscreen ? '退出全屏' : '全屏阅读'}
            title={fullscreenAvailable ? (isFullscreen ? '退出全屏' : '全屏阅读') : '当前浏览器不支持全屏'}
          >
            <Maximize2 size={14} aria-hidden className={cn(isFullscreen && 'rotate-180')} />
          </button>
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
              options={PDF_RENDER_OPTIONS}
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
                  const renderPage = shouldRenderPdfPage(pageNo);
                  const placeholderHeight = measuredPageHeights[pageNo] ?? Math.round(PDF_DEFAULT_PAGE_HEIGHT_PX * scale);
                  return (
                    <div
                      key={`page-${pageNo}`}
                      ref={(el) => {
                        pageRefsRef.current[i] = el;
                        updateMeasuredPageHeight(pageNo, el);
                      }}
                      data-page-number={pageNo}
                      className={cn(
                        'relative inline-block shadow-sm transition-shadow',
                        isFlashing && 'ring-2 ring-primary/60 shadow-lg',
                      )}
                      style={renderPage ? undefined : { minHeight: placeholderHeight }}
                      aria-label={`PDF 第 ${pageNo} 页`}
                    >
                      {renderPage ? (
                        <Page pageNumber={pageNo} scale={scale} />
                      ) : (
                        <div
                          className="flex w-[min(72vw,760px)] items-center justify-center rounded border border-dashed border-outline-variant/50 bg-surface-lowest text-[11px] text-foreground/45"
                          style={{ height: placeholderHeight }}
                        >
                          第 {pageNo} 页
                        </div>
                      )}
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
          style={{ left: btnPos.x, top: btnPos.y }}
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
// Inline page-jump input. Click to edit, Enter to jump. Continuous scroll
// still owns reading position; the adjacent step buttons provide explicit
// keyboard/screen-reader discoverability.
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
      aria-label={`当前页 ${page}，点击跳转`}
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

interface PdfTextItemLike {
  str?: unknown;
}

interface PdfTextContentLike {
  items?: unknown;
}

interface PdfPageLike {
  getTextContent?: () => Promise<PdfTextContentLike>;
}

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
  getPage?: (pageNumber: number) => Promise<PdfPageLike>;
}

function extractPdfTextContent(content: PdfTextContentLike): string {
  if (!content || !Array.isArray(content.items)) return '';
  return content.items
    .map((item: unknown) => {
      const textItem = item as PdfTextItemLike | null;
      return typeof textItem?.str === 'string' ? textItem.str : '';
    })
    .filter((text) => text.length > 0)
    .join(' ');
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
