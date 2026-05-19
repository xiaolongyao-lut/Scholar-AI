// EvolutionInbox — `/evolution` page assembly.
//
// Composes:
//   useEvolutionStatus (kill-switch reads)
//   listCandidates fetch on mount + filter/page change
//   accept / reject / snooze wired through evolutionApi
//   page-local undo banner (NOT the global ToastProvider, per S5 audit)
//     → 10-second window, click 撤销 to call rollbackCandidate
//
// State precedence inside the page:
//   - filter change → resets offset to 0
//   - any transition → marks the candidate pendingAction, refetches on success
//   - undo banner auto-dismisses after 10s and on next list refresh

import { useCallback, useEffect, useState } from 'react';
import { BookOpenCheck, RefreshCw, RotateCcw, X as XIcon } from 'lucide-react';

import { cn } from '@/lib/utils';
import { PageHeader } from '../components/common/PageHeader';
import { AuditPanel } from '../components/evolution/AuditPanel';
import { CandidateDetailDrawer } from '../components/evolution/CandidateDetailDrawer';
import { CandidateList } from '../components/evolution/CandidateList';
import { type CardPendingAction } from '../components/evolution/CandidateCard';
import {
  Filters,
  type MemoryTypeFilter,
  type StatusFilter,
} from '../components/evolution/Filters';
import { PaginationBar } from '../components/evolution/PaginationBar';
import { PromoteButton } from '../components/evolution/PromoteButton';
import { useEvolutionStatus } from '../hooks/useEvolutionStatus';
import {
  acceptCandidate,
  listCandidates,
  promoteCandidate,
  rejectCandidate,
  rollbackCandidate,
  snoozeCandidate,
} from '../services/evolutionApi';
import type {
  CandidateListPayload,
  ExperienceCandidate,
} from '../services/evolutionTypes';

const PAGE_LIMIT = 20;
const UNDO_WINDOW_MS = 10_000;

interface UndoBannerState {
  candidateId: string;
  candidateTitle: string;
}

