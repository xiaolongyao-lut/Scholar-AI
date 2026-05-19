// CandidateDetailDrawer — accessible side/sheet drawer for advanced fields.
//
// WAI-ARIA dialog pattern:
//   role="dialog", aria-modal="true", aria-labelledby=<heading id>
//   Escape closes; backdrop click closes; visible close button
//   Initial focus moves into the drawer; closing returns focus to opener
//   Tab cycles within the drawer (basic focus loop, not a full FocusTrap lib)
//
// Layout:
//   Desktop: 480px slide-over from the right edge
//   Mobile (<640px): full-height bottom sheet behavior is approximated by
//   using `inset-y-0 right-0 w-full sm:w-[480px]` — full-width on phones,
//   anchored panel on tablet+. No external sheet library to keep the slice
//   self-contained.

import { useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';

import { cn } from '@/lib/utils';
import { StatusPill } from '../common/StatusPill';
import type { ExperienceCandidate } from '../../services/evolutionTypes';
import {
  MEMORY_TYPE_LABELS,
  RISK_LABELS,
  RISK_TONES,
  SOURCE_LABELS,
  STATUS_LABELS,
  STATUS_TONES,
} from './labels';

export interface CandidateDetailDrawerProps {
  candidate: ExperienceCandidate | null;
  open: boolean;
  onClose: () => void;
}

function MetaRow({ label, value, mono = false }: { label: string; value: string | null; mono?: boolean }) {
  return (
    <div className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-0.5 py-1.5">
      <dt className="font-label text-[11px] text-foreground/45">{label}</dt>
      <dd className={cn('min-w-0 break-all text-xs text-foreground/75', mono && 'font-mono')}>
        {value ?? <span className="text-foreground/30">—</span>}
      </dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-outline-variant/30 px-5 py-4 first:border-t-0">
      <h3 className="mb-2 font-label text-[11px] uppercase tracking-[0.16em] text-foreground/40">{title}</h3>
      <div className="space-y-1">{children}</div>
    </section>
  );
}

export function CandidateDetailDrawer({ candidate, open, onClose }: CandidateDetailDrawerProps) {
  const headingId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const openerRef = useRef<Element | null>(null);

  // Focus management: capture opener on open; restore on close; initial focus
  // moves to the close button (always visible, predictable target).
  useEffect(() => {
    if (open) {
      openerRef.current = document.activeElement;
      // Defer to next tick so the panel is in the DOM.
      const id = window.setTimeout(() => closeButtonRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
    if (openerRef.current instanceof HTMLElement) {
      openerRef.current.focus();
    }
    return undefined;
  }, [open]);

  // Escape close + basic focus trap within the panel.
  useEffect(() => {
    if (!open) return undefined;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !panelRef.current) return;
      const focusables = panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !candidate) return null;

  const evidenceJson = JSON.stringify(candidate.evidence_refs, null, 2);

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex justify-end"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {/* backdrop */}
      <div className="absolute inset-0 bg-foreground/30 backdrop-blur-[1px]" aria-hidden="true" />

      {/* panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        className="relative z-10 flex h-full w-full max-w-full flex-col bg-surface-lowest shadow-xl sm:w-[480px]"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-outline-variant/40 px-5 py-4">
          <div className="min-w-0">
            <p className="font-label text-[11px] uppercase tracking-[0.16em] text-foreground/40">
              详细信息（高级）
            </p>
            <h2
              id={headingId}
              className="mt-1 truncate font-headline text-sm font-semibold text-foreground"
              title={candidate.title}
            >
              {candidate.title}
            </h2>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="关闭详情"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-high text-foreground/60 transition-colors hover:border-primary/40 hover:text-foreground"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto">
          <Section title="来源记录">
            <MetaRow label="来源类型" value={SOURCE_LABELS[candidate.source_type]} />
            <MetaRow label="经验类型" value={MEMORY_TYPE_LABELS[candidate.memory_type]} />
            <MetaRow label="路由" value={candidate.source_route} mono />
            <MetaRow label="来源 ID" value={candidate.source_id} mono />
            <div className="mt-2">
              <p className="font-label text-[11px] text-foreground/45">来源摘要</p>
              <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-foreground/75">
                {candidate.source_summary}
              </p>
            </div>
          </Section>

          <Section title={`证据引用（${candidate.evidence_refs.length}）`}>
            {candidate.evidence_refs.length === 0 ? (
              <p className="text-xs text-foreground/40">无证据引用</p>
            ) : (
              <pre className="max-h-48 overflow-auto rounded-md border border-outline-variant/30 bg-surface-low p-2 font-mono text-[11px] leading-4 text-foreground/70">
                {evidenceJson}
              </pre>
            )}
          </Section>

          <Section title="去重哈希">
            <code className="break-all font-mono text-[11px] text-foreground/65">
              {candidate.dedupe_hash}
            </code>
          </Section>

          <Section title="风险等级">
            <StatusPill tone={RISK_TONES[candidate.risk_level]}>
              {RISK_LABELS[candidate.risk_level]}
            </StatusPill>
          </Section>

          <Section title="状态">
            <StatusPill tone={STATUS_TONES[candidate.status]}>
              {STATUS_LABELS[candidate.status]}
            </StatusPill>
            {candidate.decision_reason && (
              <p className="mt-2 text-xs text-foreground/60">{candidate.decision_reason}</p>
            )}
          </Section>

          <Section title="回滚句柄">
            <code className="break-all font-mono text-[11px] text-foreground/65">
              {candidate.rollback_ref ?? '—'}
            </code>
          </Section>

          <Section title="候选 ID">
            <code className="break-all font-mono text-[11px] text-foreground/65">
              {candidate.candidate_id}
            </code>
          </Section>
        </div>
      </div>
    </div>
  );
}
