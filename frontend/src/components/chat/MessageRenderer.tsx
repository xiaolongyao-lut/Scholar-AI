import { useEffect, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { AlertTriangle, ChevronDown, ChevronRight, FileImage, GitFork, Network, Pencil, Table2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { EvidencePill, type EvidenceRefLike } from '@/components/evidence/EvidencePill';
import { AnalysisChainPanel } from '@/components/analysis_chain/AnalysisChainPanel';
import { CaptureToInboxButton } from '@/components/knowledge/CaptureToInboxButton';
import type { AnalysisChainPayload } from '@/services/discussionApi';
import { buildFigureAssetFileUrl } from '@/services/writingBackend';
import { markdownTableComponents } from './markdownTableComponents';

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
  /** Wiki + project recall fusion visibility from evidence-pack / writing audit. */
  retrieval?: ChatRetrievalDiagnostics;
}

export interface ChatRetrievalDiagnostics {
  retrieval_method?: string;
  embedding_status?: string;
  rerank_status?: string;
  lexical_only?: boolean;
  fallback_reasons?: string[];
  gateway?: ChatGatewayDiagnostics;
  tolf?: ChatTolfDiagnostics;
  qrels_status?: ChatRetrievalQrelsStatus;
  joint_recall?: ChatJointRecallDiagnostics;
}

export interface ChatGatewayDiagnostics {
  dense_hit_count?: number;
  lexical_hit_count?: number;
  visual_hit_count?: number;
  candidate_count?: number;
  dense_enabled?: boolean;
  material_balancing_enabled?: boolean;
  chroma_status?: string;
  fts_status?: string;
  fallback_reasons?: string[];
  gate_status_counts?: Record<string, number>;
}

export interface ChatTolfDiagnostics {
  status?: string;
  candidate_count?: number;
  input_count?: number;
  graph_node_count?: number;
  graph_edge_count?: number;
  gate_after_count?: number;
  activation_min?: number | null;
  activation_max?: number | null;
  activation_mean?: number | null;
  top_final_rank_score?: number | null;
  rank_contribution_keys?: string[];
  fallback_reason?: string | null;
}

export interface ChatRetrievalQrelsStatus {
  schema_version?: 'retrieval-qrels-status/v1';
  status?: 'missing' | 'candidate' | 'reviewed' | 'canonical';
  candidate_qrels_count?: number;
  reviewed_qrels_count?: number;
  canonical_qrels_count?: number;
  semantic_quality_claim_allowed?: boolean;
  quality_claim?:
    | 'no_qrels_available'
    | 'candidate_qrels_review_required'
    | 'reviewed_qrels_promotion_required'
    | 'canonical_qrels_available';
  notes?: string[];
}

export interface ChatJointRecallDiagnostics {
  status?: string;
  fusion?: string;
  project_weight?: number;
  wiki_weight?: number;
  project_hit_count?: number;
  wiki_hit_count?: number;
  fused_count?: number;
  wiki_share_after_fusion?: number;
  max_wiki_share_after_fusion?: number;
  top_doc_ids?: string[];
  wiki_summaries?: ChatJointRecallWikiSummary[];
}

export interface ChatJointRecallWikiSummary {
  title?: string;
  summary?: string;
  ref_id?: string;
  read_endpoint?: string;
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
  /** Related figure/table candidates surfaced for visual evidence questions. */
  relatedFigures?: ChatRelatedFigure[];
  /** Canonical metadata bag for diagnostic / debugging info. See
   *  `ChatMessageMetadata`. Fields default-hidden when absent so Inspector /
   *  Discussion get zero visual change. */
  metadata?: ChatMessageMetadata;
}

export interface ChatRelatedFigure {
  id: string;
  kind: 'figure' | 'table';
  label: string;
  caption: string;
  material_id: string;
  material_title?: string | null;
  page?: number | null;
  chunk_id?: string | null;
  asset_path?: string | null;
  source?: string | null;
}

export interface ChatMessageContextChunk {
  index: number;
  source: string;
  content: string;
  relevance_score?: number;
  chunk_id?: string | null;
  material_id?: string | null;
  title?: string | null;
  section_title?: string | null;
  page?: number | string | null;
  source_labels?: string[];
  source_hint?: string | null;
}

interface MessageRendererProps {
  message: ChatMessageData;
  /** Active project id forwarded to evidence pills for locator upgrade. */
  projectId?: string | null;
  /** Optional session id for capture-to-inbox traceability. */
  sessionId?: string | null;
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
  /** Hide the per-message 「记一下」 button. */
  hideCaptureToInbox?: boolean;
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
  sessionId,
  selectedEvidenceId,
  onSelectEvidence,
  navigateEvidenceAfterSelect = false,
  footer,
  onEditMessage,
  onForkMessage,
  hideCaptureToInbox = false,
  className,
}: MessageRendererProps) {
  const isUser = message.role === 'user';
  const isAgent = message.role === 'agent' || message.role === 'assistant';
  const assistantContent = isUser ? message.content : formatAssistantVisibleContent(message.content, message.evidence);

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
          <div className="prose prose-sm max-w-full break-words text-foreground [overflow-wrap:anywhere] prose-headings:my-2 prose-headings:text-foreground prose-p:my-1.5 prose-p:text-foreground prose-a:break-all prose-a:text-primary prose-strong:font-semibold prose-strong:text-foreground prose-em:text-foreground/90 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-li:text-foreground prose-code:break-words prose-code:rounded prose-code:bg-foreground/10 prose-code:px-1 prose-code:py-0.5 prose-code:text-[12px] prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none prose-pre:max-w-full prose-pre:overflow-x-auto prose-pre:bg-foreground/10">
            {message.status === 'streaming' && !message.content.trim() ? (
              <span className="text-foreground/55">AI 思考中…</span>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  ...markdownTableComponents,
                  a: ({ href, children }) => {
                    const citationIndex = parseInlineCitationHref(href);
                    if (citationIndex !== null) {
                      const evidence = message.evidence?.[citationIndex];
                      if (evidence) {
                        return (
                          <EvidencePill
                            evidence={evidence}
                            projectId={projectId}
                            selected={
                              !!selectedEvidenceId &&
                              (evidence.evidence_id === selectedEvidenceId || evidence.chunk_id === selectedEvidenceId)
                            }
                            onActivate={onSelectEvidence}
                            navigateAfterActivate={navigateEvidenceAfterSelect}
                            labelOverride={`[${citationIndex + 1}]`}
                            title={inlineCitationTitle(citationIndex, evidence)}
                            className="mx-0.5 align-baseline"
                          />
                        );
                      }
                    }
                    return <a href={href}>{children}</a>;
                  },
                }}
              >
                {assistantContent}
              </ReactMarkdown>
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

        {isAgent && message.relatedFigures && message.relatedFigures.length > 0 && (
          <RelatedFigureStrip figures={message.relatedFigures} projectId={projectId} />
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

        {(onEditMessage || onForkMessage || (isAgent && !hideCaptureToInbox)) && (
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
            {isAgent && !hideCaptureToInbox && (
              <div className="ml-auto">
                <CaptureToInboxButton
                  variant="icon"
                  label="记到待确认"
                  context={{
                    kind: 'dialog',
                    sourceLabel: message.agent?.name ? `对话 · ${message.agent.name}` : '对话回复',
                    quote: message.content,
                    locator: message.timestamp ? `时间 ${message.timestamp}` : undefined,
                    rawIds: {
                      message_id: message.id,
                      session_id: sessionId ?? null,
                      project_id: projectId ?? null,
                    },
                  }}
                />
              </div>
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

function formatAssistantVisibleContent(content: string, evidence?: EvidenceRefLike[]): string {
  const seen = new Map<string, number>();
  let nextContent = content.replace(/\[(chunk[-_][a-zA-Z0-9_-]+)\]/g, (_match, rawRef: string) => {
    const existing = seen.get(rawRef);
    if (existing !== undefined) return `［引用 ${existing}］`;
    const next = seen.size + 1;
    seen.set(rawRef, next);
    return `［引用 ${next}］`;
  });
  if (evidence && evidence.length > 0) {
    nextContent = nextContent.replace(/\[(\d{1,3})\]/g, (match, rawIndex: string) => {
      const index = Number.parseInt(rawIndex, 10);
      if (!Number.isFinite(index) || index < 1 || index > evidence.length) return match;
      return `[[${index}]](#smartread-citation-${index})`;
    });
  }
  return nextContent;
}

function parseInlineCitationHref(href: string | undefined): number | null {
  const match = /^#smartread-citation-(\d{1,3})$/.exec(String(href ?? '').trim());
  if (!match) return null;
  const index = Number.parseInt(match[1], 10);
  return Number.isFinite(index) && index > 0 ? index - 1 : null;
}

function inlineCitationTitle(index: number, evidence: EvidenceRefLike): string {
  const source = (evidence.source_title ?? evidence.source ?? '').trim() || `引用 ${index + 1}`;
  const page = typeof evidence.page === 'number' && evidence.page > 0 ? ` · p.${evidence.page}` : '';
  return `${source}${page}`;
}

function RelatedFigureStrip({
  figures,
  projectId,
}: {
  figures: ChatRelatedFigure[];
  projectId?: string | null;
}) {
  const visible = figures.slice(0, 6);
  return (
    <div className="mt-3 border-t border-outline-variant/40 pt-2">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-foreground/65">
        <FileImage className="h-3.5 w-3.5" aria-hidden />
        <span>相关图像/图表候选</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {visible.map((figure) => (
          <RelatedFigureCard key={figure.id} figure={figure} projectId={projectId} />
        ))}
      </div>
    </div>
  );
}

function RelatedFigureCard({
  figure,
  projectId,
}: {
  figure: ChatRelatedFigure;
  projectId?: string | null;
}) {
  const imageUrl = displayableFigureAssetUrl(projectId, figure.asset_path);
  const caption = figure.caption.trim() || figure.label;
  const sourceLabel = relatedFigureSourceLabel(figure.source);
  return (
    <div className="overflow-hidden rounded-md border border-outline-variant/50 bg-surface-lowest">
      <div className="flex h-28 items-center justify-center bg-surface-high">
        {imageUrl ? (
          <ProtectedFigureImage src={imageUrl} alt={`${figure.label} ${caption}`} />
        ) : (
          <div className="flex flex-col items-center gap-1 px-3 text-center text-foreground/35">
            {figure.kind === 'table' ? <Table2 className="h-5 w-5" /> : <FileImage className="h-5 w-5" />}
            <span className="text-[11px] leading-4">仅找到文本候选，暂无可显示像素图</span>
          </div>
        )}
      </div>
      <div className="space-y-1 p-2">
        <div className="flex items-center gap-1 text-[11px] font-semibold text-foreground/75">
          <span className="shrink-0">{figure.label}</span>
          {typeof figure.page === 'number' && figure.page > 0 ? (
            <span className="text-foreground/40">p.{figure.page}</span>
          ) : null}
          {sourceLabel ? (
            <span className="ml-auto shrink-0 rounded border border-outline-variant/50 px-1 py-px text-[10px] font-normal text-foreground/45">
              {sourceLabel}
            </span>
          ) : null}
        </div>
        <p className="line-clamp-2 text-[11px] leading-4 text-foreground/55">{caption}</p>
        <p className="truncate text-[10px] text-foreground/35">
          {figure.material_title || figure.material_id}
        </p>
      </div>
    </div>
  );
}

function ProtectedFigureImage({ src, alt }: { src: string; alt: string }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(() => (shouldFetchProtectedFigureAsset(src) ? null : src));
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!shouldFetchProtectedFigureAsset(src)) {
      setObjectUrl(src);
      setFailed(false);
      return undefined;
    }
    if (typeof fetch !== 'function') {
      setObjectUrl(src);
      setFailed(false);
      return undefined;
    }

    let cancelled = false;
    let nextObjectUrl: string | null = null;
    setObjectUrl(null);
    setFailed(false);

    void fetch(src)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`figure asset request failed: ${response.status}`);
        }
        return response.blob();
      })
      .then((blob) => {
        if (cancelled) {
          return;
        }
        nextObjectUrl = URL.createObjectURL(blob);
        setObjectUrl(nextObjectUrl);
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
        }
      });

    return () => {
      cancelled = true;
      if (nextObjectUrl) {
        URL.revokeObjectURL(nextObjectUrl);
      }
    };
  }, [src]);

  if (failed) {
    return (
      <div className="flex flex-col items-center gap-1 px-3 text-center text-foreground/35">
        <FileImage className="h-5 w-5" />
        <span className="text-[11px] leading-4">图像加载失败</span>
      </div>
    );
  }
  if (!objectUrl) {
    return <span className="text-[11px] text-foreground/35">正在加载原图…</span>;
  }
  return <img src={objectUrl} alt={alt} className="h-full w-full object-contain" loading="lazy" />;
}

