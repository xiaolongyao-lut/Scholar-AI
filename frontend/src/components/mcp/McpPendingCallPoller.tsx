/**
 * McpPendingCallPoller — REST-polling driver for the MCP pending-call
 * protocol.
 *
 * Per `docs/plans/runbooks/mcp-v0.4-phase2-pending-call-transport-adr-2026-05-16.md`:
 * - Polls `GET /api/mcp/pending-calls` immediately, then backs off while
 *   idle or hidden, with at most one request in flight so browser connections
 *   stay available.
 * - When the response carries one or more PendingMcpToolCall entries,
 *   renders the McpToolApprovalModal for the FIRST pending call (modal-
 *   only confirmation per D-MCPUX-3; if multiple pile up the operator
 *   handles them one at a time).
 * - `destructive` capability is short-circuited by the backend before
 *   pending creation, so it should never reach this component. As a
 *   defense-in-depth measure the modal still disables Approve for
 *   destructive, but a destructive pending call here would indicate a
 *   backend bug (the audit log is the operator's source of truth).
 * - approve/reject calls `POST /api/mcp/pending-calls/{id}/decide`.
 * - On error (network, 404, server) the poller logs and continues; the
 *   backend timeout (PENDING_CALL_TIMEOUT_SECONDS) is the safety net.
 *
 * Mount once near the root of the app (e.g. alongside CommandPalette in
 * App.tsx). It is invisible until a pending call appears.
 *
 * Test hook: `pollOverride` lets vitest swap the poll function for a
 * deterministic mock without intercepting axios at the module level.
 */
import React from 'react';
import {
  decidePendingMcpCall,
  listPendingMcpCalls,
  type PendingCallDecision,
  type PendingMcpToolCall,
} from '@/services/mcpApi';
import {
  McpToolApprovalModal,
  type McpPendingToolCall,
} from './McpToolApprovalModal';

const DEFAULT_POLL_INTERVAL_MS = 1000;
const DEFAULT_IDLE_POLL_INTERVAL_MS = 10_000;
const DEFAULT_HIDDEN_POLL_INTERVAL_MS = 30_000;

type PollPendingMcpCalls = () => Promise<PendingMcpToolCall[]>;

let sharedPollPromise: Promise<PendingMcpToolCall[]> | null = null;

interface McpPendingCallPollerProps {
  /** Override the active poll interval. Tests pass a smaller value. */
  pollIntervalMs?: number;
  /** Override the no-pending-call backoff interval. */
  idlePollIntervalMs?: number;
  /** Override the background-tab backoff interval. */
  hiddenPollIntervalMs?: number;
  /** Test seam: replace the network poll with a deterministic mock. */
  pollOverride?: () => Promise<PendingMcpToolCall[]>;
  /** Test seam: replace the network decide with a deterministic mock. */
  decideOverride?: (
    callId: string,
    decision: PendingCallDecision,
    rememberForRun: boolean,
  ) => Promise<void>;
}

function pendingToModalShape(p: PendingMcpToolCall): McpPendingToolCall {
  return {
    call_id: p.id,
    server_id: p.server_id,
    server_label: '当前 MCP 服务',
    tool_name: p.tool_name,
    capability: p.capability,
    args_preview: p.args_preview || undefined,
  };
}

function normalizePollIntervalMs(value: number | undefined, fallback: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback;
  return Math.max(50, Math.floor(value));
}

