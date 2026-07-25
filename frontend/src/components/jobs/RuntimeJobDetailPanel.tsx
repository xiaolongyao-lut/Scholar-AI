import React from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  RefreshCw,
  RotateCcw,
  X,
} from 'lucide-react';

import { StatusPill, type StatusTone } from '@/components/common/StatusPill';
import {
  formatRuntimeEventLabel,
  formatRuntimeJobStatus,
} from '@/components/writing/writingRuntimeDisplay';
import { useI18n } from '@/contexts/I18nContext';
import type { RuntimeJobDetailState } from '@/hooks/useRuntimeJobDetail';
import type { JobStatus } from '@/types/runtime';

interface RuntimeJobDetailPanelProps {
  jobName: string;
  detail: RuntimeJobDetailState;
  onClose: () => void;
  onRetry: () => void;
}

const ARTIFACT_LABELS: Record<string, string> = {
  audit_record: '审计记录',
  draft: '草稿',
  export_request: '导出请求',
  metadata: '任务元数据',
  review_note: '复审记录',
  transformed_text: '处理结果',
};

function statusTone(status: JobStatus | null): StatusTone {
  if (status === 'completed') return 'success';
  if (status === 'failed' || status === 'approval_rejected') return 'danger';
  if (status === 'started' || status === 'in_progress' || status === 'paused') return 'warning';
  return 'neutral';
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return '时间未知';
  return date.toLocaleString();
}

function artifactLabel(value: string): string {
  return ARTIFACT_LABELS[value] ?? '任务产物';
}

