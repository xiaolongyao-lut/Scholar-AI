import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  resumeChatSession,
  streamIntelligentChatMessage,
  type ChatResumeMessage,
  type CurrentPdfContext,
  type IntelligentChatStreamEvent,
} from '@/services/intelligentChatApi';
import {
  backendTierForCostTier,
  loadSmartReadCostTier,
  type SmartReadCostTier,
} from '@/services/smartReadTiers';
import type {
  ChatMessageContextChunk,
  ChatMessageData,
  ChatMessageDiagnostics,
  ChatRole,
} from '@/components/chat/MessageRenderer';
import { formatChatVisibleError } from '@/components/chat/chatDisplay';
import type { EvidenceRefLike } from '@/components/evidence/EvidencePill';
import { readEnv } from '@/services/env';

const SMART_READ_DEBUG_ENABLED = readEnv('VITE_SMART_READ_DEBUG') === '1';

/**
 * Cross-route + cross-reload persistent state for the smart-read (RAG QA)
 * conversation surface used by Workbench Inspector.
 *
 * Two concerns lifted out of consumer components:
 *
 *   1. The axios POST lives in the Provider so a chat that's still in
 *      flight when the user navigates away (or refreshes the page) does
 *      not lose its assistant reply — the Provider survives route changes,
 *      and localStorage persistence rehydrates after full reloads.
 *
 *   2. Conversations are scoped — Workbench Inspector keys by paper
 *      ``materialId`` so each paper keeps its own history; a default
 *      scope (``'_default'``) is reserved for project-level chat surfaces
 *      that aren't paper-anchored.
 *
 * Storage shape (localStorage key ``smart-read-conversations-v1``):
 *   { [scope: string]: { messages: ChatMessageData[]; updatedAt: number; sessionId?: string } }
 *
 * The ``pending`` flag is NOT persisted — if the user refreshed mid-flight
 * the Promise is dropped (the in-process axios reference is gone) so we
 * intentionally show the half-finished conversation without a spinner
 * rather than a phantom "thinking" pill. Backend task persistence is the
 * follow-up that closes this remaining gap.
 */

const STORAGE_KEY = 'smart-read-conversations-v1';
const LEGACY_DIALOG_MIGRATION_KEY = 'smart-read-dialog-migration-v1';
const LEGACY_DIALOG_STORAGE_PREFIX = 'dialog-messages_';
const LEGACY_DIALOG_MODES = ['literature_qa', 'direct', 'inspiration'] as const;
const SMART_READ_DIALOG_SCOPE_PREFIX = 'dialog-';

interface PersistedConversation {
  messages: ChatMessageData[];
  updatedAt: number;
  sessionId?: string;
}

interface RuntimeConversation extends PersistedConversation {
  pending: boolean;
}

interface SendOptions {
  projectId?: string | null;
  materialId?: string | null;
  currentPdfContext?: CurrentPdfContext | null;
  projectReasoningBiasEnabled?: boolean;
  tier?: SmartReadCostTier;
}

interface SetConversationOptions {
  updatedAt?: number;
  sessionId?: string | null;
}

type SmartReadStreamMetadata = Extract<IntelligentChatStreamEvent, { event: 'metadata' }>;
type SmartReadUsageEvent = Extract<IntelligentChatStreamEvent, { event: 'usage' }>;
type SmartReadAnalysisChainEvent = Extract<IntelligentChatStreamEvent, { event: 'analysis_chain_done' }>;

interface SmartReadContextValue {
  getConversation(scope: string): RuntimeConversation;
  sendMessage(scope: string, text: string, opts: SendOptions): Promise<void>;
  stopMessage(scope: string): void;
  setConversation(scope: string, messages: ChatMessageData[], options?: SetConversationOptions): void;
  appendMessages(scope: string, messages: ChatMessageData[]): void;
  clearConversation(scope: string): void;
}

const SmartReadContext = createContext<SmartReadContextValue | null>(null);

const EMPTY_CONVERSATION: RuntimeConversation = {
  messages: [],
  updatedAt: 0,
  pending: false,
};

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'key' | 'length'>;

