import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  FileText,
  Layers,
  BookOpen,
  FolderTree,
  ChevronRight,
  Loader2,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  GitCompareArrows,
  Database,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { EmptyState } from '@/components/common/EmptyState';
import { getWritingBackendService } from '@/services/writingBackend';
import { loadSettings } from '@/services/settingsStore';
import type { VolumeAnalysisResult, VolumeSummary } from '@/types/resources';

interface BatchTaskStatus {
  task_id: string;
  status: string;
  progress: number;
  stage: string;
  result?: Record<string, unknown>;
  error?: string;
}

interface BatchSubmitTemplate {
  id: string;
  pdf_folder: string;
  output_root: string;
  goal: string;
  batch_size: number;
  used_at: number;
}

interface BatchTaskHistoryItem {
  task_id: string;
  status: string;
  progress: number;
  stage: string;
  created_at: number;
  pdf_folder: string;
  output_root: string;
  goal: string;
  batch_size: number;
  error?: string;
}

const BATCH_TASK_HISTORY_KEY = 'batch_task_history_v1';
const BATCH_TEMPLATE_KEY = 'batch_submit_templates_v1';
const MAX_TEMPLATE_COUNT = 5;
const MAX_HISTORY_COUNT = 10;

export function VolumeAnalysis() {
  const { t } = useI18n();
  const initialWorkspace = loadSettings().workspace.localStoragePath || 'batch_output';
  const [volumes, setVolumes] = useState<VolumeSummary[]>([]);
  const [selectedVolumeKey, setSelectedVolumeKey] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<VolumeAnalysisResult | null>(null);
  const [loadingVolumes, setLoadingVolumes] = useState(true);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [batchTaskId, setBatchTaskId] = useState<string | null>(null);
  const [batchTask, setBatchTask] = useState<BatchTaskStatus | null>(null);
  const [taskHistory, setTaskHistory] = useState<BatchTaskHistoryItem[]>([]);
  const [recentTemplates, setRecentTemplates] = useState<BatchSubmitTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('');
  const [submitLoading, setSubmitLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [batchForm, setBatchForm] = useState({
    pdf_folder: '',
    output_root: initialWorkspace,
    goal: 'Conclusion Extraction',
    batch_size: 13,
  });

  const svc = useMemo(() => getWritingBackendService(), []);

  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const taskFromQuery = search.get('task_id') || search.get('taskId');
    const taskFromLocal = localStorage.getItem('latest_batch_task_id');
    setBatchTaskId(taskFromQuery || taskFromLocal || null);

    try {
      const historyRaw = localStorage.getItem(BATCH_TASK_HISTORY_KEY);
      if (historyRaw) {
        const parsed = JSON.parse(historyRaw) as BatchTaskHistoryItem[];
        if (Array.isArray(parsed)) {
          setTaskHistory(parsed.slice(0, MAX_HISTORY_COUNT));
        }
      }
    } catch {
      setTaskHistory([]);
    }

    try {
      const templateRaw = localStorage.getItem(BATCH_TEMPLATE_KEY);
      if (templateRaw) {
        const parsed = JSON.parse(templateRaw) as BatchSubmitTemplate[];
        if (Array.isArray(parsed)) {
          setRecentTemplates(parsed.slice(0, MAX_TEMPLATE_COUNT));
        }
      }
    } catch {
      setRecentTemplates([]);
    }
  }, []);

  const loadVolumes = useCallback(async () => {
    setLoadingVolumes(true);
    setListError(null);
    try {
      const payload = await svc.listVolumes();
      setVolumes(payload.volumes);
      setSelectedVolumeKey(current => current ?? payload.volumes[0]?.volume_key ?? null);
    } catch (err) {
      const message = err instanceof Error ? err.message : t('common.error');
      setListError(message);
      setVolumes([]);
      setSelectedVolumeKey(null);
    } finally {
      setLoadingVolumes(false);
    }
  }, [svc, t]);

  const loadAnalysis = useCallback(async (volumeKey: string, refresh: boolean = false) => {
    setLoadingAnalysis(true);
    setAnalysisError(null);
    try {
      const payload = await svc.getVolumeAnalysis(volumeKey, refresh);
      setAnalysis(payload);
      // 同步更新volume列表中的status，确保左右面板状态一致
      setVolumes(prev => prev.map(vol =>
        vol.volume_key === volumeKey ? { ...vol, status: 'indexed' as const } : vol
      ));
    } catch (err) {
      const message = err instanceof Error ? err.message : t('common.error');
      setAnalysisError(message);
      // 保持最后已知的good state而不是清空，改进错误恢复体验
      // setAnalysis(null) 的做法会导致丢失之前的结果
    } finally {
      setLoadingAnalysis(false);
    }
  }, [svc, t]);

  const submitBatchTask = useCallback(async () => {
    if (submitLoading) return;
    const pdfFolder = batchForm.pdf_folder.trim();
    const outputRoot = batchForm.output_root.trim();
    const goal = batchForm.goal.trim();
    if (!pdfFolder || !outputRoot || !goal) {
      setSubmitError('请填写 PDF 目录、输出目录和目标');
      return;
    }

    setSubmitLoading(true);
    setSubmitError(null);
    try {
      const now = Date.now();
      const resp = await svc.submitBatchProcessing({
        pdf_folder: pdfFolder,
        output_root: outputRoot,
        goal,
        batch_size: batchForm.batch_size,
      });
      localStorage.setItem('latest_batch_task_id', resp.task_id);
      setBatchTaskId(resp.task_id);
      setBatchTask({
        task_id: resp.task_id,
        status: resp.status,
        progress: 0,
        stage: 'queued',
      });

      const nextTemplate: BatchSubmitTemplate = {
        id: `${pdfFolder}__${outputRoot}__${goal}__${batchForm.batch_size}`,
        pdf_folder: pdfFolder,
        output_root: outputRoot,
        goal,
        batch_size: batchForm.batch_size,
        used_at: now,
      };
      setRecentTemplates(prev => {
        const merged = [
          nextTemplate,
          ...prev.filter(item => item.id !== nextTemplate.id),
        ].slice(0, MAX_TEMPLATE_COUNT);
        localStorage.setItem(BATCH_TEMPLATE_KEY, JSON.stringify(merged));
        return merged;
      });

      const historyItem: BatchTaskHistoryItem = {
        task_id: resp.task_id,
        status: resp.status,
        progress: 0,
        stage: 'queued',
        created_at: now,
        pdf_folder: pdfFolder,
        output_root: outputRoot,
        goal,
        batch_size: batchForm.batch_size,
      };
      setTaskHistory(prev => {
        const merged = [historyItem, ...prev.filter(item => item.task_id !== resp.task_id)].slice(0, MAX_HISTORY_COUNT);
        localStorage.setItem(BATCH_TASK_HISTORY_KEY, JSON.stringify(merged));
        return merged;
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : t('common.error');
      setSubmitError(message);
    } finally {
      setSubmitLoading(false);
    }
  }, [batchForm, submitLoading, svc, t]);

  const retryFailedTask = useCallback(async () => {
    if (submitLoading) return;
    const failed = taskHistory.find(item => item.status === 'failed');
    if (!failed) {
      setSubmitError('没有可重试的失败任务');
      return;
    }
    setBatchForm({
      pdf_folder: failed.pdf_folder,
      output_root: failed.output_root,
      goal: failed.goal,
      batch_size: failed.batch_size,
    });
    setSubmitError(null);
  }, [submitLoading, taskHistory]);

  useEffect(() => {
    void loadVolumes();
  }, [loadVolumes]);

  useEffect(() => {
    if (!selectedVolumeKey) {
      setAnalysis(null);
      return;
    }
    void loadAnalysis(selectedVolumeKey);
  }, [selectedVolumeKey, loadAnalysis]);

  useEffect(() => {
    if (!batchTaskId) {
      setBatchTask(null);
      return;
    }

    let cancelled = false;
    let timer: number | null = null;

    const poll = async () => {
      try {
        const status = await svc.getBatchTaskStatus(batchTaskId);
        if (cancelled) return;
        setBatchTask(status);
        setTaskHistory(prev => {
          const idx = prev.findIndex(item => item.task_id === status.task_id);
          if (idx < 0) return prev;
          const next = [...prev];
          next[idx] = {
            ...next[idx],
            status: status.status,
            progress: status.progress,
            stage: status.stage,
            error: status.error,
          };
          localStorage.setItem(BATCH_TASK_HISTORY_KEY, JSON.stringify(next));
          return next;
        });

        const isTerminal = status.status === 'succeeded' || status.status === 'failed';
        if (!isTerminal) {
          timer = window.setTimeout(() => {
            void poll();
          }, 2500);
          return;
        }

        if (status.status === 'succeeded') {
          localStorage.removeItem('latest_batch_task_id');
          await loadVolumes();
          if (selectedVolumeKey) {
            await loadAnalysis(selectedVolumeKey);
          }
        }
      } catch {
        // keep current UI; polling errors should not break the page
      }
    };

    void poll();

    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [batchTaskId, loadAnalysis, loadVolumes, selectedVolumeKey, svc]);

  const handleSelectTemplate = useCallback((templateId: string) => {
    setSelectedTemplateId(templateId);
    const template = recentTemplates.find(item => item.id === templateId);
    if (!template) return;
    setBatchForm({
      pdf_folder: template.pdf_folder,
      output_root: template.output_root,
      goal: template.goal,
      batch_size: template.batch_size,
    });
    setSubmitError(null);
  }, [recentTemplates]);

  const statusLabel = {
    indexed: t('volume.status_indexed'),
    pending: t('volume.status_pending'),
  };

  const statusStyle = {
    indexed: 'bg-emerald-50 text-emerald-600',
    pending: 'bg-surface-high text-foreground/50',
  };

  const totalPapers = volumes.reduce((sum, volume) => sum + volume.paper_count, 0);
  const totalWritingPoints = volumes.reduce((sum, volume) => sum + volume.writing_point_count, 0);
  const analyzedCount = volumes.filter(volume => volume.status === 'indexed').length;
  const selectedVolume = volumes.find(volume => volume.volume_key === selectedVolumeKey) ?? null;

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="font-display text-2xl font-semibold text-foreground">
          {t('volume.title')}
        </h1>
        <p className="font-label text-sm text-foreground/50 mt-1">
          {t('volume.subtitle')}
        </p>
        <div className="mt-3 inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-primary/8 text-primary text-xs font-label">
          <GitCompareArrows size={14} />
          {t('volume.workflow_badge')}
        </div>
        {batchTask && (
          <div className="mt-3 rounded-lg border border-outline-variant/40 bg-surface-high/40 p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs font-label text-foreground/70">
              <span className={cn(
                'px-2 py-0.5 rounded-full text-[10px] font-medium',
                batchTask.status === 'succeeded'
                  ? 'bg-emerald-50 text-emerald-700'
                  : batchTask.status === 'failed'
                    ? 'bg-red-50 text-red-700'
                    : 'bg-primary/10 text-primary'
              )}>
                batch · {batchTask.status}
              </span>
              <span>{batchTask.stage || 'running'}</span>
              <span className="tabular-nums">{Math.round(batchTask.progress || 0)}%</span>
              {batchTask.error && (
                <span className="text-red-600 line-clamp-1">{batchTask.error}</span>
              )}
            </div>
            <div className="mt-2 h-1.5 rounded-full bg-surface-high overflow-hidden">
              <div className="h-full grid grid-cols-20 gap-px">
                {Array.from({ length: 20 }, (_, idx) => {
                  const active = idx < Math.round(Math.max(0, Math.min(100, batchTask.progress || 0)) / 5);
                  return (
                    <span
                      key={`segment-${idx}`}
                      className={cn(
                        'h-full rounded-[1px] transition-colors',
                        active
                          ? (batchTask.status === 'failed' ? 'bg-red-500' : 'bg-primary')
                          : 'bg-transparent'
                      )}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="glass-card rounded-xl p-4 mb-6 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-headline text-sm font-semibold text-foreground">批处理任务</h2>
          <span className="text-[11px] font-label text-foreground/45">提交后会自动追踪进度</span>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <label className="space-y-1">
            <span className="text-[11px] font-label text-foreground/55">最近参数模板</span>
            <select
              value={selectedTemplateId}
              onChange={e => handleSelectTemplate(e.target.value)}
              className="w-full rounded-lg border border-outline-variant/40 bg-surface-high px-3 py-2 text-sm font-label text-foreground focus:outline-none focus:border-primary/40"
            >
              <option value="">选择历史模板（最多5组）</option>
              {recentTemplates.map(template => (
                <option key={template.id} value={template.id}>
                  {template.pdf_folder} ｜ {template.goal}
                </option>
              ))}
            </select>
          </label>

          <div className="space-y-1">
            <span className="text-[11px] font-label text-foreground/55">失败重试</span>
            <button
              type="button"
              onClick={() => void retryFailedTask()}
              disabled={submitLoading || !taskHistory.some(item => item.status === 'failed')}
              className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-outline-variant/50 bg-surface-high text-sm font-label text-foreground hover:border-primary/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <RefreshCw size={14} />
              一键填充最近失败参数
            </button>
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <label className="space-y-1">
            <span className="text-[11px] font-label text-foreground/55">PDF 文件夹</span>
            <input
              value={batchForm.pdf_folder}
              onChange={e => setBatchForm(prev => ({ ...prev, pdf_folder: e.target.value }))}
              placeholder="例如：C:/data/pdfs"
              className="w-full rounded-lg border border-outline-variant/40 bg-surface-high px-3 py-2 text-sm font-label text-foreground focus:outline-none focus:border-primary/40"
            />
          </label>

          <label className="space-y-1">
            <span className="text-[11px] font-label text-foreground/55">输出目录</span>
            <input
              value={batchForm.output_root}
              onChange={e => setBatchForm(prev => ({ ...prev, output_root: e.target.value }))}
              className="w-full rounded-lg border border-outline-variant/40 bg-surface-high px-3 py-2 text-sm font-label text-foreground focus:outline-none focus:border-primary/40"
            />
          </label>

          <label className="space-y-1">
            <span className="text-[11px] font-label text-foreground/55">分析目标</span>
            <input
              value={batchForm.goal}
              onChange={e => setBatchForm(prev => ({ ...prev, goal: e.target.value }))}
              className="w-full rounded-lg border border-outline-variant/40 bg-surface-high px-3 py-2 text-sm font-label text-foreground focus:outline-none focus:border-primary/40"
            />
          </label>

          <label className="space-y-1">
            <span className="text-[11px] font-label text-foreground/55">批大小</span>
            <input
              type="number"
              min={1}
              max={100}
              value={batchForm.batch_size}
              onChange={e => setBatchForm(prev => ({ ...prev, batch_size: Number(e.target.value) || 1 }))}
              className="w-full rounded-lg border border-outline-variant/40 bg-surface-high px-3 py-2 text-sm font-label text-foreground focus:outline-none focus:border-primary/40"
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void submitBatchTask()}
            disabled={submitLoading}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-label hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitLoading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {submitLoading ? t('common.loading') : '提交批处理'}
          </button>
          {submitError && <span className="text-xs font-label text-red-600">{submitError}</span>}
        </div>

        {taskHistory.length > 0 && (
          <div className="rounded-lg border border-outline-variant/30 bg-surface-high/40 p-3 space-y-2">
            <div className="text-[11px] font-label text-foreground/55">最近任务</div>
            <div className="space-y-1.5">
              {taskHistory.slice(0, 5).map(item => (
                <button
                  type="button"
                  key={item.task_id}
                  onClick={() => {
                    setBatchTaskId(item.task_id);
                    localStorage.setItem('latest_batch_task_id', item.task_id);
                  }}
                  className="w-full text-left px-2.5 py-2 rounded-md border border-outline-variant/20 hover:border-primary/30 hover:bg-surface-high transition-colors"
                >
                  <div className="flex items-center gap-2 text-[11px] font-label text-foreground/70">
                    <span className={cn(
                      'px-1.5 py-0.5 rounded',
                      item.status === 'succeeded'
                        ? 'bg-emerald-50 text-emerald-700'
                        : item.status === 'failed'
                          ? 'bg-red-50 text-red-700'
                          : 'bg-primary/10 text-primary'
                    )}>
                      {item.status}
                    </span>
                    <span className="tabular-nums">{Math.round(item.progress || 0)}%</span>
                    <span className="line-clamp-1">{item.stage || 'queued'}</span>
                    <span className="ml-auto text-foreground/40">{new Date(item.created_at).toLocaleString()}</span>
                  </div>
                  <div className="mt-1 text-[10px] font-label text-foreground/45 line-clamp-1">
                    {item.pdf_folder} · {item.goal}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4 mb-8">
        {[
          { icon: Layers, label: t('volume.stat_volumes'), value: volumes.length, color: 'text-primary' },
          { icon: FileText, label: t('volume.stat_papers'), value: totalPapers, color: 'text-emerald-500' },
          { icon: BookOpen, label: t('volume.stat_points'), value: totalWritingPoints, color: 'text-amber-500' },
          { icon: Database, label: t('volume.stat_indexed'), value: analyzedCount, color: 'text-violet-500' },
        ].map((s, i) => (
          <motion.div
            key={s.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className="glass-card p-4 rounded-lg flex items-center gap-3"
          >
            <div className={cn('h-10 w-10 rounded-lg flex items-center justify-center bg-surface-high', s.color)}>
              <s.icon size={20} />
            </div>
            <div>
              <div className="font-headline text-xl font-semibold text-foreground tabular-nums">{s.value}</div>
              <div className="font-label text-[10px] text-foreground/40">{s.label}</div>
            </div>
          </motion.div>
        ))}
      </div>

      {loadingVolumes ? (
        <div className="glass-card rounded-xl p-10 flex items-center justify-center gap-3 text-foreground/50">
          <Loader2 size={18} className="animate-spin" />
          <span className="font-label text-sm">{t('common.loading')}</span>
        </div>
      ) : listError ? (
        <div className="space-y-4">
          <EmptyState title={t('common.error')} description={listError} />
          <div className="flex justify-center">
            <button
              type="button"
              onClick={() => void loadVolumes()}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-outline-variant/50 bg-surface-high text-sm font-label text-foreground hover:border-primary/30 transition-colors"
            >
              <RefreshCw size={14} />
              {t('common.refresh')}
            </button>
          </div>
        </div>
      ) : volumes.length === 0 ? (
        <EmptyState title={t('volume.empty_title')} description={t('volume.empty_desc')} />
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-[360px_minmax(0,1fr)] gap-6">
          <div className="space-y-4">
            {volumes.map((volume, index) => (
              <motion.button
                type="button"
                key={volume.volume_key}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.05 }}
                onClick={() => setSelectedVolumeKey(volume.volume_key)}
                className={cn(
                  'w-full text-left glass-card rounded-lg p-5 group transition-all flex items-center gap-4 border',
                  selectedVolumeKey === volume.volume_key
                    ? 'border-primary/40 shadow-sm'
                    : 'border-transparent hover:border-primary/20'
                )}
              >
                <div className="h-12 w-12 bg-primary/8 rounded-xl flex items-center justify-center flex-shrink-0 group-hover:bg-primary/12 transition-all">
                  <FolderTree size={22} className="text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-headline font-semibold text-base text-foreground truncate">{volume.label}</h3>
                  <div className="flex flex-wrap items-center gap-3 mt-1 font-label text-[11px] text-foreground/45">
                    <span>{volume.paper_count} {t('volume.unit_papers')}</span>
                    <span>{volume.writing_point_count} {t('volume.unit_points')}</span>
                    {volume.created_at && <span>{new Date(volume.created_at).toLocaleString()}</span>}
                  </div>
                  <div className="mt-2 text-[11px] text-foreground/40 truncate">
                    {volume.batch_summary.pdf_folder || volume.source_root}
                  </div>
                </div>
                <span className={cn('px-2 py-1 text-[10px] font-label font-medium rounded flex items-center gap-1.5', statusStyle[volume.status])}>
                  {statusLabel[volume.status]}
                </span>
                <ChevronRight size={16} className="text-foreground/15 group-hover:text-foreground/30 transition-colors" />
              </motion.button>
            ))}
          </div>

          <div className="glass-card rounded-xl p-6 min-h-[420px]">
            {!selectedVolume ? (
              <EmptyState title={t('volume.empty_title')} description={t('volume.empty_desc')} />
            ) : loadingAnalysis ? (
              <div className="h-full flex items-center justify-center gap-3 text-foreground/50">
                <Loader2 size={18} className="animate-spin" />
                <span className="font-label text-sm">{t('volume.loading_analysis')}</span>
              </div>
            ) : analysisError ? (
              <div className="space-y-4">
                <EmptyState title={t('common.error')} description={analysisError} />
                <div className="flex justify-center">
                  <button
                    type="button"
                    onClick={() => selectedVolumeKey && void loadAnalysis(selectedVolumeKey, true)}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-outline-variant/50 bg-surface-high text-sm font-label text-foreground hover:border-primary/30 transition-colors"
                  >
                    <RefreshCw size={14} />
                    {t('volume.refresh_analysis')}
                  </button>
                </div>
              </div>
            ) : analysis ? (
              <div className="space-y-6">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h2 className="font-display text-xl font-semibold text-foreground">{analysis.volume.label}</h2>
                    <p className="font-label text-sm text-foreground/45 mt-1">{t('volume.detail_subtitle')}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void loadAnalysis(analysis.volume.volume_key, true)}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-outline-variant/50 bg-surface-high text-sm font-label text-foreground hover:border-primary/30 transition-colors"
                  >
                    <RefreshCw size={14} />
                    {t('volume.refresh_analysis')}
                  </button>
                </div>

                <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
                  {[
                    { icon: FileText, label: t('volume.stat_papers'), value: analysis.volume.paper_count },
                    { icon: BookOpen, label: t('volume.stat_points'), value: analysis.volume.writing_point_count },
                    { icon: GitCompareArrows, label: t('volume.stat_tracked_parameters'), value: analysis.analysis.tracked_parameter_count },
                    { icon: AlertTriangle, label: t('volume.stat_conflicts'), value: analysis.analysis.high_conflict_count },
                  ].map(card => (
                    <div key={card.label} className="rounded-lg border border-outline-variant/30 bg-surface-high/40 p-4 flex items-center gap-3">
                      <div className="h-10 w-10 rounded-lg bg-surface-high flex items-center justify-center text-primary">
                        <card.icon size={18} />
                      </div>
                      <div>
                        <div className="font-headline text-lg font-semibold text-foreground tabular-nums">{card.value}</div>
                        <div className="font-label text-[10px] text-foreground/40">{card.label}</div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="rounded-lg border border-outline-variant/30 bg-surface-high/30 p-4">
                  <h3 className="font-headline text-sm font-semibold text-foreground mb-3">{t('volume.batch_section_title')}</h3>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4 text-sm font-label text-foreground/60">
                    <div>
                      <div className="text-[10px] text-foreground/35">{t('volume.batch_source_folder')}</div>
                      <div className="mt-1 break-all">{analysis.volume.batch_summary.pdf_folder || '—'}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-foreground/35">{t('volume.batch_output_root')}</div>
                      <div className="mt-1">{analysis.volume.batch_summary.output_root}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-foreground/35">{t('volume.batch_success_rate')}</div>
                      <div className="mt-1">{analysis.volume.batch_summary.successful_pdfs} / {analysis.volume.batch_summary.total_pdfs}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-foreground/35">{t('volume.batch_size')}</div>
                      <div className="mt-1">{analysis.volume.batch_summary.batch_size || '—'}</div>
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 xl:grid-cols-2">
                  <section className="rounded-lg border border-orange-100 bg-orange-50/60 p-4">
                    <div className="flex items-center gap-2 text-orange-700 font-headline text-sm font-semibold mb-3">
                      <AlertTriangle size={16} />
                      {t('volume.top_conflicts_title')}
                    </div>
                    {analysis.analysis.top_conflicts.length === 0 ? (
                      <p className="text-sm font-label text-foreground/45">{t('volume.top_conflicts_empty')}</p>
                    ) : (
                      <div className="space-y-3">
                        {analysis.analysis.top_conflicts.map(item => (
                          <div key={`conflict-${item.parameter}`} className="rounded-lg bg-white/70 border border-orange-100 p-3">
                            <div className="flex items-center justify-between gap-3">
                              <div className="font-headline text-sm font-semibold text-foreground">{item.parameter}</div>
                              <div className="text-[11px] font-label text-orange-700">{item.paper_count} {t('volume.unit_papers')}</div>
                            </div>
                            <div className="mt-2 space-y-2">
                              {item.claim_groups.slice(0, 3).map((group, idx) => (
                                <div key={`${item.parameter}-${idx}`} className="text-xs font-label text-foreground/65">
                                  <div className="line-clamp-2">{group.text}</div>
                                  <div className="mt-1 text-[10px] text-foreground/40">{group.papers.join(', ')}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>

                  <section className="rounded-lg border border-emerald-100 bg-emerald-50/60 p-4">
                    <div className="flex items-center gap-2 text-emerald-700 font-headline text-sm font-semibold mb-3">
                      <CheckCircle2 size={16} />
                      {t('volume.top_consensus_title')}
                    </div>
                    {analysis.analysis.top_consensus.length === 0 ? (
                      <p className="text-sm font-label text-foreground/45">{t('volume.top_consensus_empty')}</p>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {analysis.analysis.top_consensus.map(item => (
                          <div key={`consensus-${item.parameter}`} className="px-3 py-2 rounded-lg bg-white/80 border border-emerald-100 text-sm font-label text-emerald-800">
                            <div className="font-semibold">{item.parameter}</div>
                            <div className="text-[11px] mt-1">{item.paper_count} {t('volume.unit_papers')}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                </div>

                <section>
                  <div className="flex items-center gap-2 font-headline text-sm font-semibold text-foreground mb-3">
                    <Database size={16} className="text-primary" />
                    {t('volume.trend_table_title')}
                  </div>
                  <div className="overflow-hidden rounded-lg border border-outline-variant/30">
                    <div className="grid grid-cols-[160px_120px_100px_minmax(0,1fr)] gap-3 px-4 py-3 bg-surface-high text-[11px] font-label text-foreground/45">
                      <span>{t('volume.table_parameter')}</span>
                      <span>{t('volume.table_trend')}</span>
                      <span>{t('volume.table_papers')}</span>
                      <span>{t('volume.table_notes')}</span>
                    </div>
                    <div className="divide-y divide-outline-variant/20 bg-white/70">
                      {analysis.analysis.trend_rows.map(row => (
                        <div key={`trend-${row.parameter}`} className="grid grid-cols-[160px_120px_100px_minmax(0,1fr)] gap-3 px-4 py-3 text-sm">
                          <span className="font-headline font-medium text-foreground">{row.parameter}</span>
                          <span className={cn('font-label', row.consensus ? 'text-emerald-700' : 'text-orange-700')}>
                            {row.consensus ? t('volume.trend_consensus') : t('volume.trend_divergent')}
                          </span>
                          <span className="font-label text-foreground/60">{row.papers_count}</span>
                          <span className="font-label text-foreground/60 line-clamp-2">
                            {row.representative_claim || t('volume.trend_variant_count', { count: row.claim_variants })}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </section>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
