import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  Copy,
  FileImage,
  Grid3X3,
  Image,
  Inbox,
  Layers3,
  List,
  Loader2,
  MapPin,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Table2,
  X,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { PageHeader } from '@/components/common/PageHeader';
import { EmptyState } from '@/components/common/EmptyState';
import { formatWritingRuntimeError } from '@/components/writing/writingRuntimeDisplay';
import { useWriting } from '@/contexts/WritingContext';
import { artifactContentRecord, findLatestArtifact, startBackgroundJob } from '@/services/backgroundJobRunner';
import { getWritingRuntimeClient } from '@/services/runtimeClient';
import { buildFigureAssetFileUrl, getWritingBackendService } from '@/services/writingBackend';
import type { JobStatusDetail, WritingArtifact, WritingJob } from '@/types/runtime';
import type {
  CreateFigureAssetRequest,
  FigureAssetResource,
  FigureTableCandidateResource,
  UpdateFigureAssetRequest,
} from '@/types/resources';

type FigureKind = 'figure' | 'table';
type FigureRecordState = 'asset' | 'candidate' | 'manual';

interface FigureRecord {
  id: string;
  kind: FigureKind;
  state: FigureRecordState;
  numbering: string;
  caption: string;
  displayCaption: string;
  captionStatus: 'caption' | 'needs_extraction';
  sourceTitle: string;
  materialId?: string | null;
  sourcePage?: number | null;
  chunkId?: string | null;
  chunkIndex?: number | null;
  bbox?: number[] | null;
  assetPath?: string | null;
  width?: number | null;
  height?: number | null;
  format?: string | null;
  source?: string | null;
  createdAt?: string;
  updatedAt?: string;
}

interface FigureStats {
  assets: number;
  candidates: number;
  located: number;
  withPreview: number;
}

interface ClipboardItemConstructor {
  new(items: Record<string, Blob>): ClipboardItem;
}

type FigureLoadStatus = 'idle' | 'loading' | 'completed' | 'failed' | 'cancelled';

interface FigureLoadCacheEntry {
  schemaVersion: number;
  status: FigureLoadStatus;
  assets: FigureAssetResource[];
  candidates: FigureTableCandidateResource[];
  jobId?: string;
  progress?: number;
  message?: string;
  error?: string;
  updatedAt: number;
}

const FIGURE_LOAD_POLL_INTERVAL_MS = 1200;
const FIGURE_LOAD_SCHEMA_VERSION = 3;
const FIGURE_LOAD_RUNNING_STATUSES = new Set(['created', 'queued', 'started', 'in_progress', 'paused']);
const FIGURE_LOAD_TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);
const figureLoadCacheByProject = new Map<string, FigureLoadCacheEntry>();
const figureLoadStartByProject = new Map<string, Promise<WritingJob>>();