function documentIsHidden(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readHttpStatus(error: unknown): number | null {
  if (!isRecord(error)) return null;
  const response = error.response;
  if (isRecord(response) && typeof response.status === 'number') {
    return response.status;
  }
  return typeof error.status === 'number' ? error.status : null;
}

function isDecideTerminalError(error: unknown): boolean {
  const status = readHttpStatus(error);
  return status === 404 || status === 410;
}

function runSharedPendingPoll(poll: PollPendingMcpCalls): Promise<PendingMcpToolCall[]> {
  if (sharedPollPromise) return sharedPollPromise;
  let currentPoll: Promise<PendingMcpToolCall[]>;
  currentPoll = poll().finally(() => {
    if (sharedPollPromise === currentPoll) {
      sharedPollPromise = null;
    }
  });
  sharedPollPromise = currentPoll;
  return currentPoll;
}

export function McpPendingCallPoller({
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  idlePollIntervalMs = DEFAULT_IDLE_POLL_INTERVAL_MS,
  hiddenPollIntervalMs = DEFAULT_HIDDEN_POLL_INTERVAL_MS,
  pollOverride,
  decideOverride,
}: McpPendingCallPollerProps = {}) {
  const [pending, setPending] = React.useState<PendingMcpToolCall | null>(null);
  const [inFlight, setInFlight] = React.useState(false);
  const pollInFlightRef = React.useRef(false);
  const pendingRef = React.useRef<PendingMcpToolCall | null>(null);
  // call_ids the operator already decided. Prevents an orphaned backend
  // pending entry (e.g. the runner coroutine was cancelled mid-decision so
  // `store.decide()` never ran) from re-popping the same modal every tick.
  // Bounded: once the backend reaps the entry the id simply stops appearing.
  const decidedIdsRef = React.useRef<Set<string>>(new Set());

  const poll = pollOverride ?? listPendingMcpCalls;
  const decide = decideOverride
    ? (id: string, dec: PendingCallDecision, remember: boolean) =>
        decideOverride(id, dec, remember)
    : (id: string, dec: PendingCallDecision, remember: boolean) =>
        decidePendingMcpCall(id, {
          decision: dec,
          remember_for_run: remember,
        });

  React.useEffect(() => {
    pendingRef.current = pending;
  }, [pending]);

  React.useEffect(() => {
    let cancelled = false;
    let timeoutId: number | null = null;
    const activeIntervalMs = normalizePollIntervalMs(pollIntervalMs, DEFAULT_POLL_INTERVAL_MS);
    const idleIntervalMs = normalizePollIntervalMs(idlePollIntervalMs, DEFAULT_IDLE_POLL_INTERVAL_MS);
    const backgroundIntervalMs = normalizePollIntervalMs(hiddenPollIntervalMs, DEFAULT_HIDDEN_POLL_INTERVAL_MS);

    const clearTimer = () => {
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
        timeoutId = null;
      }
    };

    const scheduleNext = (delayMs: number) => {
      if (cancelled) return;
      clearTimer();
      timeoutId = window.setTimeout(() => {
        void tick();
      }, delayMs);
    };

    const nextDelay = (foundPending: boolean): number => {
      if (documentIsHidden()) return backgroundIntervalMs;
      if (foundPending || pendingRef.current) return activeIntervalMs;
      return idleIntervalMs;
    };

    const tick = async () => {
      if (cancelled || pollInFlightRef.current) {
        return;
      }
      if (pendingRef.current) {
        scheduleNext(nextDelay(true));
        return;
      }
      // While hidden, don't burn a request the operator can't act on; just
      // reschedule on the background interval. visibilitychange fires an
      // immediate catch-up poll when the window regains focus.
      if (documentIsHidden()) {
        scheduleNext(backgroundIntervalMs);
        return;
      }

      pollInFlightRef.current = true;
      let foundPending = false;
      try {
        const list = await runSharedPendingPoll(poll);
        if (cancelled) return;
        // Drop call_ids the operator already decided this session. An orphaned
        // backend entry (runner cancelled before store.decide()) would otherwise
        // re-pop the modal on every tick until the backend reaps it.
        const fresh = list.filter((p) => !decidedIdsRef.current.has(p.id));
        foundPending = fresh.length > 0;
        // Render the first pending call; the rest queue up for next ticks.
        // Don't replace an existing pending render mid-decision.
        setPending((current) => current ?? fresh[0] ?? null);
      } catch {
        // Network / 5xx — log and continue. Backend timeout is the safety net.

        console.warn('[McpPendingCallPoller] poll failed; retrying without exposing backend detail');
      } finally {
        pollInFlightRef.current = false;
        scheduleNext(nextDelay(foundPending));
      }
    };

    const handleVisibilityChange = () => {
      if (cancelled) return;
      if (documentIsHidden() || pendingRef.current || pollInFlightRef.current) {
        scheduleNext(nextDelay(Boolean(pendingRef.current)));
        return;
      }
      void tick();
    };

    void tick();
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      cancelled = true;
      pollInFlightRef.current = false;
      clearTimer();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [hiddenPollIntervalMs, idlePollIntervalMs, poll, pollIntervalMs]);

  const settle = React.useCallback(
    async (
      callId: string,
      decision: PendingCallDecision,
      rememberForRun: boolean,
    ) => {
      if (inFlight) return;
      setInFlight(true);
      let suppressCallId = false;
      try {
        await decide(callId, decision, rememberForRun);
        suppressCallId = true;
      } catch (error: unknown) {
        // 404/410 means the backend already cleaned up (timeout or duplicate).
        // Transient network/5xx errors must stay retryable on the next poll.
        suppressCallId = isDecideTerminalError(error);

        console.warn('[McpPendingCallPoller] decide failed; closing pending prompt without exposing backend detail');
      } finally {
        // Record the decision so an orphaned backend entry can't re-pop the
        // same modal. Do not suppress transient decide failures; those need a
        // visible retry if the backend still has a real pending call.
        if (suppressCallId) {
          decidedIdsRef.current.add(callId);
        }
        setPending(null);
        setInFlight(false);
      }
    },
    [decide, inFlight],
  );

  return (
    <McpToolApprovalModal
      pending={pending ? pendingToModalShape(pending) : null}
      onApprove={(callId, { rememberForRun }) =>
        void settle(callId, 'approve', rememberForRun)
      }
      onCancel={(callId) => void settle(callId, 'reject', false)}
    />
  );
}
