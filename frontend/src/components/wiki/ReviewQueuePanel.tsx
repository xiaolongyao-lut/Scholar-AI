import { useMemo, useState } from 'react';
import { CheckCircle2, Clock3, RefreshCw, ShieldCheck, Undo2, XCircle } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { WikiReviewItemModel } from '@/types/wiki';
import { formatWikiError, formatWikiPageLabel, sanitizeWikiVisibleText } from './wikiDisplay';

interface ReviewQueuePanelProps {
  items: WikiReviewItemModel[] | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
  onApprove: (item: WikiReviewItemModel, reason: string) => Promise<void>;
  onReject: (item: WikiReviewItemModel, reason: string) => Promise<void>;
  onWithdraw: (item: WikiReviewItemModel, reason: string) => Promise<void>;
}

function statusTone(status: string): string {
  if (status === 'approved') return 'bg-emerald-50 text-emerald-700 border-emerald-200/80 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300';
  if (status === 'rejected') return 'bg-red-50 text-red-700 border-red-200/80 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300';
  return 'bg-amber-50 text-amber-700 border-amber-200/80 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300';
}

function statusIcon(status: string) {
  if (status === 'approved') return <CheckCircle2 size={12} />;
  if (status === 'rejected') return <XCircle size={12} />;
  return <Clock3 size={12} />;
}

function kindLabel(kind: string): string {
  const labels: Record<string, string> = {
    all: '全部',
    claim: '断言',
    synthesis: '综合页',
    concept: '概念',
    draft: '草稿',
    final: '确认知识',
    review: '待确认',
    source: '来源',
    note: '笔记',
    annotation_note: '批注',
  };
  return labels[kind] ?? kind;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    all: '全部',
    draft: '草稿',
    final: '确认知识',
    pending: '待审核',
    review: '待确认',
    approved: '已通过',
    rejected: '已退回',
  };
  return labels[status] ?? status;
}

