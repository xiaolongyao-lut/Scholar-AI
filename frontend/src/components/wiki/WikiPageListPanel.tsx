import { useMemo, useState } from 'react';
import { FileText, Filter, RefreshCw } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { WikiPageSummaryModel } from '@/types/wiki';

interface WikiPageListPanelProps {
  pages: WikiPageSummaryModel[] | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
  selectedPath: string | null;
  onSelectPath: (pagePath: string) => void;
}

function toneForStatus(status: string): string {
  if (status === 'final') return 'bg-emerald-50 text-emerald-700 border-emerald-200/80 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300';
  if (status === 'review') return 'bg-amber-50 text-amber-700 border-amber-200/80 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300';
  return 'bg-surface-high text-foreground/60 border-outline-variant/40';
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
    draft: '草稿',
    review: '待复审',
    final: '已定稿',
  };
  return labels[status] ?? status;
}

export function WikiPageListPanel({ pages, isLoading, error, onRefresh, selectedPath, onSelectPath }: WikiPageListPanelProps) {
  const [kindFilter, setKindFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  const kindOptions = useMemo(() => {
    const values = new Set((pages ?? []).map((page) => page.kind));
    return ['all', ...Array.from(values).sort()];
  }, [pages]);

  const statusOptions = useMemo(() => {
    const values = new Set((pages ?? []).map((page) => page.status));
    return ['all', ...Array.from(values).sort()];
  }, [pages]);

  const filteredPages = useMemo(() => (
    (pages ?? []).filter((page) => {
      const kindMatched = kindFilter === 'all' || page.kind === kindFilter;
      const statusMatched = statusFilter === 'all' || page.status === statusFilter;
      return kindMatched && statusMatched;
    })
  ), [kindFilter, pages, statusFilter]);

  return (
    <section className="glass-card rounded-2xl border border-outline-variant/40 p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="font-label text-[11px] uppercase tracking-[0.22em] text-foreground/35">页面</div>
          <h2 className="mt-2 font-display text-2xl font-semibold text-foreground">Wiki 页面列表</h2>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-xs font-label text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          刷新页面列表
        </button>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3 rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 p-4">
        <div className="inline-flex items-center gap-2 text-xs font-label tracking-[0.14em] text-foreground/40">
          <Filter size={14} />
          筛选
        </div>

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
          {filteredPages.length} / {(pages ?? []).length} 页
        </div>
      </div>

      {error ? (
        <div className="mt-5 rounded-xl border border-red-200/80 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {error}
        </div>
      ) : null}

      <div className="mt-5 space-y-3">
        {isLoading ? (
          <div className="rounded-2xl border border-outline-variant/30 bg-surface-high/60 px-4 py-8 text-center text-sm text-foreground/45">
            正在读取 Wiki 页面…
          </div>
        ) : filteredPages.length > 0 ? (
          filteredPages.map((page) => (
            <button
              key={page.path}
              type="button"
              onClick={() => onSelectPath(page.path)}
              className={cn(
                'w-full rounded-2xl border px-4 py-4 text-left transition-colors',
                selectedPath === page.path
                  ? 'border-primary/35 bg-primary/5 shadow-[0_0_0_1px_rgba(99,102,241,0.08)]'
                  : 'border-outline-variant/30 bg-surface-lowest/80 hover:border-primary/25 hover:bg-surface-lowest'
              )}
            >
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-foreground">
                    <FileText size={16} className="text-primary/60" />
                    <h3 className="truncate font-headline text-sm font-semibold">{page.title}</h3>
                    {selectedPath === page.path ? (
                      <span className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] font-label tracking-[0.14em] text-primary/80">
                        预览
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-2 break-all font-mono text-[11px] leading-5 text-foreground/45">{page.path}</div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <span className="rounded-full border border-outline-variant/40 bg-surface-high px-2.5 py-1 text-[10px] font-label tracking-[0.14em] text-foreground/55">
                    {kindLabel(page.kind)}
                  </span>
                  <span className={cn('rounded-full border px-2.5 py-1 text-[10px] font-label tracking-[0.14em]', toneForStatus(page.status))}>
                    {statusLabel(page.status)}
                  </span>
                </div>
              </div>

              <div className="mt-4 flex items-center justify-between gap-3 text-[11px] text-foreground/45">
                <span>点击此卡片，在右侧读取页面元数据与正文预览。</span>
                <span className="font-label tracking-[0.14em] text-primary/65">
                  {selectedPath === page.path ? '当前已选中' : '加载预览'}
                </span>
              </div>
            </button>
          ))
        ) : (
          <div className="rounded-2xl border border-outline-variant/30 bg-surface-high/60 px-4 py-8 text-center text-sm text-foreground/45">
            当前过滤条件下没有匹配页面。
          </div>
        )}
      </div>
    </section>
  );
}