function relatedFigureSourceLabel(source: string | null | undefined): string | null {
  const value = String(source ?? '').trim();
  if (value === 'pdf_embedded_image') return '原图';
  if (
    value === 'chunk_asset' ||
    value === 'chunk_image' ||
    value === 'chunk_image_paths' ||
    value === 'chunk_raw_image' ||
    value === 'chunk_figure_asset' ||
    value === 'chunk_figure_image_paths' ||
    value === 'chunk_raw_embedded_image' ||
    value.endsWith('_chunk_asset') ||
    value.endsWith('_chunk_image') ||
    value.endsWith('_chunk_image_paths') ||
    value.endsWith('_chunk_raw_image') ||
    value.endsWith('_chunk_figure_asset') ||
    value.endsWith('_chunk_figure_image_paths') ||
    value.endsWith('_chunk_raw_embedded_image')
  ) return '图像资产';
  return null;
}

function shouldFetchProtectedFigureAsset(src: string): boolean {
  const value = src.trim();
  if (!value || value.startsWith('data:image:') || value.startsWith('blob:')) {
    return false;
  }
  try {
    const parsed = new URL(value, typeof window === 'undefined' ? 'http://127.0.0.1:8000/' : window.location.href);
    return parsed.pathname === '/api/writing/figures/file';
  } catch {
    return false;
  }
}

