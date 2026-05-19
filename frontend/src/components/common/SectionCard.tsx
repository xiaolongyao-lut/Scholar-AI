import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

interface SectionCardProps {
  /** Optional section title. Renders an `<h2>` for accessibility. */
  title?: ReactNode;
  /** Right-aligned content for the section header (e.g. small actions). */
  headerRight?: ReactNode;
  /** Subtle line of helper text under the title. */
  subtitle?: ReactNode;
  /** Optional left-side icon next to the title. */
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Strip the inner padding (useful when embedding tables). */
  flushBody?: boolean;
}

/**
 * Canonical section card — restrained, dense, light/dark aware.
 *
 * Use it for grouped settings sections, dashboard panels, drawer panes,
 * and inspector slots. Replaces the mix of `bg-surface-lowest rounded-xl
 * shadow-…` blocks scattered across pages today.
 */
export function SectionCard({
  title,
  headerRight,
  subtitle,
  icon,
  children,
  className,
  bodyClassName,
  flushBody,
}: SectionCardProps) {
  const showHeader = title || headerRight || subtitle;
  return (
    <section
      className={cn(
        'rounded-lg border border-outline-variant/60 bg-surface-lowest',
        className,
      )}
    >
      {showHeader && (
        <header className="flex items-start justify-between gap-3 border-b border-outline-variant/40 px-4 py-3">
          <div className="min-w-0">
            {title && (
              <h2 className="flex items-center gap-2 font-headline text-sm font-semibold text-foreground">
                {icon && <span className="shrink-0 text-foreground/55">{icon}</span>}
                <span className="truncate">{title}</span>
              </h2>
            )}
            {subtitle && <p className="mt-0.5 font-label text-xs text-foreground/50">{subtitle}</p>}
          </div>
          {headerRight && <div className="flex shrink-0 items-center gap-2">{headerRight}</div>}
        </header>
      )}
      <div className={cn(flushBody ? '' : 'px-4 py-3', bodyClassName)}>{children}</div>
    </section>
  );
}
