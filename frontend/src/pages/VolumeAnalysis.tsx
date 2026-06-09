import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  RotateCcw,
  Square,
} from 'lucide-react';
import { motion } from 'framer-motion';
import axios from 'axios';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { EmptyState } from '@/components/common/EmptyState';
import { PageHeader } from '@/components/common/PageHeader';
import { StatusPill } from '@/components/common/StatusPill';
import { getWritingBackendService } from '@/services/writingBackend';
import { loadSettings } from '@/services/settingsStore';
import type { VolumeAnalysisResult, VolumeSummary } from '@/types/resources';
import { formatVolumeActionError, formatVolumePathLabel, formatVolumeTaskSummary } from './volumeAnalysisDisplay';

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

// ─── Friendly loading message system ─────────────────────────────────────────

/** Witty research-themed loading messages, shown in rotation while processing */
const LOADING_QUIPS: string[] = [
  '正在阅读三千篇文献，可能需要片刻……',
  '正在比较各学派的研究结论是否互相矛盾……',
  '尝试理解作者在注脚里真正想说的话……',
  '正在计算哪篇文章被引用了多少次……',
  '拼命翻阅近十年的研究趋势……',
  '正在为每个论点寻找旗鼓相当的对立观点……',
  '分析中，研究员已就位……',
  '正在整理凌乱的参考文献列表……',
  '向量空间中，语义在慢慢浮现……',
  '数据降维中，知识版图正在成形……',
  '正在检查文献之间是否存在隐藏的联系……',
  '统计模型已上阵，稍等结果出炉……',
  '正在将高维思维投影到可读平面……',
  '寻找文献间最短的学术距离……',
  '等待群集分析完成，这很值得……',
];

/** Map raw progress (0-100) to a human-readable phase label */
function progressToPhase(progress: number): string {
  if (progress < 5)  return '准备中';
  if (progress < 20) return '读取文献';
  if (progress < 45) return '深度分析';
  if (progress < 65) return '知识建模';
  if (progress < 85) return '降维聚类';
  if (progress < 98) return '整合输出';
  return '收尾中';
}

/** Format seconds into a readable "x分y秒" string */
function formatSeconds(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  if (m === 0) return `约 ${sec} 秒`;
  if (sec === 0) return `约 ${m} 分钟`;
  return `约 ${m} 分 ${sec} 秒`;
}

function isRequestCanceled(error: unknown): boolean {
  return (error instanceof DOMException && error.name === 'AbortError')
    || (axios.isAxiosError(error) && error.code === 'ERR_CANCELED');
}

function formatTaskStatus(status: string): string {
  switch (status) {
    case 'succeeded':
      return '已完成';
    case 'failed':
      return '失败';
    case 'cancelled':
      return '已停止';
    case 'queued':
      return '等待中';
    case 'running':
      return '处理中';
    default:
      return '处理中';
  }
}

function formatTaskStage(stage?: string): string {
  const value = String(stage || '').trim().toLowerCase();
  if (!value) return '等待中';
  if (value.includes('cancel')) return '已停止';
  if (value.includes('complete')) return '已完成';
  if (value.includes('fail')) return '失败';
  if (value.includes('queue')) return '等待中';
  if (value.includes('scan') || value.includes('read')) return '读取文献';
  if (value.includes('merge') || value.includes('volume')) return '整合卷册';
  if (value.includes('process') || value.includes('running')) return '处理中';
  return '处理中';
}

/**
 * Returns a cycling witty message and an estimated remaining time string.
 * Messages rotate every 4.5 seconds while the task is running.
 */
