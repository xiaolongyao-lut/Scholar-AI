import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useWriting } from '@/contexts/WritingContext';
import { useI18n } from '@/contexts/I18nContext';
import { cn } from '@/lib/utils';
import { getBudgetStatus, BudgetStatus } from '@/services/intelligentChatApi';

interface StatusBarProps {
  wordCount: number;
  isRunningAction: boolean;
  citationCount: number;
  onOpenExport?: () => void;
}

export function StatusBar({ wordCount, isRunningAction, citationCount, onOpenExport }: StatusBarProps) {
  const { t } = useI18n();
  const { outputMode, connectionState, sessionStatus, sessionMessage, activeJobTimeline } = useWriting();
  const [budget, setBudget] = useState<BudgetStatus | null>(null);

  useEffect(() => {
    const fetchBudget = async () => {
      try {
        const data = await getBudgetStatus();
        setBudget(data);
      } catch (e) {
        console.error('Failed to fetch budget', e);
      }
    };
    fetchBudget();
    const interval = setInterval(fetchBudget, 60000); // 1分钟更新一次
    return () => clearInterval(interval);
  }, []);

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
      : t('writing.status.persisted');

  return (
    <footer className="h-9 px-4 bg-surface-low border-t border-outline-variant flex items-center justify-between select-none z-40 relative">
        <div className="flex items-center gap-6">
          {/* Connection Status */}
          <div className="flex items-center gap-2 pr-4 border-r border-outline-variant/50">
            <div className={cn("w-1.5 h-1.5 rounded-full shadow-[0_0_8px_rgba(0,0,0,0.1)]", connectionBadge.dot)} />
            <span className="text-[10px] font-bold uppercase tracking-wider text-foreground/50 font-label">
              {connectionBadge.label}
            </span>
          </div>

          {/* Sync Message */}
          <div className="flex items-center gap-2">
            <span className={cn(
              "text-[11px] font-medium transition-colors",
              sessionStatus === 'error' ? "text-rose-500" : "text-foreground/70"
            )}>
              {liveMessage}
            </span>
            <span className="text-[10px] text-foreground/30 font-label italic">
              {persistenceLabel}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4">
           {/* Budget Info */}
           {budget && (
             <div className="flex items-center gap-2 px-3 py-1 rounded-sm bg-surface-high/40 border border-outline-variant/30 text-[10px] font-label">
               <span className="text-foreground/40 uppercase tracking-tighter">Cost Today</span>
               <span className="text-foreground/80 font-bold tabular-nums">¥{budget.cost_usd.toFixed(2)}</span>
             </div>
           )}

           <div className="flex items-center gap-2 bg-surface-high/40 px-3 py-1 rounded-sm font-label text-[11px] font-medium tabular-nums border border-outline-variant/30">
             <span className="text-foreground">{citationCount}</span>
             <span className="text-foreground/40 text-[9px] uppercase tracking-wider">
              {t('writing.status.citations')}
             </span>
           </div>

          <div className="flex items-center gap-2 bg-surface-high/40 px-3 py-1 rounded-sm font-label text-[11px] font-medium tabular-nums border border-outline-variant/30">
             <span className="text-foreground">{wordCount}</span>
             <span className="text-foreground/40 text-[9px] uppercase tracking-wider">
               {t('writing.words')}
             </span>
          </div>

          {onOpenExport && (
            <button
              onClick={onOpenExport}
              className="flex items-center gap-1.5 px-3 py-1 rounded-sm bg-primary/10 text-primary hover:bg-primary/20 transition-colors font-label text-[10px] font-bold uppercase tracking-wider shadow-sm border border-primary/20"
            >
              {t('ref.export_title')}
            </button>
          )}
        </div>
    </footer>
  );
}
