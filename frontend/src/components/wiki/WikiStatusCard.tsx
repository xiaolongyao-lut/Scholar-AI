import { AlertTriangle, CheckCircle2, Database, GitBranch, RefreshCw, ShieldCheck } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { WikiStatusModel } from '@/types/wiki';

interface WikiStatusCardProps {
  status: WikiStatusModel | null;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
}

interface StatusMetric {
  id: string;
  label: string;
  active: boolean;
  icon: typeof Database;
}

export function WikiStatusCard({ status, isLoading, error, onRefresh }: WikiStatusCardProps) {
  const metrics: StatusMetric[] = status ? [
    { id: 'graph-json', label: '图谱文件', active: status.graph_json_exists, icon: GitBranch },
    { id: 'graph-db', label: '图谱数据库', active: status.graph_db_exists, icon: Database },
    { id: 'query-index', label: '查询索引', active: status.query_index_exists, icon: ShieldCheck },
    { id: 'review-queue', label: '复审队列', active: status.review_queue_exists, icon: ShieldCheck },
  ] : [];

  const enabledTone = status?.enabled
    ? 'text-emerald-700 bg-emerald-50 border-emerald-200/80 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300'
    : 'text-amber-700 bg-amber-50 border-amber-200/80 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300';
  const staleTone = status?.stale
    ? 'text-red-700 bg-red-50 border-red-200/80 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300'
    : 'text-slate-600 bg-surface-high border-outline-variant/40';

  return (
    <section className="glass-card rounded-2xl p-6 border border-outline-variant/40 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-label text-[11px] uppercase tracking-[0.24em] text-foreground/35">Wiki 状态</span>
            <span className={cn('inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-label', enabledTone)}>
              {status?.enabled ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
              {status?.enabled ? '已启用' : '未启用'}
            </span>
            <span className={cn('inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-label', staleTone)}>
              {status?.stale ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}
              {status?.stale ? '需要重新生成' : '内容为最新'}
            </span>
          </div>
          <h2 className="font-display text-2xl font-semibold text-foreground">Wiki 状态总览</h2>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 self-start rounded-xl border border-outline-variant/40 bg-surface-high px-3 py-2 text-xs font-label text-foreground/70 transition-colors hover:border-primary/30 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw size={14} className={cn(isLoading && 'animate-spin')} />
          刷新状态
        </button>
      </div>

      {error ? (
        <div className="mt-5 rounded-xl border border-red-200/80 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300">
          {error}
        </div>
      ) : null}

      <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 p-5">
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="font-label text-[11px] tracking-[0.2em] text-foreground/35">页面数量</div>
              <div className="mt-2 font-display text-4xl font-semibold text-foreground tabular-nums">
                {status?.page_count ?? '—'}
              </div>
            </div>
            <div className="rounded-2xl bg-primary/8 p-3 text-primary">
              <Database size={24} />
            </div>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {metrics.map((metric) => (
              <div
                key={metric.id}
                className={cn(
                  'rounded-xl border px-3 py-3',
                  metric.active
                    ? 'border-emerald-200/80 bg-emerald-50/70 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300'
                    : 'border-outline-variant/40 bg-surface-high text-foreground/55'
                )}
              >
                <div className="flex items-center gap-2">
                  <metric.icon size={14} />
                  <span className="font-label text-xs">{metric.label}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <details className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 p-5">
          <summary className="cursor-pointer list-none font-label text-[11px] tracking-[0.2em] text-foreground/45 hover:text-foreground/70">
            高级 · 资源路径（点击展开）
          </summary>
          <div className="mt-4 space-y-3">
            {status ? Object.entries(status.paths).map(([key, value]) => (
              <div key={key} className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                <div className="font-label text-[10px] tracking-[0.18em] text-foreground/40">{key}</div>
                <div className="mt-1 break-all font-mono text-[11px] leading-5 text-foreground/65">{value}</div>
              </div>
            )) : (
              <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-6 text-center text-sm text-foreground/45">
                {isLoading ? '正在加载 Wiki 状态…' : '状态尚未加载'}
              </div>
            )}
          </div>
        </details>
      </div>

      {status?.warnings?.length ? (
        <div className="mt-5 rounded-2xl border border-amber-200/80 bg-amber-50/80 px-4 py-4 dark:border-amber-700/40 dark:bg-amber-500/15">
          <div className="font-label text-[11px] tracking-[0.2em] text-amber-700/80 dark:text-amber-300/80">告警</div>
          <ul className="mt-3 space-y-2 text-sm leading-6 text-amber-800 dark:text-amber-300">
            {status.warnings.map((warning) => (
              <li key={warning} className="flex items-start gap-2">
                <AlertTriangle size={14} className="mt-1 flex-shrink-0" />
                <span>{formatWikiWarning(warning)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function formatWikiWarning(warning: string): string {
  if (warning.includes('Wiki integration is disabled')) {
    return 'Wiki 集成尚未启用。';
  }
  return warning;
}