function normalizeScope(scope: string): string {
  const normalized = scope.trim();
  if (!normalized) {
    throw new Error('SmartRead conversation scope must not be empty');
  }
  return normalized;
}

export function smartReadDialogScope(projectId?: string | null): string {
  const normalizedProjectId = String(projectId || '').trim() || 'default';
  return `${SMART_READ_DIALOG_SCOPE_PREFIX}${normalizedProjectId}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed || undefined;
}

function readContentString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  return value;
}

function readFiniteNumber(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
  return value;
}

function readSessionId(value: unknown): string | undefined {
  const raw = readString(value);
  return raw && raw.length <= 256 ? raw : undefined;
}

function readChatRole(value: unknown): ChatRole | null {
  if (value === 'user' || value === 'assistant' || value === 'system' || value === 'agent') {
    return value;
  }
  return null;
}

function readTimestampIso(value: unknown): string | undefined {
  const raw = readString(value);
  if (!raw) return undefined;
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}

function timestampMillis(message: ChatMessageData): number {
  if (!message.timestamp) return 0;
  const parsed = new Date(message.timestamp);
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
}

function readEvidencePage(value: unknown): number | null | undefined {
  if (value === null) return null;
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
  }
  return undefined;
}

function coerceEvidenceRefs(value: unknown): EvidenceRefLike[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const refs = value.flatMap((item): EvidenceRefLike[] => {
    if (!isRecord(item)) return [];
    const sourceKind = item.source_kind;
    const ref: EvidenceRefLike = {
      evidence_id: readString(item.evidence_id) ?? readString(item.chunk_id) ?? null,
      material_id: readString(item.material_id) ?? null,
      chunk_id: readString(item.chunk_id) ?? null,
      page: readEvidencePage(item.page) ?? null,
      text: readString(item.text) ?? readString(item.quote) ?? null,
      source: readString(item.source) ?? null,
      source_kind: sourceKind === 'web' || sourceKind === 'mcp' || sourceKind === 'local'
        ? sourceKind
        : 'local',
    };
    return [ref];
  });
  return refs.length > 0 ? refs : undefined;
}

function extractChunkRefs(content: string): string[] {
  return Array.from(content.matchAll(/\[(chunk-[a-zA-Z0-9_-]+)\]/g), (match) => match[1]);
}

function coerceLegacyContextDiagnostics(value: unknown): ChatMessageDiagnostics['context'] | undefined {
  if (!isRecord(value) || !Array.isArray(value.chunks)) return undefined;
  const chunks = value.chunks.flatMap((item): ChatMessageContextChunk[] => {
    if (!isRecord(item)) return [];
    const index = readFiniteNumber(item.index);
    const source = readString(item.source);
    const content = readString(item.content);
    if (index === undefined || !source || !content) return [];
    return [{
      index,
      source,
      content,
      relevance_score: readFiniteNumber(item.relevance_score),
    }];
  });
  if (!chunks || chunks.length === 0) return undefined;
  return {
    chunkCount: chunks.length,
    sourceCount: new Set(chunks.map((chunk) => chunk.source)).size,
    chunks,
  };
}

function coerceLegacySampling(value: unknown): ChatMessageDiagnostics['sampling'] | undefined {
  if (!isRecord(value)) return undefined;
  const sampling = {
    temperature: readFiniteNumber(value.temperature),
    top_p: readFiniteNumber(value.top_p),
    top_k: readFiniteNumber(value.top_k),
    max_tokens: readFiniteNumber(value.max_tokens),
  };
  return Object.values(sampling).some((item) => typeof item === 'number') ? sampling : undefined;
}

function coerceLegacyDiagnostics(record: Record<string, unknown>, content: string): ChatMessageDiagnostics | undefined {
  const diagnostics: ChatMessageDiagnostics = {};
  const tier = record.tierUsed;
  if (tier === 'fast' || tier === 'balanced' || tier === 'thorough') {
    diagnostics.tier = tier;
  }
  const sampling = coerceLegacySampling(record.actualSamplingParams);
  if (sampling) {
    diagnostics.sampling = sampling;
  }
  const context = coerceLegacyContextDiagnostics(record.contextMetadata);
  if (context) {
    diagnostics.context = context;
  }
  if (record.insufficientContext === true) {
    diagnostics.insufficient = true;
  }
  const chunkRefs = extractChunkRefs(content);
  if (chunkRefs.length > 0) {
    diagnostics.chunkRefs = chunkRefs;
  }
  return Object.keys(diagnostics).length > 0 ? diagnostics : undefined;
}

function coerceLegacyDialogMessage(value: unknown, index: number): ChatMessageData | null {
  if (!isRecord(value)) return null;
  const role = readChatRole(value.role);
  const content = readContentString(value.content);
  if (!role || content === undefined) return null;

  const timestamp = readTimestampIso(value.timestamp);
  const message: ChatMessageData = {
    id: readString(value.id) ?? `legacy-dialog-${role}-${timestamp ?? index}`,
    role,
    content,
    timestamp,
  };

  if (role === 'assistant' || role === 'agent') {
    const evidence = coerceEvidenceRefs(value.evidenceRefs);
    const diagnostics = coerceLegacyDiagnostics(value, content);
    if (evidence) {
      message.evidence = evidence;
    }
    if (diagnostics) {
      message.metadata = { diagnostics };
    }
  }

  return message;
}

function coerceLegacyDialogMessages(raw: string): ChatMessageData[] {
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed)) return [];
  return parsed.flatMap((item, index): ChatMessageData[] => {
    const message = coerceLegacyDialogMessage(item, index);
    return message ? [message] : [];
  });
}

function coerceChatMessageData(value: unknown): ChatMessageData | null {
  if (!isRecord(value)) return null;
  const role = readChatRole(value.role);
  const id = readString(value.id);
  const content = readContentString(value.content);
  if (!role || !id || content === undefined) return null;
  return value as unknown as ChatMessageData;
}

function coercePersistedConversation(value: unknown): PersistedConversation | null {
  if (!isRecord(value) || !Array.isArray(value.messages)) return null;
  const messages = value.messages.flatMap((item): ChatMessageData[] => {
    const message = coerceChatMessageData(item);
    return message ? [message] : [];
  });
  const updatedAt = readFiniteNumber(value.updatedAt)
    ?? Math.max(0, ...messages.map(timestampMillis))
    ?? Date.now();
  const sessionId = readSessionId(value.sessionId ?? value.session_id);
  return sessionId ? { messages, updatedAt, sessionId } : { messages, updatedAt };
}

function readPersistedStore(storage: StorageLike): Record<string, PersistedConversation> {
  const raw = storage.getItem(STORAGE_KEY);
  if (!raw) return {};
  const parsed: unknown = JSON.parse(raw);
  if (!isRecord(parsed)) return {};
  const store: Record<string, PersistedConversation> = {};
  for (const [scope, value] of Object.entries(parsed)) {
    const normalizedScope = readString(scope);
    const conversation = coercePersistedConversation(value);
    if (normalizedScope && conversation) {
      store[normalizedScope] = conversation;
    }
  }
  return store;
}

function readMigratedLegacyKeys(storage: StorageLike): Set<string> {
  const raw = storage.getItem(LEGACY_DIALOG_MIGRATION_KEY);
  if (!raw) return new Set<string>();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return new Set(parsed.filter((item): item is string => typeof item === 'string'));
    }
    if (isRecord(parsed) && Array.isArray(parsed.migratedKeys)) {
      return new Set(parsed.migratedKeys.filter((item): item is string => typeof item === 'string'));
    }
  } catch {
    return new Set<string>();
  }
  return new Set<string>();
}

function writeMigratedLegacyKeys(storage: StorageLike, keys: Set<string>): void {
  storage.setItem(LEGACY_DIALOG_MIGRATION_KEY, JSON.stringify({
    version: 1,
    migratedKeys: Array.from(keys).sort(),
  }));
}

function listLegacyDialogMessageKeys(storage: StorageLike): string[] {
  const keys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key?.startsWith(LEGACY_DIALOG_STORAGE_PREFIX)) {
      keys.push(key);
    }
  }
  return keys.sort();
}

function scopeFromLegacyDialogKey(key: string): string | null {
  if (!key.startsWith(LEGACY_DIALOG_STORAGE_PREFIX)) return null;
  let rawScope = key.slice(LEGACY_DIALOG_STORAGE_PREFIX.length).trim();
  for (const mode of LEGACY_DIALOG_MODES) {
    const suffix = `_${mode}`;
    if (rawScope.endsWith(suffix)) {
      rawScope = rawScope.slice(0, -suffix.length).trim();
      break;
    }
  }
  return rawScope ? smartReadDialogScope(rawScope) : null;
}

function messageIdentity(message: ChatMessageData): string {
  const id = readString(message.id);
  if (id) return `id:${id}`;
  return `body:${message.role}:${message.timestamp ?? ''}:${message.content}`;
}

function mergeMessages(existing: ChatMessageData[], incoming: ChatMessageData[]): ChatMessageData[] {
  const seen = new Set<string>();
  const merged: ChatMessageData[] = [];
  for (const message of [...existing, ...incoming]) {
    const identity = messageIdentity(message);
    if (seen.has(identity)) continue;
    seen.add(identity);
    merged.push(message);
  }
  return merged;
}

function replaceOrAppendMessage(messages: ChatMessageData[], nextMessage: ChatMessageData): ChatMessageData[] {
  const index = messages.findIndex((message) => message.id === nextMessage.id);
  if (index < 0) return [...messages, nextMessage];
  return [
    ...messages.slice(0, index),
    nextMessage,
    ...messages.slice(index + 1),
  ];
}

function hasStreamingAssistantMessage(messages: ChatMessageData[]): boolean {
  return messages.some((message) => (
    message.role === 'assistant' && message.status === 'streaming'
  ));
}

function evidenceFromStreamMetadata(metadata: SmartReadStreamMetadata | null): EvidenceRefLike[] | undefined {
  const refs = metadata?.evidence_refs;
  if (!refs || refs.length === 0) return undefined;
  return refs.map((ref) => ({
    evidence_id: ref.chunk_id,
    material_id: ref.material_id ?? null,
    chunk_id: ref.chunk_id ?? null,
    page: readEvidencePage(ref.page) ?? null,
    bbox: ref.bbox ?? null,
    bbox_unit: ref.bbox_unit ?? null,
    text: ref.text ?? ref.quote ?? null,
    source: ref.source ?? null,
    source_kind: ref.source_kind ?? 'local',
  }));
}

function evidenceFromResumeMessage(message: ChatResumeMessage): EvidenceRefLike[] | undefined {
  const refs = message.evidence_refs ?? [];
  if (refs.length === 0) return undefined;
  return refs.map((ref) => ({
    evidence_id: ref.chunk_id,
    material_id: ref.material_id ?? null,
    chunk_id: ref.chunk_id ?? null,
    page: readEvidencePage(ref.page) ?? null,
    bbox: ref.bbox ?? null,
    bbox_unit: ref.bbox_unit ?? null,
    text: ref.text ?? ref.quote ?? null,
    source: ref.source ?? null,
    source_kind: ref.source_kind ?? 'local',
  }));
}

function diagnosticsFromResumeMessage(message: ChatResumeMessage): ChatMessageDiagnostics | undefined {
  if (message.role !== 'assistant') return undefined;
  const chunks = message.context_metadata?.chunks ?? [];
  const sourceCount = new Set(
    chunks.map((chunk) => chunk.source).filter((source): source is string => typeof source === 'string'),
  ).size;
  const diagnostics: ChatMessageDiagnostics = {
    tier: message.tier_used ?? undefined,
    context: chunks.length > 0
      ? {
          chunkCount: chunks.length,
          sourceCount,
          chunks: chunks.map((chunk) => ({
            index: chunk.index,
            source: chunk.source,
            content: chunk.content,
            relevance_score: chunk.relevance_score,
          })),
        }
      : undefined,
    tokens: message.tokens_used
      ? {
          prompt: message.tokens_used.prompt,
          completion: message.tokens_used.completion,
          total: message.tokens_used.total,
        }
      : undefined,
    insufficient: message.context_metadata ? chunks.length === 0 : undefined,
  };
  return Object.values(diagnostics).some((value) => value !== undefined) ? diagnostics : undefined;
}

function messageFromResumeMessage(message: ChatResumeMessage): ChatMessageData | null {
  if (message.role !== 'user' && message.role !== 'assistant') return null;
  const timestamp = readTimestampIso(message.timestamp) ?? new Date().toISOString();
  const next: ChatMessageData = {
    id: message.id,
    role: message.role,
    content: message.content,
    timestamp,
    status: 'done',
  };
  const evidence = evidenceFromResumeMessage(message);
  const diagnostics = diagnosticsFromResumeMessage(message);
  if (evidence) {
    next.evidence = evidence;
  }
  if (diagnostics) {
    next.metadata = { diagnostics };
  }
  if (message.analysis_chain) {
    next.analysis_chain = message.analysis_chain;
  }
  return next;
}

function messagesFromResumePayload(messages: ChatResumeMessage[]): ChatMessageData[] {
  return messages.flatMap((message): ChatMessageData[] => {
    const mapped = messageFromResumeMessage(message);
    return mapped ? [mapped] : [];
  });
}

function diagnosticsFromStream(
  metadata: SmartReadStreamMetadata | null,
  usage: SmartReadUsageEvent | null,
): ChatMessageDiagnostics | undefined {
  if (!metadata) return undefined;
  const chunks = metadata.context_metadata?.chunks ?? [];
  const sourceCount = new Set(
    chunks.map((chunk) => chunk.source).filter((source): source is string => typeof source === 'string'),
  ).size;
  const tokenPayload = usage?.usage;
  const diagnostics: ChatMessageDiagnostics = {
    tier: metadata.tier_used,
    sampling: metadata.actual_sampling_params ?? undefined,
    context: chunks.length > 0
      ? {
          chunkCount: chunks.length,
          sourceCount,
          chunks: chunks.map((chunk) => ({
            index: chunk.index,
            source: chunk.source,
            content: chunk.content,
            relevance_score: chunk.relevance_score,
          })),
        }
      : undefined,
    insufficient: metadata.context_chunks_used === 0,
  };
  if (tokenPayload) {
    diagnostics.tokens = {
      prompt: tokenPayload.prompt ?? tokenPayload.prompt_tokens,
      completion: tokenPayload.completion ?? tokenPayload.completion_tokens,
      total: tokenPayload.total ?? tokenPayload.total_tokens,
    };
  }
  return diagnostics;
}

function updatedAtForMessages(messages: ChatMessageData[]): number {
  return Math.max(Date.now(), ...messages.map(timestampMillis));
}

function migrateLegacyDialogMessages(storage: StorageLike): Record<string, PersistedConversation> {
  const currentStore = readPersistedStore(storage);
  const migratedKeys = readMigratedLegacyKeys(storage);
  const legacyKeys = listLegacyDialogMessageKeys(storage);
  let nextStore = currentStore;
  let changedStore = false;
  let changedMigrationState = false;

  for (const key of legacyKeys) {
    if (migratedKeys.has(key)) continue;
    changedMigrationState = true;
    migratedKeys.add(key);

    const scope = scopeFromLegacyDialogKey(key);
    const raw = storage.getItem(key);
    if (!scope || !raw) continue;

    try {
      const messages = coerceLegacyDialogMessages(raw);
      if (messages.length === 0) continue;
      const existingMessages = nextStore[scope]?.messages ?? [];
      const merged = mergeMessages(existingMessages, messages);
      nextStore = {
        ...nextStore,
        [scope]: {
          messages: merged,
          updatedAt: updatedAtForMessages(merged),
          sessionId: nextStore[scope]?.sessionId,
        },
      };
      changedStore = true;
    } catch {
      // The legacy key is marked processed below; malformed old drafts should
      // not block every future SmartReadProvider mount.
    }
  }

  if (changedStore) {
    storage.setItem(STORAGE_KEY, JSON.stringify(nextStore));
  }
  if (changedMigrationState) {
    writeMigratedLegacyKeys(storage, migratedKeys);
  }
  return nextStore;
}

function loadPersisted(): Record<string, PersistedConversation> {
  if (typeof window === 'undefined') return {};
  try {
    const migratedStore = migrateLegacyDialogMessages(window.localStorage);
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      // B7+ (0.1.8.2 hotfix v3): visible trace so users debugging
      // "持久化又丢了" can confirm whether localStorage simply had no
      // entry (fresh install / cleared) vs. a parse / quota issue.
      if (typeof console !== 'undefined' && SMART_READ_DEBUG_ENABLED) {
        console.info('[SmartReadContext] localStorage empty on mount; starting fresh.');
      }
      return migratedStore;
    }
    const parsed = readPersistedStore(window.localStorage);
    if (typeof console !== 'undefined' && SMART_READ_DEBUG_ENABLED) {
      console.info(
        '[SmartReadContext] localStorage restored: %d scopes, keys=%o',
        Object.keys(parsed).length,
        Object.keys(parsed),
      );
    }
    return parsed;
  } catch (err) {
    if (typeof console !== 'undefined') {
      console.warn('[SmartReadContext] localStorage parse failed; resetting.', err);
    }
    return {};
  }
}

function persistSnapshot(store: Record<string, PersistedConversation>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch (err) {
    // B7+: surface quota / serialization failures so the user can see
    // *why* persistence silently drops their conversation.
    if (typeof console !== 'undefined') {
      console.warn('[SmartReadContext] localStorage write failed:', err);
    }
  }
}

function conversationSnapshot(
  messages: ChatMessageData[],
  updatedAt: number,
  sessionId?: string | null,
): PersistedConversation {
  const normalizedSessionId = readSessionId(sessionId);
  return normalizedSessionId ? { messages, updatedAt, sessionId: normalizedSessionId } : { messages, updatedAt };
}

function isAbortError(value: unknown): boolean {
  if (value instanceof DOMException && value.name === 'AbortError') return true;
  if (!isRecord(value)) return false;
  return value.name === 'AbortError';
}

export function SmartReadProvider({ children }: { children: ReactNode }) {
  // store + pending kept as separate maps so an in-flight chat doesn't
  // serialize a transient pending=true into localStorage.
  const [store, setStore] = useState<Record<string, PersistedConversation>>(
    () => loadPersisted(),
  );
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const storeRef = useRef(store);
  const hydratedSessionsRef = useRef<Set<string>>(new Set());
  const mountedRef = useRef(true);
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    storeRef.current = store;
  }, [store]);

  useEffect(() => {
    persistSnapshot(store);
  }, [store]);

  useEffect(() => {
    for (const [scope, conversation] of Object.entries(store)) {
      const sessionId = conversation.sessionId;
      if (!sessionId || pending[scope]) continue;
      if (hasStreamingAssistantMessage(conversation.messages)) continue;
      const hydrationKey = `${scope}\u0000${sessionId}`;
      if (hydratedSessionsRef.current.has(hydrationKey)) continue;
      hydratedSessionsRef.current.add(hydrationKey);
      void resumeChatSession({ session_id: sessionId, limit: 100 })
        .then((response) => {
          if (!mountedRef.current || response.session_id !== sessionId) return;
          const latestConversation = storeRef.current[scope];
          if (
            !latestConversation ||
            latestConversation.sessionId !== sessionId ||
            hasStreamingAssistantMessage(latestConversation.messages)
          ) {
            return;
          }
          const restoredMessages = messagesFromResumePayload(response.messages);
          if (restoredMessages.length === 0) return;
          setStore((prev) => ({
            ...prev,
            [scope]: conversationSnapshot(
              restoredMessages,
              updatedAtForMessages(restoredMessages),
              sessionId,
            ),
          }));
        })
        .catch((error: unknown) => {
          if (typeof console !== 'undefined') {
            console.warn('[SmartReadContext] backend session hydrate failed; keeping local snapshot.', error);
          }
        });
    }
  }, [store, pending]);

  const getConversation = useCallback(
    (scope: string): RuntimeConversation => {
      const normalizedScope = normalizeScope(scope);
      const entry = store[normalizedScope] ?? { messages: [], updatedAt: 0 };
      return {
        messages: entry.messages,
        updatedAt: entry.updatedAt,
        sessionId: entry.sessionId,
        pending: Boolean(pending[normalizedScope]),
      };
    },
    [store, pending],
  );

  const sendMessage = useCallback(
    async (scope: string, text: string, opts: SendOptions): Promise<void> => {
      const normalizedScope = normalizeScope(scope);
      const userMsg: ChatMessageData = {
        id: `u-${Date.now()}`,
        role: 'user',
        content: text,
        timestamp: new Date().toISOString(),
      };
      const assistantId = `a-${Date.now()}`;
      const assistantDraft: ChatMessageData = {
        id: assistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
        status: 'streaming',
      };
      const startingSessionId = storeRef.current[normalizedScope]?.sessionId;
      const abortController = new AbortController();
      abortControllersRef.current.get(normalizedScope)?.abort();
      abortControllersRef.current.set(normalizedScope, abortController);
      // Optimistically append the user message + flip pending.
      setStore((prev) => ({
        ...prev,
        [normalizedScope]: conversationSnapshot(
          [...(prev[normalizedScope]?.messages ?? []), userMsg, assistantDraft],
          Date.now(),
          prev[normalizedScope]?.sessionId,
        ),
      }));
      setPending((prev) => ({ ...prev, [normalizedScope]: true }));

      try {
        let metadata: SmartReadStreamMetadata | null = null;
        let usage: SmartReadUsageEvent | null = null;
        let analysisChain: SmartReadAnalysisChainEvent['analysis_chain'] | null = null;
        let activeSessionId = startingSessionId;
        let streamedContent = '';
        const updateAssistant = (patch: Partial<ChatMessageData>) => {
          setStore((prev) => {
            const current = prev[normalizedScope]?.messages ?? [];
            const existing = current.find((message) => message.id === assistantId) ?? assistantDraft;
            const nextMessage: ChatMessageData = {
              ...existing,
              ...patch,
              metadata: patch.metadata ?? existing.metadata,
            };
            return {
              ...prev,
              [normalizedScope]: conversationSnapshot(
                replaceOrAppendMessage(current, nextMessage),
                Date.now(),
                activeSessionId ?? prev[normalizedScope]?.sessionId,
              ),
            };
          });
        };

        await streamIntelligentChatMessage(
          {
            query: text,
            session_id: startingSessionId,
            project_id: opts.projectId || undefined,
            project_reasoning_bias_enabled: opts.projectReasoningBiasEnabled,
            material_id: opts.materialId || undefined,
            current_pdf_context: opts.currentPdfContext || undefined,
            mode: 'literature_qa',
            tier: backendTierForCostTier(opts.tier ?? loadSmartReadCostTier('medium')),
          },
          {
            signal: abortController.signal,
            onEvent: (event) => {
              if (event.event === 'metadata') {
                metadata = event;
                activeSessionId = event.session_id || activeSessionId;
                updateAssistant({
                  evidence: evidenceFromStreamMetadata(metadata),
                  metadata: { diagnostics: diagnosticsFromStream(metadata, usage) },
                });
                return;
              }
              if (event.event === 'usage') {
                usage = event;
                updateAssistant({
                  metadata: { diagnostics: diagnosticsFromStream(metadata, usage) },
                });
                return;
              }
              if (event.event === 'analysis_chain_done') {
                analysisChain = event.analysis_chain;
                activeSessionId = event.session_id || activeSessionId;
                updateAssistant({ analysis_chain: analysisChain });
                return;
              }
              if (event.event === 'text_delta') {
                streamedContent += event.delta;
                updateAssistant({ content: streamedContent, status: 'streaming' });
                return;
              }
              if (event.event === 'error') {
                throw new Error(event.error);
              }
              if (event.event === 'done') {
                activeSessionId = event.session_id || activeSessionId;
                streamedContent = event.response ?? streamedContent;
              }
            },
          },
        );
        updateAssistant({
          content: streamedContent,
          status: 'done',
          evidence: evidenceFromStreamMetadata(metadata),
          ...(analysisChain ? { analysis_chain: analysisChain } : {}),
          metadata: { diagnostics: diagnosticsFromStream(metadata, usage) },
        });
      } catch (err) {
        if (isAbortError(err)) {
          setStore((prev) => {
            const current = prev[normalizedScope]?.messages ?? [];
            const existing = current.find((message) => message.id === assistantId) ?? assistantDraft;
            const stopped: ChatMessageData = {
              ...existing,
              content: existing.content || '已停止生成。',
              status: 'done',
            };
            return {
              ...prev,
              [normalizedScope]: conversationSnapshot(
                replaceOrAppendMessage(current, stopped),
                Date.now(),
                prev[normalizedScope]?.sessionId,
              ),
            };
          });
          return;
        }
        const detail = formatChatVisibleError(err);
        const errMsg: ChatMessageData = {
          id: assistantId,
          role: 'assistant',
          content: `回答失败：${detail}`,
          timestamp: new Date().toISOString(),
          status: 'error',
        };
        setStore((prev) => ({
          ...prev,
          [normalizedScope]: {
            ...conversationSnapshot(
              replaceOrAppendMessage(prev[normalizedScope]?.messages ?? [], errMsg),
              Date.now(),
              prev[normalizedScope]?.sessionId,
            ),
          },
        }));
      } finally {
        if (abortControllersRef.current.get(normalizedScope) === abortController) {
          abortControllersRef.current.delete(normalizedScope);
        }
        setPending((prev) => {
          const next = { ...prev };
          delete next[normalizedScope];
          return next;
        });
      }
    },
    [],
  );

  const stopMessage = useCallback((scope: string) => {
    const normalizedScope = normalizeScope(scope);
    abortControllersRef.current.get(normalizedScope)?.abort();
  }, []);

  const setConversation = useCallback((scope: string, messages: ChatMessageData[], options?: SetConversationOptions) => {
    const normalizedScope = normalizeScope(scope);
    setStore((prev) => ({
      ...prev,
      [normalizedScope]: conversationSnapshot(
        messages,
        options?.updatedAt ?? Date.now(),
        options && 'sessionId' in options ? options.sessionId : prev[normalizedScope]?.sessionId,
      ),
    }));
  }, []);

  const appendMessages = useCallback((scope: string, messages: ChatMessageData[]) => {
    const normalizedScope = normalizeScope(scope);
    if (messages.length === 0) return;
    setStore((prev) => {
      const merged = mergeMessages(prev[normalizedScope]?.messages ?? [], messages);
      return {
        ...prev,
        [normalizedScope]: conversationSnapshot(
          merged,
          Date.now(),
          prev[normalizedScope]?.sessionId,
        ),
      };
    });
  }, []);

  const clearConversation = useCallback((scope: string) => {
    const normalizedScope = normalizeScope(scope);
    setStore((prev) => {
      if (!(normalizedScope in prev)) return prev;
      const next = { ...prev };
      delete next[normalizedScope];
      return next;
    });
  }, []);

  const value = useMemo<SmartReadContextValue>(
    () => ({ getConversation, sendMessage, stopMessage, setConversation, appendMessages, clearConversation }),
    [getConversation, sendMessage, stopMessage, setConversation, appendMessages, clearConversation],
  );

  return (
    <SmartReadContext.Provider value={value}>
      {children}
    </SmartReadContext.Provider>
  );
}

export function useSmartRead(): SmartReadContextValue {
  const ctx = useContext(SmartReadContext);
  if (!ctx) {
    throw new Error('useSmartRead must be used within a SmartReadProvider');
  }
  return ctx;
}

export const SMART_READ_DEFAULT_SCOPE = '_default';
export { EMPTY_CONVERSATION };
export const __test = {
  migrateLegacyDialogMessages,
  scopeFromLegacyDialogKey,
  STORAGE_KEY,
  LEGACY_DIALOG_MIGRATION_KEY,
  messagesFromResumePayload,
};
