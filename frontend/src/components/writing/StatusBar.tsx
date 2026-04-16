import React from 'react';
import { motion } from 'framer-motion';
import { useWriting } from '@/contexts/WritingContext';
import { useI18n } from '@/contexts/I18nContext';
import { cn } from '@/lib/utils';

interface StatusBarProps {
  wordCount: number;
  isRunningAction: boolean;
  citationCount: number;
}

export function StatusBar({ wordCount, isRunningAction, citationCount }: StatusBarProps) {
  const { t } = useI18n();
  const { outputMode, connectionState, sessionStatus, sessionMessage, activeJobTimeline } = useWriting();

  const eventTypeLabels: Record<string, string> = {
    job_created: t('writing.event.job_created'),
    job_started: t('writing.event.job_started'),
    job_progress: t('writing.event.job_progress'),
    tool_requested: t('writing.event.tool_requested'),
    tool_blocked: t('writing.event.tool_blocked'),
    approval_required: t('writing.event.approval_required'),
    approval_granted: t('writing.event.approval_granted'),
    approval_rejected: t('writing.event.approval_rejected'),
    artifact_created: t('writing.event.artifact_created'),
    artifact_updated: t('writing.event.artifact_updated'),
    job_paused: t('writing.event.job_paused'),
    job_resumed: t('writing.event.job_resumed'),
    job_completed: t('writing.event.job_completed'),
    job_failed: t('writing.event.job_failed'),
    job_cancelled: t('writing.event.job_cancelled'),
  };

  const timelineEvents = activeJobTimeline?.events ?? [];
  const latestTimelineEvent = timelineEvents[timelineEvents.length - 1] ?? null;
  const latestTimelineMessage = latestTimelineEvent
    ? t('writing.status.latest_event', { label: eventTypeLabels[latestTimelineEvent.event_type] || latestTimelineEvent.event_type })
    : null;

  const connectionBadge = {
    online: { label: t('writing.canvas.online'), dot: 'bg-emerald-500' },
    degraded: { label: t('writing.canvas.degraded'), dot: 'bg-amber-500' },
    offline: { label: t('writing.canvas.offline'), dot: 'bg-rose-500' },
  }[connectionState];

  const liveMessage = sessionStatus === 'saving'
    ? t('writing.status.saving_draft')
    : sessionStatus === 'error'
      ? sessionMessage || t('writing.status.save_failed')
      : isRunningAction
        ? latestTimelineMessage || t('writing.status.tracking_events')
        : sessionMessage
          || (latestTimelineMessage && activeJobTimeline?.status
            ? `${latestTimelineMessage} · ${activeJobTimeline.status}`
            : connectionState === 'offline'
              ? t('writing.status.offline_mode')
              : connectionState === 'degraded'
                ? t('writing.status.degraded_mode')
                : t('writing.status.sync_ready'));
  const persistenceLabel = sessionStatus === 'error'
    ? (connectionState === 'offline' ? t('writing.status.waiting_network') : t('writing.status.waiting_retry'))
    : sessionStatus === 'saving'
      ? t('writing.status.syncing')
      : isRunningAction
        ? t('writing.status.event_tracking')
        : connectionState === 'offline'
          ? t('writing.status.local_only')
          : connectionState === 'degraded'
            ? t('writing.status.local_fallback')
            : t('writing.real_time_saved');

  return (
    <footer className="h-10 border-t border-outline-variant bg-surface-lowest px-8 flex items-center justify-between z-20">
       <div className="flex items-center gap-6 font-label text-[10px] font-medium text-foreground/50 uppercase tracking-wider">
          <div className="flex items-center gap-2">
             <span className={cn("w-1.5 h-1.5 rounded-full", connectionBadge.dot, connectionState === 'online' && 'animate-pulse')} />
             {connectionBadge.label}
          </div>
          <div className="h-4 w-px bg-outline-variant mx-2" />
          <div className="flex items-center gap-2">
             Mode: <span className="text-primary">{outputMode.toUpperCase()}</span>
          </div>
       </div>
       <div className="flex items-center gap-10">
          <div className="flex items-center gap-6 font-label text-[9px] font-medium text-foreground/30">
             <motion.span 
               animate={sessionStatus === 'saving' || isRunningAction ? { opacity: [0.35, 1, 0.35] } : { opacity: 1 }} 
               transition={{ repeat: sessionStatus === 'saving' || isRunningAction ? Infinity : 0, duration: 2 }} 
               role="status"
               aria-live="polite"
               aria-atomic="true"
               className={cn(
                 "tracking-tight",
                 sessionStatus === 'error' ? 'text-destructive' : 'text-primary'
               )}
             >
               {liveMessage}
             </motion.span>
             <span>{persistenceLabel}</span>
          </div>
           <div className="flex items-center gap-2 bg-surface-low px-3 py-1 rounded-sm font-label text-[11px] font-medium tabular-nums">
             <span className="text-foreground">{citationCount}</span>
             <span className="text-foreground/40 text-[9px] uppercase tracking-wider">
              {t('writing.status.citations')}
             </span>
           </div>
          <div className="flex items-center gap-2 bg-surface-low px-3 py-1 rounded-sm font-label text-[11px] font-medium tabular-nums">
             <span className="text-foreground">{wordCount}</span>
             <span className="text-foreground/40 text-[9px] uppercase tracking-wider">
               {t('writing.words')}
             </span>
          </div>
       </div>
    </footer>
  );
}
