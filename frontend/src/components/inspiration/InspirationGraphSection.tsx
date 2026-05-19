import { useMemo, useState } from 'react';
import { ChevronDown, Network } from 'lucide-react';
import { cn } from '@/lib/utils';
import { GraphPayloadViewer } from '@/components/graph/GraphPayloadViewer';
import { inspirationToGraphPayload } from '@/components/graph/inspirationToGraphPayload';
import type { InspirationSpark } from '@/types/writing';

interface InspirationGraphSectionProps {
  query: string;
  sparks: ReadonlyArray<InspirationSpark>;
  /** Optional fixed height for the viewer; defaults to 280 px to match
   *  the Workbench EvidenceGraphPanel cadence. */
  height?: number;
  /** Default-collapsed so a long spark list does not pay the React Flow
   *  chunk cost on every render. */
  defaultOpen?: boolean;
  className?: string;
}

/**
 * Collapsible "图谱视图" panel for an inspiration result set
 * (Track B E5 / D-EVR-6). Mirrors the Workbench EvidenceGraphPanel +
 * Discussion DiscussionGraphSection pattern; reuses the shared
 * GraphPayloadViewer over a payload built from
 * inspirationToGraphPayload(query, sparks).
 *
 * Renders nothing when no spark in the set carries `evidence_refs` —
 * the resulting graph would be a lonely claim node, not a useful
 * visualization.
 */
export function InspirationGraphSection({
  query,
  sparks,
  height = 280,
  defaultOpen = false,
  className,
}: InspirationGraphSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  // Always-on memo keeps payload identity stable across collapse/expand
  // cycles so React Flow doesn't tear down nodes on every toggle.
  const payload = useMemo(
    () => inspirationToGraphPayload(query, sparks),
    [query, sparks],
  );

  const evidenceCount = useMemo(
    () => payload.nodes.filter((n) => n.type === 'evidence').length,
    [payload.nodes],
  );

  if (evidenceCount === 0) return null;

  return (
    <div className={cn('mt-3 pt-3 border-t border-outline-variant/30', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[11px] font-label text-foreground/60 hover:text-foreground/80 transition-colors"
        aria-expanded={open}
        aria-controls="inspiration-evidence-graph"
      >
        <Network size={12} />
        <span>图谱视图（{evidenceCount} 条证据 · {sparks.length} 个灵感）</span>
        <ChevronDown
          size={11}
          className={cn('transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && (
        <div
          id="inspiration-evidence-graph"
          className="mt-2 rounded border border-outline-variant/40 bg-surface-lowest"
          style={{ height }}
        >
          <GraphPayloadViewer payload={payload} />
        </div>
      )}
    </div>
  );
}
