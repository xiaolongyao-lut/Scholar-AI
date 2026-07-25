import type { ChatMessageData } from '@/components/chat/MessageRenderer';
import { sanitizeChatVisibleText } from '@/components/chat/chatDisplay';
import type { GraphPayloadV0 } from './payloadToRf';

type AnswerGraphNode = GraphPayloadV0['nodes'][number];
type AnswerGraphEdge = GraphPayloadV0['edges'][number];
type AnswerGraphEvidenceRef = NonNullable<ChatMessageData['evidence']>[number];

export interface AnswerGraphProjectionOptions {
  readonly sessionId: string;
  readonly turnId?: string | null;
}
interface AnswerTurnMessages {
  readonly turnId: string;
  readonly user: ChatMessageData | null;
  readonly assistant: ChatMessageData;
}

function requiredIdentifier(value: string, fieldName: string): string {
  const normalized = value.trim();
  if (!normalized) {
    throw new Error(`${fieldName} must be a non-empty string`);
  }
  return normalized;
}

function hashGraphText(text: string): string {
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) | 0;
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

function messageTurnId(message: ChatMessageData): string | null {
  const normalized = message.turnId?.trim();
  return normalized || null;
}

function hasGraphEvidence(message: ChatMessageData): boolean {
  return message.role === 'assistant'
    && Array.isArray(message.evidence)
    && message.evidence.length > 0;
}

function resolveTurnMessages(
  messages: readonly ChatMessageData[],
  requestedTurnId: string | null,
): AnswerTurnMessages | null {
  let assistantIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!hasGraphEvidence(message)) continue;
    if (requestedTurnId && messageTurnId(message) !== requestedTurnId) continue;
    assistantIndex = index;
    break;
  }
  if (assistantIndex < 0) return null;

  const assistant = messages[assistantIndex];
  const persistedTurnId = messageTurnId(assistant);
  const turnId = requestedTurnId
    ?? persistedTurnId
    ?? `legacy-${hashGraphText(assistant.id)}`;

  let user: ChatMessageData | null = null;
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    const candidate = messages[index];
    if (candidate.role !== 'user') continue;
    const candidateTurnId = messageTurnId(candidate);
    if (persistedTurnId && candidateTurnId !== persistedTurnId) continue;
    user = candidate;
    break;
  }
  return { turnId, user, assistant };
}

function graphToken(sessionId: string, turnId: string): string {
  return hashGraphText(`${sessionId}\u0000${turnId}`);
}

function evidenceGraphId(
  prefix: string,
  evidence: AnswerGraphEvidenceRef,
  index: number,
): string {
  const materialId = String(evidence.material_id ?? '').trim();
  const chunkId = String(evidence.chunk_id ?? '').trim();
  if (materialId && chunkId) return `${prefix}:evidence:${materialId}:${chunkId}`;
  if (materialId) return `${prefix}:evidence:${materialId}:${index}`;
  const source = String(evidence.source ?? '').trim();
  const text = String(evidence.text ?? '').trim();
  return `${prefix}:evidence:external:${hashGraphText(`${source}|${text}|${index}`)}`;
}

function graphEvidenceText(evidence: AnswerGraphEvidenceRef): string {
  return sanitizeChatVisibleText(
    String(evidence.text ?? evidence.source ?? '').trim(),
    '证据',
    { maxLength: 96 },
  );
}

function graphEvidenceLabel(evidence: AnswerGraphEvidenceRef, index: number): string {
  const source = sanitizeChatVisibleText(
    String(evidence.source ?? '').trim(),
    '',
    { maxLength: 54 },
  );
  if (source) {
    return typeof evidence.page === 'number' && evidence.page > 0
      ? `${source} · p.${evidence.page}`
      : source;
  }
  const text = graphEvidenceText(evidence);
  return text === '证据' ? `证据 ${index + 1}` : text;
}

function materialNodeLabel(evidence: AnswerGraphEvidenceRef, index: number): string {
  const source = sanitizeChatVisibleText(
    String(evidence.source ?? '').trim(),
    '',
    { maxLength: 54 },
  );
  return source || `文献 ${index + 1}`;
}

function graphEvidenceRef(
  evidence: AnswerGraphEvidenceRef,
): AnswerGraphNode['evidence_refs'] {
  const materialId = String(evidence.material_id ?? '').trim();
  if (!materialId) return null;
  return [{
    material_id: materialId,
    chunk_id: evidence.chunk_id ?? null,
    page: typeof evidence.page === 'number' && evidence.page > 0 ? evidence.page : null,
    bbox: evidence.bbox ?? null,
    bbox_unit: evidence.bbox_unit ?? null,
    text: graphEvidenceText(evidence),
    score: null,
  }];
}

function scopedMetadata(
  sessionId: string,
  turnId: string,
  extra: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
  return {
    surface: 'answer',
    graph_scope: 'argument',
    session_id: sessionId,
    turn_id: turnId,
    ...extra,
  };
}

/**
 * Project exactly one answer turn into `question -> claim -> evidence -> paper`.
 * The stable scope is `session_id + turn_id`; question text is display-only and
 * never participates in turn selection.
 */
