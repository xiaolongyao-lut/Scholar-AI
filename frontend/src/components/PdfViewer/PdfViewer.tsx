import { useState, useCallback, useMemo } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Sparkles, Highlighter } from 'lucide-react';
import { cn } from '@/lib/utils';

import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PdfViewerProps {
  url: string;
  materialId: string;
  onAnalyzeText?: (text: string, page: number) => void;
  onAddHighlight?: (highlight: { page: number; text: string; color: string }) => void;
  highlights?: Array<{ page: number; text: string; color: string }>;
  className?: string;
}

export function PdfViewer({
  url,
  materialId,
  onAnalyzeText,
  onAddHighlight,
  highlights = [],
  className,
}: PdfViewerProps) {
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [selectedText, setSelectedText] = useState('');
  const [showAIBtn, setShowAIBtn] = useState(false);
  const [btnPos, setBtnPos] = useState({ x: 0, y: 0 });

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
  }, []);

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
    <div className={cn('flex flex-col h-full bg-gray-100 dark:bg-surface-lowest', className)}>
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
        </div>
      </div>

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
        </div>
      )}
    </div>
  );
}
