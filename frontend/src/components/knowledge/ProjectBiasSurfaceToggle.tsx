import { CheckCircle2, CircleOff } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ProjectBiasSurfaceToggleProps {
  enabled: boolean;
  label?: string;
  onChange?: (enabled: boolean) => void;
  disabled?: boolean;
}

export function ProjectBiasSurfaceToggle({
  enabled,
  label = '项目偏置',
  onChange,
  disabled = false,
}: ProjectBiasSurfaceToggleProps) {
  const Icon = enabled ? CheckCircle2 : CircleOff;
  const interactive = typeof onChange === 'function' && !disabled;
  const buttonDisabled = disabled || typeof onChange !== 'function';
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={label}
      disabled={buttonDisabled}
      onClick={() => {
        if (!interactive) return;
        onChange(!enabled);
      }}
      className={cn(
        'inline-flex min-h-8 items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors',
        enabled
          ? 'border-emerald-400/60 bg-emerald-50 text-emerald-700 dark:border-emerald-700/50 dark:bg-emerald-500/15 dark:text-emerald-300'
          : 'border-outline-variant/60 bg-surface-low text-foreground/55 hover:text-foreground',
        interactive ? 'cursor-pointer' : 'cursor-default',
        buttonDisabled && 'opacity-60',
      )}
    >
      <Icon size={13} />
      <span>{label}</span>
    </button>
  );
}
