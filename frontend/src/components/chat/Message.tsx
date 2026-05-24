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
  /** Plain text or pre-rendered markdown body. For Slice 3 we render as
   *  whitespace-pre-wrap; rich markdown rendering is layered in later. */
  content: string;
  /** Optional friendly agent label rendered as a header chip. */
  agent?: { name: string; color?: string };
  /** Evidence pills shown beneath the message body. Use canonical
   *  `EvidencePill` rendering — same focused-pair behaviour as drawer rows. */
  evidence?: EvidenceRefLike[];
  /** ISO string; `Message` formats locally. Omit to hide footer time. */
  timestamp?: string;
  /** Status hint; renders a small inline label. */
  status?: 'pending' | 'streaming' | 'done' | 'error';
  /** B6 (0.1.8.2): optional 6-field structured reasoning chain returned by
   *  the chat backend when analysis_chain_rag flag is on. Renders below the
   *  message body via the shared AnalysisChainPanel. */
  analysis_chain?: AnalysisChainPayload | null;
}

interface MessageProps {
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
 * Canonical `Message` shell for the Scholar Workbench (Slice 2/3).
 *
 * Designed as a superset target for the legacy `MessageBubble`:
 *   - One shape per role; agent/system/user variants only change
 *     header chip and alignment.
 *   - Evidence renders via canonical `EvidencePill` — no per-page fork.
 *   - No raw IDs, JSON, model names, or sampling parameters in the
 *     default render (R5 / R5.1).
 *   - All copy is Chinese-friendly; caller supplies user text verbatim
 *     and labels via `agent.name` (callers are responsible for using
 *     Chinese-friendly labels).
 *
 * Slice 3 mounts this in the Smart Read inspector inside `ResearchWorkbench`.
 * Slice 4 mounts it in the Discussion transcript (replacing the inline JSX).
 * Slice 7 deprecates the legacy `MessageBubble`.
 */
export function Message({
  message,
  projectId,
  selectedEvidenceId,
  onSelectEvidence,
  footer,
  className,
}: MessageProps) {
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

        {/* B7+ (0.1.8.2 hotfix v5): Inspector smart-read used the canonical
            Message component which previously did `whitespace-pre-wrap` for
            both user and assistant — so the assistant's markdown (**bold**,
            lists, headings) rendered as raw asterisks. User explicitly
            asked for parity with left-sidebar Dialog (which uses
            MessageBubble + ReactMarkdown). Apply markdown to assistant /
            agent bodies; keep user input as plain text to preserve any
            literal characters they typed. */}
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
            // B7+ (0.1.8.2 hotfix v5): user reported the timestamp on the
            // primary-tinted user bubble was illegible — text-foreground/45
            // is a low-contrast gray on top of a saturated blue bubble.
            // For user bubbles: use primary-foreground/70 so the text
            // inherits the bubble's intended contrast color (white-ish).
            // For agent bubbles: keep the muted foreground.
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
