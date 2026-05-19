import { useState } from 'react';
import { cn } from '@/lib/utils';
import { ChevronDown, ChevronUp, PanelRightClose, PanelRight } from 'lucide-react';

interface WorkbenchShellProps {
  /** Object header — title + status chips + actions. */
  header: React.ReactNode;
  /** Center canvas: the object body (PdfReaderShell for Paper, transcript for Discussion, etc.). */
  canvas: React.ReactNode;
  /** Right inspector content (per-object panes). */
  inspector: React.ReactNode;
  /** Bottom evidence drawer content. */
  drawer: React.ReactNode;
  /** Optional title shown in the drawer header. */
  drawerTitle?: string;
}

/**
 * The single-active-object Workbench shell (R7).
 *
 * Layout:
 *   - Top: object header (caller-supplied)
 *   - Middle: split between center canvas and right inspector
 *   - Bottom: collapsible evidence drawer (peek ↔ expanded)
 *
 * v1 invariant: exactly one active object; no tab strip; no second
 * header chip row. Per § 5 wireframe.
 *
 * MC-1 layout stability: inspector + drawer resize without horizontal
 * shifts to the canvas content.
 */
export function WorkbenchShell({ header, canvas, inspector, drawer, drawerTitle }: WorkbenchShellProps) {
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      {/* Object header */}
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-outline-variant/60 bg-surface-low px-4">
        <div className="flex min-w-0 flex-1 items-center gap-2">{header}</div>
        <button
          type="button"
          onClick={() => setInspectorCollapsed((v) => !v)}
          className="rounded p-1 text-foreground/55 transition-colors hover:bg-surface-high hover:text-foreground"
          title={inspectorCollapsed ? '展开检视面板' : '收起检视面板'}
          aria-label={inspectorCollapsed ? '展开检视面板' : '收起检视面板'}
        >
          {inspectorCollapsed ? <PanelRight size={16} /> : <PanelRightClose size={16} />}
        </button>
      </div>

      {/* Middle: canvas + inspector */}
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-hidden">{canvas}</div>
        </div>
        {!inspectorCollapsed && (
          <aside
            className="flex w-[360px] shrink-0 flex-col border-l border-outline-variant/60 bg-surface-lowest"
            aria-label="检视面板"
          >
            {inspector}
          </aside>
        )}
      </div>

      {/* Bottom: collapsible drawer */}
      <div className="shrink-0 border-t border-outline-variant/60 bg-surface-low">
        <button
          type="button"
          onClick={() => setDrawerOpen((v) => !v)}
          className="flex w-full items-center gap-2 px-4 py-1.5 text-left text-xs font-medium text-foreground/70 transition-colors hover:bg-surface-high"
          aria-expanded={drawerOpen}
          aria-controls="workbench-drawer"
        >
          {drawerOpen ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
          <span>{drawerTitle ?? '证据抽屉'}</span>
        </button>
        <div
          id="workbench-drawer"
          className={cn(
            'overflow-hidden transition-[height] duration-200 ease-out',
            drawerOpen ? 'h-[40vh]' : 'h-0',
          )}
        >
          <div className="h-full overflow-auto px-4 py-3">{drawer}</div>
        </div>
      </div>
    </div>
  );
}
