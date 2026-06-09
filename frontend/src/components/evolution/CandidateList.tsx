// CandidateList — three-state list (loading / error / empty / data).
//
// Pure presentational: receives data + state + per-row callbacks. The
// page (EvolutionInbox) owns refetch, undo, and the in-flight action map.
// State precedence:
//   1. error → error banner (with optional retry)
//   2. isLoading && items.length === 0 → loading skeleton
//   3. items.length === 0 → empty state
//   4. items.length > 0 → card stream

import { AlertCircle, RefreshCw } from 'lucide-react';

import { cn } from '@/lib/utils';
import { EmptyState } from '../common/EmptyState';
import { CandidateCard, type CardPendingAction } from './CandidateCard';
import type { ExperienceCandidate } from '../../services/evolutionTypes';
import { formatEvolutionError } from './labels';

export interface CandidateListProps {
  items: ExperienceCandidate[];
  isLoading: boolean;
  error: string | null;
  /** Per-candidate in-flight action; keyed by candidate_id. */
  pendingActions?: Record<string, CardPendingAction>;
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  onSnooze: (id: string) => void;
  onOpenDetails: (id: string) => void;
  onRetry?: () => void;
  /** Optional per-card action slot. Page-side hook for S5.6's
   *  PromoteButton (accepted candidates) and rollback (promoted candidates). */
  renderExtraActions?: (candidate: ExperienceCandidate) => React.ReactNode;
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3" aria-live="polite" aria-busy="true">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className={cn(
            'h-32 animate-pulse rounded-lg border border-outline-variant/40 bg-surface-low',
          )}
        />
      ))}
    </div>
  );
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const visibleMessage = formatEvolutionError(message, '读取失败，请稍后重试。');
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-lg border border-red-300/60 bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300 dark:border-red-800/50 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-2">
        <AlertCircle size={16} className="mt-0.5 shrink-0" />
        <span>{visibleMessage} 点击右上角刷新重试。</span>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-red-300/60 bg-white/50 px-2.5 py-1 text-xs font-label text-red-700 transition-colors hover:bg-white dark:bg-red-950/30 dark:text-red-300"
        >
          <RefreshCw size={12} />
          重新加载
        </button>
      )}
    </div>
  );
}

export function CandidateList({
  items,
  isLoading,
  error,
  pendingActions,
  onAccept,
  onReject,
  onSnooze,
  onOpenDetails,
  onRetry,
  renderExtraActions,
}: CandidateListProps) {
  if (error) {
    return <ErrorBanner message={error} onRetry={onRetry} />;
  }
  if (isLoading && items.length === 0) {
    return <LoadingSkeleton />;
  }
  if (items.length === 0) {
    return (
      <EmptyState
        title="还没有可保存的经验"
        description="先在设置的功能开关中开启经验候选收纳和复审入口；之后完成智能研读、讨论、写作任务、Skill 或 MCP 工具运行，这里才会出现待复审经验。"
      />
    );
  }
  return (
    <div className="space-y-3">
      {items.map((candidate) => (
        <CandidateCard
          key={candidate.candidate_id}
          candidate={candidate}
          pendingAction={pendingActions?.[candidate.candidate_id] ?? null}
          onAccept={() => onAccept(candidate.candidate_id)}
          onReject={() => onReject(candidate.candidate_id)}
          onSnooze={() => onSnooze(candidate.candidate_id)}
          onOpenDetails={() => onOpenDetails(candidate.candidate_id)}
          extraActions={renderExtraActions?.(candidate)}
        />
      ))}
    </div>
  );
}
