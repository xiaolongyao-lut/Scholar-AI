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
  discussionApi,
  DiscussionStreamError,
  type DiscussionAgentTrace,
  type DiscussionRunConfig,
  type DiscussionRunResult,
  type DiscussionStreamEvent,
} from '@/services/discussionApi';

/**
 * Cross-route persistent state for the multi-agent discussion run lifecycle.
 *
 * Lifts ``running``/``result``/``error``/``traces`` state out of the
 * DiscussionPanel component so that switching routes (e.g. /discussion ↔
 * /knowledge ↔ /workbench/research) no longer unmounts the active session.
 *
 * Setup-form state (query, agent slot config, sampling params, etc.) stays
 * inside DiscussionPanel — those are pre-run configuration and intentionally
 * ephemeral. The Context only owns the run-time slice.
 *
 * SSE transport is the wrapper ``discussionApi.runDiscussionStream``.
 * Feature flag ``discussion_streaming`` must be enabled server-side; when
 * the wrapper sees a 404 the Context degrades to the non-streaming
 * ``discussionApi.runDiscussion`` path so consumers always get a result
 * (just without progressive turn events).
 */

export type DiscussionSessionState =
  | 'idle'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'error';

export interface DiscussionSession {
  state: DiscussionSessionState;
  startedAt: number | null;
  endedAt: number | null;
  config: DiscussionRunConfig | null;
  /** Per-agent traces accumulated as agent_done events arrive. */
  liveTraces: DiscussionAgentTrace[];
  /** Highest turn_index reported so far (0-based). */
  currentTurnIndex: number;
  /** Set once synthesis_done arrives (or null on failure). */
  synthesis: DiscussionRunResult['synthesis'] | null;
  /** Set once the terminal ``done`` event arrives. */
  finalResult: DiscussionRunResult | null;
  /** Set on stream error or run failure. */
  error: string | null;
}

const IDLE_SESSION: DiscussionSession = {
  state: 'idle',
  startedAt: null,
  endedAt: null,
  config: null,
  liveTraces: [],
  currentTurnIndex: 0,
  synthesis: null,
  finalResult: null,
  error: null,
};

const SESSION_STORAGE_KEY = 'discussion-context-session-v1';

function loadPersistedSession(): DiscussionSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DiscussionSession>;
    // Only restore terminal states so a half-completed in-flight run never
    // resurrects as a phantom "running" session after a page refresh.
    if (parsed && (parsed.state === 'completed' || parsed.state === 'cancelled' || parsed.state === 'error')) {
      return { ...IDLE_SESSION, ...parsed } as DiscussionSession;
    }
    return null;
  } catch {
    return null;
  }
}

function persistSessionIfTerminal(session: DiscussionSession): void {
  if (typeof window === 'undefined') return;
  if (session.state === 'idle' || session.state === 'running') return;
  try {
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  } catch {
    /* quota / disabled storage — drop silently */
  }
}

interface DiscussionContextValue {
  session: DiscussionSession;
  startSession(config: DiscussionRunConfig): Promise<void>;
  cancelSession(): void;
  resetSession(): void;
}

const DiscussionContext = createContext<DiscussionContextValue | null>(null);

