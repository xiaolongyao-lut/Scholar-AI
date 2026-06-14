// Evolution candidate card — compact, dense, Chinese-first review row.
//
// Presentational only: receives a candidate + callbacks, does not call the
// API directly. The page (EvolutionInbox) owns refetch and undo wiring.
//
// Status-aware action rendering:
//   pending/captured: 详情 / 稍后 / 忽略 / 保存
//   blocked:          详情 only + short reason text (save disabled)
//   accepted/snoozed/rejected/expired/rolled_back: status pill, no actions
//   promoted_to_*:    rollback button is wired via `slot="promoted"`
//
// All visible labels are Chinese. Internal
// tracing fields stay out of the card surface.

import { Eye, Clock3, X as XIcon, Save, ShieldAlert } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';
import { StatusPill } from '../common/StatusPill';
import type { ExperienceCandidate } from '../../services/evolutionTypes';
import {
  deriveEvidenceState,
  EVIDENCE_STATE_LABELS,
  EVIDENCE_STATE_TONES,
  friendlyDecisionReason,
  MEMORY_TYPE_LABELS,
  RISK_LABELS,
  RISK_TONES,
  sanitizeEvolutionDetailText,
  sanitizeEvolutionUserText,
  SOURCE_LABELS,
  STATUS_LABELS,
  STATUS_TONES,
} from './labels';

export type CardPendingAction = 'accept' | 'reject' | 'snooze' | null;

export interface CandidateCardProps {
  candidate: ExperienceCandidate;
  /** Marks one action in-flight so the row's buttons stay disabled. */
  pendingAction?: CardPendingAction;
  onAccept: () => void;
  onReject: () => void;
  onSnooze: () => void;
  onOpenDetails: () => void;
  /** Action slot rendered at the end of the action row regardless of status.
   *  Page-level logic chooses what to render (PromoteButton for accepted,
   *  rollback for promoted) so the card stays presentational. */
  extraActions?: ReactNode;
}

const ACTIONABLE_STATUSES = new Set(['pending', 'captured']);

function CardField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[5rem_1fr] gap-x-3 gap-y-0.5 text-sm">
      <div className="font-label text-[11px] leading-6 text-foreground/40">{label}</div>
      <div className="min-w-0 text-foreground/80">{children}</div>
    </div>
  );
}

function promotionTargetLabel(memoryType: ExperienceCandidate['memory_type']): string {
  return memoryType === 'skill_draft' ? '流程草稿' : '长期记忆';
}

export function CandidateCard({
  candidate,
  pendingAction = null,
  onAccept,
  onReject,
  onSnooze,
  onOpenDetails,
  extraActions,
}: CandidateCardProps) {
  const isActionable = ACTIONABLE_STATUSES.has(candidate.status);
  const isBlocked = candidate.status === 'blocked';
  const anyPending = pendingAction !== null;
  const title = sanitizeEvolutionUserText(candidate.title, '待复审经验');
  const claim = sanitizeEvolutionDetailText(candidate.claim, title, 260);
  const futureUse = sanitizeEvolutionUserText(candidate.future_use, '后续参考。');
  const targetLabel = promotionTargetLabel(candidate.memory_type);
  const reviewTask = `确认这条“${MEMORY_TYPE_LABELS[candidate.memory_type]}”是否准确、可复用，并决定是否写入${targetLabel}。`;

  const evidenceState = deriveEvidenceState({
    status: candidate.status,
    risk_level: candidate.risk_level,
    evidence_count: candidate.evidence_refs.length,
    decision_reason: candidate.decision_reason,
  });

  return (
    <article
      className={cn(
        'rounded-lg border border-outline-variant/60 bg-surface-lowest px-4 py-3',
        'transition-shadow hover:shadow-sm',
        isBlocked && 'border-red-300/50',
      )}
      aria-label={`经验候选：${title}`}
    >
      {/* meta row — type + risk + status + evidence */}
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <StatusPill tone="primary">{SOURCE_LABELS[candidate.source_type]}</StatusPill>
        <StatusPill tone="neutral">{MEMORY_TYPE_LABELS[candidate.memory_type]}</StatusPill>
        <StatusPill tone={RISK_TONES[candidate.risk_level]}>
          {RISK_LABELS[candidate.risk_level]}
        </StatusPill>
        <StatusPill tone={EVIDENCE_STATE_TONES[evidenceState]}>
          {EVIDENCE_STATE_LABELS[evidenceState]}
        </StatusPill>
        {!isActionable && (
          <StatusPill tone={STATUS_TONES[candidate.status]}>
            {STATUS_LABELS[candidate.status]}
          </StatusPill>
        )}
      </div>

      {/* User-facing fields only; diagnostic capture payloads stay hidden. */}
      <div className="space-y-1.5">
        <CardField label="复审任务">
          <span className="text-foreground/75">{reviewTask}</span>
        </CardField>
        <CardField label="学到了什么">
          <span className="font-medium text-foreground">{title}</span>
        </CardField>
        <CardField label="具体内容">
          <span className="line-clamp-2 text-foreground/75">{claim}</span>
        </CardField>
        <CardField label="来自哪里">{SOURCE_LABELS[candidate.source_type]}</CardField>
        <CardField label="以后怎么用">{futureUse}</CardField>
        <CardField label="保存位置">{targetLabel}</CardField>
      </div>

      {/* blocked reason — short non-actionable */}
      {isBlocked && candidate.decision_reason && (
        <div className="mt-3 flex items-start gap-2 rounded-md border border-red-200/60 bg-red-50/70 px-3 py-2 text-xs text-red-700 dark:bg-red-950/30 dark:text-red-300 dark:border-red-800/50">
          <ShieldAlert size={14} className="mt-0.5 shrink-0" />
          <span>不能保存：{friendlyDecisionReason(candidate.decision_reason)}</span>
        </div>
      )}

      {/* action row — stable height */}
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-outline-variant/30 pt-3">
        <button
          type="button"
          onClick={onOpenDetails}
          className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-high px-3 py-1.5 text-xs font-label text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground"
          aria-label={`查看「${title}」的详细信息`}
        >
          <Eye size={14} />
          详情
        </button>

        {isActionable && (
          <>
            <button
              type="button"
              onClick={onSnooze}
              disabled={anyPending}
              className="inline-flex min-w-[64px] items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-high px-3 py-1.5 text-xs font-label text-foreground/70 transition-colors hover:border-sky-300/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              title="这条候选先不处理，7 天后再提醒"
            >
              <Clock3 size={14} />
              {pendingAction === 'snooze' ? '处理中…' : '稍后'}
            </button>
            <button
              type="button"
              onClick={onReject}
              disabled={anyPending}
              className="inline-flex min-w-[64px] items-center justify-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-high px-3 py-1.5 text-xs font-label text-foreground/70 transition-colors hover:border-red-300/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              title="确认这条候选不准确或不可复用，永久忽略"
            >
              <XIcon size={14} />
              {pendingAction === 'reject' ? '处理中…' : '忽略'}
            </button>
            <button
              type="button"
              onClick={onAccept}
              disabled={anyPending}
              className="inline-flex min-w-[64px] items-center justify-center gap-1.5 rounded-md border border-primary/40 bg-primary px-3 py-1.5 text-xs font-label text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Save size={14} />
              {pendingAction === 'accept' ? '保存中…' : `保存到${targetLabel}`}
            </button>
          </>
        )}

        {isBlocked && (
          <span className="text-xs font-label text-foreground/40">不可保存</span>
        )}

        {extraActions}
      </div>
    </article>
  );
}
