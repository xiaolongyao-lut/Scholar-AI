# -*- coding: utf-8 -*-
"""
Harness V2 Phase F.3: Recovery Execution Engine

Implements execution backends for recovery actions:
- REPLAY_JOB: Re-execute a job from canonical events
- REBUILD_WAKEUP: Reconstruct memory context for session wake-up
- REHYDRATE_RUNTIME: Apply historical state to runtime
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from datetime_utils import to_iso_z, utc_now
from canonical_event_store import CanonicalEventStore, CanonicalEvent
from memory_fact_store import MemoryFactStore, TemporalFact
from recovery_console import (
    RecoveryConsole,
    RecoveryAction,
    RecoveryActionType,
    InspectionContext,
)


logger = logging.getLogger("RecoveryExecutionEngine")


class ActionExecutionStatus(Enum):
    """Status of recovery action execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class ExecutionResult:
    """Result of executing a recovery action."""
    action_id: str
    action_type: RecoveryActionType
    status: ActionExecutionStatus
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    output: dict[str, Any]
    error: Optional[str] = None
    rolled_back_at: Optional[datetime] = None


class RecoveryExecutionEngine:
    """Executes recovery actions with result tracking."""

    def __init__(
        self,
        console: RecoveryConsole,
        event_store: CanonicalEventStore,
        fact_store: MemoryFactStore,
    ):
        """Initialize execution engine.
        
        Args:
            console: Recovery console for inspection operations
            event_store: Access to canonical events
            fact_store: Access to memory facts
        """
        self.console = console
        self.event_store = event_store
        self.fact_store = fact_store
        self._execution_log: dict[str, ExecutionResult] = {}

    def execute_action(self, action: RecoveryAction) -> ExecutionResult:
        """Execute a recovery action.
        
        Args:
            action: Recovery action to execute
            
        Returns:
            ExecutionResult with outcome and details
        """
        started_at = utc_now()
        status = ActionExecutionStatus.PENDING
        error = None
        output: dict[str, Any] = {}

        try:
            logger.info(
                "Executing recovery action: %s (type: %s)",
                action.action_id,
                action.action_type.value,
            )
            status = ActionExecutionStatus.RUNNING

            # Dispatch to appropriate executor
            if action.action_type == RecoveryActionType.REPLAY_JOB:
                output = self._execute_replay_job(action)
            elif action.action_type == RecoveryActionType.REBUILD_WAKEUP:
                output = self._execute_rebuild_wakeup(action)
            elif action.action_type == RecoveryActionType.REHYDRATE_RUNTIME:
                output = self._execute_rehydrate_runtime(action)
            else:
                raise ValueError(
                    f"Unsupported action type: {action.action_type.value}"
                )

            status = ActionExecutionStatus.SUCCEEDED
            logger.info(
                "Recovery action succeeded: %s", action.action_id
            )

        except (ValueError, AttributeError, KeyError) as exc:
            status = ActionExecutionStatus.FAILED
            error = str(exc)
            logger.error(
                "Recovery action failed: %s - %s",
                action.action_id,
                error,
                exc_info=True,
            )

        completed_at = utc_now()
        duration = (completed_at - started_at).total_seconds()

        result = ExecutionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            output=output,
            error=error,
        )

        self._execution_log[action.action_id] = result
        return result

    def _execute_replay_job(self, action: RecoveryAction) -> dict[str, Any]:
        """Execute job replay from canonical events.
        
        Args:
            action: REPLAY_JOB action with job_id parameter
            
        Returns:
            Output dict with replay details
        """
        job_id = action.parameters.get("job_id")
        if not job_id:
            raise ValueError("REPLAY_JOB requires job_id parameter")

        # Query all events for the job
        events = self.event_store.get_job_timeline(job_id)
        logger.info(
            "Replaying job %s with %d events", job_id, len(events)
        )

        # Extract execution events (non-state-changing)
        execution_events = [
            e for e in events
            if hasattr(e, 'event_type') and e.event_type
            in [
                "JobStarted",
                "JobProgressed",
                "JobSkilled",
                "JobCompleted",
                "JobFailed",
            ]
        ]

        # Build replay sequence
        replay_sequence = []
        for event in execution_events:
            replay_sequence.append({
                "event_id": getattr(event, 'event_id', None),
                "event_type": getattr(event, 'event_type', None),
                "timestamp": to_iso_z(event.timestamp),
                "data": getattr(event, 'payload', {}),
            })

        return {
            "job_id": job_id,
            "total_events": len(events),
            "execution_events": len(execution_events),
            "replay_sequence": replay_sequence,
            "status": "replayed",
            "ready_for_restart": len(execution_events) > 0,
        }

    def _execute_rebuild_wakeup(self, action: RecoveryAction) -> dict[str, Any]:
        """Rebuild memory context for session wake-up.
        
        Args:
            action: REBUILD_WAKEUP action with session_id parameter
            
        Returns:
            Output dict with wakeup context details
        """
        session_id = action.parameters.get("session_id")
        if not session_id:
            raise ValueError("REBUILD_WAKEUP requires session_id parameter")

        # Inspect memory state for the session
        context = InspectionContext(session_id=session_id)
        snapshot = self.console.inspect_memory_state(context)

        # Query session events to understand context
        session_events = self.event_store.get_session_timeline(session_id)
        logger.info(
            "Rebuilding wakeup for session %s with %d facts and %d events",
            session_id,
            snapshot.fact_count,
            len(session_events),
        )

        # Build wakeup context from facts
        wakeup_context = {
            "session_id": session_id,
            "snapshot_timestamp": to_iso_z(snapshot.timestamp),
            "fact_count": snapshot.fact_count,
            "namespaces": snapshot.namespaces,
            "facts_by_namespace": self._organize_facts_by_namespace(
                snapshot.current_facts
            ),
            "recent_events": self._extract_recent_events(
                session_events, limit=10
            ),
        }

        return {
            "session_id": session_id,
            "wakeup_ready": True,
            "context": wakeup_context,
            "status": "rebuilt",
        }

    def _execute_rehydrate_runtime(
        self, action: RecoveryAction
    ) -> dict[str, Any]:
        """Apply historical state to runtime.
        
        Args:
            action: REHYDRATE_RUNTIME action with session_id parameter
            
        Returns:
            Output dict with rehydration details
        """
        session_id = action.parameters.get("session_id")
        if not session_id:
            raise ValueError(
                "REHYDRATE_RUNTIME requires session_id parameter"
            )

        # Get historical facts
        context = InspectionContext(session_id=session_id)
        snapshot = self.console.inspect_memory_state(context)

        # Extract key execution facts
        execution_facts = [
            f for f in snapshot.current_facts if f.namespace == "execution"
        ]
        skill_facts = [f for f in snapshot.current_facts if f.namespace == "skill"]
        resource_facts = [
            f for f in snapshot.current_facts if f.namespace == "resource"
        ]

        logger.info(
            "Rehydrating runtime for session %s: %d exec, %d skill, %d resource facts",
            session_id,
            len(execution_facts),
            len(skill_facts),
            len(resource_facts),
        )

        rehydration_state = {
            "session_id": session_id,
            "execution_state": self._extract_execution_state(
                execution_facts
            ),
            "skill_state": self._extract_skill_state(skill_facts),
            "resource_state": self._extract_resource_state(resource_facts),
            "timestamp": to_iso_z(utc_now()),
        }

        return {
            "session_id": session_id,
            "rehydrated": True,
            "state": rehydration_state,
            "status": "rehydrated",
        }

    def _organize_facts_by_namespace(
        self, facts: list[TemporalFact]
    ) -> dict[str, list[dict[str, Any]]]:
        """Organize facts by namespace.
        
        Args:
            facts: List of temporal facts
            
        Returns:
            Facts organized by namespace
        """
        organized: dict[str, list[dict[str, Any]]] = {}
        for fact in facts:
            if fact.namespace not in organized:
                organized[fact.namespace] = []
            organized[fact.namespace].append({
                "fact_id": fact.fact_id,
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": fact.object,
                "valid_from": to_iso_z(fact.valid_from),
            })
        return organized

    def _extract_recent_events(
        self, events: list[CanonicalEvent], limit: int = 10
    ) -> list[dict[str, Any]]:
        """Extract recent events with limit.
        
        Args:
            events: List of events
            limit: Maximum number to extract
            
        Returns:
            Recent events formatted as dicts
        """
        recent = events[-limit:] if len(events) > limit else events
        return [
            {
                "event_id": getattr(e, 'event_id', None),
                "event_type": getattr(e, 'event_type', None),
                "timestamp": to_iso_z(e.timestamp),
            }
            for e in recent
        ]

    def _extract_execution_state(
        self, facts: list[TemporalFact]
    ) -> dict[str, Any]:
        """Extract execution state from facts.
        
        Args:
            facts: Execution namespace facts
            
        Returns:
            Extracted execution state
        """
        state: dict[str, Any] = {}
        for fact in facts:
            # Group by subject (job_id, etc.)
            subject = fact.subject
            if subject not in state:
                state[subject] = {}
            state[subject][fact.predicate] = fact.object
        return state

    def _extract_skill_state(
        self, facts: list[TemporalFact]
    ) -> dict[str, Any]:
        """Extract skill state from facts.
        
        Args:
            facts: Skill namespace facts
            
        Returns:
            Extracted skill state
        """
        state: dict[str, Any] = {}
        for fact in facts:
            skill_id = fact.subject
            if skill_id not in state:
                state[skill_id] = {}
            state[skill_id][fact.predicate] = fact.object
        return state

    def _extract_resource_state(
        self, facts: list[TemporalFact]
    ) -> dict[str, Any]:
        """Extract resource state from facts.
        
        Args:
            facts: Resource namespace facts
            
        Returns:
            Extracted resource state
        """
        state: dict[str, Any] = {}
        for fact in facts:
            resource_id = fact.subject
            if resource_id not in state:
                state[resource_id] = {}
            state[resource_id][fact.predicate] = fact.object
        return state

    def get_execution_result(self, action_id: str) -> Optional[ExecutionResult]:
        """Get result of a previous execution.
        
        Args:
            action_id: Action to look up
            
        Returns:
            ExecutionResult or None if not found
        """
        return self._execution_log.get(action_id)

    def get_execution_history(self) -> list[ExecutionResult]:
        """Get all execution results.
        
        Returns:
            List of all execution results in order
        """
        return list(self._execution_log.values())
