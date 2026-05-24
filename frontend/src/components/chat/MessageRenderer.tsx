import { type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';
import { EvidencePill, type EvidenceRefLike } from '@/components/evidence/EvidencePill';
import { AnalysisChainPanel } from '@/components/analysis_chain/AnalysisChainPanel';
import type { AnalysisChainPayload } from '@/services/discussionApi';

export type ChatRole = 'user' | 'assistant' | 'system' | 'agent';

export interface ChatMessageData {
  id: string;
  role: ChatRole;
  /** Plain text or pre-rendered markdown body. Assistant/agent renders
   *  through ReactMarkdown + remark-gfm; user keeps `whitespace-pre-wrap`. */
  content: string;
  /** Optional friendly agent label rendered as a header chip. */
  agent?: { name: string; color?: string };
  /** Evidence pills shown beneath the message body. Use canonical
   *  `EvidencePill` rendering — same focused-pair behaviour as drawer rows. */
  evidence?: EvidenceRefLike[];
  /** ISO string; `MessageRenderer` formats locally. Omit to hide footer time. */
  timestamp?: string;
  /** Status hint; renders a small inline label. */
  status?: 'pending' | 'streaming' | 'done' | 'error';
  /** B6 (0.1.8.2): optional 6-field structured reasoning chain returned by
   *  the chat backend when analysis_chain_rag flag is on. Renders below the
   *  message body via the shared AnalysisChainPanel. */
  analysis_chain?: AnalysisChainPayload | null;
}

interface MessageRendererProps {
  message: ChatMessageData;
  /** Active project id forwarded to evidence pills for locator upgrade. */
  projectId?: string | null;
  /** Selection bus glue (Slice 3+). Receives the focused evidence ref so
   *  the parent can mark the drawer row + PDF highlight per K4. */
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidence: EvidenceRefLike) => void;
  /** Extra block(s) below the body, e.g. tool-call inspector. */
  footer?: ReactNode;
  className?: string;
}

/**
 * Canonical chat message renderer (M-Slice 1a).
 *
 * Extracted from the original `Message` component as the single canonical
 * target referenced by the fullstack deduplication plan. `Message.tsx` now
 * re-exports this component as `Message` to keep existing imports stable;
 * `MessageBubble.tsx` (Dialog legacy) will be folded into the shared
 * `Conversation` flow in M-Slice 1b/4.
 *
 * Design invariants:
 *   - One shape per role; agent/system/user variants only change
 *     header chip and alignment.
 *   - Evidence renders via canonical `EvidencePill` — no per-page fork.
 *   - Assistant/agent body uses ReactMarkdown + remark-gfm; user body keeps
 *     `whitespace-pre-wrap` so literal characters they typed are preserved.
 *   - No raw IDs, JSON, model names, or sampling parameters in the
 *     default render (R5 / R5.1).
 *   - All copy is Chinese-friendly; caller supplies user text verbatim
 *     and labels via `agent.name`.
 *   - Timestamp uses `primary-foreground/70` on user bubbles (bg-primary)
 *     to stay readable on saturated blue; muted foreground on agent bubbles.
 */
export function MessageRenderer({
  message,
  projectId,
  selectedEvidenceId,
  onSelectEvidence,
  footer,
  className,
}: MessageRendererProps) {
  const isUser = message.role === 'user';
  const isAgent = message.role === 'agent' || message.role === 'assistant';

  return (
    <div className={cn('flex w-full', isUser ? 'justify-end' : 'justify-start', className)}>
      <div
        className={cn(
          'message-bubble max-w-[88%] rounded-lg px-3 py-2 text-sm leading-relaxed',
          isUser
            ? 'bg-primary text-primary-foreground'
            : 'bg-surface-low text-foreground border border-outline-variant/60',
        )}
      >
        {message.agent && !isUser && (
          <div className="mb-1 flex items-center gap-1.5">
            <span
              className="inline-block size-1.5 rounded-full"
              style={message.agent.color ? { backgroundColor: message.agent.color } : { backgroundColor: 'hsl(var(--primary))' }}
              aria-hidden
            />
            <span className="text-[11px] font-medium text-foreground/70">{message.agent.name}</span>
          </div>
        )}

        {isUser ? (
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
        ) : (
          <div className="prose prose-sm max-w-none prose-neutral dark:prose-invert prose-p:my-1.5 prose-headings:my-2 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-code:bg-foreground/10 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-[12px] prose-code:before:content-none prose-code:after:content-none prose-pre:bg-foreground/10 prose-strong:font-semibold">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        )}

        {isAgent && message.evidence && message.evidence.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {message.evidence.map((ev, i) => (
              <EvidencePill
                key={`${ev.evidence_id ?? ev.chunk_id ?? '_'}:${i}`}
                evidence={ev}
                projectId={projectId}
                selected={
                  !!selectedEvidenceId &&
                  (ev.evidence_id === selectedEvidenceId || ev.chunk_id === selectedEvidenceId)
                }
                onActivate={onSelectEvidence}
              />
            ))}
          </div>
        )}

        {isAgent && message.analysis_chain && (
          <div className="mt-2">
            <AnalysisChainPanel chain={message.analysis_chain} />
          </div>
        )}

        {footer && <div className="mt-2">{footer}</div>}

        <div
          className={cn(
            'mt-1 flex items-center justify-between gap-2 text-[10px]',
            isUser ? 'text-primary-foreground/70' : 'text-foreground/45',
          )}
        >
          {message.status === 'streaming' && <span aria-live="polite">生成中…</span>}
          {message.status === 'error' && <span className="text-destructive">生成失败</span>}
          {message.timestamp && (
            <time className="ml-auto" dateTime={message.timestamp}>
              {formatTimestamp(message.timestamp)}
            </time>
          )}
        </div>
      </div>
    </div>
  );
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}
