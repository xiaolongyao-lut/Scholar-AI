import { useMemo, useState } from 'react';
import { ChevronDown, Network } from 'lucide-react';
import { cn } from '@/lib/utils';
import { GraphPayloadViewer } from './GraphPayloadViewer';
import {
  workbenchToGraphPayload,
  type WorkbenchSource,
} from './workbenchToGraphPayload';

interface EvidenceGraphPanelProps {
  query: string;
  sources: ReadonlyArray<WorkbenchSource>;
  projectId?: string | null;
  /** Optional fixed height for the embedded viewer; defaults to 280 px. */
  height?: number;
  /** Optional initial open state; default collapsed to keep the chat scroll cheap. */
  defaultOpen?: boolean;
  className?: string;
}

/**
 * Collapsible "图谱视图" panel for a single Workbench answer. Wraps the
 * shared React Flow `GraphPayloadViewer` over a payload built from the
 * (query, sources) pair. Default-collapsed so message lists stay light;
 * the viewer is only mounted after the user expands it, which avoids
 * paying the React Flow bundle cost on every assistant message.
 *
 * Inputs:
 * - query: the user prompt this answer is responding to (becomes the
 *   single `claim` node).
 * - sources: list of retrieved chunks with material_id/chunk_id/title;
 *   each becomes an `evidence` node with a `supports` edge to the claim.
 *
 * Output:
 * - Renders nothing when sources is empty, since a one-node graph is
 *   not a useful visualization.
 */
export function EvidenceGraphPanel({
  query,
  sources,
  projectId,
  height = 280,
  defaultOpen = false,
  className,
}: EvidenceGraphPanelProps) {
  const [open, setOpen] = useState(defaultOpen);

  const hasEvidence = sources && sources.length > 0;
  // Always-on memo keeps the payload identity stable across re-renders
  // even when the panel is collapsed, so React Flow doesn't tear down
  // and rebuild on every expand toggle.
  const payload = useMemo(
    () => workbenchToGraphPayload(query, sources ?? []),
    [query, sources],
  );

  if (!hasEvidence) return null;

  return (
    <div className={cn('mt-3 pt-3 border-t border-outline-variant/30', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[11px] font-label text-foreground/60 hover:text-foreground/80 transition-colors"
        aria-expanded={open}
        aria-controls="workbench-evidence-graph"
      >
        <Network size={12} />
        <span>图谱视图（{sources.length} 条证据）</span>
        <ChevronDown
          size={11}
          className={cn('transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && (
        <div
          id="workbench-evidence-graph"
          className="mt-2 rounded border border-outline-variant/40 bg-surface-lowest"
          style={{ height }}
        >
          <GraphPayloadViewer payload={payload} projectId={projectId} />
        </div>
      )}
    </div>
  );
}
