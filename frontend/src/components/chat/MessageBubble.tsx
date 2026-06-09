import { MessageRenderer, type ChatMessageData, type ChatMessageDiagnostics } from './MessageRenderer';
import type { ContextMetadata, ContextTier, EvidenceReference } from '@/services/intelligentChatApi';

interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  tierUsed?: ContextTier;
  contextMetadata?: ContextMetadata;
  evidenceRefs?: EvidenceReference[];
  timestamp?: Date;
  insufficientContext?: boolean;
  actualSamplingParams?: {
    temperature: number;
    top_p: number;
    top_k: number;
    max_tokens: number;
  };
  /** Active project id, used by the canonical evidence pill locator. */
  projectId?: string | null;
}

/**
 * Deprecated compatibility wrapper for legacy imports.
 *
 * Dialog now adapts directly into `Conversation` / `MessageRenderer`; this
 * wrapper keeps older pages on the same rendering path while legacy component
 * imports are being migrated.
 */
export function MessageBubble(props: MessageBubbleProps) {
  const message = mapLegacyBubbleToMessage(props);
  return <MessageRenderer message={message} projectId={props.projectId} />;
}

function mapLegacyBubbleToMessage(props: MessageBubbleProps): ChatMessageData {
  const diagnostics = buildDiagnostics(props);
  return {
    id: `${props.role}-${props.timestamp?.getTime() ?? props.content.slice(0, 32)}`,
    role: props.role,
    content: props.content,
    evidence: props.evidenceRefs?.map((ref) => ({
      evidence_id: ref.chunk_id,
      chunk_id: ref.chunk_id,
      material_id: ref.material_id ?? undefined,
      source: ref.source,
      quote: ref.quote || ref.text,
      text: ref.text || ref.quote,
      score: ref.score ?? undefined,
      page: normalizePage(ref.page),
      source_hint: ref.source_hint ?? undefined,
      source_labels: ref.source_labels,
    })),
    timestamp: props.timestamp?.toISOString(),
    metadata: diagnostics ? { diagnostics } : undefined,
  };
}

function buildDiagnostics(props: MessageBubbleProps): ChatMessageDiagnostics | undefined {
  if (props.role !== 'assistant') return undefined;
  const chunks = props.contextMetadata?.chunks ?? [];
  const diagnostics: ChatMessageDiagnostics = {};
  if (props.tierUsed) {
    diagnostics.tier = props.tierUsed;
  }
  if (props.actualSamplingParams) {
    diagnostics.sampling = props.actualSamplingParams;
  }
  if (props.insufficientContext) {
    diagnostics.insufficient = true;
  }
  if (chunks.length > 0) {
    diagnostics.context = {
      chunkCount: chunks.length,
      sourceCount: new Set(chunks.map((chunk) => chunk.source)).size,
      chunks: chunks.map((chunk) => ({
        index: chunk.index,
        source: chunk.source,
        content: chunk.content,
        relevance_score: chunk.relevance_score,
      })),
    };
  }
  const chunkRefs = Array.from(props.content.matchAll(/\[(chunk-[a-zA-Z0-9_-]+)\]/g), (match) => match[1]);
  if (chunkRefs.length > 0) {
    diagnostics.chunkRefs = chunkRefs;
  }
  return Object.keys(diagnostics).length > 0 ? diagnostics : undefined;
}

function normalizePage(page: number | string | null | undefined): number | null | undefined {
  if (typeof page === 'number') {
    return Number.isFinite(page) && page > 0 ? page : undefined;
  }
  if (typeof page !== 'string' || !page.trim()) {
    return page === null ? null : undefined;
  }
  const parsed = Number(page);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}