export function buildAnswerTurnGraphPayload(
  messages: readonly ChatMessageData[],
  options: AnswerGraphProjectionOptions,
): GraphPayloadV0 | null {
  const sessionId = requiredIdentifier(options.sessionId, 'sessionId');
  const requestedTurnId = options.turnId?.trim() || null;
  const turn = resolveTurnMessages(messages, requestedTurnId);
  if (!turn) return null;

  const token = graphToken(sessionId, turn.turnId);
  const prefix = `answer:${token}`;
  const questionId = `${prefix}:question`;
  const claimId = `${prefix}:claim`;
  const nodes = new Map<string, AnswerGraphNode>();
  const edges = new Map<string, AnswerGraphEdge>();
  const materialEvidenceCounts = new Map<string, number>();

  const questionLabel = sanitizeChatVisibleText(
    turn.user?.content ?? '',
    '当前研读问题',
    { maxLength: 88 },
  );
  const claimLabel = sanitizeChatVisibleText(
    turn.assistant.content,
    '当前回答',
    { maxLength: 112 },
  );
  nodes.set(questionId, {
    id: questionId,
    label: questionLabel,
    type: 'concept',
    material_id: null,
    source_ref: null,
    evidence_refs: null,
    confidence: null,
    metadata: scopedMetadata(sessionId, turn.turnId, {
      reasoning_dimension: 'question',
      message_id: turn.user?.id ?? null,
      role: 'question',
    }),
  });
  nodes.set(claimId, {
    id: claimId,
    label: claimLabel,
    type: 'claim',
    material_id: null,
    source_ref: null,
    evidence_refs: null,
    confidence: null,
    metadata: scopedMetadata(sessionId, turn.turnId, {
      reasoning_dimension: 'observation',
      message_id: turn.assistant.id,
      role: 'answer_claim',
    }),
  });
  edges.set(`${prefix}:question-to-claim`, {
    id: `${prefix}:question-to-claim`,
    source: questionId,
    target: claimId,
    relation: 'extends',
    direction: 'directed',
    material_id: null,
    source_ref: null,
    evidence_refs: null,
    confidence: null,
    metadata: scopedMetadata(sessionId, turn.turnId, { relation_role: 'answers' }),
  });

  const evidenceItems = turn.assistant.evidence ?? [];
  for (const [evidenceIndex, evidence] of evidenceItems.entries()) {
    const evidenceId = evidenceGraphId(prefix, evidence, evidenceIndex);
    const evidenceRefs = graphEvidenceRef(evidence);
    const materialId = String(evidence.material_id ?? '').trim();
    if (!nodes.has(evidenceId)) {
      nodes.set(evidenceId, {
        id: evidenceId,
        label: graphEvidenceLabel(evidence, evidenceIndex),
        type: 'evidence',
        material_id: materialId || null,
        source_ref: materialId
          ? {
              material_id: materialId,
              chunk_id: evidence.chunk_id ?? null,
              page: typeof evidence.page === 'number' && evidence.page > 0 ? evidence.page : null,
              bbox: evidence.bbox ?? null,
              bbox_unit: evidence.bbox_unit ?? null,
            }
          : null,
        evidence_refs: evidenceRefs,
        confidence: null,
        metadata: scopedMetadata(sessionId, turn.turnId, {
          source_kind: evidence.source_kind ?? 'local',
          evidence_text: graphEvidenceText(evidence),
          reasoning_dimension: 'evidence',
        }),
      });
    }
    const claimToEvidenceId = `${prefix}:claim-to:${evidenceId}`;
    edges.set(claimToEvidenceId, {
      id: claimToEvidenceId,
      source: claimId,
      target: evidenceId,
      relation: 'uses',
      direction: 'directed',
      material_id: materialId || null,
      source_ref: null,
      evidence_refs: evidenceRefs,
      confidence: null,
      metadata: scopedMetadata(sessionId, turn.turnId, { relation_role: 'supported_by' }),
    });

    if (!materialId) continue;
    const materialNodeId = `${prefix}:material:${materialId}`;
    const previousCount = materialEvidenceCounts.get(materialNodeId) ?? 0;
    materialEvidenceCounts.set(materialNodeId, previousCount + 1);
    const existingMaterial = nodes.get(materialNodeId);
    if (existingMaterial) {
      nodes.set(materialNodeId, {
        ...existingMaterial,
        label: `${existingMaterial.label.replace(/\s·\s\d+\s条证据$/, '')} · ${previousCount + 1} 条证据`,
        evidence_refs: [
          ...(existingMaterial.evidence_refs ?? []),
          ...(evidenceRefs ?? []),
        ],
      });
    } else {
      nodes.set(materialNodeId, {
        id: materialNodeId,
        label: `${materialNodeLabel(evidence, evidenceIndex)} · 1 条证据`,
        type: 'material',
        material_id: materialId,
        source_ref: {
          material_id: materialId,
          chunk_id: evidence.chunk_id ?? null,
          page: typeof evidence.page === 'number' && evidence.page > 0 ? evidence.page : null,
          bbox: evidence.bbox ?? null,
          bbox_unit: evidence.bbox_unit ?? null,
        },
        evidence_refs: evidenceRefs,
        confidence: null,
        metadata: scopedMetadata(sessionId, turn.turnId, {
          evidence_count: 1,
          reasoning_dimension: 'evidence',
          role: 'paper',
        }),
      });
    }
    const evidenceToMaterialId = `${prefix}:${evidenceId}-to-${materialNodeId}`;
    edges.set(evidenceToMaterialId, {
      id: evidenceToMaterialId,
      source: evidenceId,
      target: materialNodeId,
      relation: 'cites',
      direction: 'directed',
      material_id: materialId,
      source_ref: null,
      evidence_refs: evidenceRefs,
      confidence: null,
      metadata: scopedMetadata(sessionId, turn.turnId, { relation_role: 'from_paper' }),
    });
  }

  return {
    version: 'v0',
    scope: { kind: 'question', ref: `${sessionId}:${turn.turnId}` },
    updated_at: turn.assistant.timestamp ?? new Date().toISOString(),
    nodes: Array.from(nodes.values()),
    edges: Array.from(edges.values()),
  };
}
