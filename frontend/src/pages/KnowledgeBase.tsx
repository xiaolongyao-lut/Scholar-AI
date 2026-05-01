import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  Database,
  Upload,
  Search,
  FileText,
  HardDrive,
  Clock,
  ChevronRight,
  Loader2,
  RefreshCw,
  FolderOpen,
  Files,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  Pencil,
  X,
  Check,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { getWritingBackendService } from '@/services/writingBackend';
import { useWriting } from '@/contexts/WritingContext';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import axios from 'axios';

type KBDocumentType = 'pdf' | 'docx' | 'bib' | 'txt' | 'other';
type KBDocumentStatus = 'indexed' | 'no_text';

interface KBDocument {
  id: string;
  name: string;
  type: KBDocumentType;
  size: string;
  addedAt: string;
  chunks: number;
  status: KBDocumentStatus;
}

interface UploadBatchItem {
  material_id?: string;
  title: string;
  content_length?: number;
  chunks?: number;
  status: 'ok' | 'error';
  error?: string;
}

interface UploadBatchResult {
  project_id: string;
  total_files: number;
  successful_files: number;
  failed_files: number;
  total_chunks: number;
  results: UploadBatchItem[];
}

const typeColors: Record<KBDocumentType, string> = {
  pdf: 'text-red-500 bg-red-50',
  docx: 'text-blue-500 bg-blue-50',
  bib: 'text-emerald-500 bg-emerald-50',
  txt: 'text-violet-500 bg-violet-50',
  other: 'text-slate-500 bg-slate-100',
};

const folderPickerProps = {
  webkitdirectory: '',
  directory: '',
} as unknown as React.InputHTMLAttributes<HTMLInputElement>;

function inferDocumentType(name: string): KBDocumentType {
  const match = name.match(/\.([^.]+)$/i)?.[1]?.toLowerCase();
  if (match === 'pdf' || match === 'docx' || match === 'bib' || match === 'txt') {
    return match;
  }
  return 'other';
}

