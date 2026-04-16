import React from 'react';
import { motion } from 'framer-motion';
import { 
  ChevronRight, 
  RefreshCw, 
  Sparkles, 
  Clock, 
  ArrowRight,
  Languages,
  Minimize2,
  Maximize2,
  GitBranch,
  UserCheck,
  FileText,
  Shield,
  Code
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useWriting } from '@/contexts/WritingContext';
import { WritingAction } from '@/types/writing';
import type { ContinuationContext } from '@/types/writing';
import { InspirationPanel } from './InspirationPanel';

interface AssistantDockProps {
  actions: WritingAction[];
  runningActionId: string | null;
  handleRunAction: (actionId: string) => void;
  rightTab: 'assistant' | 'history' | 'inspire';
  setRightTab: (tab: 'assistant' | 'history' | 'inspire') => void;
  onContinueFromSpark?: (context: ContinuationContext) => void;
}

const actionIconMap: Record<string, React.ReactNode> = {
  Languages: <Languages size={18} />, 
  RefreshCw: <RefreshCw size={18} />,
  Minimize2: <Minimize2 size={18} />, 
  Maximize2: <Maximize2 size={18} />,
  Sparkles: <Sparkles size={18} />, 
  GitBranch: <GitBranch size={18} />,
  UserCheck: <UserCheck size={18} />, 
  FileText: <FileText size={18} />,
  Shield: <Shield size={18} />, 
  Code: <Code size={18} />,
};

