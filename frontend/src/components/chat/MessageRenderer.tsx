import { type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';
import { EvidencePill, type EvidenceRefLike } from '@/components/evidence/EvidencePill';
import { AnalysisChainPanel } from '@/components/analysis_chain/AnalysisChainPanel';
import type { AnalysisChainPayload } from '@/services/discussionApi';

export type ChatRole = 'user' | 'assistant' | 'system' | 'agent';

/**
 * Canonical diagnostics block carried alongside an assistant message.
 *
 * Per the user's §五 决策 5 (2026-05-24): tier / token / context / insufficient
 * metadata is stored as a single optional `diagnostics` object rather than
 * five separate top-level props. Fields are independently optional so the
 * renderer only shows what the caller actually populates — Inspector and
 * Discussion can leave it `undefined` for zero visual change; Dialog and
 * Workbench surfaces opt in by adapting their legacy response shapes.
 *
 * Future extension (M-Slice 1b.d): sampling params + per-chunk drilldown
 * + chunk-id deep-link buttons will land here.
 */
export interface ChatMessageDiagnostics {
  /** Retrieval tier the backend served. */
  tier?: 'fast' | 'balanced' | 'thorough';
  /** LLM token accounting from the provider response. */
  tokens?: {
    prompt?: number;
    completion?: number;
    total?: number;
  };
  /** Context-window stats: how many chunks went in, and from how many
   *  distinct sources. */
  context?: {
    chunkCount: number;
    sourceCount: number;
  };
  /** True when the backend reported zero usable context chunks. */
  insufficient?: boolean;
}

export interface ChatMessageMetadata {
  diagnostics?: ChatMessageDiagnostics;
}

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
  /** Canonical metadata bag for diagnostic / debugging info. See
   *  `ChatMessageMetadata`. Fields default-hidden when absent so Inspector /
   *  Discussion get zero visual change. */
  metadata?: ChatMessageMetadata;
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

        {isAgent && message.metadata?.diagnostics && (
          <MessageDiagnosticsRow diagnostics={message.metadata.diagnostics} />
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

/**
 * Renders the optional one-line diagnostics row beneath an assistant
 * message — tier / tokens / context / insufficient-warning. Fields are
 * shown only when populated so the row collapses gracefully when the
 * caller (e.g. Inspector) only has partial data.
 */
function MessageDiagnosticsRow({ diagnostics }: { diagnostics: ChatMessageDiagnostics }) {
  const items: ReactNode[] = [];
  if (diagnostics.tier) {
    items.push(
      <span key="tier" title="检索深度">
        {diagnostics.tier === 'fast' ? '快速' : diagnostics.tier === 'thorough' ? '深度' : '平衡'}
      </span>,
    );
  }
  if (diagnostics.tokens) {
    const total = diagnostics.tokens.total;
    if (typeof total === 'number' && total > 0) {
      const prompt = diagnostics.tokens.prompt ?? 0;
      const completion = diagnostics.tokens.completion ?? 0;
      const tip = prompt && completion ? `prompt ${prompt} / completion ${completion}` : `总计 ${total}`;
      items.push(
        <span key="tokens" title={tip}>
          {total.toLocaleString()} tokens
        </span>,
      );
    }
  }
  if (diagnostics.context && diagnostics.context.chunkCount > 0) {
    items.push(
      <span key="context" title="参考的语料 chunk 数 / 来源文献数">
        {diagnostics.context.chunkCount} chunks · {diagnostics.context.sourceCount} sources
      </span>,
    );
  }
  if (diagnostics.insufficient) {
    items.push(
      <span key="insufficient" className="text-amber-700 dark:text-amber-300" title="未检索到相关上下文">
        ⚠ 上下文不足
      </span>,
    );
  }
  if (items.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-outline-variant/40 pt-1 text-[10px] text-foreground/45">
      {items.map((item, idx) => (
        <span key={idx} className="inline-flex items-center">
          {idx > 0 && <span className="mr-2 opacity-60">·</span>}
          {item}
        </span>
      ))}
    </div>
  );
}