function formatAxiosError(err: unknown): string {
  if (axios.isAxiosError(err) && err.response) {
    const detail = err.response.data?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (detail && typeof detail === 'object') {
      return JSON.stringify(detail);
    }
    return `请求失败 (${err.response.status})`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return '未知错误';
}

interface ScanResultItem {
  filename: string;
  status: 'ok' | 'error' | 'skipped';
  reason?: string;
  chunks?: number;
}

export function KnowledgeBase() {
  const { t } = useI18n();
  const [search, setSearch] = useState('');
  const [isDragOver, setIsDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [docs, setDocs] = useState<KBDocument[]>([]);
  const [uploadSummary, setUploadSummary] = useState<UploadBatchResult | null>(null);
  const [uploadSelection, setUploadSelection] = useState<string[]>([]);
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<{ 
    indexed: number; 
    skipped: number; 
    failed: number; 
    folder: string;
    results?: ScanResultItem[];
  } | null>(null);
  const [showFailedDetails, setShowFailedDetails] = useState(false);
  const [projectSourceFolder, setProjectSourceFolder] = useState('');
  const [editingFolder, setEditingFolder] = useState(false);
  const [folderDraft, setFolderDraft] = useState('');
  const [savingFolder, setSavingFolder] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const { activeProjectId } = useWriting();

  // Fetch project's source_folder when activeProjectId changes
  useEffect(() => {
    if (!activeProjectId) { setProjectSourceFolder(''); return; }
    const baseUrl = getApiBaseUrl();
    axios.get(`${baseUrl}/resources/project/${activeProjectId}`, { timeout: 8000 })
      .then(res => setProjectSourceFolder((res.data as { source_folder?: string }).source_folder ?? ''))
      .catch(() => setProjectSourceFolder(''));
  }, [activeProjectId]);

  const loadMaterials = useCallback(async () => {
    if (!activeProjectId) {
      setDocs([]);
      return;
    }
    try {
      const svc = getWritingBackendService();
      const materials = await svc.listMaterials(activeProjectId);
      let chunkCounts: Record<string, number> = {};
      try {
        const baseUrl = getApiBaseUrl();
        const { data } = await axios.get(`${baseUrl}/resources/chunks`, {
          params: { project_id: activeProjectId },
          timeout: 15000,
        });
        for (const chunk of (data.chunks ?? [])) {
          const materialId = chunk.material_id;
          chunkCounts[materialId] = (chunkCounts[materialId] || 0) + 1;
        }
      } catch {
        chunkCounts = {};
      }
      setDocs(materials.map(material => {
        const chunks = chunkCounts[material.material_id] || 0;
        return {
          id: material.material_id,
          name: material.title,
          type: inferDocumentType(material.title || ''),
          size: '',
          addedAt: material.created_at ? new Date(material.created_at).toISOString().slice(0, 10) : '',
          chunks,
          status: chunks > 0 ? 'indexed' : 'no_text',
        };
      }));
    } catch {
      setDocs([]);
    }
  }, [activeProjectId]);

  useEffect(() => {
    void loadMaterials();
  }, [loadMaterials]);

  const handleUpdateSourceFolder = useCallback(async () => {
    if (!activeProjectId || savingFolder) return;
    const trimmed = folderDraft.trim();
    setSavingFolder(true);
    try {
      const baseUrl = getApiBaseUrl();
      await axios.put(
        `${baseUrl}/resources/project/${activeProjectId}/source-folder`,
        null,
        { params: { source_folder: trimmed }, timeout: 10000 },
      );
      setProjectSourceFolder(trimmed);
      setEditingFolder(false);
    } catch (err: unknown) {
      // keep editing mode open on error so user can retry
      console.error('更新文献文件夹失败:', formatAxiosError(err));
    } finally {
      setSavingFolder(false);
    }
  }, [activeProjectId, folderDraft, savingFolder]);

  const handleScanFolder = useCallback(async () => {
    if (!activeProjectId || scanning) return;
    setScanning(true);
    setScanResult(null);
    setShowFailedDetails(false);
    try {
      const baseUrl = getApiBaseUrl();
      const { data } = await axios.post(`${baseUrl}/resources/project/${activeProjectId}/scan-folder`, {}, { timeout: 300000 });
      setScanResult({ 
        indexed: data.indexed, 
        skipped: data.skipped, 
        failed: data.failed, 
        folder: data.folder,
        results: data.results 
      });
      await loadMaterials();
    } catch (err: unknown) {
      const msg = formatAxiosError(err);
      setScanResult({ indexed: 0, skipped: 0, failed: 0, folder: msg });
    } finally {
      setScanning(false);
    }
  }, [activeProjectId, scanning, loadMaterials]);

  const handleUploadFiles = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0 || !activeProjectId) {
      return;
    }

    const pickedFiles = Array.from(files);
    const baseUrl = getApiBaseUrl();
    const formData = new FormData();
    formData.append('project_id', activeProjectId);
    pickedFiles.forEach(file => formData.append('files', file));

    setUploading(true);
    setUploadSummary(null);
    setUploadSelection(pickedFiles.map(file => file.name));

    try {
      const { data } = await axios.post<UploadBatchResult>(`${baseUrl}/resources/upload/batch`, formData, {
        timeout: Math.max(120000, pickedFiles.length * 45000),
      });
      setUploadSummary(data);
    } catch (err: unknown) {
      const errorMessage = formatAxiosError(err);
      setUploadSummary({
        project_id: activeProjectId,
        total_files: pickedFiles.length,
        successful_files: 0,
        failed_files: pickedFiles.length,
        total_chunks: 0,
        results: pickedFiles.map(file => ({
          title: file.name,
          status: 'error',
          error: errorMessage,
        })),
      });
    } finally {
      await loadMaterials();
      setUploading(false);
      setUploadSelection([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      if (folderInputRef.current) {
        folderInputRef.current.value = '';
      }
    }
  }, [activeProjectId, loadMaterials]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    void handleUploadFiles(e.dataTransfer.files);
  };

  const filteredDocs = docs.filter(doc => !search || doc.name.toLowerCase().includes(search.toLowerCase()));
  const totalChunks = docs.reduce((sum, doc) => sum + doc.chunks, 0);
  const indexedCount = docs.filter(doc => doc.status === 'indexed').length;
  const noTextCount = docs.filter(doc => doc.status === 'no_text').length;
  const recentSucceeded = (uploadSummary?.results ?? []).filter(item => item.status === 'ok').slice(0, 4);
  const recentFailed = (uploadSummary?.results ?? []).filter(item => item.status === 'error').slice(0, 4);

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.bib,.txt,.md,.csv,.json"
        className="hidden"
        title={t('kb.select_files')}
        aria-label={t('kb.select_files')}
        onChange={e => void handleUploadFiles(e.target.files)}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        className="hidden"
        title={t('kb.select_folder')}
        aria-label={t('kb.select_folder')}
        onChange={e => void handleUploadFiles(e.target.files)}
        {...folderPickerProps}
      />

      <div className="flex flex-col gap-4 mb-8 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold text-foreground">
            {t('kb.title')}
          </h1>
          <p className="font-label text-sm text-foreground/50 mt-1">
            {t('kb.subtitle')}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void loadMaterials()}
            disabled={uploading || !activeProjectId}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-outline-variant/50 bg-surface-high text-sm font-label text-foreground hover:border-primary/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw size={14} />
            {t('common.refresh')}
          </button>
          {/* Scan folder button — only visible when project has a source_folder */}
          {projectSourceFolder && (
            <button
              type="button"
              onClick={() => void handleScanFolder()}
              disabled={scanning || uploading || !activeProjectId}
              title={`扫描文件夹: ${projectSourceFolder}`}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-emerald-300/60 bg-emerald-50/40 text-sm font-label text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {scanning ? <Loader2 size={14} className="animate-spin" /> : <FolderOpen size={14} />}
              {scanning ? '扫描中…' : '扫描文献文件夹'}
            </button>
          )}
          <button
            type="button"
            onClick={() => folderInputRef.current?.click()}
            disabled={uploading || !activeProjectId}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-outline-variant/50 bg-surface-high text-sm font-label text-foreground hover:border-primary/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <FolderOpen size={14} />
            {t('kb.select_folder')}
          </button>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || !activeProjectId}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-label hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Files size={14} />
            {t('kb.select_files')}
          </button>
        </div>
      </div>

      {/* Source folder info bar */}
      {activeProjectId && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-emerald-50/50 border border-emerald-200/60 text-xs font-label">
          {editingFolder ? (
            <div className="flex items-center gap-2">
              <FolderOpen size={13} className="text-emerald-600 flex-shrink-0" />
              <span className="text-emerald-700 font-medium flex-shrink-0">文献文件夹：</span>
              <input
                autoFocus
                value={folderDraft}
                onChange={e => setFolderDraft(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') void handleUpdateSourceFolder();
                  if (e.key === 'Escape') setEditingFolder(false);
                }}
                placeholder="输入文件夹绝对路径，例如 D:\\我的文献"
                className="flex-1 bg-white/80 border border-emerald-300 rounded px-2 py-0.5 font-mono text-emerald-800 focus:outline-none focus:ring-1 focus:ring-emerald-400"
              />
              <button
                type="button"
                onClick={() => void handleUpdateSourceFolder()}
                disabled={savingFolder}
                title="保存"
                className="flex-shrink-0 p-1 rounded text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
              >
                {savingFolder ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
              </button>
              <button
                type="button"
                onClick={() => setEditingFolder(false)}
                title="取消"
                className="flex-shrink-0 p-1 rounded text-emerald-500 hover:bg-emerald-100"
              >
                <X size={13} />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <FolderOpen size={13} className="text-emerald-600 flex-shrink-0" />
              <span className="text-emerald-700 font-medium flex-shrink-0">文献文件夹：</span>
              {projectSourceFolder ? (
                <>
                  <code className="text-emerald-600 font-mono truncate flex-1">{projectSourceFolder}</code>
                  <span className="text-emerald-500/70 ml-1 flex-shrink-0">切片存在 .scholarai/</span>
                </>
              ) : (
                <span className="text-emerald-500/60 italic flex-1">未设置（切片存在 output/chunk_store/）</span>
              )}
              <button
                type="button"
                onClick={() => { setFolderDraft(projectSourceFolder); setEditingFolder(true); }}
                title="修改文献文件夹路径"
                className="flex-shrink-0 p-1 rounded text-emerald-500 hover:bg-emerald-100 hover:text-emerald-700 transition-colors"
              >
                <Pencil size={12} />
              </button>
            </div>
          )}
        </div>
      )}
      {scanResult && (
        <div className={cn(
          "mb-4 flex flex-col gap-3 px-4 py-3 rounded-xl border text-sm font-label shadow-sm transition-all",
          scanResult.failed > 0 && scanResult.indexed === 0
            ? "bg-red-50/50 border-red-200/60 text-red-800"
            : scanResult.failed > 0
              ? "bg-amber-50/50 border-amber-200/60 text-amber-800"
              : "bg-emerald-50/50 border-emerald-200/60 text-emerald-800"
        )}>
          <div className="flex items-start gap-2.5">
            {scanResult.failed > 0 && scanResult.indexed === 0 ? (
              <AlertCircle size={16} className="text-red-600 mt-0.5 flex-shrink-0" />
            ) : scanResult.failed > 0 ? (
              <AlertTriangle size={16} className="text-amber-600 mt-0.5 flex-shrink-0" />
            ) : (
              <CheckCircle2 size={16} className="text-emerald-600 mt-0.5 flex-shrink-0" />
            )}
            
            <div className="flex-1 min-w-0 space-y-1">
              <h4 className="font-semibold text-[13px]">
                {scanResult.failed > 0 && scanResult.indexed === 0 
                  ? t('kb.scan_all_failed') 
                  : scanResult.failed > 0 
                    ? t('kb.scan_partial') 
                    : t('kb.scan_done')}
              </h4>
              <div className="text-[11px] opacity-80 leading-relaxed">
                <p>
                  <strong>{scanResult.indexed}</strong> {t('kb.scan_indexed_short')},
                  {scanResult.skipped > 0 && <> <strong>{scanResult.skipped}</strong> {t('kb.scan_skipped_short')},</>}
                  <span className={cn(scanResult.failed > 0 && "text-red-600 font-bold")}>
                    {" "}<strong>{scanResult.failed}</strong> {t('kb.scan_failed_short')}
                  </span>.
                </p>
                <p className="font-mono text-[10px] opacity-70 mt-1 break-all flex items-center gap-1">
                  <FolderOpen size={10} /> {scanResult.folder}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0 ml-4">
              {scanResult.failed > 0 && (
                <>
                  <button
                    type="button"
                    onClick={() => setShowFailedDetails(!showFailedDetails)}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium bg-black/5 hover:bg-black/10 transition-colors"
                  >
                    {showFailedDetails ? t('common.close') : t('common.details') || '详情'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleScanFolder()}
                    disabled={scanning}
                    className={cn(
                      "inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-colors disabled:opacity-50",
                      scanResult.indexed === 0
                        ? "bg-red-100 hover:bg-red-200 text-red-700"
                        : "bg-amber-100 hover:bg-amber-200 text-amber-700"
                    )}
                  >
                    {scanning ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    {t('kb.scan_retry')}
                  </button>
                </>
              )}
              <button
                type="button"
                onClick={() => setScanResult(null)}
                className="p-1.5 rounded-md hover:bg-black/5 opacity-60 hover:opacity-100 transition-all"
                title={t('kb.scan_clear')}
              >
                <X size={14} />
              </button>
            </div>
          </div>

          {/* Failed Items Detail List */}
          {showFailedDetails && scanResult.results && scanResult.results.filter(r => r.status === 'error').length > 0 && (
            <motion.div 
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              className="mt-2 pt-2 border-t border-black/5 overflow-hidden"
            >
              <div className="space-y-1.5 max-h-48 overflow-y-auto custom-scrollbar pr-1">
                {scanResult.results.filter(r => r.status === 'error').slice(0, 20).map((res, i) => (
                  <div key={i} className="flex flex-col gap-0.5 bg-black/5 rounded px-2 py-1.5">
                    <div className="flex items-center gap-2 text-[11px] font-medium text-red-800">
                      <AlertCircle size={10} />
                      <span className="truncate">{res.filename}</span>
                    </div>
                    {res.reason && (
                      <p className="text-[10px] text-red-700/70 ml-4 leading-normal">
                        {res.reason}
                      </p>
                    )}
                  </div>
                ))}
                {scanResult.results.filter(r => r.status === 'error').length > 20 && (
                  <p className="text-[10px] text-center opacity-40 py-1 italic">
                    ...及另外 {scanResult.results.filter(r => r.status === 'error').length - 20} 个错误
                  </p>
                )}
              </div>
            </motion.div>
          )}
        </div>
      )}

      {!activeProjectId ? (
        <div className="glass-card rounded-xl p-8 text-center">
          <Database size={28} className="mx-auto mb-3 text-primary/60" />
          <h2 className="font-display text-xl font-semibold text-foreground mb-2">{t('kb.no_project_title')}</h2>
          <p className="font-label text-sm text-foreground/50 max-w-lg mx-auto">{t('kb.no_project_desc')}</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
            {[
              { icon: FileText, label: t('kb.stat_documents'), value: docs.length.toString(), color: 'text-primary' },
              { icon: HardDrive, label: t('kb.stat_chunks'), value: totalChunks.toString(), color: 'text-emerald-500' },
              { icon: Database, label: t('kb.stat_indexed'), value: indexedCount.toString(), color: 'text-amber-500' },
              { icon: AlertTriangle, label: t('kb.stat_no_text'), value: noTextCount.toString(), color: 'text-orange-500' },
            ].map((stat, index) => (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.05 }}
                className="glass-card p-4 rounded-lg flex items-center gap-3"
              >
                <div className={cn('h-10 w-10 rounded-lg flex items-center justify-center bg-surface-high', stat.color)}>
                  <stat.icon size={20} />
                </div>
                <div>
                  <div className="font-headline text-lg font-semibold text-foreground tabular-nums">{stat.value}</div>
                  <div className="font-label text-[10px] text-foreground/40">{stat.label}</div>
                </div>
              </motion.div>
            ))}
          </div>

          <div
            onDragOver={e => { e.preventDefault(); setIsDragOver(true); }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleDrop}
            onClick={() => !uploading && fileInputRef.current?.click()}
            className={cn(
              'border-2 border-dashed rounded-lg p-8 mb-6 text-center transition-all cursor-pointer',
              isDragOver
                ? 'border-primary bg-primary/5'
                : 'border-outline-variant/40 hover:border-primary/30 bg-surface-high/30',
              uploading && 'cursor-progress'
            )}
          >
            {uploading ? (
              <Loader2 size={28} className="mx-auto mb-3 text-primary animate-spin" />
            ) : (
              <Upload size={28} className="mx-auto mb-3 text-foreground/20" />
            )}
            <p className="font-label text-sm text-foreground/60 font-medium">
              {uploading
                ? t('kb.uploading_batch', { count: uploadSelection.length || uploadSummary?.total_files || 0 })
                : t('kb.upload_hint')}
            </p>
            <p className="font-label text-[10px] text-foreground/30 mt-1">
              {uploading ? t('kb.uploading_detail') : t('kb.upload_batch_hint')}
            </p>
            {uploadSelection.length > 0 && (
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {uploadSelection.slice(0, 6).map(name => (
                  <span key={name} className="px-2 py-1 rounded-full bg-surface-high text-[10px] font-label text-foreground/60">
                    {name}
                  </span>
                ))}
                {uploadSelection.length > 6 && (
                  <span className="px-2 py-1 rounded-full bg-surface-high text-[10px] font-label text-foreground/60">
                    +{uploadSelection.length - 6}
                  </span>
                )}
              </div>
            )}
          </div>

          {uploadSummary && (
            <div className="glass-card rounded-xl p-5 mb-6 space-y-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h3 className="font-headline text-sm font-semibold text-foreground">{t('kb.upload_summary_title')}</h3>
                  <p className="font-label text-xs text-foreground/45 mt-1">{t('kb.upload_summary_desc')}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <span className="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-label">
                    {t('kb.upload_summary_success', { success: uploadSummary.successful_files, total: uploadSummary.total_files })}
                  </span>
                  <span className="px-2.5 py-1 rounded-full bg-primary/10 text-primary text-xs font-label">
                    {t('kb.upload_summary_chunks', { count: uploadSummary.total_chunks })}
                  </span>
                  {uploadSummary.failed_files > 0 && (
                    <span className="px-2.5 py-1 rounded-full bg-orange-50 text-orange-700 text-xs font-label">
                      {t('kb.upload_summary_failed', { count: uploadSummary.failed_files })}
                    </span>
                  )}
                </div>
              </div>

              <div className="grid gap-3 lg:grid-cols-2">
                <div className="rounded-lg border border-emerald-100 bg-emerald-50/70 p-3">
                  <div className="flex items-center gap-2 text-emerald-700 text-sm font-label mb-2">
                    <CheckCircle2 size={14} />
                    {t('kb.upload_success_list')}
                  </div>
                  {recentSucceeded.length > 0 ? (
                    <div className="space-y-2">
                      {recentSucceeded.map(item => (
                        <div key={`${item.title}-${item.material_id ?? 'ok'}`} className="text-xs text-emerald-800 flex items-start justify-between gap-2">
                          <span className="truncate">{item.title}</span>
                          <span className="shrink-0">{item.chunks ?? 0} chunks</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-foreground/45">{t('kb.upload_success_empty')}</p>
                  )}
                </div>

                <div className="rounded-lg border border-orange-100 bg-orange-50/70 p-3">
                  <div className="flex items-center gap-2 text-orange-700 text-sm font-label mb-2">
                    <AlertTriangle size={14} />
                    {t('kb.upload_failed_list')}
                  </div>
                  {recentFailed.length > 0 ? (
                    <div className="space-y-2">
                      {recentFailed.map(item => (
                        <div key={`${item.title}-error`} className="text-xs text-orange-800">
                          <div className="truncate font-medium">{item.title}</div>
                          <div className="text-orange-700/80 mt-0.5 line-clamp-2">{item.error}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-foreground/45">{t('kb.upload_failed_empty')}</p>
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="flex items-center gap-2 bg-surface-lowest rounded-lg px-3 py-2 border border-outline-variant/50 focus-within:border-primary/40 transition-colors mb-5">
            <Search size={15} className="text-foreground/30" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={t('kb.search_placeholder')}
              className="flex-1 bg-transparent text-sm font-label text-foreground placeholder:text-foreground/30 focus:outline-none"
            />
          </div>

          {filteredDocs.length === 0 ? (
            <div className="glass-card rounded-xl p-8 text-center">
              <Database size={28} className="mx-auto mb-3 text-foreground/25" />
              <h3 className="font-headline text-sm font-semibold text-foreground mb-1">
                {docs.length === 0 ? t('kb.empty_title') : t('kb.no_search_results')}
              </h3>
              <p className="font-label text-sm text-foreground/45">
                {docs.length === 0 ? t('kb.empty_desc') : t('kb.no_search_results_desc')}
              </p>
            </div>
          ) : (
            <div className="glass-card rounded-lg divide-y divide-outline-variant/30">
              {filteredDocs.map((doc, index) => (
                <div key={doc.id}>
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: index * 0.03 }}
                    onClick={() => setExpandedDocId(prev => prev === doc.id ? null : doc.id)}
                    className="flex items-center gap-4 p-4 hover:bg-surface-high/50 transition-colors cursor-pointer group"
                  >
                    <div className={cn('h-10 w-10 rounded-lg flex items-center justify-center flex-shrink-0', typeColors[doc.type])}>
                      <FileText size={18} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="font-headline text-sm font-medium text-foreground truncate">{doc.name}</h4>
                      <div className="flex flex-wrap items-center gap-3 mt-0.5 font-label text-[10px] text-foreground/30">
                        {doc.addedAt && <span className="flex items-center gap-1"><Clock size={9} /> {doc.addedAt}</span>}
                        {doc.status === 'indexed' ? (
                          <span className="text-emerald-500">{doc.chunks} chunks</span>
                        ) : (
                          <span className="text-orange-600">{t('kb.doc_no_text')}</span>
                        )}
                      </div>
                    </div>
                    <span className={cn(
                      'px-2 py-0.5 text-[9px] font-label font-medium rounded',
                      doc.status === 'indexed'
                        ? 'bg-emerald-50 text-emerald-600'
                        : 'bg-orange-50 text-orange-700'
                    )}>
                      {doc.status === 'indexed' ? t('kb.status_indexed') : t('kb.status_no_text')}
                    </span>
                    <ChevronRight
                      size={14}
                      className={cn(
                        'transition-all duration-200',
                        expandedDocId === doc.id
                          ? 'rotate-90 text-primary/60 opacity-100'
                          : 'text-foreground/15 opacity-0 group-hover:opacity-100'
                      )}
                    />
                  </motion.div>
                  {expandedDocId === doc.id && (
                    <div className="px-4 pb-4 pt-2 bg-surface-lowest/60 border-t border-outline-variant/20">
                      <div className="rounded-lg border border-outline-variant/30 p-3 text-[11px] font-label space-y-1.5 bg-surface-lowest">
                        <div className="flex items-start gap-2">
                          <span className="text-foreground/40 w-16 flex-shrink-0">文档 ID</span>
                          <span className="font-mono text-[10px] text-foreground/50 break-all">{doc.id}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-foreground/40 w-16 flex-shrink-0">格式</span>
                          <span className="uppercase text-foreground/70">{doc.type}</span>
                        </div>
                        {doc.status === 'indexed' ? (
                          <div className="flex items-center gap-2">
                            <span className="text-foreground/40 w-16 flex-shrink-0">切片数</span>
                            <span className="text-emerald-600 font-medium">{doc.chunks} 个已入库</span>
                          </div>
                        ) : (
                          <p className="text-orange-600">该文档无可提取文本，未建索引</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
