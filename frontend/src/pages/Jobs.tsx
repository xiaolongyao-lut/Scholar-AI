import React, { useState, useEffect, useCallback } from 'react';
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  Clock,
  Database,
  GitBranch,
  Inbox,
  Layers3,
  Library,
  Loader2,
  XCircle,
  RefreshCw,
  Pause,
  Play,
  Square,
  Trash2,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { EmptyState } from '@/components/common/EmptyState';
import { PageHeader } from '@/components/common/PageHeader';
import { StatusPill, type StatusTone } from '@/components/common/StatusPill';
import { getWritingRuntimeClient } from '@/services/runtimeClient';
import { formatJobError, formatJobName, formatJobRuntimeError } from './jobsDisplay';
import type { WritingJob, JobStatus as RuntimeJobStatus } from '@/types/runtime';

type JobStatus = 'running' | 'completed' | 'failed' | 'queued' | 'paused' | 'cancelled';

interface Job {
  id: string;
  name: string;
  type: string;
  status: JobStatus;
  progress: number;
  startedAt: string;
  duration?: string;
  error?: string;
  stage?: string;
  message?: string;
  route?: string;
}

interface UserTaskShortcut {
  id: string;
  label: string;
  detail: string;
  route: string;
  icon: React.ElementType;
}

const statusConfig: Record<JobStatus, { icon: React.ElementType; color: string; bg: string; textKey: string }> = {
  running: { icon: Loader2, color: 'text-blue-600 dark:text-blue-300', bg: 'bg-blue-50 dark:bg-blue-500/15', textKey: 'jobs.status_running' },
  completed: { icon: CheckCircle2, color: 'text-emerald-600 dark:text-emerald-300', bg: 'bg-emerald-50 dark:bg-emerald-500/15', textKey: 'jobs.status_completed' },
  failed: { icon: XCircle, color: 'text-red-600 dark:text-red-300', bg: 'bg-red-50 dark:bg-red-500/15', textKey: 'jobs.status_failed' },
  queued: { icon: Clock, color: 'text-foreground/40', bg: 'bg-surface-high', textKey: 'jobs.status_queued' },
  paused: { icon: Pause, color: 'text-amber-600 dark:text-amber-300', bg: 'bg-amber-50 dark:bg-amber-500/15', textKey: 'jobs.status_paused' },
  cancelled: { icon: Square, color: 'text-foreground/45', bg: 'bg-surface-high', textKey: 'jobs.status_cancelled' },
};

const USER_TASK_SHORTCUTS: UserTaskShortcut[] = [
  {
    id: 'insights',
    label: '待确认',
    detail: '复审内容',
    route: '/wiki?section=insights',
    icon: Inbox,
  },
  {
    id: 'knowledge',
    label: '已沉淀',
    detail: '确认页面',
    route: '/wiki?section=knowledge',
    icon: Library,
  },
  {
    id: 'sources',
    label: '来源',
    detail: '原文与分块',
    route: '/wiki?section=sources',
    icon: Database,
  },
  {
    id: 'graph',
    label: '关联',
    detail: '关系视图',
    route: '/wiki?section=graph',
    icon: GitBranch,
  },
];

