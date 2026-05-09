import { Tooltip } from '@/components/ui/Tooltip';
import { clsx } from 'clsx';
import type { ConfidenceLabel } from '@/services/intelligentChatApi';

interface ConfidenceBadgeProps {
  score?: number | null;
  label?: ConfidenceLabel | null;
}

const STYLE_BY_LABEL: Record<ConfidenceLabel, { bg: string; text: string; border: string; word: string }> = {
  high: { bg: 'bg-green-50', text: 'text-green-800', border: 'border-green-200', word: 'High' },
  medium: { bg: 'bg-amber-50', text: 'text-amber-800', border: 'border-amber-200', word: 'Medium' },
  low: { bg: 'bg-orange-50', text: 'text-orange-800', border: 'border-orange-200', word: 'Low' },
  very_low: { bg: 'bg-red-50', text: 'text-red-800', border: 'border-red-200', word: 'Very Low' },
};

export function ConfidenceBadge({ score, label }: ConfidenceBadgeProps) {
  if (!label) {
    return null;
  }
  const style = STYLE_BY_LABEL[label];
  const scoreText = typeof score === 'number' ? score.toFixed(3) : '—';
  const tooltip =
    `Evidence strength: ${style.word} (score ${scoreText}). ` +
    `Thresholds: high≥0.8 · medium≥0.5 · low≥0.3 · very_low<0.3. ` +
    `This reflects retrieval coverage, not answer correctness.`;
  return (
    <Tooltip content={tooltip}>
      <span
        className={clsx(
          'inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium cursor-help',
          style.bg,
          style.text,
          style.border,
        )}
      >
        Evidence: {style.word}
        <span className="font-mono opacity-70">({scoreText})</span>
      </span>
    </Tooltip>
  );
}
