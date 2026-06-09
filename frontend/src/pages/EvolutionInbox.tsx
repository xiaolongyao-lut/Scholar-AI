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
import {
  BookOpenCheck,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Activity,
  X as XIcon,
} from 'lucide-react';

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
import { MemoryPalacePanel } from '../components/evolution/MemoryPalacePanel';
import { PaginationBar } from '../components/evolution/PaginationBar';
import { PromoteButton } from '../components/evolution/PromoteButton';
import { formatEvolutionError, sanitizeEvolutionUserText } from '../components/evolution/labels';
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

interface EvolutionInboxProps {
  embedded?: boolean;
}

function ExperienceKnowledgeLayerCard({
  enabled,
  reviewEnabled,
  promotionEnabled,
  candidateCount,
  pendingCount,
  isLoading,
  onRefresh,
}: {
  enabled: boolean;
  reviewEnabled: boolean;
  promotionEnabled: boolean;
  candidateCount: number;
  pendingCount: number;
  isLoading: boolean;
  onRefresh: () => void;
}) {
  return (
    <section className="rounded-lg border border-outline-variant/60 bg-surface-lowest p-4 shadow-sm">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <BookOpenCheck size={18} />
          </div>
          <div className="min-w-0">
            <h2 className="font-headline text-base font-semibold text-foreground">经验知识层</h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-foreground/55">
              这里复审任务、讨论、研读、Skill 和 MCP 运行中沉淀的可复用经验；保存后才会进入长期记忆或流程草稿，未确认内容不会自动应用。
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-1.5 self-start rounded-md border border-outline-variant/60 bg-surface-low px-2.5 py-1.5 text-xs text-foreground/65 transition-colors hover:border-primary/35 hover:text-primary disabled:cursor-wait disabled:opacity-60"
          aria-label="刷新经验候选列表"
        >
          <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
          探查触发状态
        </button>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <ExperienceFlowStatus label="运行状态" value={enabled ? '已启用' : '未启用'} detail="候选收纳" active={enabled} />
        <ExperienceFlowStatus label="候选经验" value={`${candidateCount} 条`} detail="当前筛选结果" active={candidateCount > 0} />
        <ExperienceFlowStatus label="待复审" value={`${pendingCount} 条`} detail={reviewEnabled ? '复审入口开放' : '复审入口关闭'} active={reviewEnabled} />
        <ExperienceFlowStatus label="保存应用" value={promotionEnabled ? '可应用' : '仅复审'} detail="长期记忆/流程草稿" active={promotionEnabled} />
      </div>

      {!enabled || !reviewEnabled ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-5 text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
          <div className="flex items-start gap-2">
            <ShieldCheck size={14} className="mt-0.5 shrink-0" />
            <p>
              经验候选需要先在设置里开启「经验候选收纳」和「学到的经验复审入口」；任务完成后没有新增时，先到任务中心确认对应任务是否完成。
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ExperienceFlowStatus({ label, value, detail, active }: { label: string; value: string; detail: string; active: boolean }) {
  return (
    <div className="rounded-md border border-outline-variant/50 bg-surface-low px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-foreground/45">{label}</span>
        <ShieldCheck size={13} className={active ? 'text-emerald-500' : 'text-foreground/25'} />
      </div>
      <div className="mt-1 truncate text-sm font-medium text-foreground">{value}</div>
      <div className="mt-0.5 truncate text-[11px] text-foreground/45">{detail}</div>
    </div>
  );
}

export default function EvolutionInbox({ embedded = false }: EvolutionInboxProps = {}) {
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
  const [isProbing, setIsProbing] = useState(false);

  const fetchList = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await listCandidates({
        status: statusFilter === 'all' ? undefined : statusFilter,
        memoryType: memoryTypeFilter === 'all' ? undefined : memoryTypeFilter,
        sortBy: 'confidence',
        limit: PAGE_LIMIT,
        offset,
      });
      setData(result);
    } catch (err) {
      setError(formatEvolutionError(err, '经验候选加载失败，请稍后重试。'));
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter, memoryTypeFilter, offset]);

  const handleProbe = useCallback(async () => {
    setIsProbing(true);
    try {
      await fetchList();
    } finally {
      setIsProbing(false);
    }
  }, [fetchList]);

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
      setError(formatEvolutionError(err));
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
      setError(formatEvolutionError(err));
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
      setError(formatEvolutionError(err));
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
      setError(formatEvolutionError(err));
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
      setError(formatEvolutionError(err));
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
      setError(formatEvolutionError(err));
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
    <div className={embedded ? 'space-y-4' : 'mx-auto max-w-4xl space-y-4 px-4 py-6'}>
      {!embedded ? (
        <PageHeader
          title="学到的经验"
          subtitle="AI 在你完成任务时学到的内容。你可以保留有用的、忽略没用的，永远不会自动应用。"
          icon={<BookOpenCheck size={20} />}
          actions={
            <button
              type="button"
              onClick={() => void handleProbe()}
              disabled={isLoading || isProbing}
              className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-high px-3 py-1.5 text-xs font-label text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
              aria-label="刷新候选经验列表"
            >
              <Activity size={14} className={cn((isLoading || isProbing) && 'animate-spin')} />
              探查触发状态
            </button>
          }
        />
      ) : null}

      {killError && (
        <div
          role="alert"
          className="rounded-md border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-300 dark:border-amber-800/50"
        >
          {formatEvolutionError(killError, '系统状态获取失败，请稍后重试。')}（功能仍可用，但部分开关读取可能延迟）
        </div>
      )}

      {reviewDisabled ? (
        <div
          role="status"
          className="rounded-lg border border-outline-variant/60 bg-surface-lowest px-5 py-12 text-center"
        >
          <p className="font-display text-base text-foreground/75">学到的经验功能尚未开启</p>
          <p className="mt-2 text-xs text-foreground/50">
            请到「设置 → 功能开关」打开「经验候选收纳」和「学到的经验复审入口」。开启后，系统会把智能研读、讨论、写作任务和工具运行中学到的内容放到这里等待人工确认。
          </p>
        </div>
      ) : (
        <>
          <ExperienceKnowledgeLayerCard
            enabled={Boolean(killStatus?.enabled)}
            reviewEnabled={Boolean(killStatus?.review_ui_enabled)}
            promotionEnabled={Boolean(killStatus?.promotion_enabled)}
            candidateCount={data?.total ?? 0}
            pendingCount={data?.items.filter((candidate) => candidate.status === 'pending' || candidate.status === 'captured').length ?? 0}
            isLoading={isLoading || isProbing}
            onRefresh={() => void handleProbe()}
          />

          <AuditPanel />

          <MemoryPalacePanel />

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
            已保存「{sanitizeEvolutionUserText(undoBanner.candidateTitle, '待复审经验')}」
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
    </div>
  );
}
