// AuditPanel — operator roll-up for `/evolution/audit`.
//
// Renders aggregate counts (total + by status / memory_type / source_type +
// promotion outcomes) plus a collapsed "advanced" tray with the last few
// decision_reason strings. The endpoint intentionally exposes aggregate and
// recent-decision metadata only, so candidate content stays out of this panel.
//
// Default-on, kill-switch-gated by `review_ui_enabled` (handled by the parent
// `EvolutionInbox` page). When the panel itself encounters an error or has
// zero data it surfaces a friendly Chinese message and a Refresh button.
//
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BookOpenCheck, RefreshCw } from 'lucide-react';

import { cn } from '@/lib/utils';
import {
  getEvolutionAudit,
  type EvolutionAuditPayload,
} from '../../services/evolutionApi';
import {
  friendlyDecisionReason,
  formatEvolutionError,
  MEMORY_TYPE_LABELS,
  sanitizeEvolutionUserText,
  SOURCE_LABELS,
  STATUS_LABELS,
  STATUS_TONES,
} from './labels';
import type {
  CandidateMemoryType,
  CandidateSourceType,
  CandidateStatus,
} from '../../services/evolutionTypes';
import { StatusPill } from '../common/StatusPill';

const PROMOTION_LABELS: Record<
  'promoted_to_memory' | 'promoted_to_skill_draft' | 'rolled_back',
  string
> = {
  promoted_to_memory: '已应用到长期记忆',
  promoted_to_skill_draft: '已生成流程草稿',
  rolled_back: '已撤销',
};

/** Format an ISO timestamp into a short local time string. */
function formatDecidedAt(iso: string | null): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  return new Date(t).toLocaleString();
}

interface CountRowProps {
  label: string;
  value: number;
  testId?: string;
}

function CountRow({ label, value, testId }: CountRowProps) {
  return (
    <div
      className="flex items-center justify-between rounded border border-outline-variant/40 bg-surface-lowest px-2 py-1 text-xs"
      data-testid={testId}
    >
      <span className="truncate text-foreground/70">{label}</span>
      <span className="font-mono text-foreground/85">{value}</span>
    </div>
  );
}

interface CountSectionProps<K extends string> {
  title: string;
  counts: Partial<Record<K, number>>;
  labels: Record<K, string>;
  testIdPrefix: string;
}

