# -*- coding: utf-8 -*-
"""
Harness V2 Phase C: Memory Policy Engine

Intelligent decision engine that classifies canonical events and routes them to:
- MemPalace (long-term project memory)
- Temporal Fact Store (current metadata + history)
- Skip (not memory-worthy)

Policy Rules:
1. Terminal job outcomes → long-term memory
2. Resource mutations → temporal facts
3. Approvals → permanent facts
4. New/recurring errors → memory + facts
5. Routine operations → skip (reduce noise)

Enables memory-aware execution where:
- MemPalace provides historical context
- Fact store provides current state
- Canonical events maintain immutable audit trail
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from harness_canonical_events import CanonicalEvent


class MemoryAction(str, Enum):
    """Where to route the canonical event."""
    SKIP = "skip"  # Don't write anywhere
    MEMORY = "memory"  # Write to MemPalace only
    FACT = "fact"  # Write temporal fact only
    BOTH = "both"  # Write to both MemPalace AND fact store


@dataclass(frozen=True)
class MemoryDecision:
    """
    Immutable result of policy evaluation for a canonical event.
    
    Tells the system what to do with the event after canonical event
    recording is complete.
    """
    
    action: MemoryAction
    """Whether to skip, write to memory, write to facts, or both."""
    
    memory_category: str | None
    """Wing/category in MemPalace if action includes 'memory'."""
    
    fact_namespace: str | None
    """Namespace in fact store if action includes 'fact'."""
    
    confidence: float
    """How confident we are in this decision (0.0-1.0)."""
    
    reason: str
    """Human-readable explanation of why this decision was made."""
    
    rule_name: str | None = None
    """Which rule triggered this decision."""
    
    dedupe_key: str | None = None
    """Key for deduplication if applicable."""


@dataclass(frozen=True)
class MemoryPolicyRule:
    """
    Immutable policy rule for routing canonical events.
    
    A rule specifies:
    - When to apply (condition)
    - What to do (action)
    - Where to send it (memory_category, fact_namespace)
    - Quality metrics (confidence, priority)
    """
    
    name: str
    """Rule identifier."""
    
    priority: int
    """Priority for conflict resolution (higher wins)."""
    
    condition: Callable[[CanonicalEvent, dict[str, Any] | None], bool]
    """Function that returns True if rule applies to this event."""
    
    action: MemoryAction
    """What to do with events matching this rule."""
    
    memory_category: str | None = None
    """MemPalace wing if action includes memory."""
    
    fact_namespace: str | None = None
    """Fact store namespace if action includes facts."""
    
    description: str = ""
    """Human-readable rule description."""


class MemoryPolicyEngine:
    """
    Policy decision engine for canonical events.
    
    Routes each canonical event to appropriate memory layers based on:
    - Event type patterns
    - Historical context
    - Configured policy rules
    - AI memory best practices
    """
    
    def __init__(self):
        """Initialize the policy engine with default rules."""
        self._rules: list[MemoryPolicyRule] = []
        self._historical_facts: dict[str, int] = {}  # For pattern detection
        self._important_job_kinds = {
            'write_section', 'refactor', 'research', 'planning', 'review'
        }
        self._load_default_rules()
    
    def _load_default_rules(self) -> None:
        """Load built-in policy rules."""
        
        # Terminal job events (highest priority)
        self._rules.append(MemoryPolicyRule(
            name='terminal_completion_important',
            priority=100,
            condition=lambda e, c: (
                e.event_type == 'job_completed' and
                e.payload.get('job_kind') in self._important_job_kinds
            ),
            action=MemoryAction.MEMORY,
            memory_category='project_decisions',
            description='Important job completions become long-term memory',
        ))
        
        self._rules.append(MemoryPolicyRule(
            name='terminal_failure',
            priority=99,
            condition=lambda e, c: e.event_type == 'job_failed',
            action=MemoryAction.BOTH,
            memory_category='error_resolutions',
            fact_namespace='job.failure',
            description='Job failures tracked as facts and memory',
        ))
        
        # Resource mutations
        self._rules.append(MemoryPolicyRule(
            name='resource_publication',
            priority=90,
            condition=lambda e, c: (
                e.event_type == 'resource_modified' and
                e.aggregate_type == 'resource'
            ),
            action=MemoryAction.FACT,
            fact_namespace='resource.current_state',
            description='Resource mutations update current state facts',
        ))
        
        # Approvals (permanent)
        self._rules.append(MemoryPolicyRule(
            name='approval_decision',
            priority=95,
            condition=lambda e, c: e.event_type == 'approval_decided',
            action=MemoryAction.FACT,
            fact_namespace='approval.decision',
            description='Approval decisions become permanent facts',
        ))
        
        # Error tracking
        self._rules.append(MemoryPolicyRule(
            name='new_error',
            priority=85,
            condition=lambda e, c: (
                e.event_type == 'error_occurred' and
                e.error_code and
                not self._is_known_error(e.error_code)
            ),
            action=MemoryAction.BOTH,
            memory_category='error_catalog',
            fact_namespace='error.first_occurrence',
            description='New error types captured as memory + fact',
        ))
        
        self._rules.append(MemoryPolicyRule(
            name='recurring_error',
            priority=84,
            condition=lambda e, c: (
                e.event_type == 'error_occurred' and
                self._get_error_count(e.error_code or 'unknown') >= 3
            ),
            action=MemoryAction.MEMORY,
            memory_category='recurring_problems',
            description='Errors occurring 3+ times get special memory treatment',
        ))
        
        # Artifacts (selective)
        self._rules.append(MemoryPolicyRule(
            name='important_artifact',
            priority=80,
            condition=lambda e, c: (
                e.event_type == 'artifact_created' and
                e.payload.get('importance') == 'high'
            ),
            action=MemoryAction.BOTH,
            memory_category='key_artifacts',
            fact_namespace='artifact.created',
            description='Important artifacts to both memory and facts',
        ))
        
        # Catch-all (default skip)
        self._rules.append(MemoryPolicyRule(
            name='default_skip',
            priority=0,
            condition=lambda e, c: True,  # Matches everything
            action=MemoryAction.SKIP,
            description='Routine events skipped (noise reduction)',
        ))
    
    def evaluate(
        self,
        event: CanonicalEvent,
        resource_context: dict[str, Any] | None = None,
    ) -> MemoryDecision:
        """
        Evaluate a canonical event against policy rules.
        
        Args:
            event: CanonicalEvent to classify
            resource_context: Optional context about affected resources
            
        Returns:
            MemoryDecision with action, categories, and reasoning
        """
        # Sort rules by priority (highest first)
        sorted_rules = sorted(self._rules, key=lambda r: r.priority, reverse=True)
        
        # Apply rules in priority order
        for rule in sorted_rules:
            try:
                if rule.condition(event, resource_context):
                    # Track error counts for pattern detection
                    if event.error_code:
                        self._increment_error_count(event.error_code)
                    
                    return MemoryDecision(
                        action=rule.action,
                        memory_category=rule.memory_category,
                        fact_namespace=rule.fact_namespace,
                        confidence=0.95,  # Rules are high-confidence
                        reason=rule.description,
                        rule_name=rule.name,
                        dedupe_key=self._compute_dedupe_key(event, rule),
                    )
            except (AttributeError, KeyError, TypeError):
                # Rule execution error (field missing, type mismatch, etc); try next rule
                continue
        
        # Should not reach here (default_skip should match all)
        return MemoryDecision(
            action=MemoryAction.SKIP,
            memory_category=None,
            fact_namespace=None,
            confidence=0.5,
            reason="No rule matched (conservative default)",
        )
    
    def register_rule(self, rule: MemoryPolicyRule) -> None:
        """
        Register a custom policy rule.
        
        Args:
            rule: MemoryPolicyRule to add
        """
        self._rules.append(rule)
        # Re-sort by priority
        self._rules.sort(key=lambda r: r.priority, reverse=True)
    
    def get_decision_stats(self) -> dict[str, Any]:
        """
        Get statistics about policy decisions.
        
        Returns:
            Dict with counts by action and category
        """
        return {
            'total_rules': len(self._rules),
            'known_errors': len(self._historical_facts),
            'memory_categories': list(set(
                r.memory_category for r in self._rules
                if r.memory_category
            )),
            'fact_namespaces': list(set(
                r.fact_namespace for r in self._rules
                if r.fact_namespace
            )),
        }
    
    # Helper methods
    
    def _is_known_error(self, error_code: str) -> bool:
        """Check if error code has been seen before."""
        return error_code in self._historical_facts
    
    def _get_error_count(self, error_code: str) -> int:
        """Get count of times this error has occurred."""
        return self._historical_facts.get(error_code, 0)
    
    def _increment_error_count(self, error_code: str) -> None:
        """Track error occurrence count."""
        self._historical_facts[error_code] = self._get_error_count(error_code) + 1
    
    def _compute_dedupe_key(self, event: CanonicalEvent, rule: MemoryPolicyRule) -> str | None:
        """
        Compute deduplication key to avoid duplicate memory entries.
        
        Args:
            event: Canonical event
            rule: Rule that matched
            
        Returns:
            String key for deduplication or None
        """
        if not rule.memory_category:
            return None
        
        # Example: 'project_decisions:job_completed:job_123'
        # This prevents the same job completion from being written twice
        if event.aggregate_type == 'job' and event.event_type in ['job_completed', 'job_failed']:
            return f"{rule.memory_category}:{event.event_type}:{event.job_id}"
        
        # Example: 'error_catalog:ERR_TIMEOUT'
        if event.error_code:
            return f"{rule.memory_category}:{event.error_code}"
        
        return None
    
    def add_important_job_kind(self, kind: str) -> None:
        """
        Add a job kind that should be written to long-term memory.
        
        Args:
            kind: Job kind identifier
        """
        self._important_job_kinds.add(kind)


def create_default_policy_engine() -> MemoryPolicyEngine:
    """
    Factory function to create policy engine with default rules.
    
    Returns:
        MemoryPolicyEngine ready for use
    """
    return MemoryPolicyEngine()


# Convenience decision creators

def skip_decision(reason: str = "Skipped by policy") -> MemoryDecision:
    """Create a skip decision."""
    return MemoryDecision(
        action=MemoryAction.SKIP,
        memory_category=None,
        fact_namespace=None,
        confidence=0.8,
        reason=reason,
    )


def memory_only_decision(
    category: str,
    reason: str = "Routed to long-term memory",
) -> MemoryDecision:
    """Create a memory-only decision."""
    return MemoryDecision(
        action=MemoryAction.MEMORY,
        memory_category=category,
        fact_namespace=None,
        confidence=0.9,
        reason=reason,
    )


def fact_only_decision(
    namespace: str,
    reason: str = "Tracked as current fact",
) -> MemoryDecision:
    """Create a fact-only decision."""
    return MemoryDecision(
        action=MemoryAction.FACT,
        memory_category=None,
        fact_namespace=namespace,
        confidence=0.9,
        reason=reason,
    )


def both_decision(
    memory_category: str,
    fact_namespace: str,
    reason: str = "Important enough for both memory and facts",
) -> MemoryDecision:
    """Create a decision to write both memory and facts."""
    return MemoryDecision(
        action=MemoryAction.BOTH,
        memory_category=memory_category,
        fact_namespace=fact_namespace,
        confidence=0.95,
        reason=reason,
    )
