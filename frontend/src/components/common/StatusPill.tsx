import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

export type StatusTone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'info';

interface StatusPillProps {
  tone?: StatusTone;
  /** Pill body. */
  children: ReactNode;
  /** Small icon (lucide-react element). */
  icon?: ReactNode;
  className?: string;
  title?: string;
}

const TONE_CLASSES: Record<StatusTone, string> = {
  // Slate / neutral
  neutral: 'border-outline-variant/70 bg-surface-low text-foreground/65',
  // Primary (Scholar AI indigo-purple from --primary)
  primary: 'border-primary/40 bg-primary/10 text-primary',
  // Emerald — 通过 / 已完成 / 已索引
  success: 'border-emerald-300/60 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-700/50',
  // Amber — 警告 / 运行中 / 待处理
  warning: 'border-amber-300/60 bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-700/50',
  // Tomato / red — 未通过 / 失败
  danger: 'border-red-300/60 bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300 dark:border-red-700/50',
  // Sky — 信息 / 提示
  info: 'border-sky-300/60 bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-700/50',
};

/**
 * Canonical status pill — small, compact, Chinese-first.
 *
 * One tone vocabulary across the app. No inline color overrides; all
 * tones map to dark-mode-aware Tailwind utilities so light/dark behave
 * consistently.
 */
export function StatusPill({ tone = 'neutral', children, icon, className, title }: StatusPillProps) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium',
        TONE_CLASSES[tone],
        className,
      )}
    >
      {icon && <span className="shrink-0">{icon}</span>}
      <span className="truncate">{children}</span>
    </span>
  );
}