export default function EvolutionInbox() {
  const { status: killStatus, error: killError } = useEvolutionStatus();

  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending');
  const [memoryTypeFilter, setMemoryTypeFilter] = useState<MemoryTypeFilter>('all');
  const [offset, setOffset] = useState(0);

  const [data, setData] = useState<CandidateListPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [pendingActions, setPendingActions] = useState<Record<string, CardPendingAction>>({});
  /** candidate_ids currently mid-promote or mid-rollback (separate from
   *  primary pendingActions so the typing stays tight). */
  const [extraPending, setExtraPending] = useState<Set<string>>(new Set());
  const [undoBanner, setUndoBanner] = useState<UndoBannerState | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<ExperienceCandidate | null>(null);

  const fetchList = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await listCandidates({
        status: statusFilter === 'all' ? undefined : statusFilter,
        memoryType: memoryTypeFilter === 'all' ? undefined : memoryTypeFilter,
        limit: PAGE_LIMIT,
        offset,
      });
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter, memoryTypeFilter, offset]);

  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  // Auto-dismiss the undo banner after the window expires.
  useEffect(() => {
    if (!undoBanner) return undefined;
    const id = window.setTimeout(() => setUndoBanner(null), UNDO_WINDOW_MS);
    return () => window.clearTimeout(id);
  }, [undoBanner]);

  const setPending = (id: string, action: CardPendingAction) => {
    setPendingActions((current) => {
      if (action === null) {
        const next = { ...current };
        delete next[id];
        return next;
      }
      return { ...current, [id]: action };
    });
  };

  const handleAccept = async (id: string) => {
    const candidate = data?.items.find((c) => c.candidate_id === id) ?? null;
    setPending(id, 'accept');
    try {
      await acceptCandidate(id);
      if (candidate) {
        setUndoBanner({ candidateId: id, candidateTitle: candidate.title });
      }
      await fetchList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(id, null);
    }
  };

  const handleReject = async (id: string) => {
    setPending(id, 'reject');
    try {
      await rejectCandidate(id);
      await fetchList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(id, null);
    }
  };

  const handleSnooze = async (id: string) => {
    setPending(id, 'snooze');
    try {
      await snoozeCandidate(id);
      await fetchList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(id, null);
    }
  };

  const handleOpenDetails = (id: string) => {
    const candidate = data?.items.find((c) => c.candidate_id === id) ?? null;
    setSelectedDetail(candidate);
  };

  const handleStatusChange = (next: StatusFilter) => {
    setStatusFilter(next);
    setOffset(0);
  };

  const handleMemoryTypeChange = (next: MemoryTypeFilter) => {
    setMemoryTypeFilter(next);
    setOffset(0);
  };

  const handleUndo = async () => {
    if (!undoBanner) return;
    const { candidateId } = undoBanner;
    setUndoBanner(null);
    try {
      await rollbackCandidate(candidateId);
      await fetchList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const markExtra = (id: string, on: boolean) => {
    setExtraPending((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handlePromote = async (id: string) => {
    markExtra(id, true);
    try {
      await promoteCandidate(id);
      await fetchList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      markExtra(id, false);
    }
  };

  const handleRollbackPromoted = async (id: string) => {
    markExtra(id, true);
    try {
      await rollbackCandidate(id);
      await fetchList();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      markExtra(id, false);
    }
  };

  const renderExtraActions = (candidate: ExperienceCandidate) => {
    const isPromotePending = extraPending.has(candidate.candidate_id);
    if (candidate.status === 'accepted') {
      return (
        <PromoteButton
          memoryType={candidate.memory_type}
          promotionEnabled={Boolean(killStatus?.promotion_enabled)}
          pending={isPromotePending}
          onConfirm={() => void handlePromote(candidate.candidate_id)}
        />
      );
    }
    if (
      candidate.status === 'promoted_to_memory' ||
      candidate.status === 'promoted_to_skill_draft'
    ) {
      return (
        <button
          type="button"
          disabled={isPromotePending}
          onClick={() => void handleRollbackPromoted(candidate.candidate_id)}
          className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-high px-3 py-1.5 text-xs font-label text-foreground/70 transition-colors hover:border-amber-300/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RotateCcw size={14} />
          {isPromotePending ? '撤销中…' : '撤销保存'}
        </button>
      );
    }
    return null;
  };

  const total = data?.total ?? 0;

  // Kill-switch gate: when review_ui_enabled is off the inbox is hidden
  // behind a clear "feature disabled" message so an operator who reaches
  // this route knows it's intentionally off (not broken). We still render
  // the page header so navigation stays consistent.
  const reviewDisabled = killStatus !== null && killStatus.review_ui_enabled === false;

  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-6">
      <PageHeader
        title="学到的经验"
        subtitle="AI 在你完成任务时学到的内容。你可以保留有用的、忽略没用的，永远不会自动应用。"
        icon={<BookOpenCheck size={20} />}
        actions={
          <button
            type="button"
            onClick={() => void fetchList()}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-high px-3 py-1.5 text-xs font-label text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
            aria-label="刷新候选经验列表"
          >
            <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
            刷新
          </button>
        }
      />

      {killError && (
        <div
          role="alert"
          className="rounded-md border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-300 dark:border-amber-800/50"
        >
          系统状态获取失败：{killError}（功能仍可用，但部分开关读取可能延迟）
        </div>
      )}

      {reviewDisabled ? (
        <div
          role="status"
          className="rounded-lg border border-outline-variant/60 bg-surface-lowest px-5 py-12 text-center"
        >
          <p className="font-display text-base text-foreground/75">学到的经验功能尚未开启</p>
          <p className="mt-2 text-xs text-foreground/50">
            管理员可在 <code className="font-mono">rag_integration_config.yaml</code> 中设置
            <code className="ml-1 font-mono">evolution.review_ui_enabled: true</code>
            以启用本页。
          </p>
        </div>
      ) : (
        <>
          <AuditPanel />

          <Filters
            status={statusFilter}
            memoryType={memoryTypeFilter}
            onStatusChange={handleStatusChange}
            onMemoryTypeChange={handleMemoryTypeChange}
          />

          <CandidateList
            items={data?.items ?? []}
            isLoading={isLoading}
            error={error}
            pendingActions={pendingActions}
            onAccept={(id) => void handleAccept(id)}
            onReject={(id) => void handleReject(id)}
            onSnooze={(id) => void handleSnooze(id)}
            onOpenDetails={handleOpenDetails}
            onRetry={() => void fetchList()}
            renderExtraActions={renderExtraActions}
          />

          {total > 0 && (
            <PaginationBar
              total={total}
              limit={PAGE_LIMIT}
              offset={offset}
              onPageChange={setOffset}
            />
          )}
        </>
      )}

      {/* page-local undo banner (NOT shared ToastProvider — per S5 audit) */}
      {undoBanner && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-4 left-1/2 z-40 flex max-w-[min(90vw,32rem)] -translate-x-1/2 items-center gap-3 rounded-lg border border-outline-variant/60 bg-surface-lowest px-4 py-3 text-sm shadow-lg"
        >
          <span className="min-w-0 truncate text-foreground/80">
            已保存「{undoBanner.candidateTitle}」
          </span>
          <button
            type="button"
            onClick={() => void handleUndo()}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-primary/40 bg-primary/10 px-2.5 py-1 text-xs font-label text-primary transition-colors hover:bg-primary/20"
          >
            撤销
          </button>
          <button
            type="button"
            onClick={() => setUndoBanner(null)}
            aria-label="关闭提示"
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-foreground/40 transition-colors hover:bg-surface-high hover:text-foreground"
          >
            <XIcon size={14} />
          </button>
        </div>
      )}

      <CandidateDetailDrawer
        candidate={selectedDetail}
        open={selectedDetail !== null}
        onClose={() => setSelectedDetail(null)}
      />

      {/* kill-switch debug strip — invisible to users; only readable via dev-tools.
          Production-safe because it does not render IDs/JSON in default view. */}
      {killStatus && import.meta.env.DEV && (
        <div className="hidden" data-testid="evolution-kill-switches">
          recall={String(killStatus.recall_enabled)}; capture={String(killStatus.candidate_capture_enabled)}; promote={String(killStatus.promotion_enabled)}; curator={String(killStatus.curator_enabled)};
        </div>
      )}
    </div>
  );
}
