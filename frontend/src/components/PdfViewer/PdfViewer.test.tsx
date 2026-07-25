import { useState } from 'react';
import type { ComponentProps } from 'react';
import { fireEvent, render, screen, act, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PdfViewer, formatPdfLoadError } from './PdfViewer';

let mockPdfPageCount = 5;
let renderedPdfPageNumbers: number[] = [];
let renderedPdfDocumentOptions: Array<{ isEvalSupported?: boolean } | undefined> = [];
let pdfPageTexts: Record<number, string> = {};
let pdfPageTextItems: Record<number, string[]> = {};
let pdfPageTextEolAfter: Record<number, readonly number[]> = {};
let mockIntersectionObservers: MockIntersectionObserver[] = [];
let pdfPageRenderSuccessCallbacks = new Map<number, () => void>();

function textItemsForPage(pageNumber: number): string[] {
  return pdfPageTextItems[pageNumber] ?? [pdfPageTexts[pageNumber] ?? ''];
}

// react-pdf depends on a real worker + canvas. Mock it so the test stays
// deterministic and runs in jsdom. The mock surfaces the page number and
// fires onLoadSuccess once so toolbar clamping logic can run end-to-end.
vi.mock('react-pdf', async () => {
  const React = await import('react');

  type DocumentProps = {
    onLoadSuccess?: (info: { numPages: number }) => void;
    options?: { isEvalSupported?: boolean };
    children?: React.ReactNode;
  };

  type PageProps = {
    pageNumber: number;
    onRenderSuccess?: () => void;
  };

  return {
    pdfjs: { GlobalWorkerOptions: { workerSrc: '' } },
    Document: ({ onLoadSuccess, options, children }: DocumentProps) => {
      renderedPdfDocumentOptions.push(options);
      React.useEffect(() => {
        onLoadSuccess?.({
          numPages: mockPdfPageCount,
          async getPage(pageNumber: number) {
            return {
               async getTextContent() {
                 return {
                   items: textItemsForPage(pageNumber).map((str, index) => ({
                     str,
                     hasEOL: pdfPageTextEolAfter[pageNumber]?.includes(index) === true,
                   })),
                 };
              },
            };
          },
        } as { numPages: number });
      }, [onLoadSuccess]);
      return <div data-testid="pdf-document">{children}</div>;
    },
    Page: ({ pageNumber, onRenderSuccess }: PageProps) => {
      renderedPdfPageNumbers.push(pageNumber);
      if (onRenderSuccess) pdfPageRenderSuccessCallbacks.set(pageNumber, onRenderSuccess);
      const textItems = textItemsForPage(pageNumber);
      return (
        <div className="react-pdf__Page" data-page-number={pageNumber} data-testid="pdf-page">
          page-{pageNumber}
          <div className="react-pdf__Page__textContent textLayer">
            {textItems.map((text, index) => (
              <React.Fragment key={`${pageNumber}:${index}`}>
                <span>{text}</span>
                {pdfPageTextEolAfter[pageNumber]?.includes(index) === true ? <br /> : null}
              </React.Fragment>
            ))}
          </div>
          <canvas className="react-pdf__Page__canvas" width={1000} height={1200} />
        </div>
      );
    },
  };
});

vi.mock('react-pdf/dist/Page/AnnotationLayer.css', () => ({}));
vi.mock('react-pdf/dist/Page/TextLayer.css', () => ({}));

class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin = '0px';
  readonly thresholds = [0];

  constructor(private readonly callback: IntersectionObserverCallback) {
    mockIntersectionObservers.push(this);
  }

  disconnect(): void {}
  observe(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
  unobserve(): void {}

  trigger(entries: IntersectionObserverEntry[]): void {
    this.callback(entries, this);
  }
}

function intersectionEntry(target: Element, intersectionRatio = 1): IntersectionObserverEntry {
  const bounds = target.getBoundingClientRect();
  return {
    target,
    time: 0,
    rootBounds: null,
    boundingClientRect: bounds,
    intersectionRect: bounds,
    isIntersecting: true,
    intersectionRatio,
  };
}

const PDF_BYTES = new Uint8Array([37, 80, 68, 70]);

beforeEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  mockPdfPageCount = 5;
  renderedPdfPageNumbers = [];
  renderedPdfDocumentOptions = [];
  pdfPageTextItems = {};
  pdfPageTextEolAfter = {};
  mockIntersectionObservers = [];
  pdfPageRenderSuccessCallbacks = new Map();
  pdfPageTexts = {
    1: 'introduction and framing',
    2: 'evidence synthesis and baseline',
    3: 'methods evidence and measurements',
    4: 'discussion and limitations',
    5: 'appendix materials',
  };
  vi.stubGlobal('IntersectionObserver', MockIntersectionObserver);
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: () => 'blob:mock-pdf-url',
  });
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: () => undefined,
  });
  Object.defineProperty(window, 'print', {
    configurable: true,
    writable: true,
    value: () => undefined,
  });
  Object.defineProperty(document, 'fullscreenEnabled', {
    configurable: true,
    writable: true,
    value: false,
  });
  Object.defineProperty(document, 'fullscreenElement', {
    configurable: true,
    writable: true,
    value: null,
  });
  Object.defineProperty(document, 'exitFullscreen', {
    configurable: true,
    writable: true,
    value: undefined,
  });
  Object.defineProperty(HTMLElement.prototype, 'requestFullscreen', {
    configurable: true,
    writable: true,
    value: undefined,
  });
  Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', {
    configurable: true,
    writable: true,
    value: vi.fn(() => true),
  });
  Object.defineProperty(HTMLElement.prototype, 'releasePointerCapture', {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
    configurable: true,
    writable: true,
    value: vi.fn(() => ({
      fillStyle: '#ffffff',
      fillRect: vi.fn(),
      drawImage: vi.fn(),
    })),
  });
  Object.defineProperty(HTMLCanvasElement.prototype, 'toBlob', {
    configurable: true,
    writable: true,
    value: vi.fn((callback: BlobCallback, type?: string) => {
      callback(new Blob(['captured-pdf-region'], { type: type || 'image/png' }));
    }),
  });
});

