import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import type { AnalysisChainPayload } from '@/services/discussionApi';

/**
 * Shared collapsible renderer for a 6-field AnalysisChain.
 *
 * Used by DiscussionPanel (per-agent), Dialog inspiration, and (future)
 * Workbench sources panel. Renders nothing when the chain has no
 * meaningful content so callers can pass partial chains without
 * conditional rendering on their side.
 */

interface AnalysisChainPanelProps {
  chain: AnalysisChainPayload | null | undefined;
  /** Compact 4-line header when collapsed; expand for full 6 fields. */
  defaultExpanded?: boolean;
  /** Wrapper class — caller controls outer spacing/borders. */
  className?: string;
}

function _hasContent(chain: AnalysisChainPayload): boolean {
  return Boolean(
    (chain.observation && chain.observation.trim()) ||
      (chain.mechanism && chain.mechanism.trim()) ||
      (chain.evidence && chain.evidence.length > 0) ||
      (chain.boundary && chain.boundary.trim()) ||
      (chain.counter_evidence && chain.counter_evidence.length > 0) ||
      (chain.next_action && chain.next_action.trim()),
  );
}

export function AnalysisChainPanel({
  chain,
  defaultExpanded = false,
  className,
}: AnalysisChainPanelProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (!chain || !_hasContent(chain)) {
    return null;
  }

  return (
    <div
      className={cn(
        'rounded-md border border-outline-variant/60 bg-surface-low/40 text-xs',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-foreground/60 transition-colors hover:text-foreground"
        aria-expanded={expanded}
      >
        <span className="flex items-center gap-1.5 font-medium">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {t('analysis_chain.section_label') || 'AI 推理过程'}
        </span>
        <span className="text-[10px] text-foreground/40">
          {expanded ? t('analysis_chain.collapse') : t('analysis_chain.expand')}
        </span>
      </button>
      {expanded && (
        <dl className="space-y-2 px-3 pb-3 pt-1 text-foreground/75">
          <Field label={t('analysis_chain.field_observation') || '观察'} value={chain.observation} />
          <Field label={t('analysis_chain.field_mechanism') || '机制'} value={chain.mechanism} />
          <FieldList
            label={t('analysis_chain.field_evidence') || '证据'}
            values={chain.evidence}
          />
          <Field label={t('analysis_chain.field_boundary') || '适用范围'} value={chain.boundary} />
          <FieldList
            label={t('analysis_chain.field_counter_evidence') || '反证'}
            values={chain.counter_evidence}
          />
          <Field
            label={t('analysis_chain.field_next_action') || '下一步'}
            value={chain.next_action}
          />
        </dl>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string }) {
  const trimmed = (value ?? '').trim();
  if (!trimmed) return null;
  return (
    <div>
      <dt className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-foreground/45">
        {label}
      </dt>
      <dd className="leading-relaxed">{trimmed}</dd>
    </div>
  );
}

function FieldList({ label, values }: { label: string; values?: string[] }) {
  const filtered = (values ?? []).map((v) => v.trim()).filter(Boolean);
  if (filtered.length === 0) return null;
  return (
    <div>
      <dt className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-foreground/45">
        {label}
      </dt>
      <dd>
        <ul className="ml-4 list-disc space-y-0.5 leading-relaxed">
          {filtered.map((value, idx) => (
            <li key={idx}>{value}</li>
          ))}
        </ul>
      </dd>
    </div>
  );
}
