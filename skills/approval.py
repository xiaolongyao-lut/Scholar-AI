# -*- coding: utf-8 -*-
"""Approval policies and decision models for capability execution."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
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
    """In-memory store for approval requests and decisions."""
    
    def __init__(self):
        """Initialize empty store."""
        self._requests: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, list[ApprovalDecisionRecord]] = {}
        self._profiles: dict[str, CapabilityApprovalProfile] = {}
    
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
        self._requests[request.request_id] = request
        if request.request_id not in self._decisions:
            self._decisions[request.request_id] = []
    
    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Get an approval request by ID."""
        return self._requests.get(request_id)
    
    def record_decision(self, decision: ApprovalDecisionRecord) -> None:
        """Record a user decision on an approval request."""
        if decision.request_id not in self._decisions:
            self._decisions[decision.request_id] = []
        self._decisions[decision.request_id].append(decision)
    
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
    
    def clear(self) -> None:
        """Clear all data (for testing)."""
        self._requests.clear()
        self._decisions.clear()
        self._profiles.clear()