export function DiscussionProvider({ children }: { children: ReactNode }) {
  // Restore the last terminal session from localStorage on mount so a page
  // refresh / new tab does not erase a completed discussion's transcript.
  // Running sessions are NOT restored (state machine cannot reconnect to
  // the in-flight backend run after a reload).
  const [session, setSession] = useState<DiscussionSession>(
    () => loadPersistedSession() ?? IDLE_SESSION,
  );
  const abortRef = useRef<AbortController | null>(null);

  // Persist completed / cancelled / error sessions so the next mount can
  // restore them. The full payload includes liveTraces + synthesis +
  // finalResult so the DiscussionPanel transcript rehydrates verbatim.
  useEffect(() => {
    persistSessionIfTerminal(session);
  }, [session]);

  const applyEvent = useCallback((event: DiscussionStreamEvent) => {
    setSession((prev) => {
      switch (event.event) {
        case 'agent_done':
          return {
            ...prev,
            currentTurnIndex: Math.max(prev.currentTurnIndex, event.turn_index),
            liveTraces: [...prev.liveTraces, event.trace],
          };
        case 'turn_done':
          return {
            ...prev,
            currentTurnIndex: Math.max(prev.currentTurnIndex, event.turn_index),
          };
        case 'synthesis_done':
          return { ...prev, synthesis: event.synthesis };
        case 'done':
          return {
            ...prev,
            state: 'completed',
            endedAt: Date.now(),
            finalResult: event.result,
            // Final result is authoritative — replace any partial traces with
            // the full ordered set from the server.
            liveTraces: event.result.turns.flatMap((t) => t.agent_traces),
            synthesis: event.result.synthesis,
          };
        case 'error':
          return {
            ...prev,
            state: 'error',
            endedAt: Date.now(),
            error: event.error,
          };
        default:
          return prev;
      }
    });
  }, []);

  const startSession = useCallback(
    async (config: DiscussionRunConfig) => {
      // Don't double-start; consumers should resetSession() first when
      // re-running from a terminal state.
      if (session.state === 'running') {
        return;
      }
      const controller = new AbortController();
      abortRef.current = controller;
      setSession({
        ...IDLE_SESSION,
        state: 'running',
        startedAt: Date.now(),
        config,
      });

      try {
        await discussionApi.runDiscussionStream(config, {
          onEvent: applyEvent,
          signal: controller.signal,
        });
      } catch (err) {
        // 404 (flag off) / 405 (endpoint missing in old build) / 501 / any
        // non-success that's not a user-initiated abort ⇒ degrade to the
        // non-streaming endpoint so users on older backends still see a
        // result. Caller-initiated abort is honored as cancellation.
        const isStreamUnavailable =
          err instanceof DiscussionStreamError &&
          (err.status === 404 || err.status === 405 || err.status >= 500);
        if (isStreamUnavailable && !controller.signal.aborted) {
          try {
            const result = await discussionApi.runDiscussion(config, {
              signal: controller.signal,
            });
            applyEvent({ event: 'done', result });
          } catch (fallbackErr) {
            if (!controller.signal.aborted) {
              applyEvent({
                event: 'error',
                status: 500,
                error: fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr),
              });
            }
          }
          return;
        }
        if (controller.signal.aborted) {
          setSession((prev) => ({
            ...prev,
            state: 'cancelled',
            endedAt: Date.now(),
          }));
          return;
        }
        applyEvent({
          event: 'error',
          status: err instanceof DiscussionStreamError ? err.status : 500,
          error: err instanceof Error ? err.message : String(err),
        });
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    [applyEvent, session.state],
  );

  const cancelSession = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    // Don't wait for the async catch/fallback paths to setSession; flip
    // state synchronously so the UI's "停止等待 · {N}s" pill clears the
    // instant the user clicks Stop. The backend orchestrator may still run
    // to completion (we cannot remote-cancel), but the user-facing
    // discussion is now considered cancelled.
    setSession((prev) =>
      prev.state === 'running'
        ? { ...prev, state: 'cancelled', endedAt: Date.now() }
        : prev,
    );
  }, []);

  const resetSession = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    setSession(IDLE_SESSION);
  }, []);

  const value = useMemo<DiscussionContextValue>(
    () => ({ session, startSession, cancelSession, resetSession }),
    [session, startSession, cancelSession, resetSession],
  );

  return (
    <DiscussionContext.Provider value={value}>
      {children}
    </DiscussionContext.Provider>
  );
}

export function useDiscussion(): DiscussionContextValue {
  const ctx = useContext(DiscussionContext);
  if (!ctx) {
    throw new Error('useDiscussion must be used within a DiscussionProvider');
  }
  return ctx;
}
