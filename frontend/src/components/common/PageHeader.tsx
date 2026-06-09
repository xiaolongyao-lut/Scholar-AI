import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /** Optional icon (lucide-react element). Stays small (16-18px). */
  icon?: ReactNode;
  /** Right-side action buttons / primary CTA. */
  actions?: ReactNode;
  className?: string;
}

/**
 * Canonical page header — H1 + subtitle + right-aligned actions.
 *
 * Used by index / dashboard / settings / writing surfaces (Slices D–I) so
 * every page has the same density, typography rhythm, and CTA placement.
 * Replaces the ad-hoc `<div className="flex … mb-8">` blocks scattered
 * across pages today.
 */
export function PageHeader({ title, subtitle, icon, actions, className }: PageHeaderProps) {
  return (
    <div
      className={cn(
        'mb-6 flex min-w-0 flex-col gap-4 lg:flex-row lg:items-end lg:justify-between',
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        <h1 className="flex min-w-0 items-center gap-2 font-display text-2xl font-semibold text-foreground">
          {icon && <span className="shrink-0 text-primary/70">{icon}</span>}
          <span className="truncate">{title}</span>
        </h1>
        {subtitle && (
          <p className="mt-1 max-w-4xl break-words font-label text-sm leading-5 text-foreground/55">
            {subtitle}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex max-w-full shrink-0 flex-wrap items-center justify-start gap-2 lg:justify-end">
          {actions}
        </div>
      )}
    </div>
  );
}
