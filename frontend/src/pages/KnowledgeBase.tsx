import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
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
  BookOpen,
  Trash2,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { getWritingBackendService } from '@/services/writingBackend';
import { useWriting } from '@/contexts/WritingContext';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import axios from 'axios';
import { PageHeader } from '@/components/common/PageHeader';
import { StatusPill } from '@/components/common/StatusPill';
import { SectionCard } from '@/components/common/SectionCard';
import { EmptyState } from '@/components/common/EmptyState';

type KBDocumentType = 'pdf' | 'docx' | 'bib' | 'txt' | 'other';
type KBDocumentStatus = 'indexed' | 'no_text';
type DocumentCollectionFilter = 'all' | 'indexed' | 'no_text';
type DocumentCollectionChip =
  | { id: DocumentCollectionFilter; label: string; count: number; disabled?: false }
  | { id: 'chunks'; label: string; count?: number; disabled: true };

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
  status: 'ok' | 'error' | 'duplicate';
  error?: string;
}

interface UploadBatchResult {
  project_id: string;
  total_files: number;
  successful_files: number;
  duplicate_files?: number;
  failed_files: number;
  total_chunks: number;
  results: UploadBatchItem[];
}

const typeColors: Record<KBDocumentType, string> = {
  pdf: 'text-red-500 bg-red-50 dark:bg-red-500/15 dark:text-red-300',
  docx: 'text-blue-500 bg-blue-50 dark:bg-blue-500/15 dark:text-blue-300',
  bib: 'text-emerald-500 bg-emerald-50 dark:bg-emerald-500/15 dark:text-emerald-300',
  txt: 'text-violet-500 bg-violet-50 dark:bg-violet-500/15 dark:text-violet-300',
  other: 'text-slate-500 bg-slate-100 dark:bg-slate-500/15 dark:text-slate-300',
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
  const location = useLocation();
  const navigate = useNavigate();
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
  const [projectTitle, setProjectTitle] = useState('');
  const [collectionFilter, setCollectionFilter] = useState<DocumentCollectionFilter>('all');
  const [editingFolder, setEditingFolder] = useState(false);
  const [folderDraft, setFolderDraft] = useState('');
  const [savingFolder, setSavingFolder] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const { activeProjectId } = useWriting();

  // Fetch project's source_folder + title when activeProjectId changes
  useEffect(() => {
    if (!activeProjectId) { setProjectSourceFolder(''); setProjectTitle(''); return; }
    const baseUrl = getApiBaseUrl();
    axios.get(`${baseUrl}/resources/project/${activeProjectId}`, { timeout: 8000 })
      .then(res => {
        const data = res.data as { source_folder?: string; title?: string };
        setProjectSourceFolder(data.source_folder ?? '');
        setProjectTitle(data.title ?? '');
      })
      .catch(() => { setProjectSourceFolder(''); setProjectTitle(''); });
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

  const openPdfInWorkbench = useCallback((materialId: string, page?: number) => {
    const pageQuery = page && page > 0 ? `?page=${encodeURIComponent(String(page))}` : '';
    navigate(`/workbench/paper/${encodeURIComponent(materialId)}${pageQuery}`);
  }, [navigate]);

  const handleDeleteDocument = useCallback(async (materialId: string, materialName: string) => {
    if (!window.confirm(`确定要删除「${materialName}」吗？该文献的切块和原始文件都会被移除，且无法恢复。`)) {
      return;
    }
    try {
      const baseUrl = getApiBaseUrl();
      await axios.delete(`${baseUrl}/resources/material/${encodeURIComponent(materialId)}`, { timeout: 15000 });
      if (expandedDocId === materialId) setExpandedDocId(null);
      await loadMaterials();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '未知错误';
      window.alert(`删除失败：${msg}`);
    }
  }, [expandedDocId, loadMaterials]);

  useEffect(() => {
    void loadMaterials();
  }, [loadMaterials]);

  useEffect(() => {
    if (docs.length === 0) return;
    const params = new URLSearchParams(location.search);
    const targetId = params.get('openPdf');
    if (!targetId) return;
    const doc = docs.find(d => d.id === targetId);
    if (doc && doc.type === 'pdf') {
      const pageParam = params.get('page');
      const page = pageParam ? Number(pageParam) : undefined;
      openPdfInWorkbench(doc.id, Number.isFinite(page) && page! > 0 ? page : undefined);
    } else if (doc) {
      navigate('/knowledge', { replace: true });
    }
  }, [docs, location.search, navigate, openPdfInWorkbench]);

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

  const filteredDocs = docs.filter(doc => {
    if (collectionFilter !== 'all' && doc.status !== collectionFilter) return false;
    return !search || doc.name.toLowerCase().includes(search.toLowerCase());
  });
  const totalChunks = docs.reduce((sum, doc) => sum + doc.chunks, 0);
  const indexedCount = docs.filter(doc => doc.status === 'indexed').length;
  const noTextCount = docs.filter(doc => doc.status === 'no_text').length;
  const recentSucceeded = (uploadSummary?.results ?? []).filter(item => item.status === 'ok').slice(0, 4);
  const recentFailed = (uploadSummary?.results ?? []).filter(item => item.status === 'error').slice(0, 4);

  // Library index view (Long-Run v2 Slice D) — per
  // workspace_artifacts/generated/output/scholar_ai_workbench_visual_baseline/06_left_rail_destinations/12_library_index_screen.png
  // Three regions:
  //   - left: Collections / Tags / Recent sidebar (~280px, lg+ only)
  //   - center: dense paper table with filter chips + search
  //   - right: paper detail drawer (when a row is selected, xl+ only)
  // Upload and scan flows live above this branch. R5/R5.1: no raw IDs,
  // friendly Chinese only.
  const selectedDoc = expandedDocId ? docs.find((d) => d.id === expandedDocId) ?? null : null;
  const collectionGroups = [
    { id: 'all' as const, label: '全部文献', count: docs.length },
    { id: 'indexed' as const, label: '已索引', count: indexedCount },
    { id: 'no_text' as const, label: '未提取文本', count: noTextCount },
  ];

  return (
    <div className="flex h-full min-h-0 bg-background">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.docx,.bib,.txt,.md,.csv,.json"
        className="hidden"
        title={t('kb.select_files')}
        aria-label={t('kb.select_files')}
        onChange={(e) => void handleUploadFiles(e.target.files)}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        className="hidden"
        title={t('kb.select_folder')}
        aria-label={t('kb.select_folder')}
        onChange={(e) => void handleUploadFiles(e.target.files)}
        {...folderPickerProps}
      />

      {/* Left — Collections / Tags / Recent (~280px) */}
      <aside className="hidden w-[280px] shrink-0 flex-col border-r border-outline-variant/60 bg-surface-lowest lg:flex">
        <div className="border-b border-outline-variant/40 px-4 py-3">
          <h2 className="font-headline text-sm font-semibold text-foreground">文献集</h2>
        </div>
        <div className="border-b border-outline-variant/30 p-3">
          <div className="flex items-center gap-2 rounded-md border border-outline-variant/60 bg-surface-low px-2 py-1.5">
            <Search size={13} className="text-foreground/35" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索文献集"
              aria-label="搜索文献集"
              className="w-full bg-transparent text-xs font-label text-foreground placeholder:text-foreground/35 focus:outline-none"
            />
          </div>
        </div>
        <nav className="flex-1 overflow-auto p-2 text-xs text-foreground/75">
          <ul className="space-y-0.5">
            {collectionGroups.map((g) => (
              <li key={g.id}>
                <button
                  type="button"
                  onClick={() => setCollectionFilter(g.id)}
                  className={cn(
                    'flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left transition-colors',
                    collectionFilter === g.id
                      ? 'bg-primary/10 text-primary'
                      : 'hover:bg-surface-default/60',
                  )}
                >
                  <span className="flex items-center gap-2">
                    <Database size={11} className="text-foreground/45" />
                    {g.label}
                  </span>
                  <span className="text-[10px] text-foreground/40">{g.count}</span>
                </button>
              </li>
            ))}
          </ul>
          {activeProjectId && (
            <div className="mt-3 rounded-md border border-outline-variant/60 bg-surface-low/60 p-2 text-[11px] text-foreground/70 dark:bg-surface-low/40">
              <div className="flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-400">
                <FolderOpen size={11} /> 文献文件夹
              </div>
              {editingFolder ? (
                <div className="mt-1.5 flex items-center gap-1">
                  <input
                    autoFocus
                    value={folderDraft}
                    onChange={(e) => setFolderDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void handleUpdateSourceFolder();
                      if (e.key === 'Escape') setEditingFolder(false);
                    }}
                    placeholder="文件夹绝对路径"
                    className="min-w-0 flex-1 rounded border border-outline-variant/60 bg-surface-lowest px-1.5 py-0.5 font-mono text-[10px] text-foreground focus:outline-none focus:ring-1 focus:ring-emerald-400/60 dark:bg-surface-high"
                  />
                  <button
                    type="button"
                    onClick={() => void handleUpdateSourceFolder()}
                    disabled={savingFolder}
                    title="保存"
                    className="shrink-0 rounded p-1 text-emerald-700 hover:bg-emerald-100/60 disabled:opacity-50 dark:text-emerald-400 dark:hover:bg-emerald-500/15"
                  >
                    {savingFolder ? <Loader2 size={10} className="animate-spin" /> : <Check size={10} />}
                  </button>
                </div>
              ) : (
                <div className="mt-1 flex items-start justify-between gap-1">
                  <p className="break-all font-mono text-[10px] text-foreground/70">
                    {projectSourceFolder || <span className="text-foreground/45">未设置</span>}
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      setEditingFolder(true);
                      setFolderDraft(projectSourceFolder);
                    }}
                    className="shrink-0 rounded p-0.5 text-foreground/50 hover:bg-surface-high hover:text-emerald-600 dark:hover:text-emerald-400"
                    title="编辑"
                  >
                    <Pencil size={10} />
                  </button>
                </div>
              )}
              {projectSourceFolder && (
                <button
                  type="button"
                  onClick={() => void handleScanFolder()}
                  disabled={scanning || uploading}
                  className="mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-emerald-400/60 bg-emerald-50/70 px-2 py-1 text-[10px] font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300 dark:hover:bg-emerald-500/20"
                >
                  {scanning ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
                  {scanning ? '扫描中…' : '扫描文献夹'}
                </button>
              )}
            </div>
          )}
          <div className="mt-4">
            <h3 className="px-2 pb-1 font-label text-[10px] font-medium uppercase tracking-wider text-foreground/40">
              最近打开
            </h3>
            <ul className="space-y-0.5 text-[11px] text-foreground/70">
              {docs.slice(0, 5).map((d) => (
                <li key={`recent-${d.id}`}>
                  <button
                    type="button"
                    onClick={() => setExpandedDocId(d.id)}
                    className="flex w-full items-center gap-2 truncate rounded px-2 py-1 text-left transition-colors hover:bg-surface-default/60"
                  >
                    <FileText size={10} className="shrink-0 text-foreground/40" />
                    <span className="truncate">{d.name}</span>
                  </button>
                </li>
              ))}
              {docs.length === 0 && (
                <li className="px-2 py-1 text-foreground/40">尚无文献</li>
              )}
            </ul>
          </div>
        </nav>
      </aside>

      {/* Center — Library index */}
      <main className="flex min-w-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col overflow-auto px-6 py-5">
          <PageHeader
            title={projectTitle ? t('kb.title_with_project', { name: projectTitle }) : t('kb.title')}
            subtitle={t('kb.subtitle')}
            actions={
              <>
                <button
                  type="button"
                  onClick={() => void loadMaterials()}
                  disabled={uploading || !activeProjectId}
                  className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 font-label text-xs text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50"
                >
                  <RefreshCw size={12} /> {t('common.refresh')}
                </button>
                <button
                  type="button"
                  onClick={() => folderInputRef.current?.click()}
                  disabled={uploading || !activeProjectId}
                  className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 font-label text-xs text-foreground/75 transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50"
                >
                  <FolderOpen size={12} /> {t('kb.select_folder')}
                </button>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading || !activeProjectId}
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                >
                  <Files size={12} /> {t('kb.select_files')}
                </button>
              </>
            }
          />

          {!activeProjectId ? (
            <EmptyState
              title={t('kb.no_project_title')}
              description={t('kb.no_project_desc')}
              icon={<Database size={28} />}
            />
          ) : (
            <>
              {/* Filter chip row */}
              <div className="mb-3 flex flex-wrap items-center gap-1.5">
                {([
                  { id: 'all', label: '全部', count: docs.length },
                  { id: 'indexed', label: '已索引', count: indexedCount },
                  { id: 'no_text', label: '未提取文本', count: noTextCount },
                  { id: 'chunks', label: `共 ${totalChunks} 切片`, disabled: true },
                ] satisfies DocumentCollectionChip[]).map((c) => (
                  <button
                    type="button"
                    key={c.id}
                    onClick={() => {
                      if (!c.disabled) setCollectionFilter(c.id);
                    }}
                    disabled={c.disabled}
                    className={cn(
                      'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors disabled:cursor-default',
                      !c.disabled && collectionFilter === c.id
                        ? 'border-primary/40 bg-primary/10 text-primary'
                        : 'border-outline-variant/60 bg-surface-low text-foreground/65 hover:border-primary/35 hover:text-foreground',
                    )}
                  >
                    {c.label}
                    {typeof c.count === 'number' && (
                      <span className="text-[10px] text-foreground/45">· {c.count}</span>
                    )}
                  </button>
                ))}
              </div>

              {/* Upload drop zone (compact) */}
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragOver(true);
                }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={handleDrop}
                onClick={() => !uploading && fileInputRef.current?.click()}
                className={cn(
                  'mb-3 flex cursor-pointer items-center justify-between rounded-md border border-dashed px-3 py-2 transition-colors',
                  isDragOver
                    ? 'border-primary bg-primary/5'
                    : 'border-outline-variant/50 hover:border-primary/40 bg-surface-low',
                  uploading && 'cursor-progress',
                )}
              >
                <div className="flex items-center gap-2 text-xs text-foreground/65">
                  {uploading ? (
                    <Loader2 size={14} className="animate-spin text-primary" />
                  ) : (
                    <Upload size={14} className="text-foreground/35" />
                  )}
                  <span>
                    {uploading
                      ? t('kb.uploading_batch', { count: uploadSelection.length || uploadSummary?.total_files || 0 })
                      : t('kb.upload_hint')}
                  </span>
                </div>
                <span className="hidden text-[10px] text-foreground/40 sm:inline">
                  {uploading ? t('kb.uploading_detail') : t('kb.upload_batch_hint')}
                </span>
              </div>

              {/* Upload summary (compact strip) */}
              {uploadSummary && (
                <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-outline-variant/40 bg-surface-low px-3 py-2 text-[11px]">
                  <CheckCircle2 size={12} className="text-emerald-600 dark:text-emerald-300" />
                  <span className="text-foreground/75">
                    {t('kb.upload_summary_success', {
                      success: uploadSummary.successful_files,
                      total: uploadSummary.total_files,
                    })}
                  </span>
                  <StatusPill tone="primary">
                    {t('kb.upload_summary_chunks', { count: uploadSummary.total_chunks })}
                  </StatusPill>
                  {uploadSummary.failed_files > 0 && (
                    <StatusPill tone="warning">
                      {t('kb.upload_summary_failed', { count: uploadSummary.failed_files })}
                    </StatusPill>
                  )}
                  {(uploadSummary.duplicate_files ?? 0) > 0 && (
                    <StatusPill tone="primary">
                      {t('kb.upload_summary_duplicate', { count: uploadSummary.duplicate_files ?? 0 })}
                    </StatusPill>
                  )}
                </div>
              )}

              {/* Scan result (compact strip) */}
              {scanResult && (
                <div className="mb-3 rounded-md border border-outline-variant/40 bg-surface-low px-3 py-2 text-[11px]">
                  <div className="flex flex-wrap items-center gap-2">
                    {scanResult.failed > 0 && scanResult.indexed === 0 ? (
                      <AlertCircle size={12} className="text-red-600 dark:text-red-300" />
                    ) : scanResult.failed > 0 ? (
                      <AlertTriangle size={12} className="text-amber-600 dark:text-amber-300" />
                    ) : (
                      <CheckCircle2 size={12} className="text-emerald-600 dark:text-emerald-300" />
                    )}
                    <span className="text-foreground/75">
                      {scanResult.failed > 0 && scanResult.indexed === 0
                        ? t('kb.scan_all_failed')
                        : scanResult.failed > 0
                          ? t('kb.scan_partial')
                          : t('kb.scan_done')}
                    </span>
                    <StatusPill tone="success">
                      {scanResult.indexed} {t('kb.scan_indexed_short')}
                    </StatusPill>
                    {scanResult.skipped > 0 && (
                      <StatusPill tone="neutral">
                        {scanResult.skipped} {t('kb.scan_skipped_short')}
                      </StatusPill>
                    )}
                    {scanResult.failed > 0 && (
                      <StatusPill tone="danger">
                        {scanResult.failed} {t('kb.scan_failed_short')}
                      </StatusPill>
                    )}
                    <button
                      type="button"
                      onClick={() => setScanResult(null)}
                      className="ml-auto rounded p-0.5 text-foreground/45 hover:bg-surface-high"
                      title={t('kb.scan_clear')}
                    >
                      <X size={12} />
                    </button>
                  </div>
                </div>
              )}

              {/* Search row above table */}
              <div className="mb-3 flex items-center gap-2 rounded-md border border-outline-variant/60 bg-surface-low px-2 py-1.5">
                <Search size={13} className="text-foreground/35" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索文献…"
                  aria-label="搜索文献"
                  className="flex-1 bg-transparent text-xs font-label text-foreground placeholder:text-foreground/35 focus:outline-none"
                />
              </div>

              {/* Paper table */}
              {filteredDocs.length === 0 ? (
                <EmptyState
                  title={docs.length === 0 ? t('kb.empty_title') : t('kb.no_search_results')}
                  description={docs.length === 0 ? t('kb.empty_desc') : t('kb.no_search_results_desc')}
                  icon={<Database size={28} />}
                />
              ) : (
                <div className="overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest">
                  <table className="w-full text-xs">
                    <thead className="bg-surface-low text-[10px] uppercase tracking-wider text-foreground/45">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">标题</th>
                        <th className="px-3 py-2 text-left font-medium">类型</th>
                        <th className="px-3 py-2 text-left font-medium">添加时间</th>
                        <th className="px-3 py-2 text-left font-medium">切片</th>
                        <th className="px-3 py-2 text-left font-medium">状态</th>
                        <th className="px-3 py-2 text-right font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-outline-variant/30 text-foreground/80">
                      {filteredDocs.map((doc) => {
                        const selected = doc.id === expandedDocId;
                        return (
                          <tr
                            key={doc.id}
                            onClick={() => setExpandedDocId((p) => (p === doc.id ? null : doc.id))}
                            className={cn(
                              'cursor-pointer transition-colors',
                              selected ? 'bg-primary/10' : 'hover:bg-surface-default/50',
                            )}
                          >
                            <td className="max-w-0 px-3 py-2">
                              <div className="flex items-center gap-2">
                                <FileText size={12} className="shrink-0 text-foreground/45" />
                                <span className="truncate font-medium">{doc.name}</span>
                              </div>
                            </td>
                            <td className="px-3 py-2 uppercase text-foreground/65">{doc.type}</td>
                            <td className="px-3 py-2 text-foreground/60">
                              <span className="inline-flex items-center gap-1">
                                <Clock size={10} /> {doc.addedAt || '—'}
                              </span>
                            </td>
                            <td className="px-3 py-2 tabular-nums text-foreground/70">
                              {doc.status === 'indexed' ? doc.chunks : '—'}
                            </td>
                            <td className="px-3 py-2">
                              {doc.status === 'indexed' ? (
                                <StatusPill tone="success">{t('kb.status_indexed')}</StatusPill>
                              ) : (
                                <StatusPill tone="warning">{t('kb.status_no_text')}</StatusPill>
                              )}
                            </td>
                            <td className="px-3 py-2 text-right">
                              <div className="inline-flex items-center gap-1.5">
                                {doc.type === 'pdf' && (
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      openPdfInWorkbench(doc.id);
                                    }}
                                    className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 bg-surface-low px-2 py-1 font-medium text-foreground/75 hover:border-primary/60 hover:text-primary"
                                    title="在工作台中阅读"
                                  >
                                    <BookOpen size={11} /> 阅读
                                  </button>
                                )}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void handleDeleteDocument(doc.id, doc.name);
                                  }}
                                  className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 bg-surface-low px-2 py-1 font-medium text-foreground/65 hover:border-red-500/60 hover:text-red-600"
                                  title="删除该文献"
                                  aria-label={`删除 ${doc.name}`}
                                >
                                  <Trash2 size={11} /> 删除
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>

        {/* Right — paper detail drawer */}
        {selectedDoc && (
          <aside className="hidden w-[340px] shrink-0 flex-col border-l border-outline-variant/60 bg-surface-lowest xl:flex">
            <div className="flex items-start justify-between gap-2 border-b border-outline-variant/40 px-4 py-3">
              <div className="min-w-0">
                <h2 className="truncate font-headline text-sm font-semibold text-foreground" title={selectedDoc.name}>
                  {selectedDoc.name}
                </h2>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-foreground/55">
                  <span className="uppercase">{selectedDoc.type}</span>
                  {selectedDoc.addedAt && <span>· {selectedDoc.addedAt}</span>}
                  {selectedDoc.status === 'indexed' ? (
                    <StatusPill tone="success">{t('kb.status_indexed')}</StatusPill>
                  ) : (
                    <StatusPill tone="warning">{t('kb.status_no_text')}</StatusPill>
                  )}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setExpandedDocId(null)}
                className="shrink-0 rounded p-1 text-foreground/45 hover:bg-surface-high hover:text-foreground"
                title="关闭"
              >
                <X size={14} />
              </button>
            </div>
            <div className="flex flex-1 flex-col overflow-auto p-4 text-xs">
              <SectionCard title="摘要" className="mb-3">
                <p className="text-foreground/65">
                  {selectedDoc.status === 'indexed'
                    ? `共有 ${selectedDoc.chunks} 个内容切片可供检索。可点击下方按钮在工作台中继续阅读。`
                    : '该文档暂未提取到可索引文本，可重新上传或检查源文件。'}
                </p>
              </SectionCard>
              <SectionCard title="操作" className="mb-3" bodyClassName="space-y-2">
                {selectedDoc.type === 'pdf' && (
                  <>
                    <button
                      type="button"
                      onClick={() => openPdfInWorkbench(selectedDoc.id)}
                      className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                    >
                      <BookOpen size={12} /> 在工作台中打开
                    </button>
                  </>
                )}
              </SectionCard>
              <SectionCard title="详情">
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[11px]">
                  <dt className="text-foreground/45">格式</dt>
                  <dd className="uppercase text-foreground/75">{selectedDoc.type}</dd>
                  <dt className="text-foreground/45">添加</dt>
                  <dd className="text-foreground/75">{selectedDoc.addedAt || '—'}</dd>
                  <dt className="text-foreground/45">切片数</dt>
                  <dd className="text-foreground/75">{selectedDoc.chunks}</dd>
                </dl>
              </SectionCard>
            </div>
          </aside>
        )}
      </main>
    </div>
  );
}