afterEach(() => {
  vi.useRealTimers();
});

function renderViewer(props: Partial<ComponentProps<typeof PdfViewer>> = {}) {
  return render(
    <PdfViewer
      url="/fake/path.pdf"
      materialId="mat_smoke"
      bytes={PDF_BYTES}
      {...props}
    />,
  );
}

function getCurrentPageButton(page: number): HTMLButtonElement {
  return screen.getByRole('button', { name: `当前页 ${page}，点击跳转` }) as HTMLButtonElement;
}

function installTextSelectionMock(text: string, rect: DOMRect, anchorNode: Node): void {
  if (text.trim().length === 0) {
    throw new Error('selection text must be non-empty');
  }
  const range = {
    startContainer: anchorNode,
    getBoundingClientRect: () => rect,
  } as unknown as Range;
  const selection = {
    anchorNode,
    focusNode: anchorNode,
    toString: () => text,
    rangeCount: 1,
    getRangeAt: () => range,
    removeAllRanges: vi.fn(),
  } as unknown as Selection;
  vi.spyOn(window, 'getSelection').mockReturnValue(selection);
}

function installQuoteRangeGeometry(rects: readonly DOMRect[]): void {
  const createRange = document.createRange.bind(document);
  vi.spyOn(document, 'createRange').mockImplementation(() => {
    const range = createRange();
    Object.defineProperty(range, 'getClientRects', {
      configurable: true,
      value: () => Object.assign([...rects], {
        item(index: number): DOMRect | null {
          return rects[index] ?? null;
        },
      }) as DOMRectList,
    });
    return range;
  });
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
    .mockReturnValue(new DOMRect(0, 0, 1000, 1200));
}

function firePointerEvent(
  target: Element,
  type: 'pointerdown' | 'pointerup',
  init: { button: number; pointerId: number; clientX: number; clientY: number },
): void {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    button: init.button,
    clientX: init.clientX,
    clientY: init.clientY,
  });
  Object.defineProperty(event, 'pointerId', { configurable: true, value: init.pointerId });
  fireEvent(target, event);
}

