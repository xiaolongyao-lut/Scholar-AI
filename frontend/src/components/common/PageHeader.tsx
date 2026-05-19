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
    <div className={cn('mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between', className)}>
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 font-display text-2xl font-semibold text-foreground">
          {icon && <span className="shrink-0 text-primary/70">{icon}</span>}
          <span className="truncate">{title}</span>
        </h1>
        {subtitle && <p className="mt-1 font-label text-sm text-foreground/55">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
