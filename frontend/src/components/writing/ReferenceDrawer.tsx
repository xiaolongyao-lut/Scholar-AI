import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, X, ExternalLink, ArrowRight, Link2, Target, FileText, AlertTriangle, CheckCircle2, Download, Copy, Square } from 'lucide-react';
import { useI18n } from '@/contexts/I18nContext';
import { WritingMaterial, CitationAnchor, DraftContent } from '@/types/writing';
import { cn } from '@/lib/utils';
import { useWriting } from '@/contexts/WritingContext';
import {
  downloadProjectExportBlob,
  getWritingBackendService,
  WRITING_EXPORT_FORMATS,
  type WritingExportFormat,
} from '@/services/writingBackend';
import type { ProjectExportResponseEnvelope } from '@/types/resources';
import { sanitizeRuntimeVisibleText } from './writingRuntimeDisplay';

type ReferenceDrawerTab = 'evidence' | 'chain' | 'review' | 'export';

type ParagraphRecord = {
  index: number;
  text: string;
  startOffset: number;
  endOffset: number;
  anchors: CitationAnchor[];
};

type MaterialEvidenceStatus = 'used' | 'weak' | 'unused';

const stripAnchorTokens = (value: string) => value.replace(/\[\^([^\]]+)\]/g, '').replace(/\s+/g, ' ').trim();

const shorten = (value: string, maxLength = 140) => {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
};

const buildParagraphRecords = (content: string, anchors: CitationAnchor[]): ParagraphRecord[] => {
  if (!content.trim()) {
    return [];
  }

  const records: ParagraphRecord[] = [];
  const separator = /\n\s*\n+/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let paragraphIndex = 0;

  const pushParagraph = (rawSegment: string, rawStart: number, rawEnd: number) => {
    const trimmed = rawSegment.trim();
    if (!trimmed) {
      return;
    }

    const leadingWhitespace = rawSegment.match(/^\s*/)?.[0].length ?? 0;
    const trailingWhitespace = rawSegment.match(/\s*$/)?.[0].length ?? 0;
    const startOffset = rawStart + leadingWhitespace;
    const endOffset = Math.max(startOffset, rawEnd - trailingWhitespace);
    const paragraphAnchors = anchors.filter(
      (anchor) => anchor.startOffset >= startOffset && anchor.endOffset <= endOffset,
    );

    records.push({
      index: paragraphIndex,
      text: trimmed,
      startOffset,
      endOffset,
      anchors: paragraphAnchors,
    });
    paragraphIndex += 1;
  };

  while ((match = separator.exec(content)) !== null) {
    pushParagraph(content.slice(lastIndex, match.index), lastIndex, match.index);
    lastIndex = match.index + match[0].length;
  }

  pushParagraph(content.slice(lastIndex), lastIndex, content.length);
  return records;
};

const getEvidenceStatusTone = (status: MaterialEvidenceStatus) => {
  switch (status) {
    case 'used':
      return 'bg-emerald-100 text-emerald-700 border-emerald-200/70 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-700/40';
    case 'weak':
      return 'bg-amber-100 text-amber-700 border-amber-200/70 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-700/40';
    default:
      return 'bg-surface-low text-foreground/50 border-outline-variant';
  }
};

const getEvidenceStatusLabel = (status: MaterialEvidenceStatus) => {
  switch (status) {
    case 'used':
      return '证据已使用';
    case 'weak':
      return '证据较弱';
    default:
      return '尚未引用';
  }
};

function formatReferenceDrawerError(error: unknown, fallback: string): string {
  if (error instanceof Error) {
    return sanitizeRuntimeVisibleText(error.message, fallback);
  }
  return sanitizeRuntimeVisibleText(error, fallback);
}

function materialTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    paper: '论文',
    note: '笔记',
    book: '书籍',
    report: '报告',
    dataset: '数据',
  };
  return labels[type] ?? '资料';
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') return true;
  if (typeof error !== 'object' || error === null) return false;
  const record = error as { name?: unknown; code?: unknown };
  return record.name === 'AbortError' || record.name === 'CanceledError' || record.code === 'ERR_CANCELED';
}

function exportFormatLabel(format: WritingExportFormat): string {
  const labels: Record<WritingExportFormat, string> = {
    markdown: '文稿预览',
    json: '结构化文件',
    word: 'Word 文档',
    latex: '排版工程',
    pdf: 'PDF 文件',
  };
  return labels[format] ?? '导出文件';
}

