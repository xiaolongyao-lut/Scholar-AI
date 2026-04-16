import React, { useState, useEffect, useCallback } from 'react';
import { Activity, CheckCircle2, Clock, Loader2, XCircle, RefreshCw, Trash2, ChevronDown, Pause, Play, Square } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { EmptyState } from '@/components/common/EmptyState';
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
  running: { icon: Loader2, color: 'text-blue-600', bg: 'bg-blue-50', textKey: 'jobs.status_running' },
  completed: { icon: CheckCircle2, color: 'text-emerald-600', bg: 'bg-emerald-50', textKey: 'jobs.status_completed' },
  failed: { icon: XCircle, color: 'text-red-600', bg: 'bg-red-50', textKey: 'jobs.status_failed' },
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
    <div className="p-8 max-w-4xl mx-auto">
      <div className="flex justify-between items-start mb-8">
        <div>
          <h1 className="font-display text-2xl font-semibold text-foreground flex items-center gap-2.5">
            <Activity size={24} className="text-primary" />
            {t('jobs.title')}
          </h1>
          <p className="font-label text-sm text-foreground/50 mt-1">
            {t('jobs.subtitle', { running: runningCount, total: jobs.length })}
          </p>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 p-1 bg-surface-high rounded-lg border border-outline-variant/30 mb-6 w-fit">
        {[
          { key: '', label: t('jobs.filter_all') },
          { key: 'running', label: t('jobs.filter_running') },
          { key: 'completed', label: t('jobs.filter_completed') },
          { key: 'failed', label: t('jobs.filter_failed') },
        ].map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key as JobStatus | '')}
            className={cn(
              'px-3 py-1.5 text-xs font-label font-medium rounded transition-all',
              filter === f.key ? 'bg-primary text-primary-foreground shadow-sm' : 'text-foreground/40 hover:text-foreground'
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
        <div className="space-y-3">
          {filtered.map((job, i) => {
            const cfg = statusConfig[job.status];
            return (
              <motion.div
                key={job.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
                className="glass-card rounded-lg p-4 group hover:border-primary/20 transition-all"
              >
                <div className="flex items-center gap-3">
                  <div className={cn('h-9 w-9 rounded-lg flex items-center justify-center flex-shrink-0', cfg.bg)}>
                    <cfg.icon size={16} className={cn(cfg.color, job.status === 'running' && 'animate-spin')} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h4 className="font-label text-sm font-medium text-foreground truncate">{job.name}</h4>
                    <div className="flex items-center gap-3 mt-0.5 font-label text-[10px] text-foreground/30">
                      <span>{t('jobs.started_at')} {job.startedAt}</span>
                      {job.duration && <span>{t('jobs.duration')} {job.duration}</span>}
                    </div>
                  </div>
                  <span className={cn('px-2 py-0.5 text-[9px] font-label font-medium rounded', cfg.bg, cfg.color)}>
                    {t(cfg.textKey)}
                  </span>
                  {job.status === 'failed' && (
                    <button
                      onClick={() => handleRetry(job.id)}
                      disabled={actionLoading === job.id}
                      className="p-1.5 text-foreground/20 hover:text-primary transition-colors opacity-0 group-hover:opacity-100"
                      title={t('jobs.retry')}
                    >
                      {actionLoading === job.id ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                    </button>
                  )}
                  {job.status === 'running' && (
                    <button
                      onClick={() => handlePause(job.id)}
                      disabled={actionLoading === job.id}
                      className="p-1.5 text-foreground/20 hover:text-amber-500 transition-colors opacity-0 group-hover:opacity-100"
                      title={t('jobs.pause')}
                    >
                      {actionLoading === job.id ? <Loader2 size={14} className="animate-spin" /> : <Pause size={14} />}
                    </button>
                  )}
                  {job.status === 'queued' && (
                    <button
                      onClick={() => handleResume(job.id)}
                      disabled={actionLoading === job.id}
                      className="p-1.5 text-foreground/20 hover:text-emerald-500 transition-colors opacity-0 group-hover:opacity-100"
                      title={t('jobs.resume')}
                    >
                      {actionLoading === job.id ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    </button>
                  )}
                  {(job.status === 'running' || job.status === 'queued') && (
                    <button
                      onClick={() => handleCancel(job.id)}
                      disabled={actionLoading === job.id}
                      className="p-1.5 text-foreground/20 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                      title={t('jobs.cancel')}
                    >
                      <Square size={14} />
                    </button>
                  )}
                </div>

                {/* Progress bar for running jobs */}
                {job.status === 'running' && (
                  <div className="mt-3 h-1.5 bg-surface-high rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${job.progress}%` }}
                      transition={{ duration: 0.5 }}
                      className="h-full bg-primary rounded-full"
                    />
                  </div>
                )}

                {/* Error message */}
                {job.error && (
                  <p className="mt-2 px-3 py-2 bg-red-50 text-red-600 text-[11px] font-label rounded">
                    {job.error}
                  </p>
                )}
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