export function RuntimeJobDetailPanel({
  jobName,
  detail,
  onClose,
  onRetry,
}: RuntimeJobDetailPanelProps): React.JSX.Element {
  const { t } = useI18n();
  const visibleEvents = [...detail.events].reverse();
  const statusLabel = detail.status
    ? formatRuntimeJobStatus(detail.status, t)
    : detail.loading
      ? '正在读取'
      : '状态未知';

  return (
    <section
      data-testid="runtime-job-detail"
      aria-label={`任务详情 ${jobName}`}
      className="page-section-shell mb-4 flex max-h-[46%] min-h-[14rem] shrink-0 flex-col overflow-hidden rounded-2xl"
    >
      <header className="flex shrink-0 items-center gap-3 border-b border-outline-variant/35 px-4 py-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Activity size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-display text-sm font-semibold text-foreground">{jobName}</h2>
          <p className="mt-0.5 text-[11px] text-foreground/45">运行快照与最近事件</p>
        </div>
        <StatusPill tone={statusTone(detail.status)}>{statusLabel}</StatusPill>
        <button
          type="button"
          onClick={onRetry}
          disabled={detail.loading}
          title="刷新任务详情"
          aria-label="刷新任务详情"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-foreground/50 transition-colors hover:bg-surface-high hover:text-primary disabled:opacity-45"
        >
          {detail.loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
        </button>
        <button
          type="button"
          onClick={onClose}
          title="关闭任务详情"
          aria-label="关闭任务详情"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-foreground/50 transition-colors hover:bg-surface-high hover:text-foreground"
        >
          <X size={15} />
        </button>
      </header>

      {detail.errorMessage ? (
        <div className="flex shrink-0 items-center gap-2 border-b border-red-200/70 bg-red-50/70 px-4 py-2.5 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-950/25 dark:text-red-300" role="alert">
          <AlertTriangle size={14} className="shrink-0" />
          <span className="min-w-0 flex-1">{detail.errorMessage}</span>
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md border border-current/20 px-2.5 font-label text-xs font-medium transition-colors hover:bg-red-100/70 dark:hover:bg-red-900/30"
          >
            <RotateCcw size={13} />
            重试
          </button>
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1.45fr)_minmax(15rem,0.75fr)]">
        <div className="flex min-h-0 flex-col border-b border-outline-variant/30 lg:border-b-0 lg:border-r">
          <div className="shrink-0 border-b border-outline-variant/30 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-label text-[10px] font-semibold uppercase text-foreground/40">当前阶段</p>
                <p className="mt-1 truncate text-xs font-medium text-foreground/75">
                  {detail.stage ?? '等待运行事件'}
                </p>
              </div>
              <div className="shrink-0 text-right">
                <p className="font-label text-[10px] text-foreground/40">进度</p>
                <p className="mt-1 font-label text-sm font-semibold text-foreground/75">
                  {detail.progress === null ? '--' : `${detail.progress}%`}
                </p>
              </div>
            </div>
            <div
              role="progressbar"
              aria-label="任务真实进度"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={detail.progress ?? undefined}
              aria-valuetext={detail.progress === null ? '进度未知' : `${detail.progress}%`}
              className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-high"
            >
              {detail.progress !== null ? (
                <div
                  className="h-full rounded-full bg-primary transition-[width] duration-300"
                  style={{ width: `${detail.progress}%` }}
                />
              ) : null}
            </div>
            {detail.message ? (
              <p className="mt-2 line-clamp-2 text-xs leading-5 text-foreground/55">{detail.message}</p>
            ) : null}
            <div className="mt-2 flex flex-wrap items-center gap-3 font-label text-[10px] text-foreground/40">
              <span>最新事件序号 {detail.latestSequence || '--'}</span>
              {detail.recoveryRecorded ? (
                <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-300">
                  <CheckCircle2 size={11} />
                  已记录恢复点
                </span>
              ) : null}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2.5">
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <h3 className="font-label text-xs font-semibold text-foreground/65">最近事件</h3>
              <span className="text-[10px] text-foreground/35">{detail.events.length} 条</span>
            </div>
            {detail.loading && detail.events.length === 0 ? (
              <div className="flex min-h-20 items-center justify-center gap-2 text-xs text-foreground/45">
                <Loader2 size={14} className="animate-spin" />
                正在读取运行记录
              </div>
            ) : visibleEvents.length === 0 ? (
              <p className="py-5 text-center text-xs text-foreground/40">尚无可显示事件</p>
            ) : (
              <ol className="divide-y divide-outline-variant/25" aria-label="任务事件列表">
                {visibleEvents.map((event) => (
                  <li key={event.eventId} className="grid grid-cols-[auto_minmax(0,1fr)] gap-2 py-2.5">
                    <span className="mt-1 h-1.5 w-1.5 rounded-full bg-primary/65" aria-hidden="true" />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <span className="font-label text-[11px] font-semibold text-foreground/70">
                          {formatRuntimeEventLabel(event.eventType, t)}
                        </span>
                        <span className="font-label text-[10px] text-foreground/35">#{event.sequence}</span>
                        <span className="font-label text-[10px] text-foreground/35">{formatTimestamp(event.timestamp)}</span>
                      </div>
                      {event.stage ? <p className="mt-0.5 truncate text-[11px] text-primary/75">{event.stage}</p> : null}
                      {event.message ? <p className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-foreground/50">{event.message}</p> : null}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>

        <aside className="min-h-0 overflow-y-auto px-4 py-3" aria-label="任务产物摘要">
          <div className="flex items-center justify-between gap-2">
            <h3 className="inline-flex items-center gap-1.5 font-label text-xs font-semibold text-foreground/65">
              <FileText size={13} />
              产物
            </h3>
            <span className="text-[10px] text-foreground/35">{detail.artifactCount} 项</span>
          </div>
          {detail.artifactErrorMessage ? (
            <p className="mt-2 rounded-md border border-amber-200/70 bg-amber-50/70 px-2.5 py-2 text-[11px] leading-4 text-amber-800 dark:border-amber-700/40 dark:bg-amber-950/25 dark:text-amber-200" role="status">
              {detail.artifactErrorMessage}
            </p>
          ) : null}
          {detail.artifacts.length === 0 ? (
            <p className="py-5 text-center text-xs text-foreground/40">暂无产物记录</p>
          ) : (
            <ul className="mt-2 divide-y divide-outline-variant/25">
              {detail.artifacts.map((artifact) => (
                <li key={artifact.artifactId} className="flex items-center gap-2 py-2.5">
                  <FileText size={13} className="shrink-0 text-primary/60" />
                  <span className="min-w-0 flex-1 truncate text-xs text-foreground/65">
                    {artifactLabel(artifact.artifactType)}
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1 font-label text-[10px] text-foreground/35">
                    <Clock size={10} />
                    {formatTimestamp(artifact.createdAt)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 border-t border-outline-variant/25 pt-3 text-[10px] leading-4 text-foreground/35">
            此处仅显示类型与时间。内容、路径和内部标识不会在任务中心展开。
          </p>
        </aside>
      </div>
    </section>
  );
}
