import React, { useState, useEffect, useCallback } from 'react';
import { Activity, CheckCircle2, Clock, Loader2, XCircle, RefreshCw, Trash2, ChevronDown, Pause, Play, Square } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { EmptyState } from '@/components/common/EmptyState';
import { PageHeader } from '@/components/common/PageHeader';
import { StatusPill, type StatusTone } from '@/components/common/StatusPill';
import { getWritingRuntimeClient } from '@/services/runtimeClient';

type JobStatus = 'running' | 'completed' | 'failed' | 'queued';

interface Job {
  id: string;
  name: string;
  type: string;
  status: JobStatus;
  progress: number;
  startedAt: string;
  duration?: string;
  error?: string;
}

const MOCK_JOBS_PLACEHOLDER: Job[] = [];

const statusConfig: Record<JobStatus, { icon: React.ElementType; color: string; bg: string; textKey: string }> = {
  running: { icon: Loader2, color: 'text-blue-600 dark:text-blue-300', bg: 'bg-blue-50 dark:bg-blue-500/15', textKey: 'jobs.status_running' },
  completed: { icon: CheckCircle2, color: 'text-emerald-600 dark:text-emerald-300', bg: 'bg-emerald-50 dark:bg-emerald-500/15', textKey: 'jobs.status_completed' },
  failed: { icon: XCircle, color: 'text-red-600 dark:text-red-300', bg: 'bg-red-50 dark:bg-red-500/15', textKey: 'jobs.status_failed' },
  queued: { icon: Clock, color: 'text-foreground/40', bg: 'bg-surface-high', textKey: 'jobs.status_queued' },
};

export function Jobs() {
  const { t } = useI18n();
  const [filter, setFilter] = useState<JobStatus | ''>('');
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const [jobs, setJobs] = useState<Job[]>([]);

  const loadJobs = useCallback(async () => {
    // No list-all-jobs endpoint exists; individual job status must be polled by ID.
    // Keep mock data as baseline; real jobs are managed via DraftStudio.
  }, []);

  useEffect(() => { loadJobs(); }, [loadJobs]);

  const handlePause = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const client = getWritingRuntimeClient();
      await client.pauseJob(jobId);
      setJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'queued' as JobStatus } : j));
    } catch { /* silent */ }
    setActionLoading(null);
  };

  const handleResume = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const client = getWritingRuntimeClient();
      await client.resumeJob(jobId);
      setJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'running' as JobStatus } : j));
    } catch { /* silent */ }
    setActionLoading(null);
  };

  const handleCancel = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const client = getWritingRuntimeClient();
      await client.cancelJob(jobId);
      setJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'failed' as JobStatus, error: '已取消' } : j));
    } catch { /* silent */ }
    setActionLoading(null);
  };

  const handleRetry = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const client = getWritingRuntimeClient();
      await client.startJob(jobId);
      setJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'running' as JobStatus, error: undefined, progress: 0 } : j));
    } catch { /* silent */ }
    setActionLoading(null);
  };

  const filtered = filter ? jobs.filter(j => j.status === filter) : jobs;
  const runningCount = jobs.filter(j => j.status === 'running').length;

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="shrink-0 border-b border-outline-variant/60 bg-surface-low px-6 py-4">
        <PageHeader
          icon={<Activity size={18} />}
          title={t('jobs.title')}
          subtitle={t('jobs.subtitle', { running: runningCount, total: jobs.length })}
          className="mb-0"
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

        {/* Job list */}
        {filtered.length === 0 ? (
          <EmptyState
            title={t('jobs.empty_title')}
            description={t('jobs.empty_description')}
            icon={<Activity size={40} />}
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
                  : 'neutral';
                return (
                  <li key={job.id} className="group flex flex-col gap-2 px-4 py-3 transition-colors hover:bg-surface-default/40">
                    <div className="flex items-center gap-3">
                      <div className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-md', cfg.bg)}>
                        <cfg.icon size={14} className={cn(cfg.color, job.status === 'running' && 'animate-spin')} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h4 className="truncate font-label text-sm font-medium text-foreground">{job.name}</h4>
                        <div className="mt-0.5 flex flex-wrap items-center gap-2 font-label text-[10px] text-foreground/45">
                          <span>{t('jobs.started_at')} {job.startedAt}</span>
                          {job.duration && <span>{t('jobs.duration')} {job.duration}</span>}
                        </div>
                      </div>
                      <StatusPill tone={tone}>{t(cfg.textKey)}</StatusPill>
                      <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                        {job.status === 'failed' && (
                          <button
                            type="button"
                            onClick={() => handleRetry(job.id)}
                            disabled={actionLoading === job.id}
                            title={t('jobs.retry')}
                            aria-label={t('jobs.retry')}
                            className="rounded p-1 text-foreground/55 transition-colors hover:bg-surface-high hover:text-primary"
                          >
                            {actionLoading === job.id ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                          </button>
                        )}
                        {job.status === 'running' && (
                          <button
                            type="button"
                            onClick={() => handlePause(job.id)}
                            disabled={actionLoading === job.id}
                            title={t('jobs.pause')}
                            aria-label={t('jobs.pause')}
                            className="rounded p-1 text-foreground/55 transition-colors hover:bg-surface-high hover:text-amber-500"
                          >
                            {actionLoading === job.id ? <Loader2 size={13} className="animate-spin" /> : <Pause size={13} />}
                          </button>
                        )}
                        {job.status === 'queued' && (
                          <button
                            type="button"
                            onClick={() => handleResume(job.id)}
                            disabled={actionLoading === job.id}
                            title={t('jobs.resume')}
                            aria-label={t('jobs.resume')}
                            className="rounded p-1 text-foreground/55 transition-colors hover:bg-surface-high hover:text-emerald-500"
                          >
                            {actionLoading === job.id ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                          </button>
                        )}
                        {(job.status === 'running' || job.status === 'queued') && (
                          <button
                            type="button"
                            onClick={() => handleCancel(job.id)}
                            disabled={actionLoading === job.id}
                            title={t('jobs.cancel')}
                            aria-label={t('jobs.cancel')}
                            className="rounded p-1 text-foreground/55 transition-colors hover:bg-surface-high hover:text-red-500"
                          >
                            <Square size={13} />
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Progress bar for running jobs */}
                    {job.status === 'running' && (
                      <div className="h-1.5 overflow-hidden rounded-full bg-surface-high">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${job.progress}%` }}
                          transition={{ duration: 0.5 }}
                          className="h-full rounded-full bg-primary"
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