export function AssistantDock({
  actions,
  runningActionId,
  handleRunAction,
  rightTab,
  setRightTab,
  onContinueFromSpark,
}: AssistantDockProps) {
  const { t } = useI18n();
  const { zenMode, activeJobTimeline } = useWriting();

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

  const formatEventTime = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return timestamp;
    }
  };

  const describeEventData = (data: Record<string, unknown> | undefined) => {
    if (!data) {
      return t('writing.event.no_data');
    }

    const preferredKeys = ['message', 'detail', 'error', 'output_text', 'text', 'reason'];
    for (const key of preferredKeys) {
      const value = data[key];
      if (typeof value === 'string' && value.trim()) {
        return value;
      }
    }

    const entries = Object.entries(data).filter(([, value]) => value !== undefined && value !== null);
    if (entries.length === 0) {
      return t('writing.event.no_data');
    }

    return entries
      .slice(0, 2)
      .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
      .join(' · ');
  };

  const timelineEvents = activeJobTimeline?.events ?? [];
  const latestTimelineEvent = timelineEvents[timelineEvents.length - 1] ?? null;

  return (
    <motion.div 
      animate={{ 
        opacity: zenMode ? 0.1 : 1,
        pointerEvents: zenMode ? 'none' : 'auto'
      }}
      className="w-80 border-l border-outline-variant bg-surface-lowest flex flex-col relative transition-opacity duration-500"
    >
      {/* M3 Segmented Control */}
      <div className="flex border-b border-outline-variant bg-surface-low p-1 m-4 rounded-sm">
         <button 
           onClick={() => setRightTab('inspire')} 
           aria-label={t('writing.tabs.inspire_aria')}
           className={cn(
             "flex-1 py-2 font-label text-[10px] font-medium uppercase tracking-wider rounded-sm transition-all", 
             rightTab === 'inspire' ? "bg-surface-lowest text-primary shadow-sm" : "text-foreground/50 hover:bg-surface-lowest/50"
           )}
         >
            {t('writing.tabs.inspire')}
         </button>
         <button 
           onClick={() => setRightTab('assistant')} 
           aria-label={t('writing.actions.processing_actions')}
           className={cn(
             "flex-1 py-2 font-label text-[10px] font-medium uppercase tracking-wider rounded-sm transition-all", 
             rightTab === 'assistant' ? "bg-surface-lowest text-primary shadow-sm" : "text-foreground/50 hover:bg-surface-lowest/50"
           )}
         >
            {t('writing.actions.processing_actions')}
         </button>
         <button 
           onClick={() => setRightTab('history')} 
           aria-label={t('writing.actions.revision_history')}
           className={cn(
             "flex-1 py-2 font-label text-[10px] font-medium uppercase tracking-wider rounded-sm transition-all", 
             rightTab === 'history' ? "bg-surface-lowest text-primary shadow-sm" : "text-foreground/50 hover:bg-surface-lowest/50"
           )}
         >
            {t('writing.actions.revision_history')}
         </button>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar px-5 pb-10 space-y-6">
        {rightTab === 'inspire' ? (
          <InspirationPanel
            onContinueWrite={onContinueFromSpark || (() => {})}
          />
        ) : rightTab === 'assistant' ? (
          <div className="space-y-8">
            {['translate', 'rewrite', 'check'].map(cat => (
              <div key={cat} className="space-y-3">
                <h4 className="font-label text-[10px] font-medium uppercase tracking-wider text-foreground/40 px-2">
                  {t('writing.' + cat)}
                </h4>
                <div className="grid gap-2">
                   {actions.filter(a => a.category === cat).map(action => (
                     <button
                       key={action.id}
                       onClick={() => handleRunAction(action.id)}
                       disabled={runningActionId !== null}
                       aria-label={action.nameZh}
                       className={cn(
                         "group w-full p-4 rounded-sm text-left transition-all border border-transparent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:cursor-not-allowed",
                         runningActionId === action.id 
                          ? "bg-primary/5 border-primary/20 shadow-inner" 
                          : "bg-surface-low hover:bg-surface-lowest hover:border-primary/20 hover:shadow-md active:scale-[0.98]"
                       )}
                     >
                       <div className="flex items-center gap-4">
                         <div className={cn(
                           "p-2 rounded-sm transition-all", 
                           runningActionId === action.id ? "bg-primary text-primary-foreground animate-pulse" : "bg-surface-lowest text-primary"
                         )}>
                           {runningActionId === action.id ? <RefreshCw size={18} className="animate-spin" /> : actionIconMap[action.icon] || <Sparkles size={18} />}
                         </div>
                         <div className="flex-1 min-w-0">
                           <p className="text-[11px] font-bold tracking-tight">{action.nameZh}</p>
                         </div>
                         <ChevronRight size={14} className="text-foreground/20 group-hover:text-primary transition-colors" />
                       </div>
                     </button>
                   ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-sm border border-outline-variant bg-surface-low p-4 shadow-sm">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-1.5 h-1.5 rounded-full bg-primary" />
                <span className="text-[10px] font-label font-medium uppercase text-foreground/50">
                  {activeJobTimeline ? 'Runtime Timeline' : 'History'}
                </span>
              </div>
              <p className="text-[11px] text-foreground line-clamp-2">
                {activeJobTimeline
                  ? `Job ${activeJobTimeline.jobId} · ${activeJobTimeline.status || 'pending'}`
                  : '启动动作后，这里会显示 job_created、job_started、job_completed 等真实事件。'}
              </p>
              <div className="mt-3 flex items-center justify-between text-[8px] font-medium text-foreground/40 uppercase tracking-wider">
                <span className="flex items-center gap-1">
                  <Clock size={10} />
                  {latestTimelineEvent ? formatEventTime(latestTimelineEvent.timestamp) : '等待事件'}
                </span>
                <span className="text-primary transition-colors flex items-center gap-1">
                  {activeJobTimeline?.errorMessage ? '查看失败详情' : '实时事件流'}
                  <ArrowRight size={8} />
                </span>
              </div>
            </div>

            {timelineEvents.length > 0 ? (
              timelineEvents.map((event, index) => (
                <div
                  key={event.event_id}
                  className={cn(
                    "p-4 rounded-sm border transition-all cursor-pointer group",
                    index === timelineEvents.length - 1
                      ? "bg-primary/5 border-primary/20 shadow-sm"
                      : "bg-surface-lowest border-outline-variant/50 hover:border-primary/20"
                  )}
                >
                  <div className="flex items-center gap-3 mb-2">
                    <div className={cn(
                      "w-1.5 h-1.5 rounded-full",
                      index === timelineEvents.length - 1 ? 'bg-primary animate-pulse' : 'bg-foreground/30'
                    )} />
                    <span className="font-label text-[10px] font-medium uppercase text-foreground/50">
                      {eventTypeLabels[event.event_type] || event.event_type}
                    </span>
                  </div>
                  <p className="text-[11px] text-foreground line-clamp-2">
                    {describeEventData(event.data as Record<string, unknown>)}
                  </p>
                  <div className="mt-3 flex items-center justify-between text-[8px] font-medium text-foreground/40 uppercase tracking-wider">
                    <span className="flex items-center gap-1">
                      <Clock size={10} /> {formatEventTime(event.timestamp)}
                    </span>
                    <span className="group-hover:text-primary transition-colors flex items-center gap-1">
                      {event.event_id.slice(-6)}
                      <ArrowRight size={8} />
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-sm border border-dashed border-outline-variant bg-surface-low p-4 text-[11px] text-foreground/50 leading-6">
                暂无事件。启动动作后，这里会实时刷新并显示最新 job 事件与终态。
              </div>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}
