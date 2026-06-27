import { AlertTriangle, CheckCircle2, Database, FileText, GitBranch, RefreshCw, ShieldCheck } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { WikiStatusModel } from '@/types/wiki';
import { formatWikiError, formatWikiWarning } from './wikiDisplay';

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
    { id: 'graph-file', label: '图谱文件', active: status.graph_json_exists, icon: GitBranch },
    { id: 'graph-db', label: '图谱数据库', active: status.graph_db_exists, icon: Database },
    { id: 'query-index', label: '查询索引', active: status.query_index_exists, icon: ShieldCheck },
    { id: 'review-queue', label: '待审页面', active: status.review_queue_exists, icon: ShieldCheck },
  ] : [];

  const enabledTone = status?.enabled
    ? 'text-emerald-700 bg-emerald-50 border-emerald-200/80 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300'
    : 'text-amber-700 bg-amber-50 border-amber-200/80 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300';
  const staleTone = status?.stale
    ? 'text-red-700 bg-red-50 border-red-200/80 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300'
    : 'text-slate-600 bg-surface-high border-outline-variant/40';
  const integrity = status ? buildIntegritySummary(status) : null;
  const resourceRows = status ? buildResourceRows(status) : [];
  const manifestDriftRows = status ? buildManifestDriftRows(status) : [];

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
            {integrity ? (
              <span className={cn('inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-label', integrity.tone)}>
                {integrity.blocking ? <AlertTriangle size={12} /> : <ShieldCheck size={12} />}
                {integrity.label}
              </span>
            ) : null}
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
          {formatWikiError(error, '读取 Wiki 状态失败，请稍后重试。')}
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

        <div className="rounded-2xl border border-outline-variant/30 bg-surface-lowest/70 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-label text-[11px] tracking-[0.2em] text-foreground/45">
                资源与索引配置
              </div>
            </div>
            <FileText size={18} className="shrink-0 text-primary/60" />
          </div>
          <div className="mt-4 space-y-2">
            {status ? resourceRows.map((row) => (
              <div key={row.key} className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn('h-1.5 w-1.5 rounded-full', row.exists ? 'bg-emerald-500' : 'bg-amber-500')} />
                      <span className="font-label text-xs font-medium text-foreground/70">{row.label}</span>
                      <span className={cn(
                        'rounded px-1.5 py-0.5 text-[10px]',
                        row.exists
                          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                          : 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
                      )}>
                        {row.exists ? '可用' : '待生成'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )) : (
              <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-6 text-center text-sm text-foreground/45">
                {isLoading ? '正在加载 Wiki 状态…' : '状态尚未加载'}
              </div>
            )}
          </div>
        </div>
      </div>

      {integrity ? (
        <div
          role="status"
          aria-label="Wiki 来源完整性"
          className={cn(
            'mt-5 rounded-2xl border px-4 py-4',
            integrity.blocking
              ? 'border-amber-200/80 bg-amber-50/80 dark:border-amber-700/40 dark:bg-amber-500/15'
              : 'border-outline-variant/30 bg-surface-lowest/70',
          )}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="font-label text-[11px] tracking-[0.2em] text-foreground/45">来源完整性</div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span className={cn('inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-label', integrity.tone)}>
                  {integrity.blocking ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}
                  {integrity.label}
                </span>
                <span className="text-xs text-foreground/55">模型上下文：{integrity.contextLabel}</span>
              </div>
            </div>
            <div className="grid min-w-0 gap-2 text-xs text-foreground/60 sm:grid-cols-3 lg:min-w-[420px]">
              <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-2">
                <div className="text-[10px] text-foreground/40">源页 / 索引页</div>
                <div className="mt-1 font-label text-foreground">{integrity.sourcePages} / {integrity.indexedPages}</div>
              </div>
              <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-2">
                <div className="text-[10px] text-foreground/40">来源清单</div>
                <div className="mt-1 truncate font-mono text-[11px] text-foreground">{integrity.sourceHash}</div>
              </div>
              <div className="rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-2">
                <div className="text-[10px] text-foreground/40">索引清单</div>
                <div className="mt-1 truncate font-mono text-[11px] text-foreground">{integrity.indexedHash}</div>
              </div>
            </div>
          </div>
          {manifestDriftRows.length ? (
            <div className="mt-4 grid gap-2 lg:grid-cols-3">
              {manifestDriftRows.map((row) => (
                <div key={row.key} className="min-w-0 rounded-xl border border-outline-variant/30 bg-surface-high/70 px-3 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-label text-[11px] text-foreground/60">{row.label}</span>
                    <span className="font-label text-xs text-foreground">{row.count}</span>
                  </div>
                  {row.samples.length ? (
                    <div className="mt-2 truncate font-mono text-[11px] text-foreground/55">
                      {row.samples.join(' · ')}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

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

function buildResourceRows(status: WikiStatusModel): Array<{
  key: string;
  label: string;
  exists: boolean;
}> {
  return [
    {
      key: 'page_root',
      label: '页面目录',
      exists: status.page_count > 0,
    },
    {
      key: 'graph_file',
      label: '知识图谱文件',
      exists: status.graph_json_exists,
    },
    {
      key: 'graph_db',
      label: '知识图谱数据库',
      exists: status.graph_db_exists,
    },
    {
      key: 'query_index',
      label: '检索索引',
      exists: status.query_index_exists,
    },
    {
      key: 'review_queue',
      label: '待审页面',
      exists: status.review_queue_exists,
    },
  ];
}

function buildManifestDriftRows(status: WikiStatusModel): Array<{
  key: string;
  label: string;
  count: number;
  samples: string[];
}> {
  const drilldown = status.manifest_drilldown;
  const rows = [
    {
      key: 'missing',
      label: '源页未入索引',
      count: drilldown.missing_count,
      pages: drilldown.missing_pages,
    },
    {
      key: 'extra',
      label: '索引多余页',
      count: drilldown.extra_count,
      pages: drilldown.extra_pages,
    },
    {
      key: 'mismatched',
      label: 'Hash 不一致',
      count: drilldown.mismatched_count,
      pages: drilldown.mismatched_pages,
    },
  ];
  return rows
    .filter((row) => row.count > 0)
    .map((row) => ({
      key: row.key,
      label: row.label,
      count: row.count,
      samples: row.pages.slice(0, 3).map(formatManifestPageSample),
    }));
}

function formatManifestPageSample(page: WikiStatusModel['manifest_drilldown']['missing_pages'][number]): string {
  return page.redacted ? '已隐藏路径' : page.page_path;
}

function buildIntegritySummary(status: WikiStatusModel): {
  label: string;
  tone: string;
  blocking: boolean;
  contextLabel: string;
  sourcePages: string;
  indexedPages: string;
  sourceHash: string;
  indexedHash: string;
} {
  const normalized = status.integrity_status.trim() || 'unknown';
  const blocking = status.enabled && !['aligned', 'indexed_manifest_recorded', 'empty_no_index', 'disabled'].includes(normalized);
  return {
    label: wikiIntegrityLabel(normalized),
    tone: wikiIntegrityTone(normalized, blocking),
    blocking,
    contextLabel: wikiIntegrityContextLabel(status.enabled, normalized, blocking),
    sourcePages: status.source_page_count === null ? '未知' : String(status.source_page_count),
    indexedPages: String(status.indexed_page_count),
    sourceHash: shortDigest(status.source_manifest_hash),
    indexedHash: shortDigest(status.indexed_source_manifest_hash),
  };
}

function wikiIntegrityLabel(status: string): string {
  const labels: Record<string, string> = {
    aligned: '来源已对齐',
    indexed_manifest_recorded: '已记录来源清单',
    empty_no_index: '暂无索引',
    empty_unproven: '空索引未证明',
    disabled: '完整性未启用',
    missing_index: '缺少检索索引',
    unreadable_index: '索引不可读取',
    missing_manifest: '缺少来源清单',
    page_count_mismatch: '页面数不一致',
    source_hash_mismatch: '来源已变更',
    index_count_mismatch: '索引记录不一致',
    unknown: '完整性未知',
  };
  return labels[status] ?? '完整性未知';
}

function wikiIntegrityTone(status: string, blocking: boolean): string {
  if (status === 'aligned') {
    return 'text-emerald-700 bg-emerald-50 border-emerald-200/80 dark:border-emerald-700/40 dark:bg-emerald-500/15 dark:text-emerald-300';
  }
  if (blocking) {
    return 'text-amber-800 bg-amber-50 border-amber-200/80 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300';
  }
  return 'text-slate-600 bg-surface-high border-outline-variant/40';
}

function wikiIntegrityContextLabel(enabled: boolean, status: string, blocking: boolean): string {
  if (!enabled || status === 'disabled') {
    return '未启用';
  }
  if (status === 'aligned') {
    return '允许 Wiki 引用';
  }
  if (blocking) {
    return '阻断 Wiki 引用';
  }
  if (status === 'empty_no_index') {
    return '暂无可用索引';
  }
  if (status === 'indexed_manifest_recorded') {
    return '待来源复核';
  }
  return '暂不进入';
}

function shortDigest(value: string): string {
  const normalized = value.trim();
  if (!normalized || normalized === 'unknown' || normalized === 'none') {
    return '未记录';
  }
  return normalized.slice(0, 12);
}
