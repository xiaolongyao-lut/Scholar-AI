import React from 'react';
import { useWriting } from '@/contexts/WritingContext';
import { useI18n } from '@/contexts/I18nContext';
import { cn } from '@/lib/utils';
import {
  formatRuntimeEventLabel,
  formatRuntimeJobStatus,
  sanitizeRuntimeVisibleText,
} from './writingRuntimeDisplay';

interface StatusBarProps {
  wordCount: number;
  isRunningAction: boolean;
  citationCount: number;
  onOpenExport?: () => void;
}

export function StatusBar({ wordCount, isRunningAction, citationCount, onOpenExport }: StatusBarProps) {
  const { t } = useI18n();
  const { connectionState, sessionStatus, sessionMessage, activeJobTimeline } = useWriting();

  const timelineEvents = activeJobTimeline?.events ?? [];
  const latestTimelineEvent = timelineEvents[timelineEvents.length - 1] ?? null;
  const latestTimelineMessage = latestTimelineEvent
    ? t('writing.status.latest_event', { label: formatRuntimeEventLabel(latestTimelineEvent.event_type, t) })
    : null;
  const visibleSessionMessage = sanitizeRuntimeVisibleText(
    sessionMessage,
    sessionStatus === 'error' ? t('writing.status.save_failed') : '',
  );

  const connectionBadge = {
    online: { label: t('writing.canvas.online'), dot: 'bg-emerald-500 dark:bg-emerald-400' },
    degraded: { label: t('writing.canvas.degraded'), dot: 'bg-amber-500 dark:bg-amber-400' },
    offline: { label: t('writing.canvas.offline'), dot: 'bg-rose-500 dark:bg-rose-400' },
  }[connectionState];

  const liveMessage = sessionStatus === 'saving'
    ? t('writing.status.saving_draft')
    : sessionStatus === 'error'
      ? visibleSessionMessage || t('writing.status.save_failed')
      : isRunningAction
        ? latestTimelineMessage || t('writing.status.tracking_events')
        : visibleSessionMessage
          || (latestTimelineMessage && activeJobTimeline?.status
            ? `${latestTimelineMessage} · ${formatRuntimeJobStatus(activeJobTimeline.status, t)}`
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
