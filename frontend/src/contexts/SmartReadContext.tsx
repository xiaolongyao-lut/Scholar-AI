import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import axios from 'axios';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import type { ChatMessageData } from '@/components/chat/Message';
import type { EvidenceRefLike } from '@/components/evidence/EvidencePill';

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
 *   { [scope: string]: { messages: ChatMessageData[]; updatedAt: number } }
 *
 * The ``pending`` flag is NOT persisted — if the user refreshed mid-flight
 * the Promise is dropped (the in-process axios reference is gone) so we
 * intentionally show the half-finished conversation without a spinner
 * rather than a phantom "thinking" pill. Backend task persistence is the
 * follow-up that closes this remaining gap.
 */

const STORAGE_KEY = 'smart-read-conversations-v1';

interface PersistedConversation {
  messages: ChatMessageData[];
  updatedAt: number;
}

interface RuntimeConversation extends PersistedConversation {
  pending: boolean;
}

interface SendOptions {
  projectId?: string | null;
  materialId?: string | null;
}

interface SmartReadContextValue {
  getConversation(scope: string): RuntimeConversation;
  sendMessage(scope: string, text: string, opts: SendOptions): Promise<void>;
  clearConversation(scope: string): void;
}

const SmartReadContext = createContext<SmartReadContextValue | null>(null);

const EMPTY_CONVERSATION: RuntimeConversation = {
  messages: [],
  updatedAt: 0,
  pending: false,
};

function loadPersisted(): Record<string, PersistedConversation> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return {};
    return parsed as Record<string, PersistedConversation>;
  } catch {
    return {};
  }
}

function persistSnapshot(store: Record<string, PersistedConversation>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    /* quota / disabled storage — drop silently */
  }
}

export function SmartReadProvider({ children }: { children: ReactNode }) {
  // store + pending kept as separate maps so an in-flight chat doesn't
  // serialize a transient pending=true into localStorage.
  const [store, setStore] = useState<Record<string, PersistedConversation>>(
    () => loadPersisted(),
  );
  const [pending, setPending] = useState<Record<string, boolean>>({});

  useEffect(() => {
    persistSnapshot(store);
  }, [store]);

  const getConversation = useCallback(
    (scope: string): RuntimeConversation => {
      const entry = store[scope] ?? { messages: [], updatedAt: 0 };
      return {
        messages: entry.messages,
        updatedAt: entry.updatedAt,
        pending: Boolean(pending[scope]),
      };
    },
    [store, pending],
  );

  const sendMessage = useCallback(
    async (scope: string, text: string, opts: SendOptions): Promise<void> => {
      const userMsg: ChatMessageData = {
        id: `u-${Date.now()}`,
        role: 'user',
        content: text,
        timestamp: new Date().toISOString(),
      };
      // Optimistically append the user message + flip pending.
      setStore((prev) => ({
        ...prev,
        [scope]: {
          messages: [...(prev[scope]?.messages ?? []), userMsg],
          updatedAt: Date.now(),
        },
      }));
      setPending((prev) => ({ ...prev, [scope]: true }));

      try {
        // B7+ (0.1.8.2 hotfix): when no material is anchored AND the query
        // looks like a casual greeting / short ack (no question mark, no
        // technical terms, ≤ 12 chars), skip RAG retrieval and use direct
        // mode so users asking "hi" don't trigger expensive TOLF/embedding
        // pipelines that take 60+ seconds for a 2-char input.
        const trimmed = text.trim();
        const looksCasual =
          !opts.materialId &&
          trimmed.length <= 12 &&
          !/[?？]/.test(trimmed) &&
          !/[a-zA-Z]{6,}|[一-鿿]{6,}/.test(trimmed);
        const effectiveMode = looksCasual ? 'direct' : 'literature_qa';
        const { data } = await axios.post<{
          response?: string;
          evidence_refs?: EvidenceRefLike[];
          analysis_chain?: import('@/services/discussionApi').AnalysisChainPayload | null;
        }>(
          `${getApiBaseUrl()}/api/chat`,
          {
            query: text,
            project_id: opts.projectId || undefined,
            material_id: opts.materialId || undefined,
            mode: effectiveMode,
            tier: 'thorough',
          },
          { timeout: 180000 },
        );
        const assistantMsg: ChatMessageData = {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: data.response ?? '',
          timestamp: new Date().toISOString(),
          evidence: data.evidence_refs,
          // B6 (0.1.8.2): forward the structured reasoning chain so
          // MessageBubble can render the AnalysisChainPanel below the body.
          // Null/undefined when analysis_chain_rag flag is off → no panel.
          analysis_chain: data.analysis_chain ?? null,
        };
        setStore((prev) => ({
          ...prev,
          [scope]: {
            messages: [...(prev[scope]?.messages ?? []), assistantMsg],
            updatedAt: Date.now(),
          },
        }));
      } catch (err) {
        // B7+ (0.1.8.2 hotfix): the prior catch only surfaced
        // err.message ("Request failed with status code 502") when the
        // backend already classified the error and returned a Chinese
        // detail body. Harden: always inspect axios.response shape and
        // peel out detail / nested string / status info so the user sees
        // the real reason ("Invalid URL / 上游 LLM 服务异常 (502)" etc).
        let detail = err instanceof Error ? err.message : String(err);
        if (axios.isAxiosError(err) && err.response) {
          const data = err.response.data;
          const status = err.response.status;
          const statusText = err.response.statusText || '';
          // Common FastAPI shape: { detail: "..." } or { detail: {...} }
          if (data && typeof data === 'object') {
            const rawDetail = (data as { detail?: unknown }).detail;
            if (typeof rawDetail === 'string' && rawDetail.trim()) {
              detail = rawDetail;
            } else if (rawDetail && typeof rawDetail === 'object') {
              try {
                detail = JSON.stringify(rawDetail);
              } catch {
                detail = `${status} ${statusText}`.trim();
              }
            } else {
              // No detail field at all — surface status + first 200 chars of body.
              try {
                const body = JSON.stringify(data).slice(0, 200);
                detail = `${status} ${statusText}: ${body}`.trim();
              } catch {
                detail = `${status} ${statusText}`.trim();
              }
            }
          } else if (typeof data === 'string' && data.trim()) {
            detail = `${status} ${statusText}: ${data.slice(0, 200)}`.trim();
          } else {
            detail = `${status} ${statusText}`.trim() || detail;
          }
        }
        const errMsg: ChatMessageData = {
          id: `e-${Date.now()}`,
          role: 'assistant',
          content: `回答失败：${detail}`,
          timestamp: new Date().toISOString(),
        };
        setStore((prev) => ({
          ...prev,
          [scope]: {
            messages: [...(prev[scope]?.messages ?? []), errMsg],
            updatedAt: Date.now(),
          },
        }));
      } finally {
        setPending((prev) => {
          const next = { ...prev };
          delete next[scope];
          return next;
        });
      }
    },
    [],
  );

  const clearConversation = useCallback((scope: string) => {
    setStore((prev) => {
      if (!(scope in prev)) return prev;
      const next = { ...prev };
      delete next[scope];
      return next;
    });
  }, []);

  const value = useMemo<SmartReadContextValue>(
    () => ({ getConversation, sendMessage, clearConversation }),
    [getConversation, sendMessage, clearConversation],
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
