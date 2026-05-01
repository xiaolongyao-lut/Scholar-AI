# -*- coding: utf-8 -*-
"""Approval policies and decision models for capability execution."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

from datetime_utils import utc_now_iso_z


class ApprovalPolicy(str, Enum):
    """Approval requirement classification."""
    AUTO_ALLOWED = "auto_allowed"           # Auto-execute without approval
    REQUIRES_USER_APPROVAL = "requires_user_approval"  # Need user consent
    BLOCKED = "blocked"                     # Blocked - cannot execute
    GUIDANCE_ONLY = "guidance_only"         # No execution - reference only


class ApprovalDecision(str, Enum):
    """User decision on an approval request."""
    APPROVED = "approved"
    DENIED = "denied"
    DEFERRED = "deferred"  # User postponed decision


@dataclass(frozen=True)
class ApprovalRequest:
    """Request for user approval of a capability execution."""
    request_id: str
    capability_id: str
    capability_name: str
    reason: str
    timestamp: str = field(default_factory=utc_now_iso_z)
    context: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)


@dataclass(frozen=True)
class ApprovalDecisionRecord:
    """Record of a user decision on an approval request."""
    request_id: str
    decision: str  # ApprovalDecision value
    user_id: str | None = None
    timestamp: str = field(default_factory=utc_now_iso_z)
    reason: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)
    
    def is_approved(self) -> bool:
        """Check if decision was approval."""
        return self.decision == ApprovalDecision.APPROVED.value
    
    def is_denied(self) -> bool:
        """Check if decision was denial."""
        return self.decision == ApprovalDecision.DENIED.value


@dataclass(frozen=True)
class CapabilityApprovalProfile:
    """Approval profile for a capability."""
    capability_id: str
    policy: str  # ApprovalPolicy value
    description: str
    risk_level: str  # 'low', 'medium', 'high'
    approver_group: str | None = None  # e.g., 'admin', 'user'
    auto_expires_minutes: int | None = None  # Auto-approval duration
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)
    
    def requires_approval(self) -> bool:
        """Check if this capability requires user approval."""
        return self.policy == ApprovalPolicy.REQUIRES_USER_APPROVAL.value
    
    def is_blocked(self) -> bool:
        """Check if this capability is blocked."""
        return self.policy == ApprovalPolicy.BLOCKED.value
    
    def is_auto_allowed(self) -> bool:
        """Check if this capability auto-executes."""
        return self.policy == ApprovalPolicy.AUTO_ALLOWED.value
    
    def is_guidance_only(self) -> bool:
        """Check if this capability is guidance-only."""
        return self.policy == ApprovalPolicy.GUIDANCE_ONLY.value


class ApprovalStore:
    """Store approval requests, decisions, and profiles with optional SQLite persistence."""
    
    def __init__(self, sqlite_path: str | Path | None = None):
        """Initialize the store.

        Args:
            sqlite_path: Optional SQLite path. When provided, approval requests and
                decisions are persisted across service restarts.
        """
        self._requests: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, list[ApprovalDecisionRecord]] = {}
        self._profiles: dict[str, CapabilityApprovalProfile] = {}
        self._sqlite_path = Path(sqlite_path).expanduser().resolve() if sqlite_path else None
        if self._sqlite_path is not None:
            self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_sqlite()
            self._load_sqlite_state()
    
    def register_profile(self, profile: CapabilityApprovalProfile) -> None:
        """Register an approval profile for a capability."""
        self._profiles[profile.capability_id] = profile
    
    def get_profile(self, capability_id: str) -> CapabilityApprovalProfile | None:
        """Get approval profile for a capability."""
        return self._profiles.get(capability_id)
    
    def list_profiles(self) -> list[CapabilityApprovalProfile]:
        """List all approval profiles."""
        return list(self._profiles.values())
    
    def submit_approval_request(self, request: ApprovalRequest) -> None:
        """Submit an approval request."""
        if not request.request_id:
            raise ValueError("request_id must not be empty")
        if not request.capability_id:
            raise ValueError("capability_id must not be empty")
        self._requests[request.request_id] = request
        if request.request_id not in self._decisions:
            self._decisions[request.request_id] = []
        self._persist_request(request)
    
    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Get an approval request by ID."""
        return self._requests.get(request_id)

    def list_requests(self) -> list[ApprovalRequest]:
        """List all approval requests in insertion order."""
        return list(self._requests.values())
    
    def record_decision(self, decision: ApprovalDecisionRecord) -> None:
        """Record a user decision on an approval request."""
        if not decision.request_id:
            raise ValueError("request_id must not be empty")
        if decision.decision not in {item.value for item in ApprovalDecision}:
            raise ValueError(f"Unsupported approval decision: {decision.decision}")
        if decision.request_id not in self._requests:
            raise ValueError(f"Approval request not found: {decision.request_id}")
        if decision.request_id not in self._decisions:
            self._decisions[decision.request_id] = []
        self._decisions[decision.request_id].append(decision)
        self._persist_decision(decision)
    
    def get_latest_decision(self, request_id: str) -> ApprovalDecisionRecord | None:
        """Get the latest decision for an approval request."""
        decisions = self._decisions.get(request_id, [])
        return decisions[-1] if decisions else None
    
    def get_pending_requests(self) -> list[ApprovalRequest]:
        """List all pending approval requests (without final decision)."""
        pending = []
        for request in self._requests.values():
            latest_decision = self.get_latest_decision(request.request_id)
            if latest_decision is None or latest_decision.decision == ApprovalDecision.DEFERRED.value:
                pending.append(request)
        return pending

    def list_decisions(self, request_id: str) -> list[ApprovalDecisionRecord]:
        """List decisions for one approval request in insertion order."""
        if not request_id:
            raise ValueError("request_id must not be empty")
        return list(self._decisions.get(request_id, []))
    
    def clear(self) -> None:
        """Clear all data (for testing)."""
        self._requests.clear()
        self._decisions.clear()
        self._profiles.clear()
        if self._sqlite_path is not None and self._sqlite_path.exists():
            self._sqlite_path.unlink()
            self._init_sqlite()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with row access enabled."""
        if self._sqlite_path is None:
            raise RuntimeError("sqlite_path is not configured")
        connection = sqlite3.connect(str(self._sqlite_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _init_sqlite(self) -> None:
        """Create the approval persistence schema if needed."""
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_requests (
                    request_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    capability_name TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    context_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    user_id TEXT,
                    timestamp TEXT NOT NULL,
                    reason TEXT,
                    FOREIGN KEY(request_id) REFERENCES approval_requests(request_id)
                )
                """
            )
            connection.commit()

    def _load_sqlite_state(self) -> None:
        """Load persisted requests and decisions into memory."""
        with self._connect() as connection:
            for row in connection.execute("SELECT * FROM approval_requests ORDER BY timestamp, request_id"):
                context = self._loads_json_object(row["context_json"])
                request = ApprovalRequest(
                    request_id=str(row["request_id"]),
                    capability_id=str(row["capability_id"]),
                    capability_name=str(row["capability_name"]),
                    reason=str(row["reason"]),
                    timestamp=str(row["timestamp"]),
                    context=context,
                )
                self._requests[request.request_id] = request
                self._decisions.setdefault(request.request_id, [])
            for row in connection.execute("SELECT * FROM approval_decisions ORDER BY id"):
                decision = ApprovalDecisionRecord(
                    request_id=str(row["request_id"]),
                    decision=str(row["decision"]),
                    user_id=str(row["user_id"]) if row["user_id"] is not None else None,
                    timestamp=str(row["timestamp"]),
                    reason=str(row["reason"]) if row["reason"] is not None else None,
                )
                self._decisions.setdefault(decision.request_id, []).append(decision)

    def _persist_request(self, request: ApprovalRequest) -> None:
        """Persist one request when SQLite is configured."""
        if self._sqlite_path is None:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO approval_requests (
                    request_id, capability_id, capability_name, reason, timestamp, context_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request.request_id,
                    request.capability_id,
                    request.capability_name,
                    request.reason,
                    request.timestamp,
                    json.dumps(request.context, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            connection.commit()

    def _persist_decision(self, decision: ApprovalDecisionRecord) -> None:
        """Persist one decision when SQLite is configured."""
        if self._sqlite_path is None:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO approval_decisions (request_id, decision, user_id, timestamp, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    decision.request_id,
                    decision.decision,
                    decision.user_id,
                    decision.timestamp,
                    decision.reason,
                ),
            )
            connection.commit()

    @staticmethod
    def _loads_json_object(payload: str) -> dict[str, Any]:
        """Return a JSON object, falling back to an empty object for corrupt rows."""
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
