import {
  useState,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { ChevronLeft, ChevronRight, Download, Image as ImageIcon, Maximize2, Printer, Search, ZoomIn, ZoomOut, Sparkles, Highlighter, PanelRight, Trash2, ScanSearch, Sigma, Table2, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { normalizePdfUrlBbox, toPdfHighlightRect, type PdfBbox } from '@/lib/pdfAnchor';
import {
  buildPdfQuotePageSearchOrder,
  countPdfQuoteOccurrences,
  normalizePdfQuote,
  resolvePdfQuoteAnchor,
  type PdfQuoteAnchorMatch,
} from '@/lib/pdfQuoteAnchor';

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
  /** Temporarily disables PDF-to-chat selection while an answer is running. */
  analysisDisabled?: boolean;
  initialPage?: number;
  /** Normalized visual anchor, or the safe fallback when a text quote cannot be resolved. */
  initialBbox?: PdfBbox;
  /** Bounded exact text anchor resolved before a coarse text-block bbox. */
  initialQuote?: string;
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
  onAnalyzeRegion?: (selection: PdfRegionCapture) => void;
  /** Formula detector output. Each candidate is selected as one atomic region. */
  formulaCandidates?: readonly PdfFormulaCandidate[];
  /** Visual selections owned by the parent; rendered as persistent, inert outlines. */
  selectedVisualRegions?: readonly PdfSelectedVisualRegion[];
  onAddHighlight?: (highlight: { page: number; text: string; color: string; rects?: Array<{ x: number; y: number; w: number; h: number }> }) => void;
  onDeleteHighlight?: (index: number) => void;
  highlights?: PdfViewerHighlight[];
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

interface PdfViewerHighlight {
  page: number;
  text: string;
  color: string;
  rects?: Array<{ x: number; y: number; w: number; h: number }>;
}

type CitationAnchorStatus = 'idle' | 'resolving' | 'matched' | 'page_only';

export interface PdfOutlineEntry {
  title: string;
  page?: number;
  children?: PdfOutlineEntry[];
}

export interface PdfSelectionAnchor {
  page: number;
  rects: Array<{ x: number; y: number; w: number; h: number }>;
}

export type PdfVisualSelectionKind = 'figure' | 'table' | 'formula' | 'region';

type PdfDragSelectionKind = Exclude<PdfVisualSelectionKind, 'formula'>;

export interface PdfFormulaCandidate {
  candidateId: string;
  page: number;
  bbox: PdfBbox;
  chunkId?: string;
  text?: string;
}

export interface PdfSelectedVisualRegion {
  kind: PdfVisualSelectionKind;
  page: number;
  bbox: PdfBbox;
  candidateId?: string;
}

const EMPTY_FORMULA_CANDIDATES: readonly PdfFormulaCandidate[] = [];
const EMPTY_SELECTED_VISUAL_REGIONS: readonly PdfSelectedVisualRegion[] = [];
const PDF_VISUAL_SELECTION_KINDS: ReadonlySet<PdfVisualSelectionKind> = new Set([
  'figure',
  'table',
  'formula',
  'region',
]);

export interface PdfRegionCapture {
  kind: PdfVisualSelectionKind;
  page: number;
  bbox: PdfBbox;
  label: string;
  candidateId?: string;
  chunkId?: string;
  text?: string;
  image: {
    mime: 'image/png' | 'image/jpeg';
    data_b64: string;
    size: number;
    name: string;
  };
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
const PDF_REGION_MIN_SIZE_PX = 24;
const PDF_REGION_CAPTURE_MAX_EDGE = 1600;
const PDF_REGION_CAPTURE_MAX_BYTES = 4 * 1024 * 1024;
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

function clampRatio(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function isDragSelectionKind(kind: PdfVisualSelectionKind | null): kind is PdfDragSelectionKind {
  return kind !== null && kind !== 'formula';
}

function regionBbox(
  start: { x: number; y: number },
  end: { x: number; y: number },
): PdfBbox {
  const left = clampRatio(Math.min(start.x, end.x));
  const top = clampRatio(Math.min(start.y, end.y));
  const right = clampRatio(Math.max(start.x, end.x));
  const bottom = clampRatio(Math.max(start.y, end.y));
  return [left, top, right - left, bottom - top];
}

function canvasToBlob(canvas: HTMLCanvasElement, mime: 'image/png' | 'image/jpeg', quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('无法生成选区内容'));
    }, mime, quality);
  });
}

