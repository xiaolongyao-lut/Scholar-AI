import React, { useState, useCallback, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { X, Download, Copy, FileText, Loader2, Check, Square } from 'lucide-react';
import { useI18n } from '@/contexts/I18nContext';
import { useToast } from '@/components/ui/Toast';
import { cn } from '@/lib/utils';
import { sanitizeRuntimeVisibleText } from '@/components/writing/writingRuntimeDisplay';
import {
  downloadProjectExportBlob,
  getWritingBackendService,
  resolveProjectExportForDownload,
  type WritingDocumentExportFormat,
  type WritingExportFormat,
} from '@/services/writingBackend';
import { ProjectExportResponseEnvelope } from '@/types/resources';
import {
  DOCUMENT_EXPORT_OPTIONS,
  getDocumentExportOption,
  writingExportFormatLabel,
} from './documentExportOptions';

interface ExportPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: string;
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') return true;
  if (typeof error !== 'object' || error === null) return false;
  const record = error as { name?: unknown; code?: unknown; message?: unknown };
  return record.name === 'AbortError' || record.name === 'CanceledError' || record.code === 'ERR_CANCELED';
}

export function formatExportError(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  return sanitizeRuntimeVisibleText(message, fallback);
}

export function ExportPreviewModal({ isOpen, onClose, projectId }: ExportPreviewModalProps) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ProjectExportResponseEnvelope | null>(null);
  const [copied, setCopied] = useState(false);
  const [selectedFormat, setSelectedFormat] = useState<WritingDocumentExportFormat>('markdown');
  const abortControllerRef = useRef<AbortController | null>(null);

  const stopExport = useCallback((showNotice: boolean) => {
    const controller = abortControllerRef.current;
    if (!controller) {
      return;
    }
    controller.abort();
    abortControllerRef.current = null;
    setLoading(false);
    if (showNotice) {
      toast('已停止生成导出预览。', 'info');
    }
  }, [toast]);

  const fetchExportData = useCallback(async () => {
    if (!projectId) {
      return;
    }

    stopExport(false);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    setLoading(true);
    try {
      const service = getWritingBackendService();
      const result = await service.exportProject(projectId, selectedFormat, {
        signal: abortController.signal,
      });
      if (abortController.signal.aborted) {
        return;
      }
      setData(result);
    } catch (err) {
      if (isAbortError(err) || abortController.signal.aborted) {
        return;
      }
      toast(formatExportError(err, t('ref.export_failed')), 'error');
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
        setLoading(false);
      }
    }
  }, [projectId, selectedFormat, stopExport, t, toast]);

  useEffect(() => {
    if (isOpen && projectId) {
      void fetchExportData();
    }
    return () => {
      stopExport(false);
    };
  }, [fetchExportData, isOpen, projectId, stopExport]);

  const selectedOption = getDocumentExportOption(selectedFormat);
  const isStructuredJson = data?.format === 'json';
  const previewText = isStructuredJson
    ? (data ? JSON.stringify(data, null, 2) : '')
    : (data?.content ?? '');
  const hasPreviewText = Boolean(previewText.trim());

  const handleCopy = () => {
    if (!hasPreviewText) return;
    navigator.clipboard.writeText(previewText);
    setCopied(true);
    toast(t('ref.export_copied'), 'success');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = async (format: WritingExportFormat) => {
    if (!data) return;
    try {
      const service = getWritingBackendService();
      const exportData = await resolveProjectExportForDownload(
        data,
        format,
        projectId,
        (targetProjectId, targetFormat) => service.exportProject(targetProjectId, targetFormat),
      );
      const savedPath = await downloadProjectExportBlob(exportData, format);
      toast(savedPath ? `已保存：${savedPath}` : t('ref.export_downloaded'), 'success');
    } catch (err) {
      toast(formatExportError(err, t('ref.export_failed')), 'error');
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        className="relative w-full max-w-5xl h-[85vh] min-h-0 bg-background rounded-2xl shadow-2xl border border-outline-variant flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant bg-surface-low">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-primary/10 rounded-lg">
              <FileText className="text-primary" size={20} />
            </div>
            <div>
              <h2 className="text-lg font-display font-semibold">{t('ref.export_title')}</h2>
              <p className="text-xs text-foreground/50">{t('ref.export_desc')}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-black/5 rounded-full transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
          {loading ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-4">
              <Loader2 className="animate-spin text-primary" size={32} />
              <p className="text-sm text-foreground/50 animate-pulse">{t('ref.export_generating')}</p>
              <button
                type="button"
                onClick={() => stopExport(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/70 bg-surface-low px-3 py-1.5 text-xs font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary"
              >
                <Square size={13} />
                停止
              </button>
            </div>
          ) : data ? (
            <div className="flex-1 min-h-0 flex flex-col">
              {/* Toolbar */}
              <div className="px-6 py-3 bg-surface-high border-b border-outline-variant flex flex-wrap items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="text-[11px] font-medium text-foreground/40 uppercase tracking-wider">{t('ref.export_preview')}</span>
                  <span className="rounded-md border border-outline-variant bg-surface-low px-2 py-1 text-[11px] font-medium text-foreground/55">
                    {selectedOption.extension}
                  </span>
                </div>
                <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
                  <div
                    role="group"
                    aria-label="导出格式"
                    className="grid min-w-[360px] grid-cols-3 overflow-hidden rounded-md border border-outline-variant bg-surface-low"
                  >
                    {DOCUMENT_EXPORT_OPTIONS.map(({ format, label, extension, Icon }) => {
                      const isSelected = selectedFormat === format;
                      return (
                        <button
                          key={format}
                          type="button"
                          onClick={() => setSelectedFormat(format)}
                          aria-pressed={isSelected}
                          className={cn(
                            'inline-flex h-9 items-center justify-center gap-1.5 border-r border-outline-variant px-3 text-xs font-medium transition-colors last:border-r-0',
                            isSelected
                              ? 'bg-primary text-primary-foreground shadow-sm'
                              : 'text-foreground/65 hover:bg-surface-container hover:text-foreground',
                          )}
                        >
                          <Icon size={14} aria-hidden />
                          <span>{label}</span>
                          <span className={cn('text-[10px]', isSelected ? 'text-primary-foreground/70' : 'text-foreground/40')}>
                            {extension}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <button
                    onClick={handleCopy}
                    disabled={!hasPreviewText}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-black/5 hover:bg-black/10 transition-colors disabled:opacity-40"
                  >
                    {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
                    {copied ? t('ref.export_copied') : hasPreviewText ? '复制预览' : '无文本可复制'}
                  </button>
                  <button
                    onClick={() => handleDownload(selectedFormat)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:opacity-90 transition-colors shadow-sm"
                  >
                    <Download size={14} />
                    {`下载 ${selectedOption.label}`}
                  </button>
                </div>
              </div>

              {/* Preview Area */}
              <div className={cn(
                "min-h-0 flex-1 overflow-y-auto overscroll-contain p-8 bg-surface-lowest custom-scrollbar",
                isStructuredJson ? "font-mono" : "font-serif",
              )}>
                {hasPreviewText ? (
                  isStructuredJson ? (
                    <pre className="mx-auto max-w-4xl whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-foreground/90">
                      {previewText}
                    </pre>
                  ) : (
                    <div className="max-w-3xl mx-auto space-y-6 text-foreground/90 leading-relaxed">
                      <div className="whitespace-pre-wrap break-words text-[15px]">
                        {previewText}
                      </div>
                    </div>
                  )
                ) : (
                  <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center text-center">
                    <FileText size={28} className="mb-3 text-foreground/25" />
                    <p className="text-sm font-medium text-foreground/70">{t('ref.export_empty_preview_title')}</p>
                    <p className="mt-2 max-w-md text-xs leading-5 text-foreground/45">
                      {t('ref.export_empty_preview_desc')}
                    </p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-foreground/40 italic">
              {t('ref.export_empty')}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-outline-variant bg-surface-low flex items-center justify-between text-[11px] text-foreground/40">
          <div className="flex items-center gap-4">
            <span>{selectedOption.label}</span>
            <span>{data?.filename || 'project-export'}</span>
          </div>
          <div className="flex items-center gap-1 italic">
            <Loader2 size={10} />
            {t('ref.export_realtime')}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
