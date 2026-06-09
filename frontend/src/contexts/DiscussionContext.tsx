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
import { formatChatVisibleError } from '@/components/chat/chatDisplay';
import { artifactContentRecord, findLatestArtifact, runBackgroundJob } from '@/services/backgroundJobRunner';
import { getWritingRuntimeClient } from '@/services/runtimeClient';
import type { WritingJob } from '@/types/runtime';
import {
  discussionApi,
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
  /** B7 (0.1.8.2): current stage label from backend ``started`` /
   *  ``stage_progress`` events (e.g. "retrieval" / "agents_prep").
   *  Null when not yet running or stage unknown. */
  currentStage: string | null;
  /** B1/B7: server-generated run id, populated by ``started`` event. */
  runId: string | null;
  /** Runtime task-center job id for long-running discussion execution. */
  runtimeJobId: string | null;
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
  currentStage: null,
  runId: null,
  runtimeJobId: null,
};

const SESSION_STORAGE_KEY = 'discussion-context-session-v1';
const RUN_ID_STORAGE_KEY = 'discussion-context-run-id-v1';
const DISCUSSION_VISIBLE_ERROR_FALLBACK = '讨论运行失败，请检查角色接口和证据配置。';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readDiscussionErrorText(error: unknown): string {
  if (error instanceof Error) return error.message;
  return typeof error === 'string' ? error : String(error ?? '');
}

export function formatDiscussionSessionError(error: unknown): string {
  const raw = readDiscussionErrorText(error);
  if (raw.includes('convergence_judge_agent_id')) {
    return '裁判角色必须来自当前角色列表。';
  }
  if (raw.includes('project_id is required')) {
    return '当前证据来源需要先选择项目。';
  }
  if (raw.includes('evidence_chunk_ids')) {
    return '手动证据需要填写至少一个证据编号。';
  }
  return formatChatVisibleError(raw, { fallback: DISCUSSION_VISIBLE_ERROR_FALLBACK });
}

