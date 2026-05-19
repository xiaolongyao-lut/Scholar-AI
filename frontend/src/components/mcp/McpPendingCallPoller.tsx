/**
 * McpPendingCallPoller — REST-polling driver for the MCP pending-call
 * protocol (MCP v0.4 Phase 4).
 *
 * Per `docs/plans/runbooks/mcp-v0.4-phase2-pending-call-transport-adr-2026-05-16.md`:
 * - Polls `GET /api/mcp/pending-calls` every 1000ms while mounted.
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

interface McpPendingCallPollerProps {
  /** Override the poll interval. Tests pass a smaller value. */
  pollIntervalMs?: number;
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
    // The poll response carries server_id (machine id). The modal also
    // shows it; a future enhancement could join against the server
    // catalog for a friendly label.
    server_label: p.server_id,
    tool_name: p.tool_name,
    capability: p.capability,
    args_preview: p.args_preview || undefined,
  };
}

export function McpPendingCallPoller({
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  pollOverride,
  decideOverride,
}: McpPendingCallPollerProps = {}) {
  const [pending, setPending] = React.useState<PendingMcpToolCall | null>(null);
  const [inFlight, setInFlight] = React.useState(false);

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
    let cancelled = false;

    const tick = async () => {
      try {
        const list = await poll();
        if (cancelled) return;
        // Render the first pending call; the rest queue up for next ticks.
        // Don't replace an existing pending render mid-decision.
        setPending((current) => current ?? list[0] ?? null);
      } catch (err) {
        // Network / 5xx — log and continue. Backend timeout is the safety net.

        console.warn('[McpPendingCallPoller] poll failed', err);
      }
    };

    void tick();
    const handle = window.setInterval(tick, pollIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [poll, pollIntervalMs]);

  const settle = React.useCallback(
    async (
      callId: string,
      decision: PendingCallDecision,
      rememberForRun: boolean,
    ) => {
      if (inFlight) return;
      setInFlight(true);
      try {
        await decide(callId, decision, rememberForRun);
      } catch (err) {
        // 404 means the backend already cleaned up (timeout or duplicate).
        // Either way the modal should close.

        console.warn('[McpPendingCallPoller] decide failed', err);
      } finally {
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