function useFriendlyProgress(
  isRunning: boolean,
  progress: number,
  startTimeRef: React.MutableRefObject<number | null>
): { quip: string; eta: string } {
  const [quipIndex, setQuipIndex] = useState(() => Math.floor(Math.random() * LOADING_QUIPS.length));
  const [elapsed, setElapsed] = useState(0);

  // rotate quip every 4.5s
  useEffect(() => {
    if (!isRunning) return;
    const id = window.setInterval(() => {
      setQuipIndex(i => (i + 1) % LOADING_QUIPS.length);
    }, 4500);
    return () => window.clearInterval(id);
  }, [isRunning]);

  // track elapsed time
  useEffect(() => {
    if (!isRunning) { setElapsed(0); return; }
    const id = window.setInterval(() => {
      if (startTimeRef.current != null) {
        setElapsed((Date.now() - startTimeRef.current) / 1000);
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [isRunning, startTimeRef]);

  const eta = useMemo(() => {
    if (!isRunning || progress <= 0 || elapsed <= 0) return '';
    const remaining = (elapsed / progress) * (100 - progress);
    return formatSeconds(remaining);
  }, [isRunning, progress, elapsed]);

  return { quip: LOADING_QUIPS[quipIndex], eta };
}

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

  const taskStartTimeRef = useRef<number | null>(null);
  const analysisAbortControllerRef = useRef<AbortController | null>(null);
  const submitAbortControllerRef = useRef<AbortController | null>(null);
  const analysisStopRequestedRef = useRef(false);
  const submitStopRequestedRef = useRef(false);
  const isRunning = batchTask != null && batchTask.status !== 'succeeded' && batchTask.status !== 'failed' && batchTask.status !== 'cancelled';
  const { quip, eta } = useFriendlyProgress(isRunning, batchTask?.progress ?? 0, taskStartTimeRef);

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
      setListError(formatVolumeActionError(err, '卷册列表加载失败，请稍后重试。'));
      setVolumes([]);
      setSelectedVolumeKey(null);
    } finally {
      setLoadingVolumes(false);
    }
  }, [svc, t]);

  const loadAnalysis = useCallback(async (volumeKey: string, refresh: boolean = false) => {
    analysisAbortControllerRef.current?.abort();
    const abortController = new AbortController();
    analysisAbortControllerRef.current = abortController;
    analysisStopRequestedRef.current = false;
    setLoadingAnalysis(true);
    setAnalysisError(null);
    try {
      const payload = await svc.getVolumeAnalysis(volumeKey, refresh, { signal: abortController.signal });
      setAnalysis(payload);
      // 同步更新volume列表中的status，确保左右面板状态一致
      setVolumes(prev => prev.map(vol =>
        vol.volume_key === volumeKey ? { ...vol, status: 'indexed' as const } : vol
      ));
    } catch (err) {
      if (isRequestCanceled(err)) {
        if (analysisStopRequestedRef.current) {
          setAnalysisError('已停止分析。');
        }
        return;
      }
      setAnalysisError(formatVolumeActionError(err, '卷册分析加载失败，请稍后重试。'));
      // 保持最后已知的good state而不是清空，改进错误恢复体验
      // setAnalysis(null) 的做法会导致丢失之前的结果
    } finally {
      if (analysisAbortControllerRef.current === abortController) {
        analysisAbortControllerRef.current = null;
        setLoadingAnalysis(false);
      }
    }
  }, [svc, t]);

  const stopAnalysis = useCallback(() => {
    const abortController = analysisAbortControllerRef.current;
    if (!abortController) return;
    analysisStopRequestedRef.current = true;
    abortController.abort();
    setLoadingAnalysis(false);
    setAnalysisError('已停止分析。');
  }, []);

  const submitBatchTask = useCallback(async () => {
    if (submitLoading) return;
    const pdfFolder = batchForm.pdf_folder.trim();
    const outputRoot = batchForm.output_root.trim();
    const goal = batchForm.goal.trim();
    if (!pdfFolder || !outputRoot || !goal) {
      setSubmitError('请填写 PDF 目录、输出目录和目标');
      return;
    }

    const abortController = new AbortController();
    submitAbortControllerRef.current = abortController;
    submitStopRequestedRef.current = false;
    setSubmitLoading(true);
    setSubmitError(null);
    try {
      const now = Date.now();
      const resp = await svc.submitBatchProcessing({
        pdf_folder: pdfFolder,
        output_root: outputRoot,
        goal,
        batch_size: batchForm.batch_size,
      }, { signal: abortController.signal });
      localStorage.setItem('latest_batch_task_id', resp.task_id);
      taskStartTimeRef.current = null; // reset so ETA is measured from first run transition
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
      if (isRequestCanceled(err)) {
        if (submitStopRequestedRef.current) {
          setSubmitError('已停止提交。');
        }
        return;
      }
      setSubmitError(formatVolumeActionError(err, '批处理提交失败，请检查输入目录和输出位置。'));
    } finally {
      if (submitAbortControllerRef.current === abortController) {
        submitAbortControllerRef.current = null;
        setSubmitLoading(false);
      }
    }
  }, [batchForm, submitLoading, svc, t]);

  const stopBatchSubmit = useCallback(() => {
    const abortController = submitAbortControllerRef.current;
    if (!abortController) return;
    submitStopRequestedRef.current = true;
    abortController.abort();
    setSubmitLoading(false);
    setSubmitError('已停止提交。');
  }, []);

  const stopBatchTask = useCallback(async () => {
    if (!batchTask || !isRunning) return;
    try {
      const status = await svc.cancelPipelineTask(batchTask.task_id);
      setBatchTask(status);
      taskStartTimeRef.current = null;
      localStorage.removeItem('latest_batch_task_id');
      setTaskHistory(prev => {
        const next = prev.map(item => item.task_id === status.task_id
          ? {
              ...item,
              status: status.status,
              progress: status.progress,
              stage: status.stage,
              error: status.error,
            }
          : item);
        localStorage.setItem(BATCH_TASK_HISTORY_KEY, JSON.stringify(next));
        return next;
      });
    } catch (err) {
      setSubmitError(formatVolumeActionError(err, '停止任务失败，请稍后重试。'));
    }
  }, [batchTask, isRunning, svc, t]);

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
    return () => {
      analysisAbortControllerRef.current?.abort();
      submitAbortControllerRef.current?.abort();
    };
  }, []);

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
        // Record when task first transitions to running so we can estimate ETA
        if (status.status === 'running' && taskStartTimeRef.current == null) {
          taskStartTimeRef.current = Date.now();
        }
        if (status.status === 'succeeded' || status.status === 'failed' || status.status === 'cancelled') {
          taskStartTimeRef.current = null;
        }
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

        const isTerminal = status.status === 'succeeded' || status.status === 'failed' || status.status === 'cancelled';
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
    indexed: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300',
    pending: 'bg-surface-high text-foreground/50',
  };

  const totalPapers = volumes.reduce((sum, volume) => sum + volume.paper_count, 0);
  const totalWritingPoints = volumes.reduce((sum, volume) => sum + volume.writing_point_count, 0);
  const analyzedCount = volumes.filter(volume => volume.status === 'indexed').length;
  const selectedVolume = volumes.find(volume => volume.volume_key === selectedVolumeKey) ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<GitCompareArrows size={18} />}
          title={t('volume.title')}
          subtitle={t('volume.subtitle')}
          className="mb-0"
          actions={<StatusPill tone="primary">{t('volume.workflow_badge')}</StatusPill>}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-6 py-5">
        <section className="mb-5 grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.55fr)]">
          <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-5 shadow-sm">
            <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="font-label text-[11px] tracking-[0.18em] text-foreground/35">批处理</div>
                <h2 className="mt-1 font-headline text-base font-semibold text-foreground">批处理任务</h2>
                <p className="mt-1 text-xs leading-5 text-foreground/50">选择 PDF 文件夹、输出目录和分析目标后提交；任务状态会自动追踪，并写入最近任务。</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={selectedTemplateId}
                  onChange={e => handleSelectTemplate(e.target.value)}
                  className="h-9 min-w-[220px] rounded-md border border-outline-variant/60 bg-surface-low px-3 text-xs font-label text-foreground/75 focus:border-primary/40 focus:outline-none"
                  aria-label="最近参数模板"
                >
                  <option value="">历史模板</option>
                  {recentTemplates.map(template => (
                    <option key={template.id} value={template.id}>
                      {formatVolumeTaskSummary(template.pdf_folder, template.goal)}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => void retryFailedTask()}
                  disabled={submitLoading || !taskHistory.some(item => item.status === 'failed')}
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-outline-variant/60 bg-surface-low px-3 text-xs font-label text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
                >
                  <RotateCcw size={13} />
                  填充失败参数
                </button>
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
              <label className="space-y-1.5">
                <span className="text-[11px] font-label text-foreground/55">PDF 文件夹</span>
                <input
                  value={batchForm.pdf_folder}
                  onChange={e => setBatchForm(prev => ({ ...prev, pdf_folder: e.target.value }))}
                  placeholder="选择或粘贴本机 PDF 文件夹"
                  className="h-10 w-full rounded-md border border-outline-variant/60 bg-surface-low px-3 text-sm font-label text-foreground focus:border-primary/40 focus:outline-none"
                />
              </label>

              <label className="space-y-1.5">
                <span className="text-[11px] font-label text-foreground/55">输出目录</span>
                <input
                  value={batchForm.output_root}
                  onChange={e => setBatchForm(prev => ({ ...prev, output_root: e.target.value }))}
                  className="h-10 w-full rounded-md border border-outline-variant/60 bg-surface-low px-3 text-sm font-label text-foreground focus:border-primary/40 focus:outline-none"
                />
              </label>

              <label className="space-y-1.5">
                <span className="text-[11px] font-label text-foreground/55">分析目标</span>
                <input
                  value={batchForm.goal}
                  onChange={e => setBatchForm(prev => ({ ...prev, goal: e.target.value }))}
                  className="h-10 w-full rounded-md border border-outline-variant/60 bg-surface-low px-3 text-sm font-label text-foreground focus:border-primary/40 focus:outline-none"
                />
              </label>

              <div className="grid gap-3 sm:grid-cols-[minmax(120px,0.4fr)_minmax(160px,0.6fr)]">
                <label className="space-y-1.5">
                  <span className="text-[11px] font-label text-foreground/55">批大小</span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={batchForm.batch_size}
                    onChange={e => setBatchForm(prev => ({ ...prev, batch_size: Number(e.target.value) || 1 }))}
                    className="h-10 w-full rounded-md border border-outline-variant/60 bg-surface-low px-3 text-sm font-label text-foreground focus:border-primary/40 focus:outline-none"
                  />
                </label>
                <div className="flex items-end">
                  <button
                    type="button"
                    onClick={() => submitLoading ? stopBatchSubmit() : void submitBatchTask()}
                    className={cn(
                      'inline-flex h-10 w-full items-center justify-center gap-2 rounded-md px-4 text-sm font-label font-medium text-primary-foreground transition-colors',
                      submitLoading
                        ? 'bg-red-600 hover:bg-red-700'
                        : 'bg-primary hover:bg-primary/90',
                    )}
                  >
                    {submitLoading ? <Square size={14} /> : <RefreshCw size={14} />}
                    {submitLoading ? '停止提交' : '提交批处理'}
                  </button>
                </div>
              </div>
            </div>

            {submitError && (
              <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-label text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
                {submitError}
              </div>
            )}
          </div>

          <div className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-5 shadow-sm">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="font-label text-[11px] tracking-[0.18em] text-foreground/35">任务状态</div>
                <h2 className="mt-1 font-headline text-base font-semibold text-foreground">任务状态</h2>
              </div>
              <div className="flex items-center gap-2">
                {isRunning ? (
                  <button
                    type="button"
                    onClick={() => void stopBatchTask()}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-red-200 bg-red-50 px-2.5 text-xs font-label font-medium text-red-700 transition-colors hover:bg-red-100 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300"
                  >
                    <Square size={12} />
                    停止任务
                  </button>
                ) : null}
                {batchTask ? (
                  <span className={cn(
                    'rounded-full px-2.5 py-1 text-[11px] font-label font-medium',
                    batchTask.status === 'succeeded'
                      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                      : batchTask.status === 'failed' || batchTask.status === 'cancelled'
                        ? 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300'
                        : 'bg-primary/10 text-primary'
                  )}>
                    {formatTaskStatus(batchTask.status)}
                  </span>
                ) : null}
              </div>
            </div>

            {batchTask ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3 text-xs font-label text-foreground/55">
                  <span>{isRunning ? progressToPhase(batchTask.progress ?? 0) : formatTaskStage(batchTask.stage)}</span>
                  <span className="tabular-nums">{Math.round(batchTask.progress || 0)}%{eta ? ` · 剩余 ${eta}` : ''}</span>
                </div>
                {isRunning && (
                  <div className="flex min-h-6 items-center gap-2 rounded-md bg-surface-low px-2.5 py-1.5">
                    <Loader2 size={12} className="shrink-0 animate-spin text-primary/70" />
                    <span key={quip} className="line-clamp-1 text-xs font-label text-foreground/55">{quip}</span>
                  </div>
                )}
                {batchTask.error && (
                  <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-label text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
                    {formatVolumeActionError(batchTask.error, '批处理任务失败，请检查输入目录和输出位置。')}
                  </div>
                )}
                <div className="h-2 overflow-hidden rounded-full bg-surface-high">
                  <div
                    className={cn('h-full rounded-full transition-all duration-300', batchTask.status === 'failed' || batchTask.status === 'cancelled' ? 'bg-red-500' : 'bg-primary')}
                    style={{ width: `${Math.max(0, Math.min(100, batchTask.progress || 0))}%` }}
                  />
                </div>
                <div className="text-[11px] font-label text-foreground/35">任务已记录在本机历史中。</div>
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-outline-variant/60 bg-surface-low px-3 py-6 text-center text-xs text-foreground/45">
                暂无正在追踪的批处理任务
              </div>
            )}
          </div>
        </section>

        {taskHistory.length > 0 && (
          <section className="mb-5 rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="font-headline text-sm font-semibold text-foreground">最近任务</h2>
              <span className="text-[11px] font-label text-foreground/40">保留最近 {MAX_HISTORY_COUNT} 条本机记录</span>
            </div>
            <div className="grid gap-2 lg:grid-cols-2">
              {taskHistory.slice(0, 6).map(item => (
                <button
                  type="button"
                  key={item.task_id}
                  onClick={() => {
                    setBatchTaskId(item.task_id);
                    localStorage.setItem('latest_batch_task_id', item.task_id);
                  }}
                  className="w-full rounded-md border border-outline-variant/40 bg-surface-low px-3 py-2.5 text-left transition-colors hover:border-primary/35 hover:bg-surface-high"
                >
                  <div className="flex items-center gap-2 text-[11px] font-label text-foreground/70">
                    <span className={cn(
                      'rounded px-1.5 py-0.5',
                      item.status === 'succeeded'
                        ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                        : item.status === 'failed' || item.status === 'cancelled'
                          ? 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300'
                          : 'bg-primary/10 text-primary'
                    )}>
                      {formatTaskStatus(item.status)}
                    </span>
                    <span className="tabular-nums">{Math.round(item.progress || 0)}%</span>
                    <span className="min-w-0 flex-1 truncate">{formatTaskStage(item.stage)}</span>
                    <span className="shrink-0 text-foreground/40">{new Date(item.created_at).toLocaleString()}</span>
                  </div>
                  <div className="mt-1 truncate text-[10px] font-label text-foreground/45">
                    {formatVolumeTaskSummary(item.pdf_folder, item.goal)}
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

      {/* Summary stats */}
      <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
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
            className="flex items-center gap-3 rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm"
          >
            <div className={cn('flex h-10 w-10 items-center justify-center rounded-md bg-surface-high', s.color)}>
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
        <div className="flex items-center justify-center gap-3 rounded-lg border border-outline-variant/60 bg-surface-lowest p-10 text-foreground/50">
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
                  'group flex w-full items-center gap-4 rounded-lg border bg-surface-lowest p-5 text-left shadow-sm transition-all',
                  selectedVolumeKey === volume.volume_key
                    ? 'border-primary/40 shadow-sm'
                    : 'border-outline-variant/60 hover:border-primary/20'
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
                    {formatVolumePathLabel(volume.batch_summary.pdf_folder || volume.source_root, '本地卷册目录')}
                  </div>
                </div>
                <span className={cn('px-2 py-1 text-[10px] font-label font-medium rounded flex items-center gap-1.5', statusStyle[volume.status])}>
                  {statusLabel[volume.status]}
                </span>
                <ChevronRight size={16} className="text-foreground/15 group-hover:text-foreground/30 transition-colors" />
              </motion.button>
            ))}
          </div>

          <div className="min-h-[420px] rounded-lg border border-outline-variant/60 bg-surface-lowest p-6 shadow-sm">
            {!selectedVolume ? (
              <EmptyState title={t('volume.empty_title')} description={t('volume.empty_desc')} />
            ) : loadingAnalysis ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-foreground/50">
                <div className="flex items-center gap-3">
                  <Loader2 size={18} className="animate-spin" />
                  <span className="font-label text-sm">{t('volume.loading_analysis')}</span>
                </div>
                <button
                  type="button"
                  onClick={stopAnalysis}
                  className="inline-flex min-h-9 items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 text-xs font-label font-medium text-red-700 transition-colors hover:bg-red-100 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300"
                >
                  <Square size={13} />
                  停止分析
                </button>
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
                      <div className="mt-1 break-all">{formatVolumePathLabel(analysis.volume.batch_summary.pdf_folder, '—')}</div>
                    </div>
                    <div>
                      <div className="text-[10px] text-foreground/35">{t('volume.batch_output_root')}</div>
                      <div className="mt-1">{formatVolumePathLabel(analysis.volume.batch_summary.output_root, '—')}</div>
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

                  <section className="rounded-lg border border-emerald-100 bg-emerald-50/60 p-4 dark:border-emerald-700/40 dark:bg-emerald-500/10">
                    <div className="flex items-center gap-2 text-emerald-700 font-headline text-sm font-semibold mb-3 dark:text-emerald-300">
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
    </div>
  );
}
