import { useMemo, useState } from 'react';
import { CheckCircle2, Clock3, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { WikiReviewItemModel } from '@/types/wiki';
import { formatWikiError, formatWikiPageLabel, sanitizeWikiVisibleText } from './wikiDisplay';

interface ReviewQueuePanelProps {
  items: WikiReviewItemModel[] | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
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
    source: '来源',
    note: '笔记',
  };
  return labels[kind] ?? kind;
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    all: '全部',
    pending: '待审核',
    approved: '已通过',
    rejected: '已退回',
  };
  return labels[status] ?? status;
}

export function ReviewQueuePanel({ items, isLoading, error, onRefresh }: ReviewQueuePanelProps) {
  const [kindFilter, setKindFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

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
          <div className="font-label text-[11px] uppercase text-foreground/35">待审页面</div>
          <h2 className="mt-1 font-display text-lg font-semibold text-foreground">待审页面</h2>
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
          filteredItems.map((item) => (
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
                  <div className="mt-2 text-[11px] leading-5 text-foreground/45">
                    页面：{formatWikiPageLabel(item.page_path)}
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
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
            </article>
          ))
        ) : (
          <div className="rounded-2xl border border-outline-variant/30 bg-surface-high/60 px-4 py-8 text-center text-sm text-foreground/45">
            当前筛选条件下没有匹配项。
          </div>
        )}
      </div>
    </section>
  );
}