describe('PdfViewer', () => {
  it('disables PDF.js string eval while loading documents', async () => {
    await act(async () => {
      renderViewer();
    });

    expect(renderedPdfDocumentOptions).toContainEqual({ isEvalSupported: false });
  });

  it('formats PDF load errors without exposing technical detail', () => {
    const unsafe = formatPdfLoadError(
      500,
      '/resources/material/mat-1/file env=VISION_PROVIDER capability_resolved C:\\tmp\\trace.log',
    );
    const safe = formatPdfLoadError(404, '未找到原始 PDF 文件。');

    expect(unsafe).toBe('PDF 加载失败（HTTP 500）：PDF 文件读取失败，请稍后重试。');
    expect(unsafe).not.toContain('/resources');
    expect(unsafe).not.toContain('env=');
    expect(unsafe).not.toContain('capability_resolved');
    expect(unsafe).not.toContain('C:\\tmp');
    expect(safe).toBe('PDF 加载失败（HTTP 404）：未找到原始 PDF 文件。');
  });

  it('opens at initialPage when provided', async () => {
    await act(async () => {
      renderViewer({ initialPage: 3 });
    });
    expect(getCurrentPageButton(3)).toBeInTheDocument();
  });

  it('replays the final observed page when the programmatic scroll lock expires', async () => {
    vi.useFakeTimers();
    await act(async () => {
      renderViewer({ initialPage: 3 });
    });

    const observer = mockIntersectionObservers[mockIntersectionObservers.length - 1];
    const pageTwo = screen.getAllByTestId('pdf-page').find(
      (element) => element.getAttribute('data-page-number') === '2',
    );
    const pageFour = screen.getAllByTestId('pdf-page').find(
      (element) => element.getAttribute('data-page-number') === '4',
    );
    expect(observer).toBeDefined();
    expect(pageTwo).toBeDefined();
    expect(pageFour).toBeDefined();
    if (!observer || !pageTwo || !pageFour) throw new Error('PDF observer test setup failed');

    act(() => observer.trigger([intersectionEntry(pageTwo)]));
    act(() => observer.trigger([intersectionEntry(pageFour)]));
    expect(getCurrentPageButton(3)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(601);
    });
    expect(getCurrentPageButton(4)).toBeInTheDocument();
  });

  it('does not let an older same-page scroll lock release a newer citation activation', async () => {
    const setTimeoutSpy = vi.spyOn(window, 'setTimeout');
    let view: ReturnType<typeof renderViewer>;
    await act(async () => {
      view = renderViewer({
        initialPage: 3,
        initialBbox: [0.1, 0.1, 0.2, 0.1],
      });
    });
    const firstRelease = setTimeoutSpy.mock.calls.find(([, delay]) => delay === 600)?.[0];
    expect(typeof firstRelease).toBe('function');

    await act(async () => {
      view.rerender(
        <PdfViewer
          url="/fake/path.pdf"
          materialId="mat_smoke"
          bytes={PDF_BYTES}
          initialPage={3}
          initialBbox={[0.1, 0.7, 0.2, 0.1]}
        />,
      );
    });
    const releaseCallbacks = setTimeoutSpy.mock.calls
      .filter(([, delay]) => delay === 600)
      .map(([callback]) => callback);
    const secondRelease = releaseCallbacks[releaseCallbacks.length - 1];
    expect(releaseCallbacks.length).toBeGreaterThanOrEqual(2);
    expect(typeof secondRelease).toBe('function');

    const observer = mockIntersectionObservers[mockIntersectionObservers.length - 1];
    const pageTwo = screen.getAllByTestId('pdf-page').find(
      (element) => element.getAttribute('data-page-number') === '2',
    );
    if (!observer || !pageTwo || typeof firstRelease !== 'function' || typeof secondRelease !== 'function') {
      throw new Error('PDF scroll-lock test setup failed');
    }
    act(() => observer.trigger([intersectionEntry(pageTwo)]));
    expect(getCurrentPageButton(3)).toBeInTheDocument();

    act(() => firstRelease());
    expect(getCurrentPageButton(3)).toBeInTheDocument();

    act(() => secondRelease());
    expect(getCurrentPageButton(2)).toBeInTheDocument();
  });

  it('maps a unique initial quote to sentence-level PDF highlight rectangles', async () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      writable: true,
      value: scrollTo,
    });
    installQuoteRangeGeometry([
      new DOMRect(100, 900, 520, 36),
      new DOMRect(100, 942, 260, 36),
    ]);

    await act(async () => {
      renderViewer({
        initialPage: 3,
        initialQuote: '  evidence and\n measurements  ',
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId('pdf-viewer')).toHaveAttribute(
        'data-citation-anchor-status',
        'matched',
      );
    });
    expect(screen.getAllByTestId('pdf-citation-quote-highlight')).toHaveLength(2);
    expect(getCurrentPageButton(3)).toBeInTheDocument();
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({
      behavior: 'smooth',
      top: expect.any(Number),
    }));
    expect(scrollTo.mock.calls.some(([options]) => (
      typeof options === 'object'
      && options !== null
      && typeof (options as ScrollToOptions).top === 'number'
      && ((options as ScrollToOptions).top ?? 0) > 0
    ))).toBe(true);
  });

  it('prefers a unique exact quote over a coarse citation bbox', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    installQuoteRangeGeometry([new DOMRect(100, 240, 520, 36)]);

    await act(async () => {
      renderViewer({
        initialPage: 3,
        initialQuote: 'evidence and measurements',
        initialBbox: [0.05, 0.15, 0.9, 0.7],
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId('pdf-viewer')).toHaveAttribute(
        'data-citation-anchor-status',
        'matched',
      );
    });
    expect(screen.getByTestId('pdf-citation-quote-highlight')).toBeInTheDocument();
    expect(screen.queryByTestId('pdf-citation-bbox-highlight')).not.toBeInTheDocument();
  });

  it('maps a quote across separate PDF.js text items without DOM whitespace', async () => {
    pdfPageTextItems[3] = ['methods ', 'evidence', 'and', 'measurements'];
    installQuoteRangeGeometry([new DOMRect(100, 240, 520, 36)]);

    await act(async () => {
      renderViewer({
        initialPage: 3,
        initialQuote: 'evidence and measurements',
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId('pdf-viewer')).toHaveAttribute(
        'data-citation-anchor-status',
        'matched',
      );
    });
    expect(screen.getByTestId('pdf-citation-quote-highlight')).toBeInTheDocument();
  });

  it('maps a quote across PDF.js text spans and an explicit end-of-line boundary', async () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    pdfPageTextItems[3] = ['methods', 'evidence', 'and', 'measurements'];
    pdfPageTextEolAfter[3] = [1];
    installQuoteRangeGeometry([
      new DOMRect(100, 240, 260, 36),
      new DOMRect(100, 282, 320, 36),
    ]);

    await act(async () => {
      renderViewer({
        initialPage: 3,
        initialQuote: 'evidence and measurements',
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId('pdf-viewer')).toHaveAttribute(
        'data-citation-anchor-status',
        'matched',
      );
    });
    expect(screen.getAllByTestId('pdf-citation-quote-highlight')).toHaveLength(2);
  });

  it('scrolls an explicit citation bbox to the center of its PDF page', async () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      writable: true,
      value: scrollTo,
    });
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue(new DOMRect(0, 0, 1000, 1200));

    await act(async () => {
      renderViewer({
        initialPage: 4,
        initialBbox: [0.1, 0.72, 0.45, 0.16],
      });
    });

    expect(getCurrentPageButton(4)).toBeInTheDocument();
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({
      behavior: 'smooth',
      top: expect.any(Number),
    }));
    expect(scrollTo.mock.calls.some(([options]) => (
      typeof options === 'object'
      && options !== null
      && typeof (options as ScrollToOptions).top === 'number'
      && ((options as ScrollToOptions).top ?? 0) > 0
    ))).toBe(true);
  });

  it('highlights the exact visual region for an explicit citation bbox', async () => {
    await act(async () => {
      renderViewer({
        initialPage: 4,
        initialBbox: [0.1, 0.72, 0.45, 0.16],
      });
    });

    const highlight = screen.getByTestId('pdf-citation-bbox-highlight');
    expect(highlight).toHaveStyle({
      left: '10%',
      top: '72%',
      width: '45%',
      height: '16%',
    });
    expect(highlight.closest('[data-page-number="4"]')).not.toBeNull();
  });

  it('centers an explicit citation bbox on both axes for a zoomed PDF page', async () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      writable: true,
      value: scrollTo,
    });
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(600);
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(2000);
    vi.spyOn(HTMLElement.prototype, 'scrollLeft', 'get').mockReturnValue(100);
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function getBoundingClientRect(this: HTMLElement): DOMRect {
        if (this.getAttribute('aria-label') === 'PDF 第 4 页') {
          return new DOMRect(200, 800, 1200, 1600);
        }
        if (this.classList.contains('overflow-auto')) {
          return new DOMRect(50, 100, 600, 700);
        }
        return new DOMRect(0, 0, 1000, 1200);
      });

    await act(async () => {
      renderViewer({
        initialPage: 4,
        initialBbox: [0.6, 0.2, 0.2, 0.1],
      });
    });

    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({
      left: 790,
      behavior: 'smooth',
    }));
  });

  it.each([
    ['zero', 0],
    ['past the final page', 6],
    ['fractional', 1.5],
    ['not-a-number', Number.NaN],
  ])('does not clamp a %s precise citation page onto another PDF page', async (_scenario, invalidPage) => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      writable: true,
      value: scrollTo,
    });

    await act(async () => {
      renderViewer({
        initialPage: invalidPage,
        initialBbox: [0.1, 0.2, 0.4, 0.1],
      });
    });

    expect(scrollTo).not.toHaveBeenCalled();
    expect(screen.queryByTestId('pdf-citation-bbox-highlight')).not.toBeInTheDocument();
    expect(getCurrentPageButton(1)).toBeInTheDocument();
  });

  it('repositions an explicit citation bbox after the target PDF page finishes rendering', async () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      writable: true,
      value: scrollTo,
    });
    let targetPageRendered = false;
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function getBoundingClientRect(this: HTMLElement): DOMRect {
        if (this.getAttribute('aria-label') === 'PDF 第 4 页') {
          return targetPageRendered
            ? new DOMRect(0, 900, 1000, 1200)
            : new DOMRect(0, 100, 1000, 200);
        }
        return new DOMRect(0, 0, 1000, 600);
      });

    await act(async () => {
      renderViewer({
        initialPage: 4,
        initialBbox: [0.1, 0.72, 0.45, 0.16],
      });
    });
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 260 }));

    const targetPage = screen.getAllByTestId('pdf-page').find(
      (element) => element.getAttribute('data-page-number') === '4',
    );
    expect(targetPage).toBeDefined();
    if (!targetPage) throw new Error('target PDF page did not render');
    const finishTargetPageRender = pdfPageRenderSuccessCallbacks.get(4);
    expect(finishTargetPageRender).toBeDefined();
    if (!finishTargetPageRender) throw new Error('target PDF render callback was not registered');
    targetPageRendered = true;
    act(() => finishTargetPageRender());

    await waitFor(() => {
      expect(scrollTo).toHaveBeenLastCalledWith(expect.objectContaining({
        top: 1860,
        behavior: 'smooth',
      }));
    });
  });

  it('ignores a stale page-render callback after a newer bbox activation on the same page', async () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      writable: true,
      value: scrollTo,
    });
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue(new DOMRect(0, 0, 1000, 1200));

    const view = renderViewer({
      initialPage: 3,
      initialBbox: [0.1, 0.1, 0.2, 0.1],
    });
    await waitFor(() => expect(pdfPageRenderSuccessCallbacks.get(3)).toBeDefined());
    const finishFirstRender = pdfPageRenderSuccessCallbacks.get(3);
    if (!finishFirstRender) throw new Error('first PDF render callback was not registered');

    await act(async () => {
      view.rerender(
        <PdfViewer
          url="/fake/path.pdf"
          materialId="mat_smoke"
          bytes={PDF_BYTES}
          initialPage={3}
          initialBbox={[0.1, 0.7, 0.2, 0.1]}
        />,
      );
    });
    const finishSecondRender = pdfPageRenderSuccessCallbacks.get(3);
    expect(finishSecondRender).toBeDefined();
    expect(finishSecondRender).not.toBe(finishFirstRender);
    if (!finishSecondRender) throw new Error('second PDF render callback was not registered');

    act(() => finishSecondRender());
    const callsAfterSecondRender = scrollTo.mock.calls.length;
    expect(scrollTo).toHaveBeenLastCalledWith(expect.objectContaining({ top: 900 }));

    act(() => finishFirstRender());
    expect(scrollTo).toHaveBeenCalledTimes(callsAfterSecondRender);
    expect(scrollTo).toHaveBeenLastCalledWith(expect.objectContaining({ top: 900 }));
  });

  it.each([
    ['missing', 'sentence that is absent'],
    ['ambiguous', 'shared exact quote'],
  ])('keeps page-only navigation for a %s initial quote', async (scenario, quote) => {
    if (scenario === 'ambiguous') {
      pdfPageTexts[2] = 'shared exact quote';
      pdfPageTexts[3] = 'shared exact quote';
    }
    installQuoteRangeGeometry([new DOMRect(100, 240, 520, 36)]);

    await act(async () => {
      renderViewer({ initialPage: 3, initialQuote: quote });
    });

    await waitFor(() => {
      expect(screen.getByTestId('pdf-viewer')).toHaveAttribute(
        'data-citation-anchor-status',
        'page_only',
      );
    });
    expect(screen.queryByTestId('pdf-citation-quote-highlight')).not.toBeInTheDocument();
    expect(getCurrentPageButton(3)).toBeInTheDocument();
  });

  it.each([
    ['missing', 'sentence that is absent'],
    ['ambiguous', 'shared exact quote'],
  ])('falls back to the citation bbox when a %s exact quote cannot be resolved', async (scenario, quote) => {
    if (scenario === 'ambiguous') {
      pdfPageTexts[2] = 'shared exact quote';
      pdfPageTexts[3] = 'shared exact quote';
    }
    installQuoteRangeGeometry([new DOMRect(100, 240, 520, 36)]);

    await act(async () => {
      renderViewer({
        initialPage: 3,
        initialQuote: quote,
        initialBbox: [0.1, 0.2, 0.4, 0.1],
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId('pdf-citation-bbox-highlight')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('pdf-citation-quote-highlight')).not.toBeInTheDocument();
    expect(getCurrentPageButton(3)).toBeInTheDocument();
  });

  it('notifies page changes only when the page number changes', async () => {
    const onPageChange = vi.fn();

    function Wrapper() {
      const [parentRender, setParentRender] = useState(0);
      return (
        <PdfViewer
          url="/fake/path.pdf"
          materialId="mat_smoke"
          bytes={PDF_BYTES}
          onPageChange={(page) => {
            onPageChange(page);
            if (parentRender === 0) setParentRender(1);
          }}
        />
      );
    }

    await act(async () => {
      render(<Wrapper />);
    });

    await waitFor(() => {
      expect(onPageChange).toHaveBeenCalledTimes(1);
    });
    expect(onPageChange).toHaveBeenLastCalledWith(1);
  });

  it('keeps the selection action toolbar inside the viewport', async () => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      writable: true,
      value: 480,
    });
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      writable: true,
      value: 320,
    });
    await act(async () => {
      renderViewer({ onAnalyzeText: vi.fn() });
    });
    const pageNode = screen.getAllByTestId('pdf-page')[0];
    if (!pageNode) throw new Error('missing mocked PDF page');
    const anchorNode = document.createTextNode('selected SmartRead passage');
    pageNode.appendChild(anchorNode);
    installTextSelectionMock(
      'selected SmartRead passage',
      {
        x: 920,
        y: 4,
        left: 920,
        top: 4,
        right: 1000,
        bottom: 24,
        width: 80,
        height: 20,
        toJSON: () => ({}),
      } as DOMRect,
      anchorNode,
    );
    const scrollRegion = screen.getByTestId('pdf-document').parentElement;
    if (!scrollRegion) throw new Error('missing PDF scroll region');

    await act(async () => {
      fireEvent.mouseUp(scrollRegion);
    });

    const actionToolbar = screen.getByRole('button', { name: /AI 分析选段/ }).parentElement;
    if (!actionToolbar) throw new Error('missing selection action toolbar');
    expect(actionToolbar).toHaveStyle({ left: '136px', top: '8px' });
  });

  it('captures drag-based visual selections continuously with matching typed attachments', async () => {
    const onAnalyzeRegion = vi.fn();
    await act(async () => {
      renderViewer({ onAnalyzeRegion });
    });

    const page = screen.getByLabelText('PDF 第 1 页');
    Object.defineProperty(page, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        x: 100,
        y: 200,
        left: 100,
        top: 200,
        right: 500,
        bottom: 700,
        width: 400,
        height: 500,
        toJSON: () => ({}),
      } as DOMRect),
    });

    const modes = [
      { buttonLabel: '图', kind: 'figure', captureLabel: '选中的图' },
      { buttonLabel: '表', kind: 'table', captureLabel: '选中的表' },
      { buttonLabel: '区域', kind: 'region', captureLabel: '选中的区域' },
    ] as const;

    for (const [index, mode] of modes.entries()) {
      const modeButton = screen.getByRole('button', { name: mode.buttonLabel });
      fireEvent.click(modeButton);
      expect(modeButton).toHaveAttribute('aria-pressed', 'true');

      const pointerId = index + 7;
      firePointerEvent(page, 'pointerdown', {
        button: 0,
        pointerId,
        clientX: 50,
        clientY: 150,
      });
      firePointerEvent(page, 'pointerup', {
        button: 0,
        pointerId,
        clientX: 550,
        clientY: 750,
      });

      await waitFor(() => {
        expect(onAnalyzeRegion).toHaveBeenCalledTimes(index + 1);
      });
      expect(onAnalyzeRegion).toHaveBeenNthCalledWith(index + 1, expect.objectContaining({
        kind: mode.kind,
        page: 1,
        bbox: [0, 0, 1, 1],
        label: mode.captureLabel,
        image: expect.objectContaining({
          mime: 'image/png',
          name: `pdf-page-1-${mode.kind}.png`,
          size: expect.any(Number),
          data_b64: expect.any(String),
        }),
      }));
      expect(modeButton).toHaveAttribute('aria-pressed', 'true');
    }
  });

  it('keeps prose visually passive until the user explicitly enables formula selection', async () => {
    await act(async () => {
      renderViewer({
        onAnalyzeRegion: vi.fn(),
        formulaCandidates: [{
          candidateId: 'formula-passive-until-enabled',
          page: 1,
          bbox: [0.1, 0.2, 0.4, 0.08],
        }],
      });
    });

    const page = screen.getByLabelText('PDF 第 1 页');
    fireEvent.mouseOver(page);

    expect(page).not.toHaveClass('cursor-crosshair');
    expect(page).not.toHaveClass('select-none');
    expect(screen.queryByRole('button', { name: '选择第 1 页公式 1' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('pdf-selected-visual-region')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '公式' }));
    expect(screen.getByRole('button', { name: '选择第 1 页公式 1' })).toBeInTheDocument();
  });

  it('selects a formula candidate atomically and forwards its source metadata', async () => {
    const onAnalyzeRegion = vi.fn();
    await act(async () => {
      renderViewer({
        onAnalyzeRegion,
        formulaCandidates: [{
          candidateId: 'formula-1',
          page: 1,
          bbox: [0.1, 0.2, 0.4, 0.08],
          chunkId: 'chunk-7',
          text: 'E = mc^2',
        }],
      });
    });

    const formulaModeButton = screen.getByRole('button', { name: '公式' });
    fireEvent.click(formulaModeButton);
    const page = screen.getByLabelText('PDF 第 1 页');
    expect(page).not.toHaveClass('select-none');

    firePointerEvent(page, 'pointerdown', {
      button: 0,
      pointerId: 18,
      clientX: 80,
      clientY: 80,
    });
    firePointerEvent(page, 'pointerup', {
      button: 0,
      pointerId: 18,
      clientX: 280,
      clientY: 280,
    });
    expect(screen.queryByTestId('pdf-region-draft')).not.toBeInTheDocument();
    expect(onAnalyzeRegion).not.toHaveBeenCalled();

    const candidate = screen.getByRole('button', { name: '选择第 1 页公式 1' });
    expect(candidate).toHaveClass('border-transparent');
    candidate.focus();
    expect(candidate).toHaveFocus();
    fireEvent.click(candidate);

    await waitFor(() => expect(onAnalyzeRegion).toHaveBeenCalledTimes(1));
    expect(onAnalyzeRegion).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'formula',
      page: 1,
      bbox: [0.1, 0.2, 0.4, 0.08],
      label: '选中的公式',
      candidateId: 'formula-1',
      chunkId: 'chunk-7',
      text: 'E = mc^2',
      image: expect.objectContaining({
        mime: 'image/png',
        name: 'pdf-page-1-formula.png',
      }),
    }));
    expect(formulaModeButton).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps native prose selection available while formula selection is active', async () => {
    await act(async () => {
      renderViewer({
        onAnalyzeText: vi.fn(),
        onAnalyzeRegion: vi.fn(),
        formulaCandidates: [{
          candidateId: 'formula-1',
          page: 1,
          bbox: [0.1, 0.2, 0.4, 0.08],
        }],
      });
    });
    fireEvent.click(screen.getByRole('button', { name: '公式' }));

    const pdfPage = screen.getAllByTestId('pdf-page')[0];
    if (!pdfPage) throw new Error('missing mocked PDF page');
    const anchorNode = document.createTextNode('native prose selection');
    pdfPage.appendChild(anchorNode);
    installTextSelectionMock(
      'native prose selection',
      {
        x: 20,
        y: 20,
        left: 20,
        top: 20,
        right: 180,
        bottom: 40,
        width: 160,
        height: 20,
        toJSON: () => ({}),
      } as DOMRect,
      anchorNode,
    );
    const scrollRegion = screen.getByTestId('pdf-document').parentElement;
    if (!scrollRegion) throw new Error('missing PDF scroll region');
    fireEvent.mouseUp(scrollRegion);

    expect(screen.getByRole('button', { name: /AI 分析选段/ })).toBeInTheDocument();
  });

  it('shows an explicit empty state and never starts a drag when no formula candidates exist', async () => {
    const onAnalyzeRegion = vi.fn();
    await act(async () => {
      renderViewer({ onAnalyzeRegion, formulaCandidates: [] });
    });
    fireEvent.click(screen.getByRole('button', { name: '公式' }));

    expect(screen.getByRole('status')).toHaveTextContent('当前文献尚未识别到可整体选择的公式');
    const page = screen.getByLabelText('PDF 第 1 页');
    expect(page).not.toHaveClass('select-none');
    firePointerEvent(page, 'pointerdown', {
      button: 0,
      pointerId: 19,
      clientX: 40,
      clientY: 40,
    });
    firePointerEvent(page, 'pointerup', {
      button: 0,
      pointerId: 19,
      clientX: 260,
      clientY: 260,
    });

    expect(screen.queryByTestId('pdf-region-draft')).not.toBeInTheDocument();
    expect(onAnalyzeRegion).not.toHaveBeenCalled();
  });

  it('renders persistent inert outlines only for selected visual regions', async () => {
    await act(async () => {
      renderViewer({
        selectedVisualRegions: [
          { kind: 'figure', page: 1, bbox: [0.1, 0.15, 0.3, 0.25] },
          { kind: 'formula', page: 1, bbox: [0.2, 0.55, 0.5, 0.06], candidateId: 'formula-2' },
        ],
      });
    });

    const outlines = screen.getAllByTestId('pdf-selected-visual-region');
    expect(outlines).toHaveLength(2);
    expect(outlines[0]).toHaveAttribute('data-selection-kind', 'figure');
    expect(outlines[0]).toHaveStyle({ left: '10%', top: '15%', width: '30%', height: '25%' });
    expect(outlines[1]).toHaveAttribute('data-selection-kind', 'formula');
    expect(outlines[1].parentElement).toHaveClass('pointer-events-none');
  });

  it('blocks text and visual analysis while selection is disabled', async () => {
    const onAnalyzeText = vi.fn();
    const onAnalyzeRegion = vi.fn();
    await act(async () => {
      renderViewer({ analysisDisabled: true, onAnalyzeText, onAnalyzeRegion });
    });

    for (const label of ['图', '表', '公式', '区域']) {
      expect(screen.getByRole('button', { name: label })).toBeDisabled();
    }

    const page = screen.getByLabelText('PDF 第 1 页');
    Object.defineProperty(page, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        right: 400,
        bottom: 500,
        width: 400,
        height: 500,
        toJSON: () => ({}),
      } as DOMRect),
    });
    firePointerEvent(page, 'pointerdown', {
      button: 0,
      pointerId: 17,
      clientX: 80,
      clientY: 80,
    });
    firePointerEvent(page, 'pointerup', {
      button: 0,
      pointerId: 17,
      clientX: 280,
      clientY: 280,
    });

    const anchorNode = document.createTextNode('selection blocked while generating');
    page.appendChild(anchorNode);
    installTextSelectionMock(
      'selection blocked while generating',
      {
        x: 10,
        y: 10,
        left: 10,
        top: 10,
        right: 210,
        bottom: 30,
        width: 200,
        height: 20,
        toJSON: () => ({}),
      } as DOMRect,
      anchorNode,
    );
    const scrollRegion = screen.getByTestId('pdf-document').parentElement;
    if (!scrollRegion) throw new Error('missing PDF scroll region');
    fireEvent.mouseUp(scrollRegion);

    expect(scrollRegion).toHaveAttribute('aria-disabled', 'true');
    expect(scrollRegion).toHaveClass('select-none');
    expect(screen.queryByRole('button', { name: /AI 分析选段/ })).not.toBeInTheDocument();
    expect(onAnalyzeText).not.toHaveBeenCalled();
    expect(onAnalyzeRegion).not.toHaveBeenCalled();
  });

  it('clears active text and region selection when analysis becomes disabled', async () => {
    const onAnalyzeText = vi.fn();
    const onAnalyzeRegion = vi.fn();
    let view: ReturnType<typeof renderViewer>;
    await act(async () => {
      view = renderViewer({ onAnalyzeText, onAnalyzeRegion });
    });

    const page = screen.getAllByTestId('pdf-page')[0];
    if (!page) throw new Error('missing mocked PDF page');
    const anchorNode = document.createTextNode('active selection');
    page.appendChild(anchorNode);
    installTextSelectionMock(
      'active selection',
      {
        x: 20,
        y: 20,
        left: 20,
        top: 20,
        right: 140,
        bottom: 40,
        width: 120,
        height: 20,
        toJSON: () => ({}),
      } as DOMRect,
      anchorNode,
    );
    const scrollRegion = screen.getByTestId('pdf-document').parentElement;
    if (!scrollRegion) throw new Error('missing PDF scroll region');
    fireEvent.mouseUp(scrollRegion);
    expect(screen.getByRole('button', { name: /AI 分析选段/ })).toBeInTheDocument();

    await act(async () => {
      view!.rerender(
        <PdfViewer
          url="/fake/path.pdf"
          materialId="mat_smoke"
          bytes={PDF_BYTES}
          analysisDisabled
          onAnalyzeText={onAnalyzeText}
          onAnalyzeRegion={onAnalyzeRegion}
        />,
      );
    });
    expect(screen.queryByRole('button', { name: /AI 分析选段/ })).not.toBeInTheDocument();

    await act(async () => {
      view!.rerender(
        <PdfViewer
          url="/fake/path.pdf"
          materialId="mat_smoke"
          bytes={PDF_BYTES}
          onAnalyzeText={onAnalyzeText}
          onAnalyzeRegion={onAnalyzeRegion}
        />,
      );
    });
    fireEvent.click(screen.getByRole('button', { name: '公式' }));
    const formulaSelectionHint = screen.getByText(/尚未识别到可整体选择的公式/);
    expect(formulaSelectionHint).toHaveTextContent('正文仍可直接划选');

    await act(async () => {
      view!.rerender(
        <PdfViewer
          url="/fake/path.pdf"
          materialId="mat_smoke"
          bytes={PDF_BYTES}
          analysisDisabled
          onAnalyzeText={onAnalyzeText}
          onAnalyzeRegion={onAnalyzeRegion}
        />,
      );
    });
    expect(screen.queryByText(/尚未识别到可整体选择的公式/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '公式' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('rejects visual selections smaller than the minimum capture size', async () => {
    const onAnalyzeRegion = vi.fn();
    await act(async () => {
      renderViewer({ onAnalyzeRegion });
    });
    fireEvent.click(screen.getByRole('button', { name: '图' }));

    const page = screen.getByLabelText('PDF 第 1 页');
    Object.defineProperty(page, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        right: 400,
        bottom: 500,
        width: 400,
        height: 500,
        toJSON: () => ({}),
      } as DOMRect),
    });

    firePointerEvent(page, 'pointerdown', {
      button: 0,
      pointerId: 9,
      clientX: 100,
      clientY: 100,
    });
    firePointerEvent(page, 'pointerup', {
      button: 0,
      pointerId: 9,
      clientX: 110,
      clientY: 110,
    });

    expect(await screen.findByText('框选范围太小，请重新拖拽。')).toBeInTheDocument();
    expect(onAnalyzeRegion).not.toHaveBeenCalled();
  });

  it('toolbar next/prev buttons advance page and clamp at boundaries', async () => {
    await act(async () => {
      renderViewer({ initialPage: 1 });
    });

    let prev = screen.getByRole('button', { name: '上一页' }) as HTMLButtonElement;
    let next = screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement;

    expect(getCurrentPageButton(1)).toBeInTheDocument();
    expect(prev.disabled).toBe(true);
    expect(next.disabled).toBe(false);

    await act(async () => { fireEvent.click(next); });
    expect(getCurrentPageButton(2)).toBeInTheDocument();
    prev = screen.getByRole('button', { name: '上一页' }) as HTMLButtonElement;
    next = screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement;
    expect(prev.disabled).toBe(false);

    for (let i = 0; i < 8; i++) {
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: '下一页' }));
      });
    }
    expect(getCurrentPageButton(5)).toBeInTheDocument();
    next = screen.getByRole('button', { name: '下一页' }) as HTMLButtonElement;
    expect(next.disabled).toBe(true);

    for (let i = 0; i < 10; i++) {
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: '上一页' }));
      });
    }
    expect(getCurrentPageButton(1)).toBeInTheDocument();
    prev = screen.getByRole('button', { name: '上一页' }) as HTMLButtonElement;
    expect(prev.disabled).toBe(true);
  });

  it('renders highlights panel and jumps to the highlight page on click', async () => {
    await act(async () => {
      renderViewer({
        initialPage: 1,
        highlights: [
          { page: 4, text: 'evidence quote on page four', color: '#FFEB3B' },
          { page: 2, text: 'note on page two', color: '#FFEB3B' },
        ],
      });
    });

    // Open the panel via the toolbar toggle (title contains highlight count).
    const panelToggle = screen.getByTitle('标注 (2)');
    await act(async () => { fireEvent.click(panelToggle); });

    // Both highlights show their page buttons.
    const pageFourBtn = screen.getByText('第 4 页');
    expect(pageFourBtn).toBeTruthy();
    expect(screen.getByText('第 2 页')).toBeTruthy();

    // Clicking jumps the viewer.
    await act(async () => { fireEvent.click(pageFourBtn); });
    expect(getCurrentPageButton(4)).toBeInTheDocument();
  });

  it('renders bbox-based highlight overlays on the target page', async () => {
    await act(async () => {
      renderViewer({
        initialPage: 1,
        highlights: [
          {
            page: 2,
            text: 'bbox highlight',
            color: '#60A5FA',
            rects: [{ x: 0.1, y: 0.2, w: 0.25, h: 0.08 }],
          },
        ],
      });
    });

    const panelToggle = screen.getByTitle('标注 (1)');
    await act(async () => { fireEvent.click(panelToggle); });
    expect(screen.getByText('bbox highlight')).toBeInTheDocument();
    expect(screen.getByText('第 2 页')).toBeInTheDocument();
  });

  it('windows heavy PDF page rendering for large documents while preserving page anchors', async () => {
    mockPdfPageCount = 80;

    await act(async () => {
      renderViewer({
        initialPage: 40,
        highlights: [
          {
            page: 72,
            text: 'far page highlight',
            color: '#60A5FA',
            rects: [{ x: 0.1, y: 0.2, w: 0.2, h: 0.08 }],
          },
        ],
      });
    });

    expect(screen.getByLabelText('PDF 第 1 页')).toBeInTheDocument();
    expect(screen.getByLabelText('PDF 第 80 页')).toBeInTheDocument();
    expect(screen.getAllByTestId('pdf-page')).toHaveLength(8);
    expect(new Set(renderedPdfPageNumbers)).toEqual(new Set([37, 38, 39, 40, 41, 42, 43, 72]));
    expect(screen.getByText('第 1 页')).toBeInTheDocument();
    expect(screen.getByText('第 80 页')).toBeInTheDocument();
  });

  it('searches PDF text and cycles through matched pages', async () => {
    await act(async () => {
      renderViewer({ initialPage: 1 });
    });

    await act(async () => {
      fireEvent.change(screen.getByLabelText('搜索 PDF 文本'), { target: { value: 'evidence' } });
      fireEvent.click(screen.getByRole('button', { name: '搜索 PDF' }));
    });

    await waitFor(() => {
      expect(getCurrentPageButton(2)).toBeInTheDocument();
    });
    expect(screen.getByText('1/2')).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '下一个搜索结果' }));
    });
    expect(getCurrentPageButton(3)).toBeInTheDocument();
    expect(screen.getByText('2/2')).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '上一个搜索结果' }));
    });
    expect(getCurrentPageButton(2)).toBeInTheDocument();
    expect(screen.getByText('1/2')).toBeInTheDocument();
  });

  it('downloads the loaded PDF bytes with a safe PDF filename', async () => {
    vi.useFakeTimers();
    const createObjectUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:pdf-download');
    const revokeObjectUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    let clickedHref = '';
    let clickedDownload = '';
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function clickAnchor(this: HTMLAnchorElement) {
      clickedHref = this.href;
      clickedDownload = this.download;
    });

    await act(async () => {
      renderViewer({ materialId: 'mat:/smoke paper' });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '下载 PDF' }));
    });

    expect(createObjectUrl).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(clickedHref).toBe('blob:pdf-download');
    expect(clickedDownload).toBe('mat_smoke_paper.pdf');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:pdf-download');
  });

  it('saves PDF bytes through the native desktop bridge when available', async () => {
    const createObjectUrl = vi.spyOn(URL, 'createObjectURL');
    const saveBytes = vi.fn(async () => 'C:\\exports\\mat_smoke_paper.pdf');
    window.pywebview = {
      api: {
        save_bytes: saveBytes,
      },
    };

    await act(async () => {
      renderViewer({ materialId: 'mat:/smoke paper' });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '下载 PDF' }));
    });

    await waitFor(() => {
      expect(saveBytes).toHaveBeenCalledWith('mat_smoke_paper.pdf', expect.any(String));
    });
    expect(createObjectUrl).not.toHaveBeenCalled();

    delete window.pywebview;
  });

  it('falls back to current-window print when the PDF print window is blocked', async () => {
    const createObjectUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:pdf-print');
    const revokeObjectUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined);

    await act(async () => {
      renderViewer();
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '打印 PDF' }));
    });

    expect(createObjectUrl).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith('blob:pdf-print', '_blank', 'noopener,noreferrer');
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:pdf-print');
    expect(print).toHaveBeenCalledTimes(1);
  });

  it('toggles fullscreen state through the browser Fullscreen API', async () => {
    let fullscreenElement: Element | null = null;
    Object.defineProperty(document, 'fullscreenEnabled', {
      configurable: true,
      get: () => true,
    });
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      get: () => fullscreenElement,
    });
    const requestFullscreen = vi.fn(function requestFullscreen(this: HTMLElement): Promise<void> {
      fullscreenElement = this;
      document.dispatchEvent(new Event('fullscreenchange'));
      return Promise.resolve();
    });
    const exitFullscreen = vi.fn((): Promise<void> => {
      fullscreenElement = null;
      document.dispatchEvent(new Event('fullscreenchange'));
      return Promise.resolve();
    });
    Object.defineProperty(HTMLElement.prototype, 'requestFullscreen', {
      configurable: true,
      writable: true,
      value: requestFullscreen,
    });
    Object.defineProperty(document, 'exitFullscreen', {
      configurable: true,
      writable: true,
      value: exitFullscreen,
    });

    await act(async () => {
      renderViewer();
    });

    const enterButton = screen.getByRole('button', { name: '全屏阅读' }) as HTMLButtonElement;
    await waitFor(() => expect(enterButton.disabled).toBe(false));

    await act(async () => {
      fireEvent.click(enterButton);
      await Promise.resolve();
    });

    expect(requestFullscreen).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '退出全屏' })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '退出全屏' }));
      await Promise.resolve();
    });

    expect(exitFullscreen).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '全屏阅读' })).toBeInTheDocument();
  });

  it('reacts to a new initialPage prop (evidence deep-link rebound)', async () => {
    let setInitialPage: ((p: number) => void) | undefined;
    function Wrapper() {
      const [page, setPage] = useState<number | undefined>(1);
      setInitialPage = setPage;
      return <PdfViewer url="/fake/path.pdf" materialId="mat_smoke" initialPage={page} bytes={PDF_BYTES} />;
    }

    await act(async () => { render(<Wrapper />); });
    expect(getCurrentPageButton(1)).toBeInTheDocument();

    // Simulate parent passing a new initialPage (e.g. user clicked another
    // evidence link pointing at page 4 in the same PDF).
    await act(async () => { setInitialPage!(4); });
    expect(getCurrentPageButton(4)).toBeInTheDocument();
  });
});