function CountSection<K extends string>({
  title,
  counts,
  labels,
  testIdPrefix,
}: CountSectionProps<K>) {
  const entries = (Object.entries(counts) as Array<[K, number]>).filter(
    ([, n]) => n > 0,
  );
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-label uppercase tracking-wide text-foreground/50">
        {title}
      </div>
      {entries.length === 0 ? (
        <div
          className="rounded border border-dashed border-outline-variant/40 px-2 py-1.5 text-[11px] italic text-foreground/40"
          data-testid={`${testIdPrefix}-empty`}
        >
          —
        </div>
      ) : (
        <div className="grid gap-1">
          {entries.map(([key, n]) => (
            <CountRow
              key={key}
              label={labels[key] ?? key}
              value={n}
              testId={`${testIdPrefix}-${key}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export interface AuditPanelProps {
  /** Optional workspace filter forwarded to `/evolution/audit?workspace_id=`. */
  workspaceId?: string;
  /** How many `recent_decisions` rows to request. Backend clamps to [0,50]. */
  recentDecisionLimit?: number;
}

export function AuditPanel({
  workspaceId,
  recentDecisionLimit = 10,
}: AuditPanelProps) {
  const [data, setData] = useState<EvolutionAuditPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAudit = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const payload = await getEvolutionAudit({ workspaceId, recentDecisionLimit });
      setData(payload);
    } catch (err) {
      setError(formatEvolutionError(err, '收纳总览加载失败，请稍后重试。'));
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, recentDecisionLimit]);

  useEffect(() => {
    void fetchAudit();
  }, [fetchAudit]);

  const workspaceLabel = workspaceId
    ? ` · 范围 ${sanitizeEvolutionUserText(workspaceId, '当前工作区')}`
    : '';

  return (
    <section
      data-testid="evolution-audit-panel"
      aria-label="经验收纳总览"
      className="rounded-lg border border-outline-variant/60 bg-surface-low p-3 space-y-3"
    >
      <header className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <BookOpenCheck size={14} className="text-foreground/60 flex-shrink-0" />
          <span className="text-xs font-label text-foreground/70 truncate">
            收纳总览
            <span className="ml-1 text-foreground/40">
              · 共 {data?.total ?? 0} 条候选
              {workspaceLabel}
            </span>
          </span>
        </div>
        <button
          type="button"
          onClick={() => void fetchAudit()}
          disabled={isLoading}
          className="inline-flex items-center gap-1 text-xs font-label text-foreground/60 transition-colors hover:text-foreground/85 disabled:cursor-wait disabled:opacity-50"
          data-testid="evolution-audit-refresh"
          aria-label="刷新收纳总览"
        >
          <RefreshCw size={12} className={cn(isLoading && 'animate-spin')} />
          {isLoading ? '加载中…' : '刷新'}
        </button>
      </header>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300"
          data-testid="evolution-audit-error"
        >
          <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
          <span className="min-w-0 break-words">{error}</span>
        </div>
      )}

      {!error && data && data.total === 0 && !isLoading && (
        <div
          className="rounded border border-dashed border-outline-variant/50 px-3 py-4 text-center text-xs text-foreground/50"
          data-testid="evolution-audit-empty"
        >
          暂无候选经验。
        </div>
      )}

      {!error && data && data.total > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <CountSection<CandidateStatus>
              title="按状态"
              counts={data.by_status}
              labels={STATUS_LABELS}
              testIdPrefix="evolution-audit-status"
            />
            <CountSection<CandidateMemoryType>
              title="按记忆类型"
              counts={data.by_memory_type}
              labels={MEMORY_TYPE_LABELS}
              testIdPrefix="evolution-audit-memory"
            />
            <CountSection<CandidateSourceType>
              title="按来源"
              counts={data.by_source_type}
              labels={SOURCE_LABELS}
              testIdPrefix="evolution-audit-source"
            />
            <CountSection<'promoted_to_memory' | 'promoted_to_skill_draft' | 'rolled_back'>
              title="应用结果"
              counts={data.promotion_outcomes}
              labels={PROMOTION_LABELS}
              testIdPrefix="evolution-audit-promotion"
            />
          </div>

          {data.recent_decisions.length > 0 && (
            <details
              className="rounded border border-outline-variant/40 bg-surface-lowest px-2 py-1.5"
              data-testid="evolution-audit-recent"
            >
              <summary className="cursor-pointer list-none text-xs font-label text-foreground/65 hover:text-foreground/85">
                最近的处置
                <span className="ml-1 text-foreground/40">
                  · {data.recent_decisions.length} 条
                </span>
              </summary>
              <ul className="mt-2 space-y-1.5">
                {data.recent_decisions.map((row, index) => (
                  <li
                    key={`${row.candidate_id}-${row.decided_at ?? 'na'}`}
                    className="flex items-start justify-between gap-2 rounded border border-outline-variant/30 bg-surface-low px-2 py-1.5 text-[11px]"
                    data-testid={`evolution-audit-recent-row-${index}`}
                  >
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex items-center gap-1.5">
                        <StatusPill tone={STATUS_TONES[row.status]}>
                          {STATUS_LABELS[row.status]}
                        </StatusPill>
                        <span className="truncate text-foreground/70">
                          {friendlyDecisionReason(row.decision_reason)}
                        </span>
                      </div>
                    </div>
                    <span className="flex-shrink-0 whitespace-nowrap text-[10px] text-foreground/45">
                      {formatDecidedAt(row.decided_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      {!error && isLoading && data === null && (
        <div
          className="rounded border border-dashed border-outline-variant/40 px-3 py-4 text-center text-xs text-foreground/40"
          data-testid="evolution-audit-loading"
        >
          正在加载收纳总览…
        </div>
      )}
    </section>
  );
}

export const __test = { friendlyDecisionReason, formatDecidedAt, PROMOTION_LABELS };
