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
  Code,
  Square,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { useWriting } from '@/contexts/WritingContext';
import { WritingAction } from '@/types/writing';
import type { ContinuationContext } from '@/types/writing';
import { InspirationPanel } from './InspirationPanel';
import {
  describeRuntimeEventData,
  formatRuntimeEventLabel,
  formatRuntimeJobStatus,
} from './writingRuntimeDisplay';

interface AssistantDockProps {
  actions: WritingAction[];
  runningActionId: string | null;
  handleRunAction: (actionId: string) => void;
  handleStopAction?: () => void;
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
  handleStopAction,
  rightTab,
  setRightTab,
  onContinueFromSpark,
}: AssistantDockProps) {
  const { t } = useI18n();
  const { zenMode, activeJobTimeline } = useWriting();

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
                   {actions.filter(a => a.category === cat).map(action => {
                     const runningThisAction = runningActionId === action.id;
                     return (
                       <button
                         key={action.id}
                         onClick={() => runningThisAction && handleStopAction ? handleStopAction() : handleRunAction(action.id)}
                         disabled={runningActionId !== null && !runningThisAction}
                         aria-label={runningThisAction ? '停止当前动作' : action.nameZh}
                         className={cn(
                           "group w-full p-4 rounded-sm text-left transition-all border border-transparent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:cursor-not-allowed",
                           runningThisAction
                            ? "bg-red-50 border-red-200 text-red-700 shadow-inner dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300"
                            : "bg-surface-low hover:bg-surface-lowest hover:border-primary/20 hover:shadow-md active:scale-[0.98]"
                         )}
                       >
                         <div className="flex items-center gap-4">
                           <div className={cn(
                             "p-2 rounded-sm transition-all",
                             runningThisAction ? "bg-red-600 text-white" : "bg-surface-lowest text-primary"
                           )}>
                             {runningThisAction ? <Square size={18} /> : actionIconMap[action.icon] || <Sparkles size={18} />}
                           </div>
                           <div className="flex-1 min-w-0">
                             <p className="text-[11px] font-bold tracking-tight">{runningThisAction ? '停止当前动作' : action.nameZh}</p>
                           </div>
                           <ChevronRight size={14} className="text-foreground/20 group-hover:text-primary transition-colors" />
                         </div>
                       </button>
                     );
                   })}
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
                  {activeJobTimeline ? '运行记录' : '历史记录'}
                </span>
              </div>
              <p className="text-[11px] text-foreground line-clamp-2">
                {activeJobTimeline
                  ? `当前动作 · ${formatRuntimeJobStatus(activeJobTimeline.status, t)}`
                  : '等待动作事件。'}
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
                      {formatRuntimeEventLabel(event.event_type, t)}
                    </span>
                  </div>
                  <p className="text-[11px] text-foreground line-clamp-2">
                    {describeRuntimeEventData(event.data as Record<string, unknown>, t('writing.event.no_data'))}
                  </p>
                  <div className="mt-3 flex items-center justify-between text-[8px] font-medium text-foreground/40 uppercase tracking-wider">
                    <span className="flex items-center gap-1">
                      <Clock size={10} /> {formatEventTime(event.timestamp)}
                    </span>
                    <span className="group-hover:text-primary transition-colors flex items-center gap-1">
                      详情
                      <ArrowRight size={8} />
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-sm border border-dashed border-outline-variant bg-surface-low p-4 text-[11px] text-foreground/50 leading-6">
                暂无事件。
              </div>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}
