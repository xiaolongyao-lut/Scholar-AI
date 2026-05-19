import React, { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Download, Copy, FileJson, FileText, Loader2, Check } from 'lucide-react';
import { useI18n } from '@/contexts/I18nContext';
import { useToast } from '@/components/ui/Toast';
import { getWritingBackendService } from '@/services/writingBackend';
import { ProjectExportResult } from '@/types/resources';

interface ExportPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: string;
}

export function ExportPreviewModal({ isOpen, onClose, projectId }: ExportPreviewModalProps) {
  const { t } = useI18n();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ProjectExportResult | null>(null);
  const [copied, setCopied] = useState(false);

  const fetchExportData = useCallback(async () => {
    if (!projectId) {
      return;
    }

    setLoading(true);
    try {
      const service = getWritingBackendService();
      const result = await service.exportProject(projectId);
      setData(result);
    } catch (err) {
      toast(err instanceof Error ? err.message : t('ref.export_failed'), 'error');
    } finally {
      setLoading(false);
    }
  }, [projectId, t, toast]);

  useEffect(() => {
    if (isOpen && projectId) {
      void fetchExportData();
    }
  }, [fetchExportData, isOpen, projectId]);

  const handleCopy = () => {
    if (!data?.content) return;
    navigator.clipboard.writeText(data.content);
    setCopied(true);
    toast(t('ref.export_copied'), 'success');
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = (format: 'md' | 'json') => {
    if (!data) return;
    const content = format === 'md' ? (data.content || '') : JSON.stringify(data, null, 2);
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `project-export-${projectId}.${format}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast(t('ref.export_downloaded'), 'success');
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        className="relative w-full max-w-5xl h-[85vh] bg-background rounded-2xl shadow-2xl border border-outline-variant flex flex-col overflow-hidden"
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
        <div className="flex-1 overflow-hidden flex flex-col">
          {loading ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-4">
              <Loader2 className="animate-spin text-primary" size={32} />
              <p className="text-sm text-foreground/50 animate-pulse">{t('ref.export_generating')}</p>
            </div>
          ) : data ? (
            <div className="flex-1 flex flex-col">
              {/* Toolbar */}
              <div className="px-6 py-3 bg-surface-high border-b border-outline-variant flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-medium text-foreground/40 uppercase tracking-wider">{t('ref.export_preview')}</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-black/5 hover:bg-black/10 transition-colors"
                  >
                    {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
                    {copied ? t('ref.export_copied') : t('ref.export_copy_markdown')}
                  </button>
                  <button
                    onClick={() => handleDownload('md')}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:opacity-90 transition-colors shadow-sm"
                  >
                    <Download size={14} />
                    {t('ref.export_download_md')}
                  </button>
                  <button
                    onClick={() => handleDownload('json')}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-black/5 hover:bg-black/10 transition-colors"
                  >
                    <FileJson size={14} />
                    JSON
                  </button>
                </div>
              </div>

              {/* Preview Area */}
              <div className="flex-1 overflow-y-auto p-8 bg-surface-lowest custom-scrollbar font-serif">
                <div className="max-w-3xl mx-auto space-y-6 text-foreground/90 leading-relaxed">
                  <div className="whitespace-pre-wrap break-words text-[15px]">
                    {data.content}
                  </div>
                </div>
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
            <span>{t('ref.export_evidence_count', { count: data?.evidence_rows?.length || 0 })}</span>
            <span>{t('ref.export_chain_count', { count: data?.citation_chain?.length || 0 })}</span>
            <span>{t('ref.export_review_count', { count: data?.review_findings?.length || 0 })}</span>
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