function loadPersistedRunId(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(RUN_ID_STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistRunId(runId: string | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (runId) {
      window.localStorage.setItem(RUN_ID_STORAGE_KEY, runId);
    } else {
      window.localStorage.removeItem(RUN_ID_STORAGE_KEY);
    }
  } catch {
    /* quota / disabled storage — drop silently */
  }
}

function loadPersistedSession(): DiscussionSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DiscussionSession>;
    // Only restore terminal states so a half-completed in-flight run never
    // resurrects as a phantom "running" session after a page refresh.
    if (parsed && (parsed.state === 'completed' || parsed.state === 'cancelled' || parsed.state === 'error')) {
      const restored = { ...IDLE_SESSION, ...parsed } as DiscussionSession;
      return restored.error
        ? { ...restored, error: formatDiscussionSessionError(restored.error) }
        : restored;
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
  const activeRuntimeJobIdRef = useRef<string | null>(null);

  // Persist completed / cancelled / error sessions so the next mount can
  // restore them. The full payload includes liveTraces + synthesis +
  // finalResult so the DiscussionPanel transcript rehydrates verbatim.
  useEffect(() => {
    persistSessionIfTerminal(session);
  }, [session]);

  const applyEvent = useCallback((event: DiscussionStreamEvent) => {
    // Keep the dev trace as a control-flow marker only. Full event payloads
    // may contain user prompts, evidence, or model output.
    if (typeof console !== 'undefined') {
      console.info('[DiscussionContext] event', event.event);
    }
    setSession((prev) => {
      switch (event.event) {
        case 'started':
          // B1 (0.1.8.2): server-side run_id arrives in the first SSE event.
          // Persist it so a page reload / new tab can reconnect via the
          // /runs/{run_id}/stream/resume endpoint.
          persistRunId(event.run_id);
          return {
            ...prev,
            runId: event.run_id,
            currentStage: event.stage,
          };
        case 'stage_progress':
          return {
            ...prev,
            currentStage: event.stage,
          };
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
          activeRuntimeJobIdRef.current = null;
          return {
            ...prev,
            state: 'completed',
            endedAt: Date.now(),
            finalResult: event.result,
            runtimeJobId: null,
            // Final result is authoritative — replace any partial traces with
            // the full ordered set from the server.
            liveTraces: event.result.turns.flatMap((t) => t.agent_traces),
            synthesis: event.result.synthesis,
          };
        case 'error':
          activeRuntimeJobIdRef.current = null;
          return {
            ...prev,
            state: 'error',
            endedAt: Date.now(),
            error: formatDiscussionSessionError(event.error),
            runtimeJobId: null,
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
      // Control-flow marker only; avoid logging the user's prompt.
      if (typeof console !== 'undefined') {
        console.info(
          '[DiscussionContext] startSession invoked; agents=%d',
          config.agent_configs?.length ?? 0,
        );
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
        const result = await runBackgroundJob({
          sessionTitle: '多智能体讨论',
          sessionMetadata: {
            source: 'discussion_panel',
            project_id: config.project_id ?? undefined,
          },
          request: {
            kind: 'discussion',
            input_text: config.query,
            metadata: {
              config,
              title: config.query,
              source: 'discussion_panel',
            },
            tags: ['discussion', 'multi-agent'],
          },
          timeoutMs: Math.max(120_000, (config.timeout_seconds ?? 120) * 1000 + 30_000),
          signal: controller.signal,
          onJobCreated: (job: WritingJob) => {
            activeRuntimeJobIdRef.current = job.job_id;
            setSession((prev) => ({
              ...prev,
              runtimeJobId: job.job_id,
            }));
          },
        });
        if (result.status.status !== 'completed') {
          throw new Error(result.status.error || '讨论任务未完成。');
        }
        const content = artifactContentRecord(findLatestArtifact(result.artifacts, 'transformed_text'));
        const resultPayload = content.result;
        if (isRecord(resultPayload)) {
          const synthesized = resultPayload as unknown as DiscussionRunResult;
          applyEvent({
            event: 'done',
            result: synthesized,
          });
        } else {
          applyEvent({
            event: 'error',
            status: 500,
            error: '讨论任务未返回可用结果。',
          });
        }
      } catch (err) {
        if (controller.signal.aborted) {
          activeRuntimeJobIdRef.current = null;
          setSession((prev) => ({
            ...prev,
            state: 'cancelled',
            endedAt: Date.now(),
            runtimeJobId: null,
          }));
          return;
        }
        applyEvent({
          event: 'error',
          status: 500,
          error: formatDiscussionSessionError(err),
        });
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
        activeRuntimeJobIdRef.current = null;
      }
    },
    [applyEvent, session.state],
  );

  const cancelSession = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    if (activeRuntimeJobIdRef.current) {
      void getWritingRuntimeClient().cancelJob(activeRuntimeJobIdRef.current).catch(() => undefined);
      activeRuntimeJobIdRef.current = null;
    }
    // B1: stop tracking this run so a future mount doesn't try to reconnect
    // to a cancelled session.
    persistRunId(null);
    // Don't wait for the async catch/fallback paths to setSession; flip
    // state synchronously so the UI's "停止等待 · {N}s" pill clears the
    // instant the user clicks Stop. The backend orchestrator may still run
    // to completion (we cannot remote-cancel), but the user-facing
    // discussion is now considered cancelled.
    setSession((prev) =>
      prev.state === 'running'
        ? { ...prev, state: 'cancelled', endedAt: Date.now(), runId: null, runtimeJobId: null }
        : prev,
    );
  }, []);

  const resetSession = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    persistRunId(null);
    activeRuntimeJobIdRef.current = null;
    setSession(IDLE_SESSION);
  }, []);

  // B1 (0.1.8.2): on mount, attempt to reconnect to a previously-tracked run.
  // - Terminal state → restore final transcript and clear run_id
  // - Running state → start SSE resume stream and let applyEvent rehydrate
  // - 404 (server restarted / TTL expired / unknown) → silently drop the
  //   stored run_id; user starts fresh
  // Only runs once on mount; runs while the page is alive don't need resume
  // because the Context state is in-memory.
  useEffect(() => {
    let cancelled = false;
    const storedRunId = loadPersistedRunId();
    if (!storedRunId) return;

    (async () => {
      try {
        const snapshot = await discussionApi.getDiscussionRun(storedRunId);
        if (cancelled) return;
        if (!snapshot) {
          persistRunId(null);
          return;
        }
        if (snapshot.state === 'running' || snapshot.state === 'pending') {
          // Live reconnect: hydrate Context with whatever was already in the
          // store, then tail new events via the resume SSE.
          setSession((prev) => ({
            ...prev,
            state: 'running',
            startedAt: snapshot.created_at * 1000,
            runId: snapshot.run_id,
            currentStage: snapshot.current_stage,
            currentTurnIndex: snapshot.current_turn_index,
            liveTraces: snapshot.live_traces,
            synthesis: snapshot.synthesis,
          }));
          const controller = new AbortController();
          abortRef.current = controller;
          try {
            await discussionApi.resumeDiscussionStream(snapshot.run_id, {
              onEvent: applyEvent,
              signal: controller.signal,
            });
          } catch (err: unknown) {
            if (!cancelled && !controller.signal.aborted) {
              applyEvent({
                event: 'error',
                status: 500,
                error: formatDiscussionSessionError(err),
              });
            }
          } finally {
            if (abortRef.current === controller) abortRef.current = null;
          }
          return;
        }
        // Terminal state (completed / cancelled / error) — restore once then
        // drop the run_id so future mounts don't re-fetch the same run.
        // Normalize backend 'pending' (shouldn't reach here due to above
        // branch, but guard anyway) to 'completed' for type safety.
        const terminalState: DiscussionSessionState =
          snapshot.state === 'completed' ||
          snapshot.state === 'cancelled' ||
          snapshot.state === 'error'
            ? snapshot.state
            : 'error';
        setSession((prev) => ({
          ...prev,
          state: terminalState,
          startedAt: snapshot.created_at * 1000,
          endedAt: snapshot.updated_at * 1000,
          runId: snapshot.run_id,
          currentStage: snapshot.current_stage,
          currentTurnIndex: snapshot.current_turn_index,
          liveTraces: snapshot.live_traces,
          synthesis: snapshot.synthesis,
          finalResult: snapshot.final_result,
          error: snapshot.error ? formatDiscussionSessionError(snapshot.error) : null,
        }));
        persistRunId(null);
      } catch {
        // Network error / endpoint missing on older backend → silently
        // ignore; user sees a fresh idle state.
        persistRunId(null);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []); // mount-only

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
