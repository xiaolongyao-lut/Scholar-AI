// PaginationBar — prev/next using the backend's real total.
//
// Boundary rules enforced here (the parent should not have to repeat them):
//   - prev disabled when offset === 0
//   - next disabled when offset + limit >= total
//   - prev jump clamps to 0
//   - next jump never exceeds total (we never set offset === total because
//     that would render an empty page; we cap at the last valid page start)

import { ChevronLeft, ChevronRight } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface PaginationBarProps {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (nextOffset: number) => void;
}

export function PaginationBar({ total, limit, offset, onPageChange }: PaginationBarProps) {
  const safeLimit = Math.max(1, limit);
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(total, offset + safeLimit);
  const prevDisabled = offset <= 0;
  const nextDisabled = offset + safeLimit >= total;

  const handlePrev = () => {
    if (prevDisabled) return;
    onPageChange(Math.max(0, offset - safeLimit));
  };

  const handleNext = () => {
    if (nextDisabled) return;
    const lastPageStart = Math.max(0, (Math.ceil(total / safeLimit) - 1) * safeLimit);
    const nextOffset = Math.min(offset + safeLimit, lastPageStart);
    onPageChange(nextOffset);
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-outline-variant/40 bg-surface-low px-3 py-2 text-xs">
      <div className="font-label text-foreground/50">
        {total === 0
          ? '没有可显示的条目'
          : `第 ${start}-${end} 项 / 共 ${total} 项`}
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handlePrev}
          disabled={prevDisabled}
          aria-label="上一页"
          className={cn(
            'inline-flex items-center gap-1 rounded-md border border-outline-variant/60 bg-surface-high px-2.5 py-1 text-xs font-label text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground',
            'disabled:cursor-not-allowed disabled:opacity-40',
          )}
        >
          <ChevronLeft size={14} />
          上一页
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={nextDisabled}
          aria-label="下一页"
          className={cn(
            'inline-flex items-center gap-1 rounded-md border border-outline-variant/60 bg-surface-high px-2.5 py-1 text-xs font-label text-foreground/70 transition-colors hover:border-primary/40 hover:text-foreground',
            'disabled:cursor-not-allowed disabled:opacity-40',
          )}
        >
          下一页
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
