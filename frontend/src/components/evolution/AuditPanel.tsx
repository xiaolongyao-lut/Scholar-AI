// AuditPanel — operator roll-up for `/evolution/audit` (Opt §6).
//
// Renders aggregate counts (total + by status / memory_type / source_type +
// promotion outcomes) plus a collapsed "advanced" tray with the last few
// decision_reason strings. All values come from the backend Opt §6 endpoint;
// no raw candidate text (claim / title / future_use / source_summary) is ever
// surfaced through this panel because the endpoint itself does not expose it.
//
// Default-on, kill-switch-gated by `review_ui_enabled` (handled by the parent
// `EvolutionInbox` page). When the panel itself encounters an error or has
// zero data it surfaces a friendly Chinese message and a Refresh button.
//
// Reference:
//   - docs/plans/runbooks/evolution-opt6-audit-endpoint-20260519.md
//   - docs/plans/runbooks/evolution-round1-audit-panel-20260519.md
//   - frontend/src/components/settings/McpAuditPanel.tsx (in-repo precedent)

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BookOpenCheck, RefreshCw } from 'lucide-react';

import { cn } from '@/lib/utils';
import {
  getEvolutionAudit,
  type EvolutionAuditPayload,
} from '../../services/evolutionApi';
import {
  MEMORY_TYPE_LABELS,
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

/** Translate the common backend-written decision_reason prefixes into a
 *  one-line Chinese phrase. The raw string is always available in the
 *  advanced collapsed view; this translator is only for the human-readable
 *  one-liner. */
function friendlyDecisionReason(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '（无说明）';
  if (trimmed === 'ui_reject_permanent') return '用户标记为永久忽略';
  if (trimmed === 'ui_snooze_7d') return '用户稍后再看（7 天）';
  if (trimmed.startsWith('curator:')) return `系统整理：${trimmed.slice('curator:'.length).trim()}`;
  if (trimmed.startsWith('promoted:')) return `已应用：${trimmed.slice('promoted:'.length).trim()}`;
  if (trimmed.startsWith('secret_scan:')) return '被密钥扫描拦截';
  if (trimmed.startsWith('dedupe:')) return '重复候选，已合并';
  return trimmed;
}

/** Format an ISO timestamp into a short local time string. Returns the raw
 *  input on parse failure so the panel never silently swallows an unexpected
 *  format. */
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
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, recentDecisionLimit]);

  useEffect(() => {
    void fetchAudit();
  }, [fetchAudit]);

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
              {workspaceId ? ` · 工作区 ${workspaceId}` : ''}
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
          还没有任何候选经验被收纳，等系统从你的写作流程里学到内容后再来看看。
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
                {data.recent_decisions.map((row) => (
                  <li
                    key={`${row.candidate_id}-${row.decided_at ?? 'na'}`}
                    className="flex items-start justify-between gap-2 rounded border border-outline-variant/30 bg-surface-low px-2 py-1.5 text-[11px]"
                    data-testid={`evolution-audit-recent-row-${row.candidate_id}`}
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
                      <details className="ml-1 text-foreground/50">
                        <summary className="cursor-pointer list-none text-[10px] hover:text-foreground/70">
                          查看原始记录
                        </summary>
                        <div className="mt-1 space-y-0.5 rounded bg-surface-lowest px-1.5 py-1 font-mono text-[10px] text-foreground/65">
                          <div>id: {row.candidate_id}</div>
                          <div className="break-words whitespace-pre-wrap">
                            reason: {row.decision_reason}
                          </div>
                        </div>
                      </details>
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