export function FiguresTables() {
  const { t } = useI18n();
  const { activeProjectId } = useWriting();
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [filter, setFilter] = useState<'all' | FigureKind | 'asset' | 'candidate'>('all');
  const [search, setSearch] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [manualItems, setManualItems] = useState<FigureRecord[]>([]);
  const [assets, setAssets] = useState<FigureRecord[]>([]);
  const [candidates, setCandidates] = useState<FigureRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [previewItem, setPreviewItem] = useState<FigureRecord | null>(null);
  const [loadJobId, setLoadJobId] = useState<string | null>(null);
  const [loadProgress, setLoadProgress] = useState(0);
  const [loadMessage, setLoadMessage] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const loadTokenRef = useRef(0);

  const records = useMemo(() => [...assets, ...candidates, ...manualItems], [assets, candidates, manualItems]);
  const stats = useMemo<FigureStats>(() => ({
    assets: records.filter((item) => item.state === 'asset' || item.state === 'manual').length,
    candidates: records.filter((item) => item.state === 'candidate').length,
    located: records.filter((item) => hasLocator(item)).length,
    withPreview: records.filter((item) => Boolean(toDisplayableAssetUrl(activeProjectId, item.assetPath))).length,
  }), [activeProjectId, records]);

  const filteredRecords = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    return records.filter((item) => {
      if (filter === 'figure' && item.kind !== 'figure') return false;
      if (filter === 'table' && item.kind !== 'table') return false;
      if (filter === 'asset' && item.state !== 'asset' && item.state !== 'manual') return false;
      if (filter === 'candidate' && item.state !== 'candidate') return false;

      if (!normalizedSearch) return true;
      const searchable = [
        item.numbering,
        item.caption,
        item.sourceTitle,
        item.materialId,
      ].filter(Boolean).join(' ').toLowerCase();

      return searchable.includes(normalizedSearch);
    });
  }, [filter, records, search]);

  const applyFigureLoadCache = useCallback((projectId: string, entry: FigureLoadCacheEntry, token: number): boolean => {
    if (loadTokenRef.current !== token || projectId !== String(activeProjectId ?? '').trim()) {
      return false;
    }
    setAssets(entry.assets.map(toAssetRecord));
    setCandidates(entry.candidates.map(toCandidateRecord));
    setLoadJobId(entry.jobId ?? null);
    setLoadProgress(entry.progress ?? figureLoadFallbackProgress(entry.status));
    setLoadMessage(entry.message ?? null);
    setLoading(entry.status === 'loading');
    setError(entry.error ?? null);
    return true;
  }, [activeProjectId]);

  const loadProjectItems = useCallback(async (forceRefresh = false) => {
    const projectId = String(activeProjectId ?? '').trim();
    const token = loadTokenRef.current + 1;
    loadTokenRef.current = token;

    if (!projectId) {
      setAssets([]);
      setCandidates([]);
      setLoadJobId(null);
      setLoadProgress(0);
      setLoadMessage(null);
      setLoading(false);
      return;
    }

    const candidateCache = figureLoadCacheByProject.get(projectId);
    const cached = !forceRefresh && candidateCache?.schemaVersion === FIGURE_LOAD_SCHEMA_VERSION
      ? candidateCache
      : undefined;
    if (candidateCache && candidateCache.schemaVersion !== FIGURE_LOAD_SCHEMA_VERSION) {
      figureLoadCacheByProject.delete(projectId);
    }
    if (cached) {
      applyFigureLoadCache(projectId, cached, token);
      if (cached.status === 'completed') {
        return;
      }
    } else {
      setLoading(true);
      setLoadProgress(0);
      setLoadMessage('正在提交图表加载任务');
      setError(null);
    }

    try {
      let jobId = cached?.status === 'failed' || cached?.status === 'cancelled' ? undefined : cached?.jobId;
      if (forceRefresh || !jobId) {
        const resolvedJob = await resolveFigureLoadJob(projectId, forceRefresh);
        jobId = resolvedJob.job_id;
      }

      const runningEntry = upsertFigureLoadCache(projectId, {
        status: 'loading',
        jobId,
        message: '已进入后台任务，可在任务中心停止',
        progress: cached?.progress ?? 5,
      });
      applyFigureLoadCache(projectId, runningEntry, token);

      const finalEntry = await pollFigureLoadJob(projectId, jobId, (entry) => {
        applyFigureLoadCache(projectId, entry, token);
      });
      applyFigureLoadCache(projectId, finalEntry, token);
    } catch (err) {
      const message = formatWritingRuntimeError(err, '图表加载失败，请稍后重试。');
      const failedEntry = upsertFigureLoadCache(projectId, {
        status: 'failed',
        error: message,
        message,
        progress: 100,
      });
      applyFigureLoadCache(projectId, failedEntry, token);
    }
  }, [activeProjectId, applyFigureLoadCache]);

  useEffect(() => {
    void loadProjectItems();
  }, [loadProjectItems]);

  useEffect(() => () => {
    loadTokenRef.current += 1;
  }, []);

  const handleAddFigure = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files) return;
    const timestamp = Date.now();
    const nextItems = Array.from(files).map((file, index): FigureRecord => {
      const kind: FigureKind = file.name.toLowerCase().includes('table') ? 'table' : 'figure';
      return {
        id: `manual-${timestamp}-${index}`,
        kind,
        state: 'manual',
        source: 'manual',
        numbering: kind === 'table'
          ? `表 ${manualItems.filter((item) => item.kind === 'table').length + index + 1}`
          : `图 ${manualItems.filter((item) => item.kind === 'figure').length + index + 1}`,
        caption: file.name,
        displayCaption: file.name,
        captionStatus: 'caption',
        sourceTitle: '手动添加',
        assetPath: URL.createObjectURL(file),
        width: null,
        height: null,
        format: file.type.split('/')[1] || null,
        createdAt: new Date().toISOString(),
      };
    });

    setManualItems((prev) => [...nextItems, ...prev]);
    event.target.value = '';
  };

  const handleRegisterCandidate = async (item: FigureRecord) => {
    if (!activeProjectId || item.state !== 'candidate') return;
    setError(null);
    if (!item.assetPath?.trim()) {
      setError('只有切块已产出的像素级图表可以保存到图表库。');
      return;
    }
    try {
      const request: CreateFigureAssetRequest = {
        project_id: activeProjectId,
        kind: item.kind,
        caption: item.caption,
        numbering: item.numbering,
        material_id: item.materialId ?? undefined,
        source_page: item.sourcePage ?? undefined,
        bbox: item.bbox ?? undefined,
        asset_path: item.assetPath,
        width: item.width ?? undefined,
        height: item.height ?? undefined,
        format: item.format ?? undefined,
      };
      const created = await getWritingBackendService().createFigureAsset(request);
      setAssets((prev) => [toAssetRecord(created), ...prev]);
      setCandidates((prev) => prev.filter((candidate) => candidate.id !== item.id));
    } catch (err) {
      setError(formatWritingRuntimeError(err, '保存到图表库失败，请稍后重试。'));
    }
  };

  const handleGenerateFigures = async () => {
    if (!activeProjectId || generating) return;
    setGenerating(true);
    setError(null);
    try {
      const response = await getWritingBackendService().generateFigureAssets({
        project_id: activeProjectId,
        max_items: 6,
      });
      const generatedRecords = response.generated_assets.map(toAssetRecord);
      if (generatedRecords.length > 0) {
        const generatedAssetPaths = new Set(generatedRecords.map((item) => item.assetPath).filter(Boolean));
        setAssets((prev) => [...generatedRecords, ...prev]);
        setCandidates((prev) => prev.filter((candidate) => !generatedAssetPaths.has(candidate.assetPath ?? '')));
      } else {
        setError(response.message || '没有可生成的本地图表资产；请先完成文献切块或图表加载。');
      }
    } catch (err) {
      setError(formatWritingRuntimeError(err, '生成本地图表资产失败，请稍后重试。'));
    } finally {
      setGenerating(false);
    }
  };

  const handleRefreshAsset = async (item: FigureRecord) => {
    if (!activeProjectId || item.state !== 'asset') return;
    setError(null);
    try {
      const request: UpdateFigureAssetRequest = {
        caption: item.caption,
        numbering: item.numbering,
      };
      const updated = await getWritingBackendService().updateFigureAsset(item.id, request);
      setAssets((prev) => prev.map((asset) => (asset.id === item.id ? toAssetRecord(updated) : asset)));
    } catch (err) {
      setError(formatWritingRuntimeError(err, '图表信息更新失败，请稍后重试。'));
    }
  };

  const handleDeleteAsset = async (item: FigureRecord) => {
    if (!activeProjectId || item.state !== 'asset') return;
    setError(null);
    try {
      await getWritingBackendService().deleteFigureAsset(item.id);
      setAssets((prev) => prev.filter((asset) => asset.id !== item.id));
    } catch (err) {
      setError(formatWritingRuntimeError(err, '图表删除失败，请稍后重试。'));
    }
  };

  const handleCopyCitation = async (item: FigureRecord) => {
    try {
      await navigator.clipboard.writeText(`${item.numbering} ${item.displayCaption}`.trim());
      setCopiedId(item.id);
      window.setTimeout(() => setCopiedId(null), 1800);
    } catch {
      setCopiedId(null);
    }
  };

  const handleCopyForManuscript = async (item: FigureRecord) => {
    const imageUrl = toDisplayableAssetUrl(activeProjectId, item.assetPath);
    const caption = `${item.numbering} ${item.displayCaption || item.caption}`.trim();
    const markdown = imageUrl ? `![${escapeMarkdownAlt(caption)}](${imageUrl})\n\n${caption}` : caption;
    try {
      await copyFigureToClipboard(markdown, imageUrl);
      setCopiedId(`insert:${item.id}`);
      window.setTimeout(() => setCopiedId(null), 1800);
    } catch {
      try {
        await navigator.clipboard.writeText(markdown);
        setCopiedId(`insert:${item.id}`);
        window.setTimeout(() => setCopiedId(null), 1800);
      } catch {
        setCopiedId(null);
      }
    }
  };

  const figures = records.filter((item) => item.kind === 'figure');
  const tables = records.filter((item) => item.kind === 'table');

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<Image size={18} />}
          title={t('writing.figures.title')}
          subtitle={t('writing.figures.subtitle', { figures: figures.length, tables: tables.length })}
          className="mb-0"
          actions={
            <>
              <button
                type="button"
                onClick={() => void loadProjectItems(true)}
                disabled={loading}
                className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-60"
              >
                {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                刷新
              </button>
              <button
                type="button"
                onClick={() => void handleGenerateFigures()}
                disabled={!activeProjectId || generating || loading}
                className="inline-flex items-center gap-1.5 rounded-md border border-primary/25 bg-primary/10 px-3 py-1.5 font-label text-xs font-medium text-primary transition-colors hover:bg-primary/15 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {generating ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                生成
              </button>
              <div className="flex gap-0.5 rounded-md border border-outline-variant/60 bg-surface-low p-0.5">
                <button
                  type="button"
                  onClick={() => setViewMode('grid')}
                  aria-label="网格视图"
                  title="网格视图"
                  className={cn('rounded-sm p-1.5 transition-all', viewMode === 'grid' ? 'bg-primary text-primary-foreground shadow-sm' : 'text-foreground/45')}
                >
                  <Grid3X3 size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('list')}
                  aria-label="列表视图"
                  title="列表视图"
                  className={cn('rounded-sm p-1.5 transition-all', viewMode === 'list' ? 'bg-primary text-primary-foreground shadow-sm' : 'text-foreground/45')}
                >
                  <List size={13} />
                </button>
              </div>
              <button
                type="button"
                onClick={handleAddFigure}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 font-label text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                <Plus size={13} />
                添加图片
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                title="添加图片"
                aria-label="添加图片"
                onChange={handleFileSelected}
              />
            </>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-auto px-6 py-5">
        {error ? (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
            {error}
          </div>
        ) : null}

        <section className="mb-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="已保存图表" value={stats.assets} icon={<FileImage size={14} />} />
            <Metric label="待确认候选" value={stats.candidates} icon={<Layers3 size={14} />} />
            <Metric label="可定位" value={stats.located} icon={<MapPin size={14} />} />
            <Metric label="可显示原图" value={stats.withPreview} icon={<Image size={14} />} />
          </div>
          <div className="rounded-md border border-outline-variant/60 bg-surface-lowest p-4">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Table2 size={15} />
              </div>
              <div className="min-w-0">
                <h2 className="font-headline text-sm font-semibold text-foreground">已保存图表与待确认图表</h2>
                <p className="mt-1 text-xs leading-5 text-foreground/55">
                  已保存 / 待确认。
                </p>
              </div>
            </div>
          </div>
        </section>

        {loading && loadJobId ? (
          <div className="mb-4 rounded-md border border-primary/20 bg-primary/5 px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2 font-label text-[11px] text-foreground/60">
              <span>{loadMessage ?? '图表加载已进入后台，可在任务中心查看或停止。'}</span>
              <span>{Math.max(0, Math.min(100, loadProgress))}%</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-high">
              <div
                className="h-full rounded-full bg-primary transition-[width]"
                style={{ width: `${Math.max(3, Math.min(100, loadProgress))}%` }}
              />
            </div>
          </div>
        ) : null}

        <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-outline-variant/50 bg-surface-lowest px-3 py-2 focus-within:border-primary/40">
            <Search size={15} className="shrink-0 text-foreground/30" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索编号、题注或文献名称"
              className="min-w-0 flex-1 bg-transparent text-sm font-label text-foreground placeholder:text-foreground/30 focus:outline-none"
            />
          </div>
          <div className="flex flex-wrap gap-1 rounded-md border border-outline-variant/60 bg-surface-low p-1">
            {[
              ['all', '全部'],
              ['asset', '已保存'],
              ['candidate', '待确认'],
              ['figure', '图'],
              ['table', '表'],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value as typeof filter)}
                className={cn(
                  'rounded px-2.5 py-1.5 font-label text-[11px] font-medium transition-colors',
                  filter === value ? 'bg-primary text-primary-foreground shadow-sm' : 'text-foreground/50 hover:bg-surface-high hover:text-foreground',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {loading && records.length === 0 ? (
          <div className="flex items-center justify-center gap-2 rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-10 text-sm text-foreground/50">
            <Loader2 size={16} className="animate-spin" />
            正在后台读取切块像素图表，可在任务中心停止
          </div>
        ) : filteredRecords.length === 0 ? (
          <EmptyState
            title={activeProjectId ? '没有匹配的图表条目' : '未激活项目'}
            description={activeProjectId ? '换个关键词。' : '先选择项目。'}
            icon={<Inbox size={40} />}
            action={
              <button
                type="button"
                onClick={handleAddFigure}
                className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                <Plus size={14} />
                添加图片
              </button>
            }
          />
        ) : viewMode === 'grid' ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {filteredRecords.map((item, index) => (
              <motion.div
                key={item.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className="group overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest shadow-sm transition-colors hover:border-primary/30"
              >
                <FigurePreview item={item} projectId={activeProjectId} onOpen={() => setPreviewItem(item)} />
                <FigureRecordBody
                  item={item}
                  copied={copiedId === item.id}
                  insertCopied={copiedId === `insert:${item.id}`}
                  onCopy={() => void handleCopyCitation(item)}
                  onCopyForManuscript={() => void handleCopyForManuscript(item)}
                  onRegister={() => void handleRegisterCandidate(item)}
                  onRefresh={() => void handleRefreshAsset(item)}
                  onDelete={() => void handleDeleteAsset(item)}
                />
              </motion.div>
            ))}
          </div>
        ) : (
          <div className="divide-y divide-outline-variant/30 overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest shadow-sm">
            {filteredRecords.map((item, index) => (
              <motion.div
                key={item.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: index * 0.02 }}
                className="grid gap-3 p-4 transition-colors hover:bg-surface-high/50 lg:grid-cols-[88px_minmax(0,1fr)_auto]"
              >
                <FigurePreview item={item} projectId={activeProjectId} compact onOpen={() => setPreviewItem(item)} />
                <FigureRecordSummary item={item} />
                <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                  <IconButton label={copiedId === item.id ? '已复制' : '复制题注'} onClick={() => void handleCopyCitation(item)}>
                    {copiedId === item.id ? <CheckCircle2 size={13} /> : <Copy size={13} />}
                  </IconButton>
                  <button
                    type="button"
                    onClick={() => void handleCopyForManuscript(item)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-primary/25 bg-primary/10 px-2.5 py-1.5 font-label text-[11px] font-medium text-primary transition-colors hover:bg-primary/15"
                  >
                    {copiedId === `insert:${item.id}` ? <CheckCircle2 size={12} /> : <Copy size={12} />}
                  {copiedId === `insert:${item.id}` ? '已复制' : '复制图片到手稿'}
                  </button>
                  <button
                    type="button"
                    disabled={item.state !== 'candidate'}
                    onClick={() => void handleRegisterCandidate(item)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 font-label text-[11px] font-medium text-foreground/55 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Plus size={12} />
                    保存到图表库
                  </button>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
      <FigurePreviewDialog
        item={previewItem}
        projectId={activeProjectId ?? ''}
        onClose={() => setPreviewItem(null)}
      />
    </div>
  );
}

function upsertFigureLoadCache(
  projectId: string,
  updates: Partial<Omit<FigureLoadCacheEntry, 'updatedAt'>>,
): FigureLoadCacheEntry {
  const previous = figureLoadCacheByProject.get(projectId);
  const next: FigureLoadCacheEntry = {
    schemaVersion: FIGURE_LOAD_SCHEMA_VERSION,
    status: updates.status ?? previous?.status ?? 'idle',
    assets: updates.assets ?? previous?.assets ?? [],
    candidates: updates.candidates ?? previous?.candidates ?? [],
    jobId: updates.jobId ?? previous?.jobId,
    progress: updates.progress ?? previous?.progress,
    message: updates.message ?? previous?.message,
    error: updates.error,
    updatedAt: Date.now(),
  };
  figureLoadCacheByProject.set(projectId, next);
  return next;
}

function figureLoadFallbackProgress(status: FigureLoadStatus): number {
  if (status === 'completed' || status === 'failed' || status === 'cancelled') return 100;
  if (status === 'loading') return 60;
  return 0;
}

function sleepFigureLoad(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function startFigureLoadJob(projectId: string): Promise<WritingJob> {
  const normalizedProjectId = projectId.trim();
  if (!normalizedProjectId) {
    throw new Error('project_id is required');
  }
  const { job } = await startBackgroundJob({
    sessionTitle: '图表加载',
    sessionMetadata: {
      source: 'manuscript_studio',
      route: '/writing/figures',
      target_route: '/writing/figures',
      user_task: true,
      figure_loader_version: FIGURE_LOAD_SCHEMA_VERSION,
      project_id: normalizedProjectId,
    },
    request: {
      kind: 'figure_load',
      input_text: '加载切块像素级图表',
      tags: ['writing', 'figures'],
      metadata: {
        title: '图表加载',
        display_name: '图表加载',
        project_id: normalizedProjectId,
        route: '/writing/figures',
        target_route: '/writing/figures',
        user_task: true,
        cancellable: true,
        figure_loader_version: FIGURE_LOAD_SCHEMA_VERSION,
        limit: 96,
      },
    },
  });
  upsertFigureLoadCache(normalizedProjectId, {
    status: 'loading',
    jobId: job.job_id,
    progress: 5,
    message: '已进入后台任务，可在任务中心停止',
  });
  return job;
}

async function resolveFigureLoadJob(projectId: string, forceRefresh: boolean): Promise<WritingJob> {
  const normalizedProjectId = projectId.trim();
  if (!normalizedProjectId) {
    throw new Error('project_id is required');
  }
  const inflight = forceRefresh ? undefined : figureLoadStartByProject.get(normalizedProjectId);
  if (inflight) {
    return inflight;
  }

  const promise = (async (): Promise<WritingJob> => {
    const reusableJob = forceRefresh ? null : await findReusableFigureLoadJob(normalizedProjectId);
    return reusableJob ?? startFigureLoadJob(normalizedProjectId);
  })();

  if (!forceRefresh) {
    figureLoadStartByProject.set(normalizedProjectId, promise);
    const cleanup = () => {
      if (figureLoadStartByProject.get(normalizedProjectId) === promise) {
        figureLoadStartByProject.delete(normalizedProjectId);
      }
    };
    promise.then(cleanup, cleanup);
  }

  return promise;
}

async function findReusableFigureLoadJob(projectId: string): Promise<WritingJob | null> {
  const client = getWritingRuntimeClient();
  const jobs = await client.listJobs({ limit: 100 });
  const matches = jobs.filter((job) => isFigureLoadJobForProject(job, projectId));
  return matches.find((job) => FIGURE_LOAD_RUNNING_STATUSES.has(String(job.status))) ??
    matches.find((job) => job.status === 'completed') ??
    null;
}

function isFigureLoadJobForProject(job: WritingJob, projectId: string): boolean {
  const metadata = isRecord(job.metadata) ? job.metadata : {};
  return String(job.kind) === 'figure_load'
    && String(metadata.project_id ?? '').trim() === projectId
    && metadata.figure_loader_version === FIGURE_LOAD_SCHEMA_VERSION;
}

async function pollFigureLoadJob(
  projectId: string,
  jobId: string,
  onUpdate: (entry: FigureLoadCacheEntry) => void,
): Promise<FigureLoadCacheEntry> {
  const client = getWritingRuntimeClient();

  for (;;) {
    const detail = await client.getJobStatus(jobId);
    const metadata = isRecord(detail.metadata) ? detail.metadata : {};
    const progress = readFigureLoadProgress(detail, metadata);
    const message = readFigureLoadMessage(metadata) ?? '图表加载正在后台执行';
    const status = String(detail.status);

    if (status === 'completed') {
      const artifacts = await client.getJobArtifacts(jobId);
      const payload = readFigureLoadArtifactPayload(artifacts);
      if (payload.schemaVersion !== FIGURE_LOAD_SCHEMA_VERSION) {
        figureLoadCacheByProject.delete(projectId);
        const replacementJob = await startFigureLoadJob(projectId);
        return pollFigureLoadJob(projectId, replacementJob.job_id, onUpdate);
      }
      const entry = upsertFigureLoadCache(projectId, {
        status: 'completed',
        jobId,
        progress: 100,
        message: '图表加载完成',
        assets: payload.assets,
        candidates: payload.candidates,
      });
      onUpdate(entry);
      return entry;
    }

    if (status === 'failed') {
      const error = detail.error?.trim() || '图表加载失败，请稍后重试。';
      const entry = upsertFigureLoadCache(projectId, {
        status: 'failed',
        jobId,
        progress: 100,
        message: error,
        error,
      });
      onUpdate(entry);
      return entry;
    }

    if (status === 'cancelled') {
      const error = '图表加载已在任务中心取消。';
      const entry = upsertFigureLoadCache(projectId, {
        status: 'cancelled',
        jobId,
        progress: 100,
        message: error,
        error,
      });
      onUpdate(entry);
      return entry;
    }

    if (!FIGURE_LOAD_RUNNING_STATUSES.has(status) && !FIGURE_LOAD_TERMINAL_STATUSES.has(status)) {
      throw new Error(`Unsupported figure load status: ${status}`);
    }

    const entry = upsertFigureLoadCache(projectId, {
      status: 'loading',
      jobId,
      progress,
      message,
    });
    onUpdate(entry);
    await sleepFigureLoad(FIGURE_LOAD_POLL_INTERVAL_MS);
  }
}

function readFigureLoadProgress(detail: JobStatusDetail, metadata: Record<string, unknown>): number {
  const raw = metadata.progress;
  const numeric = typeof raw === 'number' ? raw : Number(raw);
  if (Number.isFinite(numeric)) {
    return Math.max(0, Math.min(100, Math.round(numeric)));
  }
  return detail.status === 'paused' ? 50 : 60;
}

function readFigureLoadMessage(metadata: Record<string, unknown>): string | null {
  const raw = metadata.progress_message;
  return typeof raw === 'string' && raw.trim() ? raw.trim() : null;
}

function readFigureLoadArtifactPayload(artifacts: WritingArtifact[]): {
  schemaVersion: number;
  assets: FigureAssetResource[];
  candidates: FigureTableCandidateResource[];
} {
  const latest = findLatestArtifact(artifacts, 'transformed_text') ?? findLatestArtifact(artifacts);
  const content = artifactContentRecord(latest);
  return {
    schemaVersion: Number(content.figure_loader_version ?? 0),
    assets: readFigureAssetResources(content.assets),
    candidates: readPixelCandidateResources(content.candidates),
  };
}

function readFigureAssetResources(value: unknown): FigureAssetResource[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isFigureAssetResource);
}

function readPixelCandidateResources(value: unknown): FigureTableCandidateResource[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isPixelCandidateResource);
}

function isFigureAssetResource(value: unknown): value is FigureAssetResource {
  if (!isRecord(value)) return false;
  return hasStringField(value, 'asset_id')
    && hasStringField(value, 'project_id')
    && hasStringField(value, 'kind')
    && hasStringField(value, 'caption')
    && hasStringField(value, 'numbering')
    && hasStringField(value, 'asset_path')
    && hasStringField(value, 'created_at')
    && hasStringField(value, 'updated_at');
}

function isPixelCandidateResource(value: unknown): value is FigureTableCandidateResource {
  if (!isRecord(value)) return false;
  return hasStringField(value, 'id')
    && hasStringField(value, 'kind')
    && hasStringField(value, 'label')
    && hasStringField(value, 'caption')
    && hasStringField(value, 'material_id')
    && hasStringField(value, 'material_title')
    && hasStringField(value, 'chunk_id')
    && hasStringField(value, 'asset_path');
}

function hasStringField(value: Record<string, unknown>, key: string): boolean {
  const field = value[key];
  return typeof field === 'string' && field.trim().length > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function Metric({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <div className="rounded-md border border-outline-variant/60 bg-surface-lowest p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-label text-[11px] text-foreground/45">{label}</span>
        <span className="text-primary/60">{icon}</span>
      </div>
      <div className="mt-2 font-headline text-xl font-semibold text-foreground">{value}</div>
    </div>
  );
}

function FigureRecordBody({
  item,
  copied,
  insertCopied,
  onCopy,
  onCopyForManuscript,
  onRegister,
  onRefresh,
  onDelete,
}: {
  item: FigureRecord;
  copied: boolean;
  insertCopied: boolean;
  onCopy: () => void;
  onCopyForManuscript: () => void;
  onRegister: () => void;
  onRefresh: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="space-y-3 p-3">
      <FigureRecordSummary item={item} />
      <div className="flex flex-wrap items-center gap-2">
        <IconButton label={copied ? '已复制' : '复制题注'} onClick={onCopy}>
          {copied ? <CheckCircle2 size={13} /> : <Copy size={13} />}
        </IconButton>
        <button
          type="button"
          onClick={onCopyForManuscript}
          className="inline-flex items-center gap-1.5 rounded-md border border-primary/25 bg-primary/10 px-2.5 py-1.5 font-label text-[11px] font-medium text-primary transition-colors hover:bg-primary/15"
        >
          {insertCopied ? <CheckCircle2 size={12} /> : <Copy size={12} />}
          {insertCopied ? '已复制' : '复制图片到手稿'}
        </button>
        <button
          type="button"
          disabled={item.state !== 'candidate'}
          onClick={onRegister}
          className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 font-label text-[11px] font-medium text-foreground/55 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Plus size={12} />
          保存到图表库
        </button>
        {item.state === 'asset' ? (
          <>
            <button
              type="button"
              onClick={onRefresh}
              className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 font-label text-[11px] font-medium text-foreground/55 transition-colors hover:border-primary/35 hover:text-primary"
            >
              <RefreshCw size={12} />
              刷新
            </button>
            <button
              type="button"
              onClick={onDelete}
              className="inline-flex items-center gap-1.5 rounded-md border border-red-200/70 bg-red-50/60 px-2.5 py-1.5 font-label text-[11px] font-medium text-red-700 transition-colors hover:bg-red-100"
            >
              <X size={12} />
              删除
            </button>
          </>
        ) : null}
        {hasLocator(item) ? (
          <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-1 font-label text-[10px] font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
            <MapPin size={11} />
            可定位
          </span>
        ) : null}
      </div>
    </div>
  );
}

function FigureRecordSummary({ item }: { item: FigureRecord }) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex min-w-0 flex-wrap items-center gap-1.5">
        <span className={cn(
          'rounded px-1.5 py-0.5 font-label text-[10px] font-medium',
          item.kind === 'figure' ? 'bg-primary/10 text-primary' : 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
        )}>
          {item.numbering}
        </span>
        <span className={cn(
          'rounded px-1.5 py-0.5 font-label text-[10px] font-medium',
          item.state === 'asset' || item.state === 'manual'
            ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
            : 'bg-surface-high text-foreground/45',
        )}>
          {item.state === 'candidate' ? '待确认' : '已保存'}
        </span>
        {item.sourcePage ? (
          <span className="rounded bg-surface-high px-1.5 py-0.5 font-label text-[10px] text-foreground/45">
            第 {item.sourcePage} 页
          </span>
        ) : null}
      </div>
      <h3 className="line-clamp-2 font-headline text-sm font-semibold leading-snug text-foreground">
        {item.captionStatus === 'caption' ? item.displayCaption : '未识别到题注'}
      </h3>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-label text-[11px] text-foreground/42">
        <span className="min-w-0 truncate">文献：{item.sourceTitle}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {item.captionStatus === 'caption' ? <Capability label="已识别题注" tone="ok" /> : <Capability label="正文提及" tone="muted" />}
        {hasLocator(item) ? <Capability label="可定位" tone="ok" /> : <Capability label="待定位" tone="muted" />}
        {item.assetPath ? <Capability label={item.state === 'candidate' ? '切块像素图' : '可显示原图'} tone="ok" /> : <Capability label="未提取到像素图" tone="muted" />}
        {item.format ? <Capability label={item.format} tone="muted" /> : null}
      </div>
    </div>
  );
}

function Capability({ label, tone }: { label: string; tone: 'ok' | 'muted' }) {
  return (
    <span className={cn(
      'rounded border px-1.5 py-0.5 font-label text-[9px] font-medium',
      tone === 'ok'
        ? 'border-emerald-200/70 bg-emerald-50 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/10 dark:text-emerald-300'
        : 'border-outline-variant bg-surface-low text-foreground/38',
    )}>
      {label}
    </span>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-low text-foreground/50 transition-colors hover:border-primary/35 hover:text-primary"
    >
      {children}
    </button>
  );
}

function toAssetRecord(asset: FigureAssetResource): FigureRecord {
  return {
    id: asset.asset_id,
    kind: normalizeKind(asset.kind),
    state: 'asset',
    numbering: asset.numbering,
    caption: asset.caption,
    displayCaption: asset.caption,
    captionStatus: 'caption',
    sourceTitle: asset.material_id || '项目图表库',
    materialId: asset.material_id ?? null,
    sourcePage: asset.source_page ?? null,
    bbox: asset.bbox ?? null,
    assetPath: asset.asset_path,
    width: asset.width ?? null,
    height: asset.height ?? null,
    format: asset.format ?? null,
    source: 'asset',
    createdAt: asset.created_at,
    updatedAt: asset.updated_at,
  };
}

function toCandidateRecord(candidate: FigureTableCandidateResource): FigureRecord {
  const caption = candidate.caption || '';
  const displayCaption = toDisplayCaption(caption, candidate.label);
  return {
    id: candidate.id,
    kind: normalizeKind(candidate.kind),
    state: 'candidate',
    numbering: candidate.label,
    caption: caption || '来自项目切块的图表候选',
    displayCaption,
    captionStatus: displayCaption ? 'caption' : 'needs_extraction',
    sourceTitle: candidate.material_title || candidate.material_id,
    materialId: candidate.material_id,
    sourcePage: candidate.page ?? null,
    chunkId: candidate.chunk_id,
    chunkIndex: candidate.chunk_index ?? null,
    bbox: candidate.bbox ?? null,
    assetPath: candidate.asset_path ?? null,
    source: candidate.source ?? 'chunk_text',
  };
}

function normalizeKind(value: string): FigureKind {
  return value === 'table' ? 'table' : 'figure';
}

function toDisplayCaption(value: string, label: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  const labelPattern = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s*');
  const patterns = [
    new RegExp(`(${labelPattern}\\s*[.:：]\\s*[^。.!?]{8,180})`, 'i'),
    /((?:Figure|Fig\.?|Table)\s*\d+[a-z]?\s*[.:：]\s*[^.!?。]{8,180})/i,
    /((?:图|表)\s*\d+[a-zA-Z]?\s*[.:：]\s*[^。.!?]{8,180})/,
  ];

  for (const pattern of patterns) {
    const match = normalized.match(pattern);
    if (match?.[1]) {
      return truncateCaption(match[1]);
    }
  }

  return truncateCaption(normalized);
}

function truncateCaption(value: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= 180) return normalized;
  return `${normalized.slice(0, 176).trimEnd()}...`;
}

function hasLocator(item: FigureRecord): boolean {
  return Boolean(item.materialId && (item.sourcePage || item.chunkId || item.bbox?.length));
}

function escapeMarkdownAlt(value: string): string {
  return value.replace(/[[\]\\]/g, ' ').replace(/\s+/g, ' ').trim();
}

async function copyFigureToClipboard(markdown: string, imageUrl: string | null): Promise<void> {
  if (!navigator.clipboard) {
    throw new Error('clipboard is unavailable');
  }

  const ClipboardItemCtor = (globalThis as unknown as { ClipboardItem?: ClipboardItemConstructor }).ClipboardItem;
  if (!imageUrl || !navigator.clipboard.write || !ClipboardItemCtor) {
    await navigator.clipboard.writeText(markdown);
    return;
  }

  const response = await fetch(imageUrl);
  if (!response.ok) {
    await navigator.clipboard.writeText(markdown);
    return;
  }
  const imageBlob = await response.blob();
  const textBlob = new Blob([markdown], { type: 'text/plain' });
  await navigator.clipboard.write([
    new ClipboardItemCtor({
      [imageBlob.type || 'image/png']: imageBlob,
      'text/plain': textBlob,
    }),
  ]);
}

function FigurePreview({
  item,
  projectId = '',
  compact = false,
  onOpen,
}: {
  item: FigureRecord;
  projectId?: string;
  compact?: boolean;
  onOpen?: () => void;
}) {
  const src = toDisplayableAssetUrl(projectId, item.assetPath);
  const alt = `${item.numbering}：${item.caption}`;
  const sizeClass = compact ? 'h-20 w-28 shrink-0 rounded' : 'h-52 w-full';

  if (src) {
    return (
      <button
        type="button"
        onClick={() => onOpen?.()}
        className={cn('relative overflow-hidden bg-surface-high text-left outline-none transition-colors hover:bg-surface-container focus-visible:ring-2 focus-visible:ring-ring', sizeClass)}
        aria-label={`查看${item.numbering}原图`}
        title="查看原图"
      >
        <img src={src} alt={alt} className="h-full w-full object-contain" loading="lazy" />
        {!compact ? (
          <span className="absolute left-2 top-2 rounded bg-surface-lowest/90 px-2 py-1 font-label text-[10px] text-foreground/60 shadow-sm">
            {item.state === 'candidate' ? '切块像素图' : '图片文件'}
          </span>
        ) : null}
      </button>
    );
  }

  return (
    <div className={cn('flex flex-col items-center justify-center gap-1 bg-surface-high text-foreground/30', sizeClass)}>
      {item.kind === 'table' ? <Table2 size={compact ? 18 : 28} /> : <FileImage size={compact ? 18 : 28} />}
      {!compact && item.state === 'candidate' ? (
        <span className="px-3 text-center font-label text-[11px] leading-4 text-foreground/45">
          没有可显示的切块像素图；重新运行文献切块或图表抽取后再刷新
        </span>
      ) : null}
    </div>
  );
}

function FigurePreviewDialog({
  item,
  projectId,
  onClose,
}: {
  item: FigureRecord | null;
  projectId: string;
  onClose: () => void;
}) {
  if (!item) return null;
  const src = toDisplayableAssetUrl(projectId, item.assetPath);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 px-4 py-6"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-outline-variant/60 bg-surface-lowest shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-outline-variant/60 px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate font-headline text-sm font-semibold text-foreground">{item.numbering} {item.displayCaption || item.caption}</h2>
            <p className="mt-1 text-xs text-foreground/45">
              {item.state === 'candidate' ? '来源：文献切块像素图' : item.assetPath ? '来源：图片文件' : '未提取到像素图'}
              {item.sourcePage ? ` · 第 ${item.sourcePage} 页` : ''}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-foreground/45 transition-colors hover:bg-surface-high hover:text-foreground"
            aria-label="关闭预览"
            title="关闭"
          >
            <X size={16} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-surface-high p-4">
          {src ? (
            <img src={src} alt={`${item.numbering}：${item.caption}`} className="mx-auto max-h-[72vh] max-w-full object-contain" />
          ) : (
            <div className="flex min-h-[300px] flex-col items-center justify-center gap-2 text-center text-foreground/45">
              <FileImage size={34} />
              <p className="text-sm">没有可显示的像素图</p>
              <p className="max-w-lg text-xs leading-5">刷新图表抽取结果。</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function toDisplayableAssetUrl(projectId: string, assetPath: string | null | undefined): string | null {
  const value = String(assetPath ?? '').trim();
  if (!value) return null;
  if (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('/') || value.startsWith('data:image:') || value.startsWith('blob:')) {
    return value;
  }
  if (!projectId.trim() || value.startsWith('candidate://')) return null;
  return buildFigureAssetFileUrl(projectId, value);
}
