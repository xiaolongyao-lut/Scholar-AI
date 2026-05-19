import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from '@/contexts/ThemeContext';
import { cn } from '@/lib/utils';
import type { ThemeMode } from '@/hooks/useThemeMode';

const OPTIONS: Array<{ value: ThemeMode; icon: typeof Sun; label: string; title: string }> = [
  { value: 'light', icon: Sun, label: '浅', title: '浅色模式' },
  { value: 'dark', icon: Moon, label: '深', title: '深色模式' },
  { value: 'system', icon: Monitor, label: '系统', title: '跟随系统' },
];

export function ThemeToggle({ className }: { className?: string }) {
  const { mode, setMode } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="主题模式"
      className={cn(
        'inline-flex items-center gap-0.5 rounded-md border border-outline-variant/60 bg-surface-low p-0.5',
        className,
      )}
    >
      {OPTIONS.map(({ value, icon: Icon, label, title }) => {
        const active = mode === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={title}
            title={title}
            onClick={() => setMode(value)}
            className={cn(
              'inline-flex items-center gap-1 rounded-sm px-2 py-1 text-xs font-medium transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              active
                ? 'bg-surface-lowest text-foreground shadow-sm'
                : 'text-foreground/55 hover:text-foreground hover:bg-surface-default/60',
            )}
          >
            <Icon size={13} strokeWidth={1.75} />
            <span className="hidden sm:inline">{label}</span>
          </button>
        );
      })}
    </div>
  );
}
