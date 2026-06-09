// PromoteButton — kill-switch-aware promote control.
//
// Two-step UX: idle button → inline confirm popover (Yes/No). No modal.
// Copy adapts to memory_type:
//   - skill_draft → "生成流程草稿"
//   - everything else → "应用到长期记忆"
//
// When the long-term-memory action is disabled, the tooltip stays user-facing.

import { useState } from 'react';
import { Sparkles } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { CandidateMemoryType } from '../../services/evolutionTypes';

export interface PromoteButtonProps {
  memoryType: CandidateMemoryType;
  promotionEnabled: boolean;
  pending?: boolean;
  onConfirm: () => void;
}

function promoteLabel(memoryType: CandidateMemoryType): string {
  return memoryType === 'skill_draft' ? '生成流程草稿' : '应用到长期记忆';
}

export function PromoteButton({
  memoryType,
  promotionEnabled,
  pending = false,
  onConfirm,
}: PromoteButtonProps) {
  const [confirming, setConfirming] = useState(false);
  const label = promoteLabel(memoryType);

  if (!promotionEnabled) {
    return (
      <button
        type="button"
        disabled
        title="长期记忆功能尚未开启。请到设置的功能开关中打开后再应用。"
        aria-label={`${label}（功能尚未开启）`}
        className="inline-flex items-center gap-1.5 rounded-md border border-outline-variant/60 bg-surface-high px-3 py-1.5 text-xs font-label text-foreground/40 disabled:cursor-not-allowed"
      >
        <Sparkles size={14} />
        {label}
      </button>
    );
  }

  if (!confirming) {
    return (
      <button
        type="button"
        disabled={pending}
        onClick={() => setConfirming(true)}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-label text-primary transition-colors hover:bg-primary/20',
          'disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        <Sparkles size={14} />
        {pending ? `${label}中…` : label}
      </button>
    );
  }

  return (
    <span
      role="group"
      aria-label={`确认${label}`}
      className="inline-flex items-center gap-1 rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-xs"
    >
      <span className="font-label text-primary/80">确认{label}？</span>
      <button
        type="button"
        onClick={() => setConfirming(false)}
        className="rounded-sm px-2 py-0.5 font-label text-foreground/55 transition-colors hover:bg-surface-high hover:text-foreground"
      >
        取消
      </button>
      <button
        type="button"
        onClick={() => {
          setConfirming(false);
          onConfirm();
        }}
        className="rounded-sm bg-primary px-2 py-0.5 font-label text-primary-foreground transition-colors hover:bg-primary/90"
      >
        确认
      </button>
    </span>
  );
}