export function Jobs() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<JobStatus | ''>('');
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const client = getWritingRuntimeClient();
      const payload = await client.listJobs({ limit: 100 });
      setJobs(payload.map(mapRuntimeJob));
    } catch (err) {
      setLoadError(formatJobError(err));
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadJobs();
    // B17 (2026-06-13): 任务中心需要看到 job 实时进度，原本只在首次加载或
    // 用户点"刷新"按钮才更新。改成每 4s 自动轮询，"刷新"按钮保留用于强制
    // 立即拉取。轮询仅在 tab 可见时跑，节省后台/隐藏窗口的请求。
    const tick = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        return;
      }
      void loadJobs();
    };
    const id = window.setInterval(tick, 4000);
    return () => {
      window.clearInterval(id);
    };
  }, [loadJobs]);

  const handlePause = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const client = getWritingRuntimeClient();
      await client.pauseJob(jobId);
      await loadJobs();
    } catch (err) {
      setLoadError(formatJobError(err));
    }
    setActionLoading(null);
  };

  const handleResume = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const client = getWritingRuntimeClient();
      await client.resumeJob(jobId);
      await loadJobs();
    } catch (err) {
      setLoadError(formatJobError(err));
    }
    setActionLoading(null);
  };

  const handleCancel = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const client = getWritingRuntimeClient();
      await client.cancelJob(jobId);
      await loadJobs();
    } catch (err) {
      setLoadError(formatJobError(err));
    }
    setActionLoading(null);
  };

  const handleDelete = async (jobId: string) => {
    const confirmed = window.confirm('删除任务会清除该任务的事件、产物和后台状态，确认删除？');
    if (!confirmed) return;
    setActionLoading(jobId);
    try {
      const client = getWritingRuntimeClient();
      await client.deleteJob(jobId);
      await loadJobs();
    } catch (err) {
      setLoadError(formatJobError(err));
    }
    setActionLoading(null);
  };

  const handleRetry = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const client = getWritingRuntimeClient();
      await client.startJob(jobId);
      await loadJobs();
    } catch (err) {
      setLoadError(formatJobError(err));
    }
    setActionLoading(null);
  };

  const filtered = filter ? jobs.filter(j => j.status === filter) : jobs;
  const runningCount = jobs.filter(j => j.status === 'running').length;

  const handleJobRoute = (route: string | undefined) => {
    if (!route) return;
    navigate(route);
  };

  const handleJobRouteKeyDown = (event: React.KeyboardEvent<HTMLElement>, route: string | undefined) => {
    if (!route) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      navigate(route);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<Activity size={18} />}
          title={t('jobs.title')}
          subtitle={t('jobs.subtitle', { running: runningCount, total: jobs.length })}
          className="mb-0"
          actions={
            <button
              type="button"
              onClick={() => void loadJobs()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-1.5 font-label text-xs font-medium text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:opacity-60"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              刷新
            </button>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-auto px-6 py-4">
        {/* Filter chips */}
        <div className="mb-4 flex flex-wrap items-center gap-1.5">
          {[
            { key: '' as const, label: t('jobs.filter_all') },
            { key: 'running' as const, label: t('jobs.filter_running') },
            { key: 'completed' as const, label: t('jobs.filter_completed') },
            { key: 'failed' as const, label: t('jobs.filter_failed') },
            { key: 'paused' as const, label: '已暂停' },
          ].map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key as JobStatus | '')}
              className={cn(
                'inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-medium transition-colors',
                filter === f.key
                  ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                  : 'border-outline-variant/60 bg-surface-low text-foreground/65 hover:border-primary/40 hover:text-foreground',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        <section className="mb-4 rounded-md border border-outline-variant/60 bg-surface-lowest px-3 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Layers3 size={16} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="font-display text-sm font-semibold text-foreground">知识沉淀</h2>
              <p className="mt-0.5 text-[11px] text-foreground/45">记录、复审、沉淀、召回。</p>
            </div>
            <button
              type="button"
              onClick={() => navigate('/wiki')}
              className="inline-flex items-center gap-1 rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary"
            >
              打开
              <ChevronRight size={13} />
            </button>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {USER_TASK_SHORTCUTS.map((task) => (
              <button
                key={task.id}
                type="button"
                onClick={() => navigate(task.route)}
                className="group flex min-h-12 min-w-0 items-center gap-2 rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2 text-left transition-colors hover:border-primary/35 hover:bg-surface-default/40"
              >
                <task.icon size={14} className="shrink-0 text-primary/75" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-label text-xs font-semibold text-foreground/75">{task.label}</span>
                  <span className="mt-0.5 block truncate text-[10px] text-foreground/40">{task.detail}</span>
                </span>
                <ChevronRight size={12} className="shrink-0 text-foreground/30 transition-colors group-hover:text-primary" />
              </button>
            ))}
          </div>
        </section>

        {/* Job list */}
        {loading ? (
          <div className="flex items-center justify-center gap-2 rounded-md border border-outline-variant/60 bg-surface-lowest px-4 py-10 text-sm text-foreground/50">
            <Loader2 size={16} className="animate-spin" />
            正在加载任务
          </div>
        ) : loadError ? (
          <EmptyState
            title="任务加载失败"
            description={loadError}
            icon={<XCircle size={40} />}
            action={
              <button
                type="button"
                onClick={() => void loadJobs()}
                className="inline-flex items-center gap-2 rounded-lg border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary"
              >
                <RefreshCw size={14} />
                重新加载
              </button>
            }
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            title={t('jobs.empty_title')}
            description={filter ? '当前筛选下没有任务。切换到“全部”可查看其他状态。' : t('jobs.empty_description')}
            icon={<Activity size={40} />}
            action={
              <button
                type="button"
                onClick={() => void loadJobs()}
                className="inline-flex items-center gap-2 rounded-lg border border-outline-variant/60 bg-surface-low px-3 py-2 text-sm font-medium text-foreground/70 transition-colors hover:border-primary/35 hover:text-primary"
              >
                <RefreshCw size={14} />
                检查任务
              </button>
            }
          />
        ) : (
          <div className="overflow-hidden rounded-md border border-outline-variant/60 bg-surface-lowest">
            <ul className="divide-y divide-outline-variant/30">
              {filtered.map((job) => {
                const cfg = statusConfig[job.status];
                const tone: StatusTone =
                  job.status === 'running' ? 'warning'
                  : job.status === 'completed' ? 'success'
                  : job.status === 'failed' ? 'danger'
                  : job.status === 'cancelled' ? 'neutral'
                  : job.status === 'paused' ? 'warning'
                  : 'neutral';
                return (
                  <li
                    key={job.id}
                    role={job.route ? 'button' : undefined}
                    tabIndex={job.route ? 0 : undefined}
                    onClick={() => handleJobRoute(job.route)}
                    onKeyDown={(event) => handleJobRouteKeyDown(event, job.route)}
                    className={cn(
                      'group flex flex-col gap-2 px-4 py-3 transition-colors hover:bg-surface-default/40',
                      job.route && 'cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <div className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-md', cfg.bg)}>
                        <cfg.icon size={14} className={cn(cfg.color, job.status === 'running' && 'animate-spin')} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h4 className="truncate font-label text-sm font-medium text-foreground">{job.name}</h4>
                        <div className="mt-0.5 flex flex-wrap items-center gap-2 font-label text-[10px] text-foreground/45">
                          <span>{t('jobs.started_at')} {job.startedAt}</span>
                          {job.duration && <span>{t('jobs.duration')} {job.duration}</span>}
                          {job.stage && <span>{job.stage}</span>}
                        </div>
                        {job.message ? (
                          <p className="mt-1 line-clamp-1 text-xs text-foreground/55">{job.message}</p>
                        ) : null}
                      </div>
                      <StatusPill tone={tone}>{t(cfg.textKey)}</StatusPill>
                      {job.route ? <ChevronRight size={14} className="shrink-0 text-foreground/28 group-hover:text-primary" /> : null}
                      <div className="flex shrink-0 items-center gap-1">
                        {(job.status === 'failed' || job.status === 'cancelled') && (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleRetry(job.id);
                            }}
                            disabled={actionLoading === job.id}
                            title={t('jobs.retry')}
                            aria-label={t('jobs.retry')}
                            className="rounded p-1 text-foreground/55 transition-colors hover:bg-surface-high hover:text-primary"
                          >
                            {actionLoading === job.id ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                          </button>
                        )}
                        {job.status === 'queued' && (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleRetry(job.id);
                            }}
                            disabled={actionLoading === job.id}
                            title="开始任务"
                            aria-label="开始任务"
                            className="rounded border border-outline-variant/50 bg-surface-low p-1 text-foreground/55 transition-colors hover:border-emerald-300/60 hover:text-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {actionLoading === job.id ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                          </button>
                        )}
                        {job.status === 'running' && (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handlePause(job.id);
                            }}
                            disabled={actionLoading === job.id}
                            title={t('jobs.pause')}
                            aria-label={t('jobs.pause')}
                            className="rounded p-1 text-foreground/55 transition-colors hover:bg-surface-high hover:text-amber-500"
                          >
                            {actionLoading === job.id ? <Loader2 size={13} className="animate-spin" /> : <Pause size={13} />}
                          </button>
                        )}
                        {job.status === 'paused' && (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleResume(job.id);
                            }}
                            disabled={actionLoading === job.id}
                            title={t('jobs.resume')}
                            aria-label={t('jobs.resume')}
                            className="rounded p-1 text-foreground/55 transition-colors hover:bg-surface-high hover:text-emerald-500"
                          >
                            {actionLoading === job.id ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                          </button>
                        )}
                        {(job.status === 'running' || job.status === 'queued' || job.status === 'paused') && (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleCancel(job.id);
                            }}
                            disabled={actionLoading === job.id}
                            title={t('jobs.cancel')}
                            aria-label={t('jobs.cancel')}
                            className="rounded p-1 text-foreground/55 transition-colors hover:bg-surface-high hover:text-red-500"
                          >
                            <Square size={13} />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleDelete(job.id);
                          }}
                          disabled={actionLoading === job.id}
                          title="删除任务并清除数据"
                          aria-label="删除任务并清除数据"
                          className="rounded border border-red-200/70 bg-red-50/60 p-1 text-red-700 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300"
                        >
                          {actionLoading === job.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                        </button>
                      </div>
                    </div>

                    {/* Progress bar for running jobs */}
                    {(job.status === 'running' || job.status === 'paused') && (
                      <div className="h-1.5 overflow-hidden rounded-full bg-surface-high">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${job.progress}%` }}
                          transition={{ duration: 0.5 }}
                          className={cn('h-full rounded-full', job.status === 'paused' ? 'bg-amber-400' : 'bg-primary')}
                        />
                      </div>
                    )}

                    {/* Error message */}
                    {job.error && (
                      <p className="rounded-md border border-red-200 bg-red-50 px-3 py-1.5 font-label text-[11px] text-red-700 dark:border-red-700/40 dark:bg-red-950/30 dark:text-red-300">
                        {job.error}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function mapRuntimeJob(job: WritingJob): Job {
  const status = mapRuntimeStatus(job.status as RuntimeJobStatus);
  const metadata = isRecord(job.metadata) ? job.metadata : {};
  return {
    id: job.job_id,
    name: formatJobName(job),
    type: job.kind,
    status,
    progress: readProgress(metadata, status),
    startedAt: formatJobTime(job.started_at ?? job.created_at),
    duration: formatDuration(job.started_at, job.completed_at),
    error: formatJobRuntimeError(job.error),
    stage: readVisibleString(metadata.progress_stage),
    message: readVisibleString(metadata.progress_message),
    route: readJobRoute(metadata),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readVisibleString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function readJobRoute(metadata: Record<string, unknown>): string | undefined {
  for (const key of ['route', 'target_route', 'targetRoute']) {
    const value = metadata[key];
    if (typeof value === 'string' && value.trim().startsWith('/')) {
      return value.trim();
    }
  }
  return undefined;
}

function readProgress(metadata: Record<string, unknown>, status: JobStatus): number {
  const raw = metadata.progress;
  const numeric = typeof raw === 'number' ? raw : Number(raw);
  if (Number.isFinite(numeric)) {
    return Math.max(0, Math.min(100, Math.round(numeric)));
  }
  return jobProgress(status);
}

function mapRuntimeStatus(status: RuntimeJobStatus): JobStatus {
  switch (status) {
    case 'completed':
      return 'completed';
    case 'failed':
    case 'approval_rejected':
      return 'failed';
    case 'cancelled':
      return 'cancelled';
    case 'paused':
      return 'paused';
    case 'started':
    case 'in_progress':
      return 'running';
    case 'created':
    case 'queued':
    case 'approval_pending':
    default:
      return 'queued';
  }
}

function jobProgress(status: JobStatus): number {
  if (status === 'completed') return 100;
  if (status === 'failed' || status === 'cancelled') return 100;
  if (status === 'paused') return 50;
  if (status === 'running') return 60;
  return 0;
}

function formatJobTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatDuration(start: string | null | undefined, end: string | null | undefined): string | undefined {
  if (!start || !end) return undefined;
  const started = new Date(start).getTime();
  const completed = new Date(end).getTime();
  if (!Number.isFinite(started) || !Number.isFinite(completed) || completed < started) {
    return undefined;
  }
  const seconds = Math.round((completed - started) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}
