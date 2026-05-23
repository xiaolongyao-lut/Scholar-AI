import { useRef, useEffect } from 'react';
import { X, FileText } from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePdfTabs } from '@/contexts/PdfTabsContext';

interface PdfTabStripProps {
  /** Called after the tab list mutates so the router can keep the URL
   *  pinned to the active tab. */
  onActivate: (materialId: string) => void;
  /** Called when the last tab closes; lets the page navigate away. */
  onEmpty: () => void;
}

/**
 * Horizontal, infinitely-scrolling tab strip on top of the workbench.
 *
 * Zotero #2955 / #2383: the strip is unbounded — bytes live in the
 * tab-context LRU, not here. Closing a tab evicts its bytes via the
 * context's closeTab().
 */
export function PdfTabStrip({ onActivate, onEmpty }: PdfTabStripProps) {
  const { tabs, activeId, setActive, closeTab } = usePdfTabs();
  const scrollerRef = useRef<HTMLDivElement>(null);
  const activeTabRef = useRef<HTMLButtonElement>(null);

  // Scroll the active tab into view whenever it changes — important
  // when the strip overflows and the user opens a deep-link tab.
  useEffect(() => {
    activeTabRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
  }, [activeId]);

  if (tabs.length === 0) return null;

  return (
    <div
      ref={scrollerRef}
      role="tablist"
      aria-label="PDF tabs"
      className="flex h-9 shrink-0 items-center gap-0.5 overflow-x-auto border-b border-outline-variant/60 bg-surface-low px-1 [scrollbar-width:thin]"
    >
      {tabs.map(tab => {
        const isActive = tab.materialId === activeId;
        return (
          <div
            key={tab.materialId}
            className={cn(
              'group flex h-7 min-w-[120px] max-w-[220px] shrink-0 items-center gap-1 rounded-t-md border border-b-0 px-2 transition-colors',
              isActive
                ? 'border-outline-variant/80 bg-surface-lowest text-foreground'
                : 'border-transparent text-foreground/60 hover:bg-surface-high hover:text-foreground/85',
            )}
          >
            <button
              ref={isActive ? activeTabRef : undefined}
              role="tab"
              type="button"
              aria-selected={isActive}
              onClick={() => {
                setActive(tab.materialId);
                onActivate(tab.materialId);
              }}
              className="flex min-w-0 flex-1 items-center gap-1.5 text-xs"
              title={tab.title}
            >
              <FileText size={11} className="shrink-0 text-primary/55" aria-hidden />
              <span className="truncate">{tab.title}</span>
            </button>
            <button
              type="button"
              aria-label={`关闭 ${tab.title}`}
              title="关闭"
              onClick={(e) => {
                e.stopPropagation();
                const next = closeTab(tab.materialId);
                if (next) onActivate(next);
                else onEmpty();
              }}
              className={cn(
                'shrink-0 rounded p-0.5 text-foreground/40 transition-opacity hover:bg-surface-container hover:text-foreground/80',
                isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
              )}
            >
              <X size={11} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
