import type { ElementType } from 'react';
import { AlertTriangle, Clock3, FileText, Lightbulb, Scale, ShieldCheck, Target } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { InspirationSpark } from '@/types/writing';
import {
  buildInspirationAnalysisDisplay,
  type InspirationAnalysisField,
} from '@/components/inspiration/inspirationDisplay';

const FIELD_ICON: Record<InspirationAnalysisField['key'], ElementType> = {
  observation: Lightbulb,
  mechanism: Scale,
  evidence: FileText,
  boundary: ShieldCheck,
  counter_evidence: AlertTriangle,
  next_action: Target,
};

interface InspirationAnalysisChainProps {
  spark: Pick<
    InspirationSpark,
    'analysis_chain' | 'fincot_chain' | 'frame' | 'confidence_reason' | 'temporal_sensitivity'
  >;
  className?: string;
  compact?: boolean;
}

function formatSensitivity(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function renderField(field: InspirationAnalysisField, compact: boolean): JSX.Element {
  const Icon = FIELD_ICON[field.key];
  return (
    <div
      key={field.key}
      className={cn(
        'rounded-sm border border-outline-variant/60 bg-surface-lowest',
        compact ? 'p-2.5' : 'p-3',
      )}
    >
      <div className="mb-1.5 flex items-center gap-2">
        <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-sm bg-primary/8 text-primary">
          <Icon size={12} />
        </span>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-foreground/50">
          {field.stageLabel}
        </span>
        <span className="text-[11px] font-medium text-foreground/65">
          {field.label}
        </span>
      </div>
      {field.kind === 'list' ? (
        <ul className="space-y-1.5">
          {field.values.map((value, index) => (
            <li key={`${field.key}:${index}:${value}`} className="flex gap-2 text-[11px] leading-5 text-foreground/70">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/45" />
              <span>{value}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[11px] leading-5 text-foreground/70">{field.values[0]}</p>
      )}
    </div>
  );
}

/**
 * Renders the public, six-field analysis summary attached to an Inspiration spark.
 *
 * The component intentionally accepts old or partial spark records; invalid
 * chain fields are omitted and the caller's normal spark content remains the
 * fallback display.
 */
export function InspirationAnalysisChain({
  spark,
  className,
  compact = false,
}: InspirationAnalysisChainProps): JSX.Element | null {
  const display = buildInspirationAnalysisDisplay(spark);
  if (!display) return null;

  return (
    <section
      aria-label={display.title}
      data-testid="inspiration-analysis-chain"
      className={cn(
        'rounded-sm border border-primary/15 bg-primary/[0.03]',
        compact ? 'p-3' : 'p-4',
        className,
      )}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-foreground/60">
          {display.title}
        </h3>
        {display.temporalSensitivity !== null && display.temporalSensitivity >= 0.5 && (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-300">
            <Clock3 size={11} />
            时效 {formatSensitivity(display.temporalSensitivity)}
          </span>
        )}
      </div>

      {display.fields.length > 0 && (
        <div className={cn('grid gap-2', compact ? 'grid-cols-1' : 'grid-cols-1 xl:grid-cols-2')}>
          {display.fields.map((field) => renderField(field, compact))}
        </div>
      )}

      {display.confidenceReason && (
        <p className="mt-3 rounded-sm border border-outline-variant/60 bg-surface-lowest px-3 py-2 text-[11px] leading-5 text-foreground/60">
          <span className="font-medium text-foreground/70">置信说明：</span>
          {display.confidenceReason}
        </p>
      )}
    </section>
  );
}
