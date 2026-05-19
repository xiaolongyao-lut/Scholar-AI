import { cn } from '@/lib/utils';

interface CitationChipProps {
  /** Friendly source label, e.g. "Vaswani 2017" or chunk excerpt. Never a raw ID. */
  label: string;
  /** Optional page label, e.g. "p.7". */
  page?: number | string | null;
  selected?: boolean;
  onClick?: () => void;
  className?: string;
  title?: string;
}

/**
 * Canonical inline citation chip. Lighter than `EvidencePill`: no
 * locator round-trip, no navigation responsibility. Use for inline
 * citations inside transcripts, message bodies, wiki claims.
 *
 * R5 / R5.1: caller MUST pass a friendly label. The chip itself never
 * formats raw IDs.
 */
export function CitationChip({ label, page, selected, onClick, className, title }: CitationChipProps) {
  const Tag: 'button' | 'span' = onClick ? 'button' : 'span';
  return (
    <Tag
      {...(onClick ? { type: 'button' as const, onClick } : {})}
      title={title ?? label}
      aria-pressed={onClick && selected ? true : undefined}
      className={cn(
        'inline-flex items-center gap-1 rounded border px-1.5 py-px text-[10px] font-medium transition-colors align-baseline',
        selected
          ? 'border-primary bg-primary/10 text-primary'
          : 'border-outline-variant/70 bg-surface-low text-foreground/70',
        onClick && 'cursor-pointer hover:border-primary/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        className,
      )}
    >
      <span className="max-w-[140px] truncate">{label}</span>
      {page != null && page !== '' && (
        <span className="text-[9px] opacity-70">p.{String(page)}</span>
      )}
    </Tag>
  );
}