async function capturePdfRegion(
  pageElement: HTMLDivElement,
  bbox: PdfBbox,
  kind: PdfVisualSelectionKind,
  page: number,
  metadata: Pick<PdfRegionCapture, 'candidateId' | 'chunkId' | 'text'> = {},
): Promise<PdfRegionCapture> {
  const sourceCanvas = pageElement.querySelector<HTMLCanvasElement>('canvas.react-pdf__Page__canvas, canvas');
  if (!sourceCanvas || sourceCanvas.width <= 0 || sourceCanvas.height <= 0) {
    throw new Error('当前页尚未完成渲染，请稍后重试。');
  }
  const [x, y, width, height] = bbox;
  const sourceX = Math.max(0, Math.floor(x * sourceCanvas.width));
  const sourceY = Math.max(0, Math.floor(y * sourceCanvas.height));
  const sourceWidth = Math.max(1, Math.min(sourceCanvas.width - sourceX, Math.ceil(width * sourceCanvas.width)));
  const sourceHeight = Math.max(1, Math.min(sourceCanvas.height - sourceY, Math.ceil(height * sourceCanvas.height)));
  const scale = Math.min(1, PDF_REGION_CAPTURE_MAX_EDGE / Math.max(sourceWidth, sourceHeight));
  const output = document.createElement('canvas');
  output.width = Math.max(1, Math.round(sourceWidth * scale));
  output.height = Math.max(1, Math.round(sourceHeight * scale));
  const context = output.getContext('2d');
  if (!context) throw new Error('当前环境无法裁剪 PDF 区域。');
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, output.width, output.height);
  context.drawImage(
    sourceCanvas,
    sourceX,
    sourceY,
    sourceWidth,
    sourceHeight,
    0,
    0,
    output.width,
    output.height,
  );

  let mime: 'image/png' | 'image/jpeg' = 'image/png';
  let blob = await canvasToBlob(output, mime);
  if (blob.size > PDF_REGION_CAPTURE_MAX_BYTES) {
    mime = 'image/jpeg';
    blob = await canvasToBlob(output, mime, 0.9);
  }
  if (blob.size > PDF_REGION_CAPTURE_MAX_BYTES) {
    throw new Error('框选区域过大，请缩小范围后重试。');
  }
  const extension = mime === 'image/png' ? 'png' : 'jpg';
  const labelByKind: Record<PdfVisualSelectionKind, string> = {
    figure: '选中的图',
    table: '选中的表',
    formula: '选中的公式',
    region: '选中的区域',
  };
  return {
    kind,
    page,
    bbox,
    label: labelByKind[kind],
    ...(metadata.candidateId ? { candidateId: metadata.candidateId } : {}),
    ...(metadata.chunkId ? { chunkId: metadata.chunkId } : {}),
    ...(metadata.text ? { text: metadata.text } : {}),
    image: {
      mime,
      data_b64: await blobToBase64(blob),
      size: blob.size,
      name: `pdf-page-${page}-${kind}.${extension}`,
    },
  };
}

