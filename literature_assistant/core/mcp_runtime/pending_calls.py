"""MCP pending-call protocol.

Provides the backend signal that the modal-only UX skeleton (shipped
2026-05-16 in `frontend/src/components/mcp/McpToolApprovalModal.tsx`)
needs to drive: when the dispatcher classifies a tool call as ``ask``,
the runner registers a ``PendingMcpToolCall`` here and the frontend
polls / decides via the REST endpoints in ``routers/mcp_router``.

This module owns three concerns:

1. **Capability → action classification** (``classify_action``). Pure
   function over ``McpToolCapability``. Mapping:
       read         -> allow
       write        -> ask
       network      -> ask
       filesystem   -> ask
       unknown      -> ask          (locked by user 2026-05-16)
       destructive  -> block

2. **In-memory pending-call store** (``PendingCallStore``). Per-process
   dict keyed by ``pending_call_id`` (uuid hex). No persistence — pending
   calls die with the process; cross-session "remember" is forbidden
   (D-MCPUX-4).

3. **Module-level singleton** (``get_pending_call_store`` /
   ``set_pending_call_store``) so FastAPI handlers and the runner share
   one store instance per process. Test hook for injection.

Transport: REST polling. See
``docs/plans/runbooks/mcp-v0.4-phase2-pending-call-transport-adr-2026-05-16.md``
for the upgrade path.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

from models.mcp import McpToolCapability, PendingMcpToolCall


PENDING_CALL_TIMEOUT_SECONDS_DEFAULT = 60.0


Action = Literal["allow", "ask", "block"]


# ---------------------------------------------------------------------------
# §1 classification
# ---------------------------------------------------------------------------


_ACTION_MAP: dict[McpToolCapability, Action] = {
    McpToolCapability.READ: "allow",
    McpToolCapability.WRITE: "ask",
    McpToolCapability.NETWORK: "ask",
    McpToolCapability.FILESYSTEM: "ask",
    McpToolCapability.UNKNOWN: "ask",
    McpToolCapability.DESTRUCTIVE: "block",
}


def classify_action(capability: McpToolCapability) -> Action:
    """Map an MCP tool capability tag to the protocol action.

    Capability mapping:
      read -> allow (silent + audit)
      write/network/filesystem/unknown -> ask (modal)
      destructive -> block (toast / inline error)
    """
    return _ACTION_MAP[capability]


# ---------------------------------------------------------------------------
# §2 in-memory pending-call store
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PendingCallStore:
    """Per-process pending-call registry. Thread-safe via a single lock.

    Lifecycle:
      - ``create`` registers a new pending call and returns its id.
      - ``list_all`` returns every still-pending call (for the GET poll).
      - ``decide`` records an operator decision and removes the entry.
        Returns the recorded decision dict; raises KeyError if id unknown.
      - ``expire_older_than`` removes entries older than ``ttl_seconds``
        and returns the removed ids (timeout path).

    Per the ADR, no session_id partitioning yet — single local process,
    single operator. ``list_all`` is the poll target.
    """

    def __init__(self) -> None:
        self._calls: dict[str, PendingMcpToolCall] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        server_id: str,
        tool_name: str,
        capability: McpToolCapability,
        args_preview: str = "",
    ) -> PendingMcpToolCall:
        call_id = uuid.uuid4().hex
        pending = PendingMcpToolCall(
            id=call_id,
            server_id=server_id,
            tool_name=tool_name,
            capability=capability,
            args_preview=args_preview,
            created_at=_utc_now(),
        )
        with self._lock:
            self._calls[call_id] = pending
        return pending

    def list_all(self) -> list[PendingMcpToolCall]:
        with self._lock:
            return list(self._calls.values())

    def get(self, call_id: str) -> PendingMcpToolCall | None:
        with self._lock:
            return self._calls.get(call_id)

    def decide(
        self,
        call_id: str,
        *,
        decision: Literal["approve", "reject"],
        remember_for_run: bool = False,
        decision_user: str = "operator",
    ) -> dict:
        """Record an operator decision and remove the entry. Returns the
        decision dict for audit consumption; raises KeyError if unknown.
        """
        with self._lock:
            pending = self._calls.pop(call_id, None)
        if pending is None:
            raise KeyError(f"unknown_pending_call: {call_id}")
        return {
            "call_id": call_id,
            "server_id": pending.server_id,
            "tool_name": pending.tool_name,
            "capability": pending.capability.value,
            "decision": decision,
            "remember_for_run": remember_for_run,
            "decision_user": decision_user,
            "decided_at": _utc_now(),
        }

    def expire_older_than(self, ttl_seconds: float) -> list[str]:
        """Remove pending calls older than ``ttl_seconds``. Returns the
        ids removed so callers can write timeout audit records.

        Uses ``created_at`` (ISO-8601 UTC) parsed against now.
        """
        cutoff_epoch = time.time() - ttl_seconds
        removed: list[str] = []
        with self._lock:
            for call_id, pending in list(self._calls.items()):
                try:
                    created_epoch = datetime.fromisoformat(
                        pending.created_at
                    ).timestamp()
                except ValueError:
                    continue
                if created_epoch <= cutoff_epoch:
                    self._calls.pop(call_id, None)
                    removed.append(call_id)
        return removed

    def clear(self) -> None:
        """Test helper."""
        with self._lock:
            self._calls.clear()


# ---------------------------------------------------------------------------
# §3 singleton hooks
# ---------------------------------------------------------------------------


_singleton: PendingCallStore | None = None
_singleton_lock = threading.Lock()


def get_pending_call_store() -> PendingCallStore:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = PendingCallStore()
        return _singleton


def set_pending_call_store(store: PendingCallStore | None) -> None:
    """Test hook: inject a custom store or reset to default."""
    global _singleton
    with _singleton_lock:
        _singleton = store


__all__ = [
    "Action",
    "PENDING_CALL_TIMEOUT_SECONDS_DEFAULT",
    "PendingCallStore",
    "classify_action",
    "get_pending_call_store",
    "set_pending_call_store",
]
