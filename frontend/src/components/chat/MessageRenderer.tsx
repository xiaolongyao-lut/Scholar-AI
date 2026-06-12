import { useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AlertTriangle, ChevronDown, ChevronRight, GitFork, Pencil } from 'lucide-react';
import { cn } from '@/lib/utils';
import { EvidencePill, type EvidenceRefLike } from '@/components/evidence/EvidencePill';
import { AnalysisChainPanel } from '@/components/analysis_chain/AnalysisChainPanel';
import type { AnalysisChainPayload } from '@/services/discussionApi';

export type ChatRole = 'user' | 'assistant' | 'system' | 'agent';

const DIAGNOSTIC_INTERNAL_TEXT_PATTERN =
  /(?:\/api\/|https?:\/\/|[A-Za-z]:\\|api[_\s-]?key|base[_\s-]?url|authorization|bearer|token|secret|env=|env_refs|capability_[a-z0-9_]+|fingerprint|sha256:|[{}[\]"`])/i;

const DIAGNOSTIC_IDENTIFIER_PATTERN =
  /\b(?:chunk|source|session|project|workspace|candidate|audit|job|provider|server|credential|capability)_[a-z0-9_-]+\b/i;

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
 * Future extensions such as sampling details and per-source drilldown belong
 * in this metadata bag instead of new top-level message fields.
 */
export interface ChatMessageDiagnostics {
  /** Retrieval tier the backend served. */
  tier?: 'fast' | 'balanced' | 'thorough';
  /** Actual sampling params returned by the backend. */
  sampling?: {
    temperature?: number;
    top_p?: number;
    top_k?: number;
    max_tokens?: number;
  };
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
    chunks?: ChatMessageContextChunk[];
  };
  /** True when the backend reported zero usable context chunks. */
  insufficient?: boolean;
  /** Chunk ids mentioned inline in the answer body. */
  chunkRefs?: string[];
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
  /** Optional structured reasoning chain returned by the chat backend.
   *  Renders below the message body via the shared AnalysisChainPanel. */
  analysis_chain?: AnalysisChainPayload | null;
  /** Canonical metadata bag for diagnostic / debugging info. See
   *  `ChatMessageMetadata`. Fields default-hidden when absent so Inspector /
   *  Discussion get zero visual change. */
  metadata?: ChatMessageMetadata;
}

export interface ChatMessageContextChunk {
  index: number;
  source: string;
  content: string;
  relevance_score?: number;
}

interface MessageRendererProps {
  message: ChatMessageData;
  /** Active project id forwarded to evidence pills for locator upgrade. */
  projectId?: string | null;
  /** Receives the focused evidence ref so parent surfaces can synchronize
   *  drawer rows and PDF highlights. */
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (evidence: EvidenceRefLike) => void;
  navigateEvidenceAfterSelect?: boolean;
  /** Extra block(s) below the body, e.g. tool-call inspector. */
  footer?: ReactNode;
  /** Start a new local branch by editing this sent user message. */
  onEditMessage?: (message: ChatMessageData) => void;
  /** Start a new local branch from this message. */
  onForkMessage?: (message: ChatMessageData) => void;
  className?: string;
}

/**
 * Canonical chat message renderer.
 *
 * `Message.tsx` re-exports this component as `Message` to keep existing
 * imports stable. `MessageBubble.tsx` adapts older props into this renderer.
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
  navigateEvidenceAfterSelect = false,
  footer,
  onEditMessage,
  onForkMessage,
  className,
}: MessageRendererProps) {
  const isUser = message.role === 'user';
  const isAgent = message.role === 'agent' || message.role === 'assistant';
  const assistantContent = isUser ? message.content : formatAssistantVisibleContent(message.content);

  return (
    <div className={cn('flex w-full', isUser ? 'justify-end' : 'justify-start', className)}>
      <div
        className={cn(
          'message-bubble min-w-0 max-w-[88%] overflow-hidden rounded-lg px-3 py-2 text-sm leading-relaxed',
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
          <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{message.content}</div>
        ) : (
          <div className="prose prose-sm max-w-full break-words text-foreground [overflow-wrap:anywhere] prose-headings:my-2 prose-headings:text-foreground prose-p:my-1.5 prose-p:text-foreground prose-a:break-all prose-a:text-primary prose-strong:font-semibold prose-strong:text-foreground prose-em:text-foreground/90 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-li:text-foreground prose-code:break-words prose-code:rounded prose-code:bg-foreground/10 prose-code:px-1 prose-code:py-0.5 prose-code:text-[12px] prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none prose-pre:max-w-full prose-pre:overflow-x-auto prose-pre:bg-foreground/10 prose-table:block prose-table:max-w-full prose-table:overflow-x-auto">
            {message.status === 'streaming' && !message.content.trim() ? (
              <span className="text-foreground/55">AI 思考中…</span>
            ) : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{assistantContent}</ReactMarkdown>
            )}
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
                navigateAfterActivate={navigateEvidenceAfterSelect}
                showSourceLabels
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
          <MessageDiagnostics diagnostics={message.metadata.diagnostics} />
        )}

        {footer && <div className="mt-2">{footer}</div>}

        {(onEditMessage || onForkMessage) && (
          <div
            className={cn(
              'mt-2 flex items-center gap-1 border-t pt-1.5',
              isUser ? 'border-primary-foreground/20' : 'border-outline-variant/40',
            )}
          >
            {isUser && onEditMessage && (
              <button
                type="button"
                onClick={() => onEditMessage(message)}
                className={cn(
                  'inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors',
                  isUser
                    ? 'text-primary-foreground/75 hover:bg-primary-foreground/15 hover:text-primary-foreground'
                    : 'text-foreground/50 hover:bg-surface-high hover:text-foreground',
                )}
                aria-label="修改这条消息并从这里继续"
                title="修改这条消息并从这里继续"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
            {onForkMessage && (
              <button
                type="button"
                onClick={() => onForkMessage(message)}
                className={cn(
                  'inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors',
                  isUser
                    ? 'text-primary-foreground/75 hover:bg-primary-foreground/15 hover:text-primary-foreground'
                    : 'text-foreground/50 hover:bg-surface-high hover:text-foreground',
                )}
                aria-label="从这里分叉"
                title="从这里分叉"
              >
                <GitFork className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}

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

function formatAssistantVisibleContent(content: string): string {
  const seen = new Map<string, number>();
  return content.replace(/\[(chunk[-_][a-zA-Z0-9_-]+)\]/g, (_match, rawRef: string) => {
    const existing = seen.get(rawRef);
    if (existing !== undefined) return `［引用 ${existing}］`;
    const next = seen.size + 1;
    seen.set(rawRef, next);
    return `［引用 ${next}］`;
  });
}

/**
 * Renders optional assistant diagnostics. Each block is independently hidden
 * unless the caller provides its data, preserving legacy surfaces that do not
 * opt in.
 */
function MessageDiagnostics({ diagnostics }: { diagnostics: ChatMessageDiagnostics }) {
  return (
    <>
      {diagnostics.insufficient && (
        <div className="mb-2 mt-2 flex items-center gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-200">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
          <span className="font-medium">上下文不足：未检索到足够相关的项目材料。</span>
        </div>
      )}
      <MessageContextDetails diagnostics={diagnostics} />
      <MessageSourceRefs chunkRefs={diagnostics.chunkRefs} />
      <MessageDiagnosticsRow diagnostics={diagnostics} />
    </>
  );
}

function MessageContextDetails({ diagnostics }: { diagnostics: ChatMessageDiagnostics }) {
  const [expanded, setExpanded] = useState(false);
  const chunks = diagnostics.context?.chunks ?? [];
  if (chunks.length === 0) return null;
  const sourceCount = diagnostics.context?.sourceCount ?? new Set(chunks.map((chunk) => chunk.source)).size;
  return (
    <div className="mt-3 border-t border-outline-variant/40 pt-2">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex items-center gap-1 text-xs text-foreground/55 transition-colors hover:text-foreground/75"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <span>{chunks.length} 个参考片段 · {sourceCount} 个来源</span>
      </button>
      {expanded && (
        <div className="mt-2 space-y-2">
          {chunks.map((chunk) => (
            <div
              key={`${chunk.index}:${chunk.source}`}
              className="rounded border border-outline-variant/50 bg-surface-lowest p-2 text-xs"
            >
              <div className="mb-1 font-semibold text-foreground/80">
                参考片段 {formatDiagnosticOrdinal(chunk.index)} · {sanitizeDiagnosticText(chunk.source, '来源材料')}
              </div>
              <div className="line-clamp-3 text-foreground/60">
                {sanitizeDiagnosticText(chunk.content, '相关片段内容已隐藏')}
              </div>
              {typeof chunk.relevance_score === 'number' && (
                <div className="mt-1 text-[10px] text-foreground/45">
                  相关度 {chunk.relevance_score.toFixed(3)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MessageSourceRefs({ chunkRefs }: { chunkRefs?: string[] }) {
  const uniqueRefs = Array.from(new Set((chunkRefs ?? []).map((ref) => ref.trim()).filter(Boolean)));
  if (uniqueRefs.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {uniqueRefs.map((chunkRef, index) => (
        <button
          key={chunkRef}
          type="button"
          onClick={() => {
            window.dispatchEvent(new CustomEvent('cite-locate', { detail: { id: `[${chunkRef}]` } }));
          }}
          className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] text-primary transition-colors hover:bg-primary/15"
          aria-label={`定位回答中的第 ${index + 1} 个引用`}
          title={`定位回答中的第 ${index + 1} 个引用`}
        >
          定位引用 {index + 1}
        </button>
      ))}
    </div>
  );
}

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
      const tip = prompt && completion ? `输入 ${prompt} / 输出 ${completion}` : `总计 ${total}`;
      items.push(
        <span key="tokens" title={tip}>
          用量 {total.toLocaleString()}
        </span>,
      );
    }
  }
  if (diagnostics.sampling) {
    const samplingParts = [
      typeof diagnostics.sampling.temperature === 'number' ? `温度 ${diagnostics.sampling.temperature}` : '',
      typeof diagnostics.sampling.top_p === 'number' ? `概率采样 ${diagnostics.sampling.top_p}` : '',
      typeof diagnostics.sampling.top_k === 'number' ? `候选数量 ${diagnostics.sampling.top_k}` : '',
      typeof diagnostics.sampling.max_tokens === 'number' ? `最大输出 ${diagnostics.sampling.max_tokens}` : '',
    ].filter(Boolean);
    if (samplingParts.length > 0) {
      items.push(
        <span key="sampling" title={samplingParts.join(' / ')}>
          已应用采样设置
        </span>,
      );
    }
  }
  if (diagnostics.context && diagnostics.context.chunkCount > 0) {
    items.push(
      <span key="context" title="参考材料片段数 / 来源材料数">
        {diagnostics.context.chunkCount} 个片段 · {diagnostics.context.sourceCount} 个来源
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

function sanitizeDiagnosticText(value: string, fallback: string): string {
  const raw = value.trim();
  if (!raw) return fallback;
  if (raw.length > 320) return fallback;
  if (DIAGNOSTIC_INTERNAL_TEXT_PATTERN.test(raw)) return fallback;
  if (DIAGNOSTIC_IDENTIFIER_PATTERN.test(raw)) return fallback;
  return raw;
}

function formatDiagnosticOrdinal(index: number): string {
  if (!Number.isFinite(index)) return '1';
  return String(Math.max(1, Math.trunc(index)));
}
