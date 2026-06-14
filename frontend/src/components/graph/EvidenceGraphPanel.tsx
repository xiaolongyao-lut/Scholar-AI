import { useMemo, useState } from 'react';
import { ChevronDown, Network } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { AnalysisChainPayload } from '@/services/discussionApi';
import { WikiGraphSegmentedView } from './WikiGraphSegmentedView';
import {
  workbenchToGraphPayload,
  type WorkbenchSource,
} from './workbenchToGraphPayload';

interface EvidenceGraphPanelProps {
  query: string;
  sources: ReadonlyArray<WorkbenchSource>;
  projectId?: string | null;
  /** 答案带 AnalysisChain 时，会额外叠加六维度节点。 */
  analysisChain?: AnalysisChainPayload | null;
  /** Optional fixed height for the embedded viewer; defaults to 280 px. */
  height?: number;
  /** Optional initial open state; default collapsed to keep the chat scroll cheap. */
  defaultOpen?: boolean;
  className?: string;
}

/**
 * Collapsible "图谱视图" panel for a single Workbench answer. Wraps the
 * shared React Flow viewer over a payload built from the (query, sources)
 * pair, plus an optional AnalysisChain overlay so the dimension lanes
 * show reasoning roles directly. Default-collapsed so message lists stay
 * light; the viewer is only mounted after the user expands it.
 *
 * Inputs:
 * - query: the user prompt this answer is responding to (becomes the
 *   single `claim` node tagged with reasoning_dimension=question).
 * - sources: list of retrieved chunks with material_id/chunk_id/title;
 *   each becomes an `evidence` node with a `supports` edge to the claim.
 * - analysisChain (optional): observation / mechanism / evidence /
 *   boundary / counter_evidence / next_action — each non-empty field
 *   becomes a typed node tagged with analysis_chain_field so the
 *   dimension viewer can place it in the matching lane.
 *
 * Output:
 * - Renders nothing when there is no evidence and no analysis chain,
 *   since a one-node graph is not a useful visualization.
 */
export function EvidenceGraphPanel({
  query,
  sources,
  projectId,
  analysisChain,
  height = 280,
  defaultOpen = false,
  className,
}: EvidenceGraphPanelProps) {
  const [open, setOpen] = useState(defaultOpen);

  const hasEvidence = sources && sources.length > 0;
  const hasChain = Boolean(
    analysisChain && (
      analysisChain.observation ||
      analysisChain.mechanism ||
      (analysisChain.evidence && analysisChain.evidence.length > 0) ||
      analysisChain.boundary ||
      (analysisChain.counter_evidence && analysisChain.counter_evidence.length > 0) ||
      analysisChain.next_action
    ),
  );
  // Always-on memo keeps the payload identity stable across re-renders
  // even when the panel is collapsed, so React Flow doesn't tear down
  // and rebuild on every expand toggle.
  const payload = useMemo(
    () => workbenchToGraphPayload(query, sources ?? [], analysisChain ?? null),
    [query, sources, analysisChain],
  );

  if (!hasEvidence && !hasChain) return null;

  const summary = hasEvidence && hasChain
    ? `图谱视图（${sources.length} 条证据 · 思维链）`
    : hasEvidence
      ? `图谱视图（${sources.length} 条证据）`
      : '图谱视图（思维链）';

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
        <span>{summary}</span>
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
          <WikiGraphSegmentedView payload={payload} projectId={projectId} />
        </div>
      )}
    </div>
  );
}
