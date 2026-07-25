import { useId, useMemo, useState } from 'react';
import { ChevronDown, Network } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ChatMessageData } from '@/components/chat/MessageRenderer';
import { WikiGraphSegmentedView } from './WikiGraphSegmentedView';
import { buildAnswerTurnGraphPayload } from './answerGraphProjection';
import type { WorkbenchSource } from './workbenchToGraphPayload';

interface EvidenceGraphPanelProps {
  query: string;
  answer: string;
  sessionId: string;
  turnId: string;
  sources: ReadonlyArray<WorkbenchSource>;
  projectId?: string | null;
  /** Optional fixed height for the embedded viewer; defaults to 280 px. */
  height?: number;
  /** Optional initial open state; default collapsed to keep the chat scroll cheap. */
  defaultOpen?: boolean;
  className?: string;
}

/**
 * Collapsible graph for one Workbench answer. It projects an exact local
 * session/turn pair through the shared read-only viewport. Default-collapsed
 * keeps message lists cheap; the viewport mounts only after expansion.
 *
 * Inputs:
 * - query/answer: display text for the question and final answer claim.
 * - sessionId/turnId: stable graph identity; query text is never a graph key.
 * - sources: list of retrieved chunks with material_id/chunk_id/title;
 *   each becomes an evidence node and optional paper node.
 *
 * Output:
 * - Renders nothing when there is no evidence, since a question/claim-only
 *   graph is not useful in this compact panel.
 */
export function EvidenceGraphPanel({
  query,
  answer,
  sessionId,
  turnId,
  sources,
  projectId,
  height = 280,
  defaultOpen = false,
  className,
}: EvidenceGraphPanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  const graphPanelId = `workbench-evidence-graph-${useId()}`;

  const hasEvidence = sources && sources.length > 0;
  const messages = useMemo<ChatMessageData[]>(
    () => [
      {
        id: `workbench-user:${turnId}`,
        role: 'user',
        turnId,
        content: query,
      },
      {
        id: `workbench-assistant:${turnId}`,
        role: 'assistant',
        turnId,
        content: answer,
        evidence: (sources ?? []).map((source) => ({
          source: source.title,
          text: source.excerpt ?? source.title,
          material_id: source.material_id,
          chunk_id: source.chunk_id,
        })),
      },
    ],
    [answer, query, sources, turnId],
  );
  const payload = useMemo(
    () => buildAnswerTurnGraphPayload(messages, { sessionId, turnId }),
    [messages, sessionId, turnId],
  );

  if (!hasEvidence || !payload) return null;

  const summary = `图谱视图（${sources.length} 条证据）`;

  return (
    <div className={cn('mt-3 pt-3 border-t border-outline-variant/30', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-[11px] font-label text-foreground/60 hover:text-foreground/80 transition-colors"
        aria-expanded={open}
        aria-controls={graphPanelId}
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
          id={graphPanelId}
          className="mt-2 rounded border border-outline-variant/40 bg-surface-lowest"
          style={{ height }}
        >
          <WikiGraphSegmentedView payload={payload} domain="answer" projectId={projectId} />
        </div>
      )}
    </div>
  );
}