export function ReviewQueuePanel({
  items,
  isLoading,
  error,
  onRefresh,
  onApprove,
  onReject,
  onWithdraw,
}: ReviewQueuePanelProps) {
  const [kindFilter, setKindFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [decisionReasons, setDecisionReasons] = useState<Record<string, string>>({});
  const [withdrawalReasons, setWithdrawalReasons] = useState<Record<string, string>>({});
  const [submittingItemId, setSubmittingItemId] = useState<string | null>(null);
  const [decisionErrors, setDecisionErrors] = useState<Record<string, string>>({});

  const submitDecision = async (
    item: WikiReviewItemModel,
    action: 'approve' | 'reject' | 'withdraw',
  ): Promise<void> => {
    const itemId = item.item_id;
    const isPageTarget = item.target?.type === 'wiki_page_revision';
    if (!item.allowed_actions.includes(action)) {
      setDecisionErrors((current) => ({ ...current, [itemId]: '该待审项当前不允许执行此操作，请刷新后重试。' }));
      return;
    }
    if (action === 'withdraw' && !isPageTarget) {
      setDecisionErrors((current) => ({ ...current, [itemId]: '只有 Wiki 页面晋升可以撤回。' }));
      return;
    }
    if (action === 'reject' && item.promotion_intent) {
      setDecisionErrors((current) => ({ ...current, [itemId]: '该晋升已开始，请继续完成原操作。' }));
      return;
    }
    if (action === 'withdraw' && !item.promotion_intent) {
      setDecisionErrors((current) => ({ ...current, [itemId]: '当前没有可撤回的晋升操作，请刷新后重试。' }));
      return;
    }
    const reason = (
      action === 'withdraw'
        ? withdrawalReasons[itemId]
        : item.promotion_intent?.reason ?? decisionReasons[itemId]
    )?.trim() ?? '';
    if (!reason) {
      setDecisionErrors((current) => ({
        ...current,
        [itemId]: action === 'withdraw' ? '请填写撤回理由。' : '请填写审核理由。',
      }));
      return;
    }
    setSubmittingItemId(itemId);
    setDecisionErrors((current) => ({ ...current, [itemId]: '' }));
    try {
      if (action === 'approve') await onApprove(item, reason);
      else if (action === 'reject') await onReject(item, reason);
      else await onWithdraw(item, reason);
      if (action === 'withdraw') {
        setWithdrawalReasons((current) => ({ ...current, [itemId]: '' }));
      } else {
        setDecisionReasons((current) => ({ ...current, [itemId]: '' }));
      }
    } catch (decisionError: unknown) {
      const message = decisionError instanceof Error ? decisionError.message : '';
      setDecisionErrors((current) => ({
        ...current,
        [itemId]: formatWikiError(message, '审核操作失败，请稍后重试。'),
      }));
    } finally {
      setSubmittingItemId(null);
    }
  };

  const kindOptions = useMemo(() => {
    const values = new Set((items ?? []).map((item) => item.kind));
    return ['all', ...Array.from(values).sort()];
  }, [items]);

  const statusOptions = useMemo(() => {
    const values = new Set((items ?? []).map((item) => item.status));
    return ['all', ...Array.from(values).sort()];
  }, [items]);

  const filteredItems = useMemo(() => (
    (items ?? []).filter((item) => {
      const kindMatched = kindFilter === 'all' || item.kind === kindFilter;
      const statusMatched = statusFilter === 'all' || item.status === statusFilter;
      return kindMatched && statusMatched;
    })
  ), [items, kindFilter, statusFilter]);

  return (
    <section className="glass-card rounded-lg border border-outline-variant/40 p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="font-label text-[11px] uppercase text-foreground/35">人工审核</div>
          <h2 className="mt-1 font-display text-lg font-semibold text-foreground">审核队列</h2>
          <p className="mt-1 text-xs leading-5 text-foreground/50">
            Wiki 页面可显式晋升；批注审核只记录决定。
          </p>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-xs font-label text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          刷新待审页面
        </button>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3 rounded-lg border border-outline-variant/30 bg-surface-lowest/70 p-4">
        <label className="flex items-center gap-2 text-xs text-foreground/55">
          <span className="font-label tracking-[0.14em] text-foreground/35">类型</span>
          <select
            aria-label="类型"
            value={kindFilter}
            onChange={(event) => setKindFilter(event.target.value)}
            className="rounded-lg border border-outline-variant/40 bg-surface-high px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/10"
          >
            {kindOptions.map((option) => (
              <option key={option} value={option}>{kindLabel(option)}</option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 text-xs text-foreground/55">
          <span className="font-label tracking-[0.14em] text-foreground/35">状态</span>
          <select
            aria-label="状态"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="rounded-lg border border-outline-variant/40 bg-surface-high px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/10"
          >
            {statusOptions.map((option) => (
              <option key={option} value={option}>{statusLabel(option)}</option>
            ))}
          </select>
        </label>

        <div className="ml-auto text-xs font-label text-foreground/45">
          {filteredItems.length} / {(items ?? []).length} 项
        </div>
      </div>

      {error ? (
        <div className="mt-5 rounded-xl border border-red-200/80 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {formatWikiError(error, '读取待审页面失败，请稍后重试。')}
        </div>
      ) : null}

      <div className="mt-5 space-y-3">
        {isLoading ? (
          <div className="rounded-2xl border border-outline-variant/30 bg-surface-high/60 px-4 py-8 text-center text-sm text-foreground/45">
            正在读取待审页面…
          </div>
        ) : filteredItems.length > 0 ? (
          filteredItems.map((item) => {
            const isPageTarget = item.target?.type === 'wiki_page_revision';
            const isAnnotationTarget = item.target?.type === 'annotation_note';
            const promotionInProgress = item.promotion_intent !== null;
            const decisionReason = item.promotion_intent?.reason ?? decisionReasons[item.item_id] ?? '';
            const withdrawalReason = withdrawalReasons[item.item_id] ?? '';
            const targetLabel = isPageTarget ? 'Wiki 页面' : isAnnotationTarget ? '文献批注' : '审核项';
            const reasonLabel = isAnnotationTarget ? '批注审核理由' : '审核理由';
            const approveLabel = isPageTarget ? '接受并晋升' : isAnnotationTarget ? '通过批注审核' : '通过审核';
            const rejectLabel = isPageTarget ? '退回候选' : isAnnotationTarget ? '退回批注' : '退回审核项';
            return (
              <article key={item.item_id} className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/80 px-4 py-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <ShieldCheck size={16} className="text-primary/60" />
                    <h3 className="font-headline text-sm font-semibold text-foreground">
                      {sanitizeWikiVisibleText(item.title, formatWikiPageLabel(item.page_path))}
                    </h3>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-foreground/65">
                    {sanitizeWikiVisibleText(item.summary, '复审摘要已隐藏，避免显示内部路径或系统字段。')}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <span className="rounded-full border border-primary/20 bg-primary/5 px-2.5 py-1 text-[10px] font-label tracking-[0.14em] text-primary/75">
                    {targetLabel}
                  </span>
                  <span className="rounded-full border border-outline-variant/40 bg-surface-high px-2.5 py-1 text-[10px] font-label tracking-[0.14em] text-foreground/55">
                    {kindLabel(item.kind)}
                  </span>
                  <span className={cn('inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-label tracking-[0.14em]', statusTone(item.status))}>
                    {statusIcon(item.status)}
                    {statusLabel(item.status)}
                  </span>
                </div>
              </div>

              {item.decision ? (
                <div className="mt-4 rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3 text-xs text-foreground/60">
                  <div className="font-label tracking-[0.14em] text-foreground/35">审核结论</div>
                  <div className="mt-1">
                    {sanitizeWikiVisibleText(item.decision.reason, '复审结论已记录。')}
                  </div>
                  <div className="mt-1 text-[11px] text-foreground/40">
                    {statusLabel(item.decision.status)} · 已记录审核 · {sanitizeWikiVisibleText(item.decision.decided_at, '已记录时间')}
                  </div>
                </div>
              ) : null}

              {item.status === 'pending' && !item.decision && item.allowed_actions.length > 0 ? (
                <div className="mt-4 rounded-xl border border-primary/20 bg-primary/5 px-3 py-3">
                  <label className="block text-xs font-label text-foreground/60">
                    {promotionInProgress ? '原审核理由' : reasonLabel}
                    <textarea
                      value={decisionReason}
                      onChange={(event) => {
                        const value = event.target.value;
                        setDecisionReasons((current) => ({ ...current, [item.item_id]: value }));
                        if (decisionErrors[item.item_id]) {
                          setDecisionErrors((current) => ({ ...current, [item.item_id]: '' }));
                        }
                      }}
                      maxLength={500}
                      rows={2}
                      aria-label={`${reasonLabel}：${sanitizeWikiVisibleText(item.title, item.item_id)}`}
                      placeholder={isAnnotationTarget
                        ? '说明通过或退回批注的依据；此操作不会创建 Wiki 页面。'
                        : '说明接受或退回的依据；不会自动生成决定。'}
                      disabled={submittingItemId === item.item_id}
                      readOnly={promotionInProgress}
                      className="mt-2 w-full resize-y rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-sm text-foreground outline-none transition-colors focus:border-primary/50 focus:ring-2 focus:ring-primary/10 disabled:cursor-wait disabled:opacity-60"
                    />
                  </label>
                  {promotionInProgress && item.allowed_actions.includes('withdraw') ? (
                    <label className="mt-3 block text-xs font-label text-foreground/60">
                      撤回理由
                      <textarea
                        value={withdrawalReason}
                        onChange={(event) => {
                          const value = event.target.value;
                          setWithdrawalReasons((current) => ({ ...current, [item.item_id]: value }));
                          if (decisionErrors[item.item_id]) {
                            setDecisionErrors((current) => ({ ...current, [item.item_id]: '' }));
                          }
                        }}
                        maxLength={500}
                        rows={2}
                        aria-label={`撤回理由：${sanitizeWikiVisibleText(item.title, item.item_id)}`}
                        placeholder="说明为什么撤回本次晋升；候选仍会保留为待审核。"
                        disabled={submittingItemId === item.item_id}
                        className="mt-2 w-full resize-y rounded-lg border border-outline-variant/50 bg-surface-lowest px-3 py-2 text-sm text-foreground outline-none transition-colors focus:border-primary/50 focus:ring-2 focus:ring-primary/10 disabled:cursor-wait disabled:opacity-60"
                      />
                    </label>
                  ) : null}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {item.allowed_actions.includes('approve') ? (
                      <button
                        type="button"
                        onClick={() => void submitDecision(item, 'approve')}
                        disabled={submittingItemId !== null || !decisionReason.trim()}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300/70 bg-emerald-50 px-3 py-1.5 text-xs font-label text-emerald-700 transition-colors hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-emerald-700/50 dark:bg-emerald-500/15 dark:text-emerald-300"
                      >
                        <CheckCircle2 size={13} />
                        {promotionInProgress ? '继续完成晋升' : approveLabel}
                      </button>
                    ) : null}
                    {item.allowed_actions.includes('reject') && !promotionInProgress ? (
                      <button
                        type="button"
                        onClick={() => void submitDecision(item, 'reject')}
                        disabled={submittingItemId !== null || !decisionReason.trim()}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-red-300/70 bg-red-50 px-3 py-1.5 text-xs font-label text-red-700 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-700/50 dark:bg-red-500/15 dark:text-red-300"
                      >
                        <XCircle size={13} />
                        {rejectLabel}
                      </button>
                    ) : null}
                    {item.allowed_actions.includes('withdraw') && promotionInProgress ? (
                      <button
                        type="button"
                        onClick={() => void submitDecision(item, 'withdraw')}
                        disabled={submittingItemId !== null || !withdrawalReason.trim()}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300/70 bg-amber-50 px-3 py-1.5 text-xs font-label text-amber-800 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-amber-700/50 dark:bg-amber-500/15 dark:text-amber-200"
                      >
                        <Undo2 size={13} />
                        撤回晋升
                      </button>
                    ) : null}
                    {submittingItemId === item.item_id ? (
                      <span className="self-center text-xs text-foreground/45">正在保存操作…</span>
                    ) : null}
                  </div>
                  {decisionErrors[item.item_id] ? (
                    <div className="mt-2 text-xs text-red-600 dark:text-red-300" role="alert">
                      {decisionErrors[item.item_id]}
                    </div>
                  ) : null}
                  <p className="mt-2 text-[11px] leading-5 text-foreground/45">
                    {isAnnotationTarget
                      ? '批注审核只记录人工决定，不会创建 Wiki 页面或确认图谱事实。'
                      : '只有点击上述按钮才会写入；刷新和查看不会自动晋升或撤回。'}
                  </p>
                </div>
              ) : null}
              </article>
            );
          })
        ) : (
          <div className="rounded-2xl border border-outline-variant/30 bg-surface-high/60 px-4 py-8 text-center text-sm text-foreground/45">
            当前筛选条件下没有匹配项。
          </div>
        )}
      </div>
    </section>
  );
}