function ExportPanel() {
  const { t } = useI18n();
  const { activeProjectId } = useWriting();
  const [exportData, setExportData] = React.useState<ProjectExportResponseEnvelope | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [selectedFormat, setSelectedFormat] = React.useState<WritingExportFormat>('markdown');
  const abortControllerRef = React.useRef<AbortController | null>(null);

  const handleStopExport = React.useCallback((showNotice: boolean = true) => {
    const controller = abortControllerRef.current;
    if (!controller) return;
    controller.abort();
    abortControllerRef.current = null;
    setLoading(false);
    if (showNotice) {
      setError('已停止生成导出预览。');
    }
  }, []);

  const handleFetchExport = React.useCallback(async (format: WritingExportFormat) => {
    if (!activeProjectId) return;
    handleStopExport(false);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    setLoading(true);
    setError(null);
    try {
      const svc = getWritingBackendService();
      const data = await svc.exportProject(activeProjectId, format, {
        signal: abortController.signal,
      });
      if (abortController.signal.aborted) return;
      setExportData(data);
    } catch (err) {
      if (isAbortError(err) || abortController.signal.aborted) return;
      setError(formatReferenceDrawerError(err, t('ref.export_failed')));
      setExportData(null);
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
        setLoading(false);
      }
    }
  }, [activeProjectId, handleStopExport, t]);

  React.useEffect(() => {
    return () => {
      handleStopExport(false);
    };
  }, [handleStopExport]);

  const handleDownload = React.useCallback((format: WritingExportFormat) => {
    if (!exportData) return;
    downloadProjectExportBlob(exportData, format);
  }, [activeProjectId, exportData]);

  const handleCopy = React.useCallback(async () => {
    if (!exportData?.content) return;
    try {
      await navigator.clipboard.writeText(exportData.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [exportData]);

  const evidenceRows = exportData?.evidence_rows;
  const citationChain = exportData?.citation_chain;
  const reviewFindings = exportData?.review_findings;
  const previewText = exportData?.content ?? '';
  const canCopyPreview = previewText.trim().length > 0;

  return (
    <div className="space-y-4">
      {!activeProjectId ? (
        <div className="rounded-sm border border-dashed border-outline-variant bg-surface-low px-5 py-6 text-center">
          <p className="font-headline text-sm font-semibold text-foreground">{t('ref.export_no_project')}</p>
          <p className="mt-2 font-body text-[11px] text-foreground/50">{t('ref.export_no_project_desc')}</p>
        </div>
      ) : (
        <>
          <div className="flex gap-2">
            <select
              aria-label="导出格式"
              value={selectedFormat}
              onChange={(event) => setSelectedFormat(event.target.value as WritingExportFormat)}
              className="min-w-0 flex-1 rounded-sm border border-outline-variant bg-surface-low px-3 py-2 font-label text-[11px] font-medium text-foreground/70"
            >
              {WRITING_EXPORT_FORMATS.map((format) => (
                <option key={format} value={format}>{exportFormatLabel(format)}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => loading ? handleStopExport() : void handleFetchExport(selectedFormat)}
              className="min-w-[120px] inline-flex items-center justify-center gap-1.5 rounded-sm border border-primary/30 bg-primary/10 px-3 py-2 font-label text-[11px] font-medium text-primary transition-all hover:bg-primary/20 disabled:opacity-50"
            >
              {loading ? <Square size={12} /> : <Download size={12} />}
              {loading ? '停止' : `获取${exportFormatLabel(selectedFormat)}`}
            </button>
          </div>

          {error && (
            <div className="rounded-sm border border-red-200/70 bg-red-50/60 px-4 py-3 flex items-start gap-2">
              <AlertTriangle size={14} className="text-red-600 mt-0.5 flex-shrink-0" />
              <div>
                <div className="font-headline text-xs font-semibold text-red-800">{t('ref.export_failed')}</div>
                <p className="font-body text-[11px] text-red-700/80 mt-0.5">{error}</p>
              </div>
            </div>
          )}

          {exportData && (
            <>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => handleDownload('json')}
                  className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-sm border border-emerald-200/70 bg-emerald-50/60 px-3 py-1.5 font-label text-[10px] font-medium text-emerald-700 transition-all hover:bg-emerald-100 dark:border-emerald-700/40 dark:bg-emerald-500/10 dark:text-emerald-300 dark:hover:bg-emerald-500/20"
                >
                  <Download size={10} />
                  {t('ref.export_download_json')}
                </button>
                <button
                  type="button"
                  onClick={() => handleDownload(selectedFormat)}
                  className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-sm border border-emerald-200/70 bg-emerald-50/60 px-3 py-1.5 font-label text-[10px] font-medium text-emerald-700 transition-all hover:bg-emerald-100 dark:border-emerald-700/40 dark:bg-emerald-500/10 dark:text-emerald-300 dark:hover:bg-emerald-500/20"
                >
                  <Download size={10} />
                  {selectedFormat === 'json' ? t('ref.export_download_json') : `下载${exportFormatLabel(selectedFormat)}`}
                </button>
                <button
                  type="button"
                  onClick={() => void handleCopy()}
                  disabled={!canCopyPreview}
                  className="inline-flex items-center justify-center gap-1.5 rounded-sm border border-outline-variant bg-surface-low px-3 py-1.5 font-label text-[10px] font-medium text-foreground/60 transition-all hover:text-foreground disabled:opacity-40"
                >
                  {copied ? <CheckCircle2 size={10} className="text-emerald-600 dark:text-emerald-400" /> : <Copy size={10} />}
                  {copied ? t('ref.export_copied') : canCopyPreview ? t('ref.export_copy') : '无文本可复制'}
                </button>
              </div>

              {previewText && (
                <div className="rounded-sm border border-outline-variant bg-surface-low p-4">
                  <div className="font-headline text-xs font-semibold text-foreground mb-2">{exportFormatLabel(exportData.format)}</div>
                  <div className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words font-body text-[11px] text-foreground/75 custom-scrollbar">
                    {previewText}
                  </div>
                </div>
              )}

              {Array.isArray(evidenceRows) && evidenceRows.length > 0 && (
                <div className="rounded-sm border border-outline-variant bg-surface-low p-4">
                  <h5 className="font-headline text-xs font-semibold text-foreground mb-3 flex items-center gap-2">
                    <FileText size={13} className="text-primary/60" />
                    {t('ref.export_evidence_table')} ({evidenceRows.length})
                  </h5>
                  <div className="space-y-2 max-h-48 overflow-y-auto custom-scrollbar">
                    {evidenceRows.slice(0, 10).map((row, i) => (
                      <div key={`ev-${i}`} className="rounded-sm border border-outline-variant bg-surface-lowest px-3 py-2">
                        <div className="font-headline text-[11px] font-semibold text-foreground truncate">{row.provenance.material_title}</div>
                        <p className="font-body text-[10px] text-foreground/55 mt-0.5 line-clamp-2">{row.excerpt}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {Array.isArray(citationChain) && citationChain.length > 0 && (
                <div className="rounded-sm border border-outline-variant bg-surface-low p-4">
                  <h5 className="font-headline text-xs font-semibold text-foreground mb-3 flex items-center gap-2">
                    <Link2 size={13} className="text-primary/60" />
                    {t('ref.export_citation_chain')} ({citationChain.length})
                  </h5>
                  <div className="space-y-2 max-h-48 overflow-y-auto custom-scrollbar">
                    {citationChain.slice(0, 10).map((row, i) => (
                      <div key={`cc-${i}`} className="rounded-sm border border-outline-variant bg-surface-lowest px-3 py-2 flex items-center gap-2">
                        <span className="font-label text-[9px] text-primary bg-primary/10 px-1.5 py-0.5 rounded-sm">#{String(row.paragraph_index || i + 1)}</span>
                        <span className="font-body text-[10px] text-foreground/60 truncate flex-1">{row.claim_excerpt}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {Array.isArray(reviewFindings) && reviewFindings.length > 0 && (
                <div className="rounded-sm border border-outline-variant bg-surface-low p-4">
                  <h5 className="font-headline text-xs font-semibold text-foreground mb-3 flex items-center gap-2">
                    <AlertTriangle size={13} className="text-amber-500 dark:text-amber-400" />
                    {t('ref.export_review_findings')} ({reviewFindings.length})
                  </h5>
                  <div className="space-y-2">
                    {reviewFindings.map((row, i) => (
                      <div key={`rf-${i}`} className={cn(
                        'rounded-sm border px-3 py-2',
                        row.severity === 'warning' ? 'border-amber-200/70 bg-amber-50/60 dark:border-amber-700/40 dark:bg-amber-500/10' : 'border-emerald-200/70 bg-emerald-50/60 dark:border-emerald-700/40 dark:bg-emerald-500/10'
                      )}>
                        <div className="font-headline text-[11px] font-semibold text-foreground">{row.severity}</div>
                        <p className="font-body text-[10px] text-foreground/55 mt-0.5">{row.message}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

interface ReferenceDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  materials: WritingMaterial[];
  draft: DraftContent | null;
  citationAnchors: CitationAnchor[];
  citationCountByMaterial: Record<string, number>;
  activeMaterialId: string | null;
  activeCitationAnchorInstanceId: string | null;
  activeSectionTitle?: string | null;
  onRequestCitationInsertion: (materialId: string | null) => void;
  onRequestAnchorFocus: (anchor: CitationAnchor) => void;
  onSelectMaterial: (materialId: string | null) => void;
}

export function ReferenceDrawer({
  isOpen,
  onClose,
  materials,
  draft,
  citationAnchors,
  citationCountByMaterial,
  activeMaterialId,
  activeCitationAnchorInstanceId,
  activeSectionTitle,
  onRequestCitationInsertion,
  onRequestAnchorFocus,
  onSelectMaterial,
}: ReferenceDrawerProps) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = React.useState<ReferenceDrawerTab>('evidence');

  const materialLookup = React.useMemo(() => {
    return new Map(materials.map((material) => [material.id, material] as const));
  }, [materials]);

  const anchorsByMaterial = React.useMemo(() => {
    return citationAnchors.reduce<Record<string, CitationAnchor[]>>((acc, anchor) => {
      const key = anchor.materialId || '__unbound__';
      acc[key] = acc[key] || [];
      acc[key].push(anchor);
      return acc;
    }, {});
  }, [citationAnchors]);

  const paragraphRecords = React.useMemo(() => {
    return buildParagraphRecords(draft?.content || '', citationAnchors);
  }, [draft?.content, citationAnchors]);

  const danglingMaterialAnchors = React.useMemo(() => {
    return citationAnchors.filter((anchor) => Boolean(anchor.materialId) && !materialLookup.has(anchor.materialId as string));
  }, [citationAnchors, materialLookup]);

  const citationChain = React.useMemo(() => {
    return citationAnchors.map((anchor) => {
      const paragraph = paragraphRecords.find(
        (entry) => anchor.startOffset >= entry.startOffset && anchor.endOffset <= entry.endOffset,
      ) || null;
      const material = anchor.materialId ? materialLookup.get(anchor.materialId) || null : null;
      const claimExcerpt = paragraph ? shorten(stripAnchorTokens(paragraph.text), 160) : '未能从当前草稿定位到对应段落。';

      return {
        anchor,
        material,
        paragraphIndex: paragraph ? paragraph.index + 1 : null,
        claimExcerpt,
      };
    });
  }, [citationAnchors, materialLookup, paragraphRecords]);

  const evidenceRows = React.useMemo(() => {
    return materials.map((material) => {
      const anchorsForMaterial = anchorsByMaterial[material.id] || [];
      const citationCount = citationCountByMaterial[material.id] || 0;
      const linkedParagraphs = citationChain
        .filter((entry) => entry.anchor.materialId === material.id && entry.paragraphIndex !== null)
        .map((entry) => entry.paragraphIndex as number);
      const uniqueParagraphs = [...new Set(linkedParagraphs)];
      const excerpt = material.summaryZh || material.focusPointsZh[0] || material.titleZh;
      const hasEvidenceSurface = Boolean(material.summaryZh.trim() || material.focusPointsZh.length);
      const status: MaterialEvidenceStatus = citationCount === 0 ? 'unused' : hasEvidenceSurface ? 'used' : 'weak';

      return {
        material,
        anchorsForMaterial,
        citationCount,
        uniqueParagraphs,
        excerpt: shorten(excerpt || '暂无摘要或焦点，可考虑补一条 evidence note。', 160),
        status,
      };
    });
  }, [anchorsByMaterial, citationChain, citationCountByMaterial, materials]);

  const uncitedParagraphs = React.useMemo(() => {
    return paragraphRecords.filter((entry) => stripAnchorTokens(entry.text).length >= 80 && entry.anchors.length === 0);
  }, [paragraphRecords]);

  const unboundAnchors = React.useMemo(() => {
    return citationAnchors.filter((anchor) => !anchor.materialId);
  }, [citationAnchors]);

  const unusedMaterials = React.useMemo(() => {
    return evidenceRows.filter((row) => row.status === 'unused');
  }, [evidenceRows]);

  const weakMaterials = React.useMemo(() => {
    return evidenceRows.filter((row) => row.status === 'weak');
  }, [evidenceRows]);

  const dominantMaterial = React.useMemo(() => {
    const ranked = Object.entries(citationCountByMaterial)
      .filter(([, count]) => count > 0)
      .sort((a, b) => b[1] - a[1]);

    if (!ranked.length || citationAnchors.length < 3) {
      return null;
    }

    const [materialId, count] = ranked[0];
    if (count / citationAnchors.length < 0.6) {
      return null;
    }

    return {
      material: materialLookup.get(materialId) || null,
      count,
    };
  }, [citationAnchors.length, citationCountByMaterial, materialLookup]);

  const reviewFindings = React.useMemo(() => {
    const findings: Array<{
      id: string;
      tone: 'ok' | 'warn';
      title: string;
      description: string;
    }> = [];

    if (uncitedParagraphs.length > 0) {
      findings.push({
        id: 'uncited-paragraphs',
        tone: 'warn',
        title: '存在无引长段落',
        description: `检测到 ${uncitedParagraphs.length} 个长度较长且没有引用点的段落，建议先补证据再扩写。`,
      });
    }

    if (unboundAnchors.length > 0) {
      findings.push({
        id: 'unbound-anchors',
        tone: 'warn',
        title: '存在未绑定资料的引用点',
        description: `当前有 ${unboundAnchors.length} 个引用点没有绑定资料，导出时容易失去来源链。`,
      });
    }

    if (danglingMaterialAnchors.length > 0) {
      findings.push({
        id: 'dangling-material-anchors',
        tone: 'warn',
        title: '存在悬挂引用',
        description: `当前有 ${danglingMaterialAnchors.length} 个引用点指向已经不存在的资料，建议先修复资料映射再导出。`,
      });
    }

    if (weakMaterials.length > 0) {
      findings.push({
        id: 'weak-materials',
        tone: 'warn',
        title: '部分证据条目摘要较弱',
        description: `${weakMaterials.length} 个已被引用的资料缺少摘要或焦点提示，建议补充摘要和焦点，提升证据表可读性。`,
      });
    }

    if (dominantMaterial?.material) {
      findings.push({
        id: 'dominant-material',
        tone: 'warn',
        title: '引用过度集中',
        description: `当前最多被引用的是「${dominantMaterial.material.titleZh}」，占 ${dominantMaterial.count}/${citationAnchors.length} 个引用点；建议补充第二证据源以降低单源依赖。`,
      });
    }

    if (findings.length === 0) {
      findings.push({
        id: 'healthy',
        tone: 'ok',
        title: '当前 section 的证据面板健康',
        description: '未检测到明显的无引长段落、未绑定引用点或单源过度集中问题，可以继续扩写。',
      });
    }

    return findings;
  }, [citationAnchors.length, danglingMaterialAnchors.length, dominantMaterial, uncitedParagraphs.length, unboundAnchors.length, weakMaterials.length]);

  const tabs: Array<{ id: ReferenceDrawerTab; label: string; count?: number }> = [
    { id: 'evidence', label: '证据', count: evidenceRows.length },
    { id: 'chain', label: '引用链', count: citationChain.length },
    { id: 'review', label: '审计', count: reviewFindings.filter((entry) => entry.tone === 'warn').length },
    { id: 'export', label: '导出' },
  ];

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div 
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ type: 'spring', damping: 25, stiffness: 200 }}
          id="reference-drawer"
          role="complementary"
          aria-labelledby="reference-drawer-title"
          className="absolute right-0 top-0 bottom-0 w-[400px] bg-surface-lowest border-l border-outline-variant z-50 shadow-[-8px_0_24px_rgba(0,0,0,0.06)] flex flex-col"
        >
          <div className="p-6 border-b border-outline-variant flex items-center justify-between">
            <div className="flex items-center gap-3">
               <div className="p-2 bg-primary/10 text-primary rounded-sm">
                 <BookOpen size={20} />
               </div>
               <div>
                 <h3 id="reference-drawer-title" className="font-headline font-semibold text-base text-foreground">
                   {t('writing.materials_library')}
                 </h3>
                 <p className="font-label text-[10px] text-foreground/40 mt-1">
                   {activeSectionTitle ? `当前章节：${activeSectionTitle}` : '当前章节：未命名 section'}
                 </p>
               </div>
            </div>
            <button 
              onClick={onClose} 
              aria-label={t('writing.materials.close_aria')}
              className="p-2 hover:bg-surface-container rounded-sm transition-colors"
            >
              <X size={20} />
            </button>
          </div>

          <div className="px-6 pt-4 border-b border-outline-variant/70 bg-surface-lowest">
            <div className="grid grid-cols-3 gap-2 pb-4">
              {tabs.map((tab) => {
                const isActive = tab.id === activeTab;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      'rounded-sm border px-3 py-2 text-left transition-all',
                      isActive
                        ? 'border-primary/30 bg-primary/10 text-primary shadow-sm'
                        : 'border-outline-variant bg-surface-low text-foreground/55 hover:border-primary/20 hover:text-foreground',
                    )}
                  >
                    <div className="font-label text-[10px] font-medium uppercase tracking-wider">{tab.label}</div>
                    <div className="font-headline text-sm font-semibold mt-1">{tab.count ?? 0}</div>
                  </button>
                );
              })}
            </div>
          </div>
          
          <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-4">
            {activeTab === 'evidence' && materials.length === 0 && (
              <div className="rounded-sm border border-dashed border-outline-variant bg-surface-low px-5 py-6 text-center">
                <p className="font-headline text-sm font-semibold text-foreground">{t('writing.no_materials')}</p>
                <p className="mt-2 font-body text-[11px] leading-5 text-foreground/50">
                  {t('writing.materials.empty_description')}
                </p>
              </div>
            )}
            {activeTab === 'evidence' && evidenceRows.map(({ material, anchorsForMaterial, citationCount, uniqueParagraphs, excerpt, status }) => {
              const isActive = activeMaterialId === material.id || anchorsForMaterial.some((anchor) => anchor.instanceId === activeCitationAnchorInstanceId);

              return (
                <div
                  key={material.id}
                  className={cn(
                    'glass-card p-5 rounded-sm group border transition-all hover:shadow-md',
                    isActive ? 'border-primary/30 shadow-md bg-primary/5' : 'border-transparent hover:border-primary/20',
                  )}
                >
                  <div className="flex items-center justify-between mb-4 gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-label text-[8px] font-medium uppercase px-2 py-0.5 bg-primary/10 text-primary rounded-sm tracking-wider">
                        {materialTypeLabel(material.type)}
                      </span>
                      <span className={cn('font-label text-[8px] font-medium uppercase px-2 py-0.5 rounded-sm tracking-wider border', getEvidenceStatusTone(status))}>
                        {getEvidenceStatusLabel(status)}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => onSelectMaterial(material.id)}
                      className="p-1.5 rounded-sm text-foreground/30 hover:text-primary hover:bg-surface-container transition-colors"
                      aria-label={t('writing.ref.focus_material_aria', { title: material.titleZh })}
                      title={t('writing.ref.focus_material')}
                    >
                      <Target size={12} />
                    </button>
                  </div>

                  <h5 className="font-headline text-[13px] font-semibold mb-2 group-hover:text-primary transition-colors leading-snug text-foreground">
                    {material.titleZh}
                  </h5>
                  <p className="font-body text-[11px] text-foreground/60 leading-relaxed mb-4">
                    {excerpt}
                  </p>

                  <div className="grid grid-cols-3 gap-2 mb-4">
                    <div className="rounded-sm border border-outline-variant bg-surface-low px-3 py-2">
                      <div className="font-label text-[9px] uppercase tracking-wider text-foreground/40">引用点</div>
                      <div className="font-headline text-sm font-semibold mt-1 text-foreground">{citationCount}</div>
                    </div>
                    <div className="rounded-sm border border-outline-variant bg-surface-low px-3 py-2">
                      <div className="font-label text-[9px] uppercase tracking-wider text-foreground/40">段落</div>
                      <div className="font-headline text-sm font-semibold mt-1 text-foreground">{uniqueParagraphs.length}</div>
                    </div>
                    <div className="rounded-sm border border-outline-variant bg-surface-low px-3 py-2">
                      <div className="font-label text-[9px] uppercase tracking-wider text-foreground/40">焦点</div>
                      <div className="font-headline text-sm font-semibold mt-1 text-foreground">{material.focusPointsZh.length}</div>
                    </div>
                  </div>

                  {anchorsForMaterial.length > 0 && (
                    <div className="mb-4 flex flex-wrap gap-2">
                      {anchorsForMaterial.slice(0, 4).map((anchor) => (
                        <button
                          type="button"
                          key={anchor.instanceId}
                          onClick={() => onRequestAnchorFocus(anchor)}
                          className={cn(
                            'inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1 font-label text-[9px] font-medium transition-all',
                            activeCitationAnchorInstanceId === anchor.instanceId
                              ? 'border-primary/30 bg-primary/10 text-primary'
                              : 'border-outline-variant bg-surface-lowest text-foreground/50 hover:border-primary/20 hover:text-foreground',
                          )}
                        >
                          <Link2 size={10} />
                          <span>#{anchor.ordinal}</span>
                        </button>
                      ))}
                      {anchorsForMaterial.length > 4 && (
                        <span className="inline-flex items-center rounded-sm border border-outline-variant bg-surface-low px-2.5 py-1 font-label text-[9px] font-medium text-foreground/40">
                          +{anchorsForMaterial.length - 4}
                        </span>
                      )}
                    </div>
                  )}

                  <div className="flex flex-wrap gap-1.5 mb-4">
                    {material.focusPointsZh.length > 0 ? material.focusPointsZh.map((focusPoint, index) => (
                      <span
                        key={`${material.id}-focus-${index}`}
                        className="font-label text-[9px] font-medium px-2 py-0.5 bg-surface-low rounded-sm border border-outline-variant/50"
                      >
                        {focusPoint}
                      </span>
                    )) : (
                      <span className="font-label text-[9px] font-medium px-2 py-0.5 bg-amber-50 text-amber-700 rounded-sm border border-amber-200/70 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-700/40">
                        缺少焦点摘要
                      </span>
                    )}
                  </div>

                  {uniqueParagraphs.length > 0 && (
                    <p className="font-label text-[10px] text-foreground/45 mb-4">
                      已覆盖段落：{uniqueParagraphs.map((paragraphIndex) => `P${paragraphIndex}`).join('、')}
                    </p>
                  )}

                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => onRequestCitationInsertion(material.id)}
                      className="inline-flex items-center gap-1.5 rounded-sm bg-primary px-3 py-1.5 font-label text-[10px] font-medium text-primary-foreground transition-all hover:bg-primary/90"
                      aria-label={t('writing.ref.insert_citation_aria', { title: material.titleZh })}
                    >
                      <ArrowRight size={10} />
                      {t('writing.ref.insert_citation')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        onSelectMaterial(material.id);
                        if (anchorsForMaterial[0]) {
                          onRequestAnchorFocus(anchorsForMaterial[0]);
                          setActiveTab('chain');
                        }
                      }}
                      disabled={!anchorsForMaterial.length}
                      className="inline-flex items-center gap-1.5 rounded-sm border border-outline-variant bg-surface-lowest px-3 py-1.5 font-label text-[10px] font-medium text-foreground/60 transition-all hover:text-foreground hover:border-primary/20 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <ExternalLink size={10} />
                      {t('writing.ref.locate_text')}
                    </button>
                  </div>
                </div>
              );
            })}

            {activeTab === 'chain' && (
              citationChain.length > 0 ? citationChain.map(({ anchor, material, paragraphIndex, claimExcerpt }) => {
                const isActive = activeCitationAnchorInstanceId === anchor.instanceId;
                const materialTitle = material?.titleZh || (anchor.materialId ? '缺失资料' : '未绑定资料');

                return (
                  <button
                    key={anchor.instanceId}
                    type="button"
                    onClick={() => onRequestAnchorFocus(anchor)}
                    className={cn(
                      'w-full rounded-sm border p-4 text-left transition-all',
                      isActive
                        ? 'border-primary/30 bg-primary/5 shadow-sm'
                        : 'border-outline-variant bg-surface-low hover:border-primary/20 hover:bg-surface-lowest',
                    )}
                  >
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="inline-flex items-center gap-1 rounded-sm bg-primary/10 text-primary px-2 py-0.5 font-label text-[9px] font-medium uppercase tracking-wider">
                          <Link2 size={10} />
                          引用点 #{anchor.ordinal}
                        </span>
                        <span className="font-label text-[10px] text-foreground/45 truncate">
                          {paragraphIndex ? `P${paragraphIndex}` : '未定位段落'}
                        </span>
                      </div>
                      <span className="font-label text-[9px] uppercase tracking-wider text-foreground/35">{activeSectionTitle || '当前章节'}</span>
                    </div>

                    <div className="font-headline text-xs font-semibold text-foreground mb-2 truncate">{materialTitle}</div>
                    <p className="font-body text-[11px] leading-5 text-foreground/60 mb-3">{claimExcerpt}</p>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="rounded-sm border border-outline-variant bg-surface-lowest px-2 py-0.5 font-label text-[9px] text-foreground/50">
                        引用标记已记录
                      </span>
                      {anchor.materialId && !material ? (
                        <span className="rounded-sm border border-amber-200/70 bg-amber-50 px-2 py-0.5 font-label text-[9px] text-amber-700 dark:border-amber-700/40 dark:bg-amber-500/10 dark:text-amber-300">
                          资料缺失
                        </span>
                      ) : anchor.materialId ? (
                        <span className="rounded-sm border border-emerald-200/70 bg-emerald-50 px-2 py-0.5 font-label text-[9px] text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/10 dark:text-emerald-300">
                          已绑定资料
                        </span>
                      ) : (
                        <span className="rounded-sm border border-amber-200/70 bg-amber-50 px-2 py-0.5 font-label text-[9px] text-amber-700 dark:border-amber-700/40 dark:bg-amber-500/10 dark:text-amber-300">
                          未绑定资料
                        </span>
                      )}
                    </div>
                  </button>
                );
              }) : (
                <div className="rounded-sm border border-dashed border-outline-variant bg-surface-low px-5 py-6 text-center">
                  <p className="font-headline text-sm font-semibold text-foreground">还没有引用链</p>
                  <p className="mt-2 font-body text-[11px] leading-5 text-foreground/50">
                    先在草稿里插入引用点，这里就会显示“段落 → 引用点 → 资料”的追踪链。
                  </p>
                </div>
              )
            )}

            {activeTab === 'review' && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-sm border border-outline-variant bg-surface-low px-4 py-3">
                    <div className="font-label text-[9px] uppercase tracking-wider text-foreground/40">引用点</div>
                    <div className="font-headline text-lg font-semibold text-foreground mt-1">{citationAnchors.length}</div>
                  </div>
                  <div className="rounded-sm border border-outline-variant bg-surface-low px-4 py-3">
                    <div className="font-label text-[9px] uppercase tracking-wider text-foreground/40">无引段落</div>
                    <div className="font-headline text-lg font-semibold text-foreground mt-1">{uncitedParagraphs.length}</div>
                  </div>
                  <div className="rounded-sm border border-outline-variant bg-surface-low px-4 py-3">
                    <div className="font-label text-[9px] uppercase tracking-wider text-foreground/40">未用资料</div>
                    <div className="font-headline text-lg font-semibold text-foreground mt-1">{unusedMaterials.length}</div>
                  </div>
                  <div className="rounded-sm border border-outline-variant bg-surface-low px-4 py-3">
                    <div className="font-label text-[9px] uppercase tracking-wider text-foreground/40">未绑定引用</div>
                    <div className="font-headline text-lg font-semibold text-foreground mt-1">{unboundAnchors.length}</div>
                  </div>
                </div>

                <div className="space-y-3">
                  {reviewFindings.map((entry) => (
                    <div
                      key={entry.id}
                      className={cn(
                        'rounded-sm border px-4 py-4',
                        entry.tone === 'ok'
                          ? 'border-emerald-200/70 bg-emerald-50/60 dark:border-emerald-700/40 dark:bg-emerald-500/10'
                          : 'border-amber-200/70 bg-amber-50/60 dark:border-amber-700/40 dark:bg-amber-500/10',
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <div className={cn(
                          'mt-0.5 rounded-sm p-1.5',
                          entry.tone === 'ok' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
                        )}>
                          {entry.tone === 'ok' ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                        </div>
                        <div>
                          <div className="font-headline text-xs font-semibold text-foreground">{entry.title}</div>
                          <p className="font-body text-[11px] leading-5 text-foreground/60 mt-1">{entry.description}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {uncitedParagraphs.length > 0 && (
                  <div className="rounded-sm border border-outline-variant bg-surface-low p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <FileText size={14} className="text-foreground/40" />
                      <h5 className="font-headline text-xs font-semibold text-foreground">待补证据的段落</h5>
                    </div>
                    <div className="space-y-2">
                      {uncitedParagraphs.slice(0, 4).map((paragraph) => (
                        <div key={`uncited-${paragraph.index}`} className="rounded-sm border border-outline-variant bg-surface-lowest px-3 py-3">
                          <div className="font-label text-[9px] uppercase tracking-wider text-foreground/35 mb-2">P{paragraph.index + 1}</div>
                          <p className="font-body text-[11px] leading-5 text-foreground/60">{shorten(stripAnchorTokens(paragraph.text), 180)}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {activeTab === 'export' && (
              <ExportPanel />
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