export function PdfViewer({
  url,
  materialId,
  analysisDisabled = false,
  initialPage,
  initialBbox,
  initialQuote,
  bytes,
  onBytesLoaded,
  scale: controlledScale,
  onScaleChange,
  onAnalyzeText,
  onAnalyzeRegion,
  formulaCandidates = EMPTY_FORMULA_CANDIDATES,
  selectedVisualRegions = EMPTY_SELECTED_VISUAL_REGIONS,
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
  const [regionMode, setRegionMode] = useState<PdfVisualSelectionKind | null>(null);
  const [regionDraft, setRegionDraft] = useState<{
    page: number;
    pointerId: number;
    start: { x: number; y: number };
    current: { x: number; y: number };
  } | null>(null);
  const [regionStatus, setRegionStatus] = useState<string | null>(null);
  const [pendingFormulaCandidateId, setPendingFormulaCandidateId] = useState<string | null>(null);
  const analysisDisabledRef = useRef(analysisDisabled);
  const formulaCaptureInFlightRef = useRef(false);
  const [showPanel, setShowPanel] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchStatus, setSearchStatus] = useState<SearchStatus>('idle');
  const [searchResults, setSearchResults] = useState<PdfSearchResult[]>([]);
  const [activeSearchIndex, setActiveSearchIndex] = useState(-1);
  const [citationQuoteHighlight, setCitationQuoteHighlight] = useState<PdfViewerHighlight | null>(null);
  const [citationAnchorStatus, setCitationAnchorStatus] = useState<CitationAnchorStatus>('idle');
  const citationBboxRect = useMemo(() => toPdfHighlightRect(initialBbox), [initialBbox]);
  const normalizedCitationQuote = useMemo(
    () => normalizePdfQuote(initialQuote),
    [initialQuote],
  );
  const citationAnchorInputKey = useMemo(() => JSON.stringify([
    materialId,
    url,
    loadAttempt,
    initialPage ?? null,
    normalizedCitationQuote,
    citationBboxRect?.x ?? null,
    citationBboxRect?.y ?? null,
    citationBboxRect?.w ?? null,
    citationBboxRect?.h ?? null,
  ]), [citationBboxRect, initialPage, loadAttempt, materialId, normalizedCitationQuote, url]);
  const [citationBboxFallbackKey, setCitationBboxFallbackKey] = useState<string | null>(null);
  const citationTargetPage = useMemo(() => (
    typeof initialPage === 'number'
    && Number.isSafeInteger(initialPage)
    && initialPage >= 1
    && initialPage <= numPages
      ? initialPage
      : null
  ), [initialPage, numPages]);
  const activeCitationBboxRect = citationBboxRect
    && (!normalizedCitationQuote || citationBboxFallbackKey === citationAnchorInputKey)
    ? citationBboxRect
    : null;
  const citationBboxHighlight = useMemo<PdfViewerHighlight | null>(() => {
    if (!activeCitationBboxRect || citationTargetPage === null) return null;
    return {
      page: citationTargetPage,
      text: '引用区域',
      color: '#60A5FA',
      rects: [{ ...activeCitationBboxRect }],
    };
  }, [activeCitationBboxRect, citationTargetPage]);
  const citationBboxActivationKey = useMemo(() => {
    if (!activeCitationBboxRect || citationTargetPage === null) return null;
    return JSON.stringify([
      materialId,
      url,
      loadAttempt,
      scale,
      citationTargetPage,
      activeCitationBboxRect.x,
      activeCitationBboxRect.y,
      activeCitationBboxRect.w,
      activeCitationBboxRect.h,
    ]);
  }, [activeCitationBboxRect, citationTargetPage, loadAttempt, materialId, scale, url]);
  const activeCitationBboxActivationKeyRef = useRef<string | null>(null);
  const pendingCitationBboxRenderKeyRef = useRef<string | null>(null);
  useLayoutEffect(() => {
    activeCitationBboxActivationKeyRef.current = citationBboxActivationKey;
    pendingCitationBboxRenderKeyRef.current = citationBboxActivationKey;
  }, [citationBboxActivationKey]);
  const citationQuotePages = useMemo(
    () => buildPdfQuotePageSearchOrder(initialPage, numPages),
    [initialPage, numPages],
  );
  const [visiblePageWindow, setVisiblePageWindow] = useState<{ first: number; last: number }>(() => {
    const initialWindowPage = initialPage ?? 1;
    return { first: initialWindowPage, last: initialWindowPage };
  });
  const [measuredPageHeights, setMeasuredPageHeights] = useState<Record<number, number>>({});
  const viewerRootRef = useRef<HTMLDivElement | null>(null);
  const onPageChangeRef = useRef(onPageChange);
  const [fullscreenAvailable, setFullscreenAvailable] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const formulaCandidatesByPage = useMemo(() => {
    const grouped = new Map<number, PdfFormulaCandidate[]>();
    for (const candidate of formulaCandidates) {
      const candidateId = typeof candidate.candidateId === 'string' ? candidate.candidateId.trim() : '';
      const page = candidate.page;
      const bbox = normalizePdfUrlBbox(candidate.bbox);
      if (!candidateId || !Number.isSafeInteger(page) || page < 1 || !bbox) continue;
      const normalized: PdfFormulaCandidate = {
        candidateId,
        page,
        bbox,
        ...(typeof candidate.chunkId === 'string' && candidate.chunkId.trim()
          ? { chunkId: candidate.chunkId.trim() }
          : {}),
        ...(typeof candidate.text === 'string' && candidate.text.trim()
          ? { text: candidate.text.trim() }
          : {}),
      };
      const pageCandidates = grouped.get(page) ?? [];
      pageCandidates.push(normalized);
      grouped.set(page, pageCandidates);
    }
    return grouped;
  }, [formulaCandidates]);

  const selectedVisualRegionsByPage = useMemo(() => {
    const grouped = new Map<number, PdfSelectedVisualRegion[]>();
    for (const selection of selectedVisualRegions) {
      const page = selection.page;
      const bbox = normalizePdfUrlBbox(selection.bbox);
      if (
        !Number.isSafeInteger(page)
        || page < 1
        || !PDF_VISUAL_SELECTION_KINDS.has(selection.kind)
        || !bbox
      ) continue;
      const normalized: PdfSelectedVisualRegion = {
        kind: selection.kind,
        page,
        bbox,
        ...(typeof selection.candidateId === 'string' && selection.candidateId.trim()
          ? { candidateId: selection.candidateId.trim() }
          : {}),
      };
      const pageSelections = grouped.get(page) ?? [];
      pageSelections.push(normalized);
      grouped.set(page, pageSelections);
    }
    return grouped;
  }, [selectedVisualRegions]);

  useEffect(() => {
    analysisDisabledRef.current = analysisDisabled;
    if (!analysisDisabled) return;
    setRegionMode(null);
    setRegionDraft(null);
    setRegionStatus(null);
    setShowAIBtn(false);
    setSelectedText('');
    window.getSelection()?.removeAllRanges();
  }, [analysisDisabled]);
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
    if (analysisDisabled || isDragSelectionKind(regionMode)) {
      setShowAIBtn(false);
      setSelectedText('');
      return;
    }
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
  }, [analysisDisabled, regionMode]);

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
    if (!analysisDisabled && selectedText && onAnalyzeText) {
      const anchor = computeSelectionRectsAndPage();
      onAnalyzeText(selectedText, anchor.page, anchor);
    }
    setShowAIBtn(false);
    window.getSelection()?.removeAllRanges();
  }, [analysisDisabled, computeSelectionRectsAndPage, selectedText, onAnalyzeText]);

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
  const deferredObservedPageRef = useRef<number | null>(null);
  const pendingScrollReleaseTimerRef = useRef<number | null>(null);
  const scrollLockGenerationRef = useRef(0);
  // Pdf document instance — needed to resolve internal-link annotations
  // (the "[14]" citation references that ship as Link annotations in
  // every modern journal PDF).
  const pdfDocRef = useRef<PdfDocumentLike | null>(null);
  // Flash pulse for the destination page after a link jump so the user
  // notices the scroll actually moved.
  const [flashPage, setFlashPage] = useState<number | null>(null);

  const scrollToPageAnchor = useCallback((
    target: number,
    rects: readonly { x: number; y: number; w: number; h: number }[],
  ): boolean => {
    if (!numPages || numPages <= 0) return false;
    const clamped = Math.max(1, Math.min(numPages, Math.floor(target)));
    const pageElement = pageRefsRef.current[clamped - 1];
    const container = scrollContainerRef.current;
    const validRects = rects.filter((rect) => (
      Number.isFinite(rect.x)
      && Number.isFinite(rect.y)
      && Number.isFinite(rect.w)
      && Number.isFinite(rect.h)
      && rect.w > 0
      && rect.h > 0
    ));
    if (!pageElement || !container || validRects.length === 0) return false;

    const left = Math.min(...validRects.map((rect) => rect.x));
    const right = Math.max(...validRects.map((rect) => rect.x + rect.w));
    const top = Math.min(...validRects.map((rect) => rect.y));
    const bottom = Math.max(...validRects.map((rect) => rect.y + rect.h));
    const anchorCenterX = Math.max(0, Math.min(1, (left + right) / 2));
    const anchorCenterY = Math.max(0, Math.min(1, (top + bottom) / 2));
    const pageRect = pageElement.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    if (
      !Number.isFinite(pageRect.left)
      || !Number.isFinite(pageRect.width)
      || pageRect.width <= 0
      || !Number.isFinite(pageRect.top)
      || !Number.isFinite(pageRect.height)
      || pageRect.height <= 0
      || !Number.isFinite(containerRect.left)
      || !Number.isFinite(containerRect.top)
    ) {
      return false;
    }

    const desiredLeft = container.scrollLeft
      + (pageRect.left - containerRect.left)
      + (pageRect.width * anchorCenterX)
      - (container.clientWidth / 2);
    const desiredTop = container.scrollTop
      + (pageRect.top - containerRect.top)
      + (pageRect.height * anchorCenterY)
      - (container.clientHeight / 2);
    const maxScrollLeft = container.scrollWidth - container.clientWidth;
    const maxScrollTop = container.scrollHeight - container.clientHeight;
    const boundedLeft = maxScrollLeft > 0
      ? Math.max(0, Math.min(maxScrollLeft, desiredLeft))
      : Math.max(0, desiredLeft);
    const boundedTop = maxScrollTop > 0
      ? Math.max(0, Math.min(maxScrollTop, desiredTop))
      : Math.max(0, desiredTop);
    container.scrollTo({ left: boundedLeft, top: boundedTop, behavior: 'smooth' });
    setPageNumber(clamped);
    return true;
  }, [numPages]);

  const goToPageWithScrollLock = useCallback((target: number): void => {
    if (!numPages || numPages <= 0) return;
    const clamped = Math.max(1, Math.min(numPages, Math.floor(target)));
    const generation = scrollLockGenerationRef.current + 1;
    scrollLockGenerationRef.current = generation;
    if (pendingScrollReleaseTimerRef.current !== null) {
      window.clearTimeout(pendingScrollReleaseTimerRef.current);
    }
    pendingScrollPageRef.current = clamped;
    deferredObservedPageRef.current = null;
    goToPage(clamped);
    pendingScrollReleaseTimerRef.current = window.setTimeout(() => {
      if (scrollLockGenerationRef.current !== generation) return;
      if (pendingScrollPageRef.current === clamped) {
        pendingScrollPageRef.current = null;
        const deferredPage = deferredObservedPageRef.current;
        deferredObservedPageRef.current = null;
        if (deferredPage !== null) {
          setPageNumber((previous) => (previous === deferredPage ? previous : deferredPage));
        }
      }
      pendingScrollReleaseTimerRef.current = null;
    }, 600);
  }, [goToPage, numPages]);

  const goToPageAnchorWithScrollLock = useCallback((
    target: number,
    rects: readonly { x: number; y: number; w: number; h: number }[],
  ): void => {
    if (!numPages || numPages <= 0) return;
    const clamped = Math.max(1, Math.min(numPages, Math.floor(target)));
    const generation = scrollLockGenerationRef.current + 1;
    scrollLockGenerationRef.current = generation;
    if (pendingScrollReleaseTimerRef.current !== null) {
      window.clearTimeout(pendingScrollReleaseTimerRef.current);
    }
    pendingScrollPageRef.current = clamped;
    deferredObservedPageRef.current = null;
    if (!scrollToPageAnchor(clamped, rects)) goToPage(clamped);
    pendingScrollReleaseTimerRef.current = window.setTimeout(() => {
      if (scrollLockGenerationRef.current !== generation) return;
      if (pendingScrollPageRef.current === clamped) {
        pendingScrollPageRef.current = null;
        const deferredPage = deferredObservedPageRef.current;
        deferredObservedPageRef.current = null;
        if (deferredPage !== null) {
          setPageNumber((previous) => (previous === deferredPage ? previous : deferredPage));
        }
      }
      pendingScrollReleaseTimerRef.current = null;
    }, 600);
  }, [goToPage, numPages, scrollToPageAnchor]);

  useEffect(() => () => {
    scrollLockGenerationRef.current += 1;
    if (pendingScrollReleaseTimerRef.current !== null) {
      window.clearTimeout(pendingScrollReleaseTimerRef.current);
    }
    pendingScrollReleaseTimerRef.current = null;
    pendingScrollPageRef.current = null;
    deferredObservedPageRef.current = null;
  }, []);

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
    if (numPages <= 0) return;
    const hasCitationAnchorInput = initialBbox !== undefined || normalizedCitationQuote !== null;
    if (hasCitationAnchorInput && citationTargetPage === null) {
      setPageNumber(1);
      return;
    }
    if (initialPage === undefined) return;
    if (activeCitationBboxRect) {
      if (citationTargetPage !== null) {
        goToPageAnchorWithScrollLock(citationTargetPage, [activeCitationBboxRect]);
      }
      return;
    }
    goToPageWithScrollLock(citationTargetPage ?? initialPage);
  }, [
    activeCitationBboxRect,
    citationTargetPage,
    goToPageAnchorWithScrollLock,
    goToPageWithScrollLock,
    initialBbox,
    initialPage,
    normalizedCitationQuote,
    numPages,
  ]);

  useEffect(() => {
    setCitationQuoteHighlight(null);
    if (!normalizedCitationQuote) {
      setCitationBboxFallbackKey(null);
      setCitationAnchorStatus(citationBboxRect && citationTargetPage !== null ? 'matched' : 'idle');
      return undefined;
    }
    if (citationQuotePages.length === 0 || numPages <= 0) {
      setCitationBboxFallbackKey(null);
      setCitationAnchorStatus('page_only');
      return undefined;
    }

    const pdf = pdfDocRef.current;
    if (!pdf || typeof pdf.getPage !== 'function') {
      if (citationBboxRect && citationTargetPage !== null) {
        setCitationBboxFallbackKey(citationAnchorInputKey);
        setCitationAnchorStatus('matched');
      } else {
        setCitationBboxFallbackKey(null);
        setCitationAnchorStatus('page_only');
      }
      return undefined;
    }

    let cancelled = false;
    let observer: MutationObserver | null = null;
    let retryTimer: number | null = null;
    let finalTimer: number | null = null;
    setCitationAnchorStatus('resolving');

    const disposeWatchers = (): void => {
      observer?.disconnect();
      observer = null;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      if (finalTimer !== null) window.clearTimeout(finalTimer);
      retryTimer = null;
      finalTimer = null;
    };
    const finishFallback = (): void => {
      if (cancelled) return;
      disposeWatchers();
      setCitationQuoteHighlight(null);
      if (citationBboxRect && citationTargetPage !== null) {
        setCitationBboxFallbackKey(citationAnchorInputKey);
        setCitationAnchorStatus('matched');
      } else {
        setCitationBboxFallbackKey(null);
        setCitationAnchorStatus('page_only');
      }
    };
    const finishMatched = (page: number, match: PdfQuoteAnchorMatch): void => {
      if (cancelled) return;
      disposeWatchers();
      setCitationBboxFallbackKey(null);
      setCitationQuoteHighlight({
        page,
        text: match.quote,
        color: '#60A5FA',
        rects: match.rects.map((rect) => ({ ...rect })),
      });
      setCitationAnchorStatus('matched');
      goToPageAnchorWithScrollLock(page, match.rects);
      setFlashPage(page);
    };

    void (async () => {
      try {
        let matchedPage: number | null = null;
        for (const page of citationQuotePages) {
          const pdfPage = await pdf.getPage?.(page);
          if (cancelled) return;
          if (!pdfPage || typeof pdfPage.getTextContent !== 'function') {
            finishFallback();
            return;
          }
          const occurrences = countPdfQuoteOccurrences(
            extractPdfTextContent(await pdfPage.getTextContent()),
            normalizedCitationQuote,
          );
          if (cancelled) return;
          if (occurrences > 1 || (occurrences === 1 && matchedPage !== null)) {
            finishFallback();
            return;
          }
          if (occurrences === 1) matchedPage = page;
        }

        if (matchedPage === null) {
          finishFallback();
          return;
        }

        const mapRenderedTextLayer = (): boolean => {
          const pageElement = pageRefsRef.current[matchedPage - 1];
          const textLayer = pageElement?.querySelector<HTMLElement>(
            '.react-pdf__Page__textContent.textLayer, .textLayer',
          );
          if (!textLayer) return false;
          const resolution = resolvePdfQuoteAnchor(textLayer, normalizedCitationQuote);
          if (resolution.status === 'matched') {
            finishMatched(matchedPage, resolution.match);
            return true;
          }
          if (resolution.status === 'ambiguous') {
            finishFallback();
            return true;
          }
          return false;
        };
        const scheduleMap = (): void => {
          if (cancelled || retryTimer !== null) return;
          retryTimer = window.setTimeout(() => {
            retryTimer = null;
            mapRenderedTextLayer();
          }, 0);
        };

        if (typeof MutationObserver !== 'undefined' && pageWrapperRef.current) {
          observer = new MutationObserver(scheduleMap);
          observer.observe(pageWrapperRef.current, {
            childList: true,
            subtree: true,
            characterData: true,
          });
        }
        scheduleMap();
        finalTimer = window.setTimeout(() => {
          if (!mapRenderedTextLayer()) finishFallback();
        }, 4000);
      } catch {
        finishFallback();
      }
    })();

    return () => {
      cancelled = true;
      disposeWatchers();
    };
  }, [citationAnchorInputKey, citationBboxRect, citationQuotePages, citationTargetPage, goToPageAnchorWithScrollLock, loadAttempt, normalizedCitationQuote, numPages]);

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
          if (pendingScrollPageRef.current) {
            if (pendingScrollPageRef.current !== best.page) {
              deferredObservedPageRef.current = best.page;
              return;
            }
            deferredObservedPageRef.current = null;
          }
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
    const m = new Map<number, PdfViewerHighlight[]>();
    for (const h of highlights ?? []) {
      const list = m.get(h.page);
      if (list) list.push(h);
      else m.set(h.page, [h]);
    }
    if (citationQuoteHighlight) {
      const list = m.get(citationQuoteHighlight.page);
      if (list) list.push(citationQuoteHighlight);
      else m.set(citationQuoteHighlight.page, [citationQuoteHighlight]);
    }
    if (citationBboxHighlight) {
      const list = m.get(citationBboxHighlight.page);
      if (list) list.push(citationBboxHighlight);
      else m.set(citationBboxHighlight.page, [citationBboxHighlight]);
    }
    return m;
  }, [citationBboxHighlight, citationQuoteHighlight, highlights]);
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
      for (const page of citationQuotePages) pages.add(page);
    }
    return pages;
  }, [citationQuotePages, flashPage, highlightsByPage, numPages, pageNumber]);
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

  const handlePdfPageRenderSuccess = useCallback((
    pageNo: number,
    expectedActivationKey: string | null,
  ): void => {
    const pageElement = pageRefsRef.current[pageNo - 1];
    updateMeasuredPageHeight(pageNo, pageElement);
    if (
      !expectedActivationKey
      || activeCitationBboxActivationKeyRef.current !== expectedActivationKey
      || pendingCitationBboxRenderKeyRef.current !== expectedActivationKey
      || !citationBboxRect
      || citationTargetPage === null
      || pageNo !== citationTargetPage
    ) return;
    pendingCitationBboxRenderKeyRef.current = null;
    goToPageAnchorWithScrollLock(citationTargetPage, [citationBboxRect]);
  }, [citationBboxRect, citationTargetPage, goToPageAnchorWithScrollLock, updateMeasuredPageHeight]);

  const toggleRegionMode = useCallback((kind: PdfVisualSelectionKind): void => {
    if (analysisDisabled) return;
    setRegionMode((current) => current === kind ? null : kind);
    setRegionDraft(null);
    setRegionStatus(null);
    setShowAIBtn(false);
    setSelectedText('');
    window.getSelection()?.removeAllRanges();
  }, [analysisDisabled]);

  const handleRegionPointerDown = useCallback((
    page: number,
    event: ReactPointerEvent<HTMLDivElement>,
  ): void => {
    if (analysisDisabled || !isDragSelectionKind(regionMode) || event.button !== 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = {
      x: clampRatio((event.clientX - rect.left) / rect.width),
      y: clampRatio((event.clientY - rect.top) / rect.height),
    };
    setRegionStatus(null);
    setRegionDraft({ page, pointerId: event.pointerId, start: point, current: point });
  }, [analysisDisabled, regionMode]);

  const handleRegionPointerMove = useCallback((
    page: number,
    event: ReactPointerEvent<HTMLDivElement>,
  ): void => {
    if (analysisDisabled || !isDragSelectionKind(regionMode) || !regionDraft || regionDraft.page !== page || regionDraft.pointerId !== event.pointerId) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    event.preventDefault();
    setRegionDraft((current) => current ? {
      ...current,
      current: {
        x: clampRatio((event.clientX - rect.left) / rect.width),
        y: clampRatio((event.clientY - rect.top) / rect.height),
      },
    } : null);
  }, [analysisDisabled, regionDraft, regionMode]);

  const finishRegionSelection = useCallback(async (
    page: number,
    event: ReactPointerEvent<HTMLDivElement>,
  ): Promise<void> => {
    if (analysisDisabled || !isDragSelectionKind(regionMode) || !regionDraft || regionDraft.page !== page || regionDraft.pointerId !== event.pointerId) return;
    const selectionKind = regionMode;
    const pageElement = event.currentTarget;
    const pageRect = pageElement.getBoundingClientRect();
    event.preventDefault();
    event.stopPropagation();
    const end = {
      x: clampRatio((event.clientX - pageRect.left) / pageRect.width),
      y: clampRatio((event.clientY - pageRect.top) / pageRect.height),
    };
    const bbox = regionBbox(regionDraft.start, end);
    setRegionDraft(null);
    if (pageElement.hasPointerCapture(event.pointerId)) {
      pageElement.releasePointerCapture(event.pointerId);
    }
    if (bbox[2] * pageRect.width < PDF_REGION_MIN_SIZE_PX || bbox[3] * pageRect.height < PDF_REGION_MIN_SIZE_PX) {
      setRegionStatus('框选范围太小，请重新拖拽。');
      return;
    }
    setRegionStatus('正在准备选区内容…');
    try {
      const capture = await capturePdfRegion(pageElement, bbox, selectionKind, page);
      if (!analysisDisabledRef.current) {
        onAnalyzeRegion?.(capture);
      }
      setRegionStatus(null);
    } catch (error) {
      setRegionStatus(error instanceof Error ? error.message : '框选失败，请重试。');
    }
  }, [analysisDisabled, onAnalyzeRegion, regionDraft, regionMode]);

  const cancelRegionSelection = useCallback((event: ReactPointerEvent<HTMLDivElement>): void => {
    if (regionDraft && event.currentTarget.hasPointerCapture(regionDraft.pointerId)) {
      event.currentTarget.releasePointerCapture(regionDraft.pointerId);
    }
    setRegionDraft(null);
  }, [regionDraft]);

  const handleFormulaCandidateClick = useCallback(async (
    candidate: PdfFormulaCandidate,
    event: ReactMouseEvent<HTMLButtonElement>,
  ): Promise<void> => {
    event.preventDefault();
    event.stopPropagation();
    if (
      analysisDisabled
      || regionMode !== 'formula'
      || formulaCaptureInFlightRef.current
    ) return;
    const pageElement = event.currentTarget.closest('[data-page-number]') as HTMLDivElement | null;
    if (!pageElement) {
      setRegionStatus('无法定位公式所在页面，请重新加载后重试。');
      return;
    }

    formulaCaptureInFlightRef.current = true;
    setPendingFormulaCandidateId(candidate.candidateId);
    setRegionStatus('正在准备公式内容…');
    try {
      const capture = await capturePdfRegion(
        pageElement,
        candidate.bbox,
        'formula',
        candidate.page,
        {
          candidateId: candidate.candidateId,
          chunkId: candidate.chunkId,
          text: candidate.text,
        },
      );
      if (!analysisDisabledRef.current) {
        onAnalyzeRegion?.(capture);
      }
      setRegionStatus(null);
    } catch (error) {
      setRegionStatus(error instanceof Error ? error.message : '公式选择失败，请重试。');
    } finally {
      formulaCaptureInFlightRef.current = false;
      setPendingFormulaCandidateId(null);
    }
  }, [analysisDisabled, onAnalyzeRegion, regionMode]);

  const activeSelectionStatus = regionStatus ?? (
    regionMode === 'formula'
      ? formulaCandidatesByPage.size > 0
        ? '整条公式选择已开启；可连续选择公式，也可直接划选正文。'
        : '当前文献尚未识别到可整体选择的公式；正文仍可直接划选。'
      : regionMode
        ? `拖拽框选${regionMode === 'figure' ? '图' : regionMode === 'table' ? '表' : '区域'}；可连续选择多个内容。`
        : null
  );
  const selectionStatusIsWarning = Boolean(
    regionStatus || (regionMode === 'formula' && formulaCandidatesByPage.size === 0),
  );

  return (
    <div
      ref={viewerRootRef}
      data-testid="pdf-viewer"
      data-citation-anchor-status={citationAnchorStatus}
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
          {onAnalyzeRegion && (
            <>
              <span className="mx-1 h-4 w-px bg-outline-variant/70" aria-hidden />
              <button
                type="button"
                onClick={() => toggleRegionMode('figure')}
                disabled={analysisDisabled}
                className={cn(
                  'inline-flex h-7 items-center gap-1 rounded px-2 text-[10px] font-label text-foreground/75 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent',
                  regionMode === 'figure' && 'bg-primary/12 text-primary ring-1 ring-primary/35',
                )}
                aria-pressed={regionMode === 'figure'}
                title="拖拽框选图，并附到本次提问"
              >
                <ImageIcon size={13} aria-hidden />
                图
              </button>
              <button
                type="button"
                onClick={() => toggleRegionMode('table')}
                disabled={analysisDisabled}
                className={cn(
                  'inline-flex h-7 items-center gap-1 rounded px-2 text-[10px] font-label text-foreground/75 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent',
                  regionMode === 'table' && 'bg-primary/12 text-primary ring-1 ring-primary/35',
                )}
                aria-pressed={regionMode === 'table'}
                title="拖拽框选表，并附到本次提问"
              >
                <Table2 size={13} aria-hidden />
                表
              </button>
              <button
                type="button"
                onClick={() => toggleRegionMode('formula')}
                disabled={analysisDisabled}
                className={cn(
                  'inline-flex h-7 items-center gap-1 rounded px-2 text-[10px] font-label text-foreground/75 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent',
                  regionMode === 'formula' && 'bg-primary/12 text-primary ring-1 ring-primary/35',
                )}
                aria-pressed={regionMode === 'formula'}
                title="按完整公式选择，并附到本次提问"
              >
                <Sigma size={13} aria-hidden />
                公式
              </button>
              <button
                type="button"
                onClick={() => toggleRegionMode('region')}
                disabled={analysisDisabled}
                className={cn(
                  'inline-flex h-7 items-center gap-1 rounded px-2 text-[10px] font-label text-foreground/75 transition-colors hover:bg-surface-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent',
                  regionMode === 'region' && 'bg-primary/12 text-primary ring-1 ring-primary/35',
                )}
                aria-pressed={regionMode === 'region'}
                title="拖拽框选任意区域，并附到本次提问"
              >
                <ScanSearch size={13} aria-hidden />
                区域
              </button>
            </>
          )}
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

      {activeSelectionStatus && (
        <div
          className={cn(
            'flex min-h-8 items-center justify-between gap-3 border-b border-outline-variant/60 px-3 py-1 text-[11px] font-label',
            selectionStatusIsWarning
              ? 'bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200'
              : 'bg-primary/10 text-foreground/70',
          )}
          role="status"
        >
          <span>{activeSelectionStatus}</span>
          <button
            type="button"
            onClick={() => {
              setRegionMode(null);
              setRegionDraft(null);
              setRegionStatus(null);
            }}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-foreground/55 hover:bg-surface-high hover:text-foreground"
            aria-label={regionMode === 'formula' ? '退出公式选择' : '取消框选'}
            title={regionMode === 'formula' ? '退出公式选择' : '取消框选'}
          >
            <X size={13} aria-hidden />
          </button>
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* PDF pages — continuous vertical scroll (Zotero-style). */}
        <div
          ref={scrollContainerRef}
          className={cn(
            'flex-1 overflow-auto flex flex-col items-center py-4 gap-4',
            analysisDisabled && 'select-none',
          )}
          onMouseUp={handleMouseUp}
          aria-disabled={analysisDisabled || undefined}
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
                  const pageFormulaCandidates = formulaCandidatesByPage.get(pageNo) ?? EMPTY_FORMULA_CANDIDATES;
                  const pageSelectedVisualRegions = selectedVisualRegionsByPage.get(pageNo) ?? EMPTY_SELECTED_VISUAL_REGIONS;
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
                      onPointerDown={(event) => handleRegionPointerDown(pageNo, event)}
                      onPointerMove={(event) => handleRegionPointerMove(pageNo, event)}
                      onPointerUp={(event) => { void finishRegionSelection(pageNo, event); }}
                      onPointerCancel={cancelRegionSelection}
                      className={cn(
                        'relative inline-block shadow-sm transition-shadow',
                        isFlashing && 'ring-2 ring-primary/60 shadow-lg',
                        isDragSelectionKind(regionMode) && 'cursor-crosshair select-none touch-none',
                      )}
                      style={renderPage ? undefined : { minHeight: placeholderHeight }}
                      aria-label={`PDF 第 ${pageNo} 页`}
                    >
                      {renderPage ? (
                        <Page
                          pageNumber={pageNo}
                          scale={scale}
                          onRenderSuccess={() => handlePdfPageRenderSuccess(
                            pageNo,
                            citationBboxActivationKey,
                          )}
                        />
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
                                data-testid={
                                  h === citationQuoteHighlight
                                    ? 'pdf-citation-quote-highlight'
                                    : h === citationBboxHighlight
                                      ? 'pdf-citation-bbox-highlight'
                                      : undefined
                                }
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
                      {renderPage && pageSelectedVisualRegions.length > 0 && (
                        <div className="pointer-events-none absolute inset-0 z-10" aria-hidden>
                          {pageSelectedVisualRegions.map((selection, selectionIndex) => (
                            <div
                              key={`${selection.candidateId ?? selection.kind}-${selection.bbox.join('-')}-${selectionIndex}`}
                              data-testid="pdf-selected-visual-region"
                              data-selection-kind={selection.kind}
                              className="absolute rounded-sm border-2 border-primary/80 bg-primary/5 shadow-[0_0_0_1px_rgba(255,255,255,0.65)]"
                              style={{
                                left: `${selection.bbox[0] * 100}%`,
                                top: `${selection.bbox[1] * 100}%`,
                                width: `${selection.bbox[2] * 100}%`,
                                height: `${selection.bbox[3] * 100}%`,
                              }}
                            />
                          ))}
                        </div>
                      )}
                      {renderPage && regionMode === 'formula' && pageFormulaCandidates.length > 0 && (
                        <div className="pointer-events-none absolute inset-0 z-20" role="group" aria-label={`第 ${pageNo} 页公式`}>
                          {pageFormulaCandidates.map((candidate, candidateIndex) => (
                            <button
                              key={candidate.candidateId}
                              type="button"
                              data-formula-candidate-id={candidate.candidateId}
                              className="pointer-events-auto absolute border border-transparent bg-transparent transition-colors hover:border-primary/70 hover:bg-primary/5 focus-visible:border-primary focus-visible:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:pointer-events-none disabled:opacity-50"
                              style={{
                                left: `${candidate.bbox[0] * 100}%`,
                                top: `${candidate.bbox[1] * 100}%`,
                                width: `${candidate.bbox[2] * 100}%`,
                                height: `${candidate.bbox[3] * 100}%`,
                              }}
                              aria-label={`选择第 ${pageNo} 页公式 ${candidateIndex + 1}`}
                              title="选择整条公式"
                              disabled={analysisDisabled || pendingFormulaCandidateId !== null}
                              onClick={(event) => { void handleFormulaCandidateClick(candidate, event); }}
                            />
                          ))}
                        </div>
                      )}
                      {regionDraft?.page === pageNo && (
                        <div className="pointer-events-none absolute inset-0 z-20" aria-hidden>
                          <div
                            data-testid="pdf-region-draft"
                            className="absolute border-2 border-primary bg-primary/10 shadow-[0_0_0_9999px_rgba(15,23,42,0.18)]"
                            style={{
                              left: `${regionBbox(regionDraft.start, regionDraft.current)[0] * 100}%`,
                              top: `${regionBbox(regionDraft.start, regionDraft.current)[1] * 100}%`,
                              width: `${regionBbox(regionDraft.start, regionDraft.current)[2] * 100}%`,
                              height: `${regionBbox(regionDraft.start, regionDraft.current)[3] * 100}%`,
                            }}
                          />
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
      {!analysisDisabled && showAIBtn && selectedText && (
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
  hasEOL?: unknown;
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
  const fragments: string[] = [];
  for (const item of content.items) {
    const textItem = item as PdfTextItemLike | null;
    if (typeof textItem?.str === 'string') fragments.push(textItem.str);
    if (textItem?.hasEOL === true) fragments.push('\n');
  }
  return fragments.join('');
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