function displayableFigureAssetUrl(projectId: string | null | undefined, assetPath: string | null | undefined): string | null {
  const value = String(assetPath ?? '').trim();
  if (!value) return null;
  if (
    value.startsWith('http://') ||
    value.startsWith('https://') ||
    value.startsWith('/') ||
    value.startsWith('data:image:') ||
    value.startsWith('blob:')
  ) {
    return value;
  }
  if (!projectId?.trim() || value.startsWith('candidate://')) return null;
  return buildFigureAssetFileUrl(projectId, value);
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
      <MessageJointRecallDetails diagnostics={diagnostics} />
      <MessageRetrievalHealthDetails diagnostics={diagnostics} />
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
          {chunks.map((chunk) => {
            const safeContent = sanitizeDiagnosticOptionalText(chunk.content);
            const metaItems = diagnosticChunkMetaItems(chunk);
            return (
              <div
                key={`${chunk.index}:${chunk.source}`}
                className="rounded border border-outline-variant/50 bg-surface-lowest p-2 text-xs"
              >
                <div className="mb-1 font-semibold text-foreground/80">
                  参考片段 {formatDiagnosticOrdinal(chunk.index)} · {sanitizeDiagnosticText(chunk.source, '来源材料')}
                </div>
                <div className="mb-1.5 flex flex-wrap gap-1.5 text-[10px] text-foreground/50">
                  <span className="rounded border border-outline-variant/45 bg-surface-low px-1.5 py-0.5">
                    相关度 {formatDiagnosticRelevance(chunk.relevance_score)}
                  </span>
                  {metaItems.map((item) => (
                    <span
                      key={item}
                      className="rounded border border-outline-variant/45 bg-surface-low px-1.5 py-0.5"
                    >
                      {item}
                    </span>
                  ))}
                </div>
                {safeContent ? (
                  <div className="line-clamp-3 text-foreground/60">{safeContent}</div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MessageJointRecallDetails({ diagnostics }: { diagnostics: ChatMessageDiagnostics }) {
  const [expanded, setExpanded] = useState(false);
  const joint = diagnostics.retrieval?.joint_recall;
  if (!joint || joint.status === 'unavailable') return null;
  const projectHits = safeCount(joint.project_hit_count);
  const wikiHits = safeCount(joint.wiki_hit_count);
  const wikiShare = safePercent(joint.wiki_share_after_fusion);
  const maxWikiShare = safePercent(joint.max_wiki_share_after_fusion);
  const projectWeight = safeWeight(joint.project_weight);
  const wikiWeight = safeWeight(joint.wiki_weight);
  const fusion = sanitizeDiagnosticLabel(joint.fusion, 'weighted_rrf');
  const summaries = (joint.wiki_summaries ?? []).slice(0, 3);
  return (
    <div className="mt-3 border-t border-outline-variant/40 pt-2">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className="flex min-w-0 items-center gap-1 text-xs text-foreground/55 transition-colors hover:text-foreground/75"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <Network className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="truncate">
          联合召回 · 项目 {projectHits} · Wiki {wikiHits} · {wikiShare}
        </span>
      </button>
      {expanded && (
        <div className="mt-2 rounded border border-outline-variant/50 bg-surface-lowest p-2 text-xs text-foreground/65">
          <div className="grid gap-1 sm:grid-cols-2">
            <span>融合: {fusion}</span>
            <span>权重: 项目 {projectWeight} / Wiki {wikiWeight}</span>
            <span>Wiki 占比: {wikiShare}</span>
            <span>上限: {maxWikiShare}</span>
          </div>
          {summaries.length > 0 ? (
            <div className="mt-2 grid gap-1.5">
              {summaries.map((item, index) => (
                <div
                  key={`${item.ref_id ?? item.read_endpoint ?? index}`}
                  className="rounded border border-outline-variant/40 bg-surface-low px-2 py-1.5"
                >
                  <div className="truncate font-medium text-foreground/80">
                    {sanitizeDiagnosticText(item.title ?? '', 'Wiki 摘要')}
                  </div>
                  {item.summary ? (
                    <div className="mt-0.5 line-clamp-2 text-[11px] leading-5 text-foreground/55">
                      {sanitizeDiagnosticText(item.summary, '摘要已隐藏')}
                    </div>
                  ) : null}
                  {item.ref_id ? (
                    <div className="mt-1 truncate font-mono text-[10px] text-foreground/35">
                      {sanitizeDiagnosticRef(item.ref_id)}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

function MessageRetrievalHealthDetails({ diagnostics }: { diagnostics: ChatMessageDiagnostics }) {
  const [expanded, setExpanded] = useState(false);
  const retrieval = diagnostics.retrieval;
  const gateway = retrieval?.gateway;
  const tolf = retrieval?.tolf;
  const fallbackReasons = retrieval?.fallback_reasons ?? gateway?.fallback_reasons ?? [];
  if (!gateway && !tolf && fallbackReasons.length === 0 && !retrieval?.lexical_only) return null;
  const denseHits = safeInteger(gateway?.dense_hit_count);
  const lexicalHits = safeInteger(gateway?.lexical_hit_count);
  const visualHits = safeInteger(gateway?.visual_hit_count);
  const candidateCount = safeInteger(gateway?.candidate_count);
  return (
    <div className="mt-3 border-t border-outline-variant/40 pt-2">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className="flex min-w-0 items-center gap-1 text-xs text-foreground/55 transition-colors hover:text-foreground/75"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <Network className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="truncate">
          检索状态 · dense {denseHits} · lexical {lexicalHits} · visual {visualHits}
        </span>
      </button>
      {expanded && (
        <div className="mt-2 space-y-2 rounded border border-outline-variant/50 bg-surface-lowest p-2 text-xs text-foreground/65">
          {gateway ? (
            <div className="grid gap-1 sm:grid-cols-2">
              <span>候选: {candidateCount}</span>
              <span>Dense: {gateway.dense_enabled ? '可用' : '未启用'}</span>
              <span>Chroma: {sanitizeDiagnosticLabel(gateway.chroma_status, 'unavailable')}</span>
              <span>FTS: {sanitizeDiagnosticLabel(gateway.fts_status, 'unavailable')}</span>
            </div>
          ) : null}
          {tolf ? (
            <div className="grid gap-1 sm:grid-cols-2">
              <span>TOLF: {sanitizeDiagnosticLabel(tolf.status, 'active')}</span>
              <span>图: {safeInteger(tolf.graph_node_count)} 节点 / {safeInteger(tolf.graph_edge_count)} 边</span>
              <span>Gate 后: {safeInteger(tolf.gate_after_count)}</span>
              <span>激活均值: {formatDiagnosticNumber(tolf.activation_mean)}</span>
              <span>最高排序分: {formatDiagnosticNumber(tolf.top_final_rank_score)}</span>
              <span>贡献: {formatDiagnosticList(tolf.rank_contribution_keys)}</span>
            </div>
          ) : null}
          {retrieval?.lexical_only ? (
            <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-amber-800 dark:border-amber-700/40 dark:bg-amber-500/15 dark:text-amber-200">
              当前回答进入 lexical-only fallback。
            </div>
          ) : null}
          {fallbackReasons.length > 0 ? (
            <div className="text-foreground/55">
              fallback: {formatDiagnosticList(fallbackReasons)}
            </div>
          ) : null}
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
  const retrieval = diagnostics.retrieval;
  if (retrieval?.retrieval_method) {
    const method = sanitizeDiagnosticLabel(retrieval.retrieval_method, '检索');
    const embedding = sanitizeDiagnosticLabel(retrieval.embedding_status, '');
    const rerank = sanitizeDiagnosticLabel(retrieval.rerank_status, '');
    const tip = [embedding ? `Embedding ${embedding}` : '', rerank ? `Rerank ${rerank}` : ''].filter(Boolean).join(' / ');
    items.push(
      <span key="retrieval" title={tip || '检索诊断'}>
        {method}
      </span>,
    );
  }
  if (retrieval?.lexical_only) {
    items.push(
      <span key="lexical-only" className="text-amber-700 dark:text-amber-300" title="Dense 路径不可用，当前使用词面检索 fallback">
        lexical-only fallback
      </span>,
    );
  }
  if (retrieval?.gateway) {
    items.push(
      <span key="gateway-counts" title="dense / lexical / visual 命中数">
        {safeInteger(retrieval.gateway.dense_hit_count)} / {safeInteger(retrieval.gateway.lexical_hit_count)} / {safeInteger(retrieval.gateway.visual_hit_count)} 命中
      </span>,
    );
  }
  if (retrieval?.tolf) {
    items.push(
      <span key="tolf-graph" title="TOLF 图节点 / 边 / gate 后候选">
        TOLF {safeInteger(retrieval.tolf.graph_node_count)} 节点 · {safeInteger(retrieval.tolf.graph_edge_count)} 边 · gate {safeInteger(retrieval.tolf.gate_after_count)}
      </span>,
    );
  }
  const qrelsItem = formatQrelsStatus(retrieval?.qrels_status);
  if (qrelsItem) {
    items.push(
      <span key="qrels" title={qrelsItem.title} className={qrelsItem.className}>
        {qrelsItem.label}
      </span>,
    );
    if (qrelsItem.countLabel) {
      items.push(
        <span key="qrels-count" title={qrelsItem.title}>
          {qrelsItem.countLabel}
        </span>,
      );
    }
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

function formatQrelsStatus(qrels: ChatRetrievalQrelsStatus | undefined): {
  label: string;
  countLabel: string;
  title: string;
  className?: string;
} | null {
  if (!qrels) return null;
  const candidateCount = safeInteger(qrels.candidate_qrels_count);
  const reviewedCount = safeInteger(qrels.reviewed_qrels_count);
  const canonicalCount = safeInteger(qrels.canonical_qrels_count);
  if (qrels.status === 'canonical' && qrels.semantic_quality_claim_allowed === true && canonicalCount > 0) {
    return {
      label: '语义质量已验证',
      countLabel: `canonical ${canonicalCount}`,
      title: '已有 canonical qrels，可用于检索质量评估',
      className: 'text-emerald-700 dark:text-emerald-300',
    };
  }
  if (qrels.status === 'reviewed' && reviewedCount > 0) {
    return {
      label: 'qrels 待提升',
      countLabel: `已审 ${reviewedCount}`,
      title: '已有人工 judgment，但尚未提升为 canonical qrels',
      className: 'text-amber-700 dark:text-amber-300',
    };
  }
  if (qrels.status === 'candidate' && candidateCount > 0) {
    return {
      label: 'qrels 待复核',
      countLabel: `候选 ${candidateCount}`,
      title: '候选 qrels 需要人工复核，不能作为语义质量证明',
      className: 'text-amber-700 dark:text-amber-300',
    };
  }
  if (qrels.status === 'missing') {
    return {
      label: 'qrels 未建立',
      countLabel: '',
      title: '没有 canonical qrels，当前只显示检索路径而非质量证明',
      className: 'text-foreground/45',
    };
  }
  return null;
}

function safeCount(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? String(Math.trunc(value))
    : '0';
}

function safeInteger(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0;
}

function formatDiagnosticNumber(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : '未报告';
}

function formatDiagnosticList(values: unknown): string {
  if (!Array.isArray(values)) return '未报告';
  const labels = values
    .map((item) => sanitizeDiagnosticLabel(item, ''))
    .filter(Boolean)
    .slice(0, 6);
  return labels.length > 0 ? labels.join(' / ') : '未报告';
}

function safePercent(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? `${Math.round(Math.min(value, 1) * 100)}%`
    : '0%';
}

function safeWeight(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value.toFixed(1)
    : '0.0';
}

function sanitizeDiagnosticLabel(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback;
  const raw = value.trim();
  if (!raw || raw.length > 48 || DIAGNOSTIC_INTERNAL_TEXT_PATTERN.test(raw)) return fallback;
  return raw.replace(/_/g, ' ');
}

function sanitizeDiagnosticRef(value: string): string {
  const raw = value.trim();
  if (!raw || raw.length > 120) return 'ref';
  if (!/^(?:wiki|chunk|evidence_pack):[a-zA-Z0-9/_:.-]+$/.test(raw)) return 'ref';
  return raw;
}

function sanitizeDiagnosticOptionalText(value: string | null | undefined): string | null {
  const raw = String(value ?? '').trim();
  if (!raw) return null;
  const sanitized = sanitizeDiagnosticText(raw, '');
  return sanitized.trim() ? sanitized : null;
}

function sanitizeDiagnosticText(value: string, fallback: string): string {
  const raw = value.trim();
  if (!raw) return fallback;
  if (raw.length > 320) return fallback;
  if (DIAGNOSTIC_INTERNAL_TEXT_PATTERN.test(raw)) return fallback;
  if (DIAGNOSTIC_IDENTIFIER_PATTERN.test(raw)) return fallback;
  return raw;
}

function formatDiagnosticRelevance(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '未返回';
  return value.toFixed(3);
}

function diagnosticChunkMetaItems(chunk: ChatMessageContextChunk): string[] {
  const items: string[] = [];
  const page = formatDiagnosticPage(chunk.page);
  if (page) items.push(page);
  const section = sanitizeDiagnosticOptionalText(chunk.section_title);
  if (section) items.push(`章节 ${section}`);
  const title = sanitizeDiagnosticOptionalText(chunk.title);
  const source = sanitizeDiagnosticOptionalText(chunk.source);
  if (title && title !== source) items.push(title);
  for (const label of chunk.source_labels ?? []) {
    const safeLabel = sanitizeDiagnosticOptionalText(label);
    if (safeLabel && !items.includes(safeLabel)) {
      items.push(safeLabel);
    }
    if (items.length >= 5) break;
  }
  const hint = sanitizeDiagnosticOptionalText(chunk.source_hint);
  if (hint && !items.includes(hint) && items.length < 5) items.push(hint);
  return items.slice(0, 5);
}

function formatDiagnosticPage(value: unknown): string | null {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return `p.${Math.trunc(value)}`;
  }
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!/^\d{1,5}$/.test(trimmed)) return null;
  const numeric = Number.parseInt(trimmed, 10);
  return numeric > 0 ? `p.${numeric}` : null;
}

function formatDiagnosticOrdinal(index: number): string {
  if (!Number.isFinite(index)) return '1';
  return String(Math.max(1, Math.trunc(index)));
}
