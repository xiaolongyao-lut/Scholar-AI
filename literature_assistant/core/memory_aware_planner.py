# -*- coding: utf-8 -*-
"""
Harness V2 Phase E: Memory-Aware Planner

Makes job scheduling and skill selection decisions using:
- Current system state (temporal facts from Phase D)
- Historical patterns and success rates
- Memory policy guidance (Phase C)
- Resource availability constraints

This module:
- Defines planning inputs (PlanningContext) and outputs (ExecutionPlan)
- Implements configurable planning rules
- Queries facts for constraints and patterns
- Generates execution strategies informed by memory
- Injects memory context at job/session creation
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from datetime_utils import utc_now, utc_timestamp
from memory_fact_store import MemoryFactStore, TemporalFact
from memory_policy import MemoryPolicyEngine


class ExecutionStrategy(Enum):
    """Parallelism strategy for job execution."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    ADAPTIVE = "adaptive"


class ConfidenceLevel(Enum):
    """Confidence score interpretation."""
    VERY_LOW = (0.0, 0.2)
    LOW = (0.2, 0.4)
    MEDIUM = (0.4, 0.6)
    HIGH = (0.6, 0.8)
    VERY_HIGH = (0.8, 1.0)


@dataclass
class PlanningContext:
    """Context for making planning decisions."""
    
    session_id: str                         # Current session
    job_kind: str                           # Job type (generate, analyze, refactor, etc.)
    user_id: str                            # User identifier
    constraints: dict[str, Any]             # Resource/skill constraints
    optional_scope: str | None = None       # Execution scope if any
    memory_namespace: str | None = None     # Memory domain for consultation
    historical_context: dict[str, Any] | None = None  # Previous job info


@dataclass(frozen=True)
class ExecutionPlan:
    """Immutable execution plan informed by memory and facts."""
    
    plan_id: str                            # Unique plan identifier
    session_id: str                         # Session this plan is for
    job_kind: str                           # Job type
    created_at: datetime                    # Plan creation timestamp
    
    # Execution strategy
    parallelism_strategy: str               # "sequential", "parallel", "adaptive"
    skill_sequence: list[str]               # Skills to execute in order
    skill_constraints: dict[str, Any] = field(default_factory=dict)  # Per-skill constraints
    
    # Resource strategy
    resources_required: dict[str, Any] = field(default_factory=dict)  # Resource needs
    resource_constraints: dict[str, Any] = field(default_factory=dict)  # Constraints
    
    # Memory context
    injected_memory: dict[str, Any] = field(default_factory=dict)  # Memory to inject
    memory_policy_applied: str = ""         # Which policy rule applied
    confidence: float = 0.5                 # Confidence score (0.0-1.0)
    
    # Traceability
    fact_sources: list[str] = field(default_factory=list)  # IDs of facts used
    policy_sources: list[str] = field(default_factory=list)  # IDs of policies applied
    reasoning: str = ""                     # Human-readable explanation


class PlanningRule(ABC):
    """Base class for planning decision rules."""
    
    @abstractmethod
    def can_apply(self, context: PlanningContext, facts: list[TemporalFact]) -> bool:
        """Check if this rule should apply."""

    @abstractmethod
    def apply(
        self,
        context: PlanningContext,
        plan_data: dict[str, Any],
        fact_store: MemoryFactStore,
    ) -> None:
        """Apply rule logic to modify plan data dict."""


class SkillAvailabilityRule(PlanningRule):
    """Filter plan to only use currently enabled skills."""
    
    def can_apply(self, context: PlanningContext, facts: list[TemporalFact]) -> bool:
        """Apply if job_kind suggests skill execution."""
        return context.job_kind in ["generate", "analyze", "refactor", "validate"]
    
    def apply(
        self,
        context: PlanningContext,
        plan_data: dict[str, Any],
        fact_store: MemoryFactStore,
    ) -> None:
        """Filter to only enabled skills."""
        # Get currently enabled skills
        enabled_facts = fact_store.get_current_facts(
            "skills",
            predicate="enabled"
        )
        enabled_skills = {
            f.subject for f in enabled_facts
            if f.object == "true"
        }
        
        # Filter skill sequence
        original_sequence = plan_data["skill_sequence"]
        filtered = [s for s in original_sequence if s in enabled_skills]
        plan_data["skill_sequence"] = filtered
        
        if not filtered and original_sequence:
            plan_data["confidence"] *= 0.3
            plan_data["reasoning"] += "\n[SkillAvailability] Filtered sequence, no enabled skills available"
        else:
            plan_data["reasoning"] += f"\n[SkillAvailability] Filtered to {len(filtered)} enabled skills"


class ResourceConstraintRule(PlanningRule):
    """Apply current resource availability constraints."""
    
    def can_apply(self, context: PlanningContext, facts: list[TemporalFact]) -> bool:
        """Apply if context has constraints."""
        return bool(context.constraints)
    
    def apply(
        self,
        context: PlanningContext,
        plan_data: dict[str, Any],
        fact_store: MemoryFactStore,
    ) -> None:
        """Add resource constraints to plan."""
        # Get resource availability
        resource_facts = fact_store.get_current_facts("resources")
        
        unavailable_resources = [
            f.subject for f in resource_facts
            if f.object in ["deleted", "unavailable"]
        ]
        
        # Add constraints
        for resource in unavailable_resources:
            plan_data["resource_constraints"][resource] = "wait_or_skip"
        
        if unavailable_resources:
            plan_data["confidence"] *= 0.7
            plan_data["reasoning"] += f"\n[ResourceConstraint] {len(unavailable_resources)} resources unavailable"


class ExecutionStrategyRule(PlanningRule):
    """Decide sequential vs parallel execution based on load."""
    
    def can_apply(self, context: PlanningContext, facts: list[TemporalFact]) -> bool:
        """Always applicable."""
        return True
    
    def apply(
        self,
        context: PlanningContext,
        plan_data: dict[str, Any],
        fact_store: MemoryFactStore,
    ) -> None:
        """Select execution strategy based on current load."""
        # Check execution load
        execution_facts = fact_store.get_current_facts("execution")
        running_jobs = [f for f in execution_facts if f.object == "running"]
        
        if len(running_jobs) > 5:
            strategy = ExecutionStrategy.SEQUENTIAL.value
            confidence_mult = 0.8
        elif len(running_jobs) > 2:
            strategy = ExecutionStrategy.ADAPTIVE.value
            confidence_mult = 0.9
        else:
            strategy = ExecutionStrategy.PARALLEL.value
            confidence_mult = 1.0
        
        plan_data["parallelism_strategy"] = strategy
        plan_data["confidence"] *= confidence_mult
        plan_data["reasoning"] += f"\n[ExecutionStrategy] Selected {strategy} ({len(running_jobs)} jobs running)"


class SuccessPatternRule(PlanningRule):
    """Adjust confidence based on historical success patterns."""
    
    def can_apply(self, context: PlanningContext, facts: list[TemporalFact]) -> bool:
        """Apply if there's skill sequence."""
        return len(context.constraints.get("initial_skills", [])) > 0 or True
    
    def apply(
        self,
        context: PlanningContext,
        plan_data: dict[str, Any],
        fact_store: MemoryFactStore,
    ) -> None:
        """Adjust confidence based on skill success rates."""
        total_confidence = 1.0
        
        for skill in plan_data["skill_sequence"]:
            # Get skill execution timeline
            timeline = fact_store.get_fact_timeline(
                "execution",
                skill,
                "status"
            )
            
            if timeline:
                # Count successes
                completed = sum(1 for f in timeline if f.object == "completed")
                failed = sum(1 for f in timeline if f.object == "failed")
                total = completed + failed
                
                if total > 0:
                    success_rate = completed / total
                    total_confidence *= success_rate
        
        plan_data["confidence"] *= total_confidence
        plan_data["reasoning"] += "\n[SuccessPattern] Adjusted confidence based on skill histories"


class MemoryContextRule(PlanningRule):
    """Determine memory context to inject based on patterns."""
    
    def can_apply(self, context: PlanningContext, facts: list[TemporalFact]) -> bool:
        """Apply if context has namespace specified."""
        return context.memory_namespace is not None
    
    def apply(
        self,
        context: PlanningContext,
        plan_data: dict[str, Any],
        fact_store: MemoryFactStore,
    ) -> None:
        """Inject relevant memory context."""
        if not context.memory_namespace:
            return
        
        # Get relevant facts as memory context
        facts = fact_store.get_current_facts(context.memory_namespace)
        
        memory_context = {
            "namespace": context.memory_namespace,
            "facts": [
                {
                    "subject": f.subject,
                    "predicate": f.predicate,
                    "object": f.object,
                }
                for f in facts
            ],
            "count": len(facts),
        }
        
        plan_data["injected_memory"] = memory_context
        plan_data["reasoning"] += f"\n[MemoryContext] Injected {len(facts)} facts from {context.memory_namespace}"


class MemoryAwarePlanner:
    """
    Plans job execution using temporal facts and memory policies.
    
    Generates execution plans that:
    - Check current constraints from Phase D facts
    - Consider historical success patterns
    - Apply planning rules to modify strategy
    - Inject memory context at job start
    """
    
    def __init__(
        self,
        fact_store: MemoryFactStore,
        policy_engine: MemoryPolicyEngine | None = None,
    ):
        """
        Initialize planner with fact store and optional policy engine.
        
        Args:
            fact_store: MemoryFactStore for querying state facts
            policy_engine: Optional MemoryPolicyEngine for policy consultation
        """
        self.fact_store = fact_store
        self.policy_engine = policy_engine
        self.planning_rules: list[PlanningRule] = [
            SkillAvailabilityRule(),
            ResourceConstraintRule(),
            ExecutionStrategyRule(),
            SuccessPatternRule(),
            MemoryContextRule(),
        ]
    
    def plan_job(
        self,
        context: PlanningContext,
        default_skills: list[str] | None = None,
    ) -> ExecutionPlan:
        """
        Generate an execution plan for a job.
        
        Args:
            context: PlanningContext with session, job, user info
            default_skills: Default skill sequence if not in context
        
        Returns:
            ExecutionPlan with strategy, skills, and memory
        """
        # Build plan data as mutable dict first
        plan_data = {
            "plan_id": f"plan_{context.session_id}_{utc_timestamp()}",
            "session_id": context.session_id,
            "job_kind": context.job_kind,
            "created_at": utc_now(),
            "parallelism_strategy": ExecutionStrategy.ADAPTIVE.value,
            "skill_sequence": default_skills or self._default_skills_for_kind(context.job_kind),
            "skill_constraints": {},
            "resources_required": {},
            "resource_constraints": {},
            "injected_memory": {},
            "memory_policy_applied": "",
            "confidence": 1.0,
            "fact_sources": [],
            "policy_sources": [],
            "reasoning": f"Planning {context.job_kind} for session {context.session_id}",
        }
        
        # Get facts for current state
        facts = self.fact_store.get_current_facts("execution")
        
        # Apply all planning rules
        for rule in self.planning_rules:
            if rule.can_apply(context, facts):
                rule.apply(context, plan_data, self.fact_store)
        
        # Convert back to immutable ExecutionPlan
        return ExecutionPlan(
            plan_id=plan_data["plan_id"],
            session_id=plan_data["session_id"],
            job_kind=plan_data["job_kind"],
            created_at=plan_data["created_at"],
            parallelism_strategy=plan_data["parallelism_strategy"],
            skill_sequence=list(plan_data["skill_sequence"]),
            skill_constraints=dict(plan_data["skill_constraints"]),
            resources_required=dict(plan_data["resources_required"]),
            resource_constraints=dict(plan_data["resource_constraints"]),
            injected_memory=dict(plan_data["injected_memory"]),
            memory_policy_applied=plan_data["memory_policy_applied"],
            confidence=plan_data["confidence"],
            fact_sources=list(plan_data["fact_sources"]),
            policy_sources=list(plan_data["policy_sources"]),
            reasoning=plan_data["reasoning"],
        )
    
    def _default_skills_for_kind(self, job_kind: str) -> list[str]:
        """Get default skill sequence for job kind."""
        defaults = {
            "generate": ["code_generator", "formatter"],
            "analyze": ["analyzer", "reviewer"],
            "refactor": ["analyzer", "refactorer", "validator"],
            "validate": ["validator"],
        }
        return defaults.get(job_kind, ["generic_processor"])
    
    def get_confidence_level(self, plan: ExecutionPlan) -> str:
        """Get human-readable confidence interpretation."""
        for level in ConfidenceLevel:
            min_conf, max_conf = level.value
            if min_conf <= plan.confidence < max_conf:
                return level.name
        return "VERY_HIGH"
    
    def recommend_alternative_skill(
        self,
        current_skill: str,
        fact_store: MemoryFactStore,
    ) -> str | None:
        """
        Recommend alternative skill if current is failing.
        
        Args:
            current_skill: Skill to potentially replace
            fact_store: Fact store for querying history
        
        Returns:
            Recommended skill or None
        """
        # Get failure timeline
        timeline = fact_store.get_fact_timeline(
            "execution",
            current_skill,
            "status"
        )
        
        failures = [f for f in timeline if f.object == "failed"]
        if len(failures) > 3:
            # This skill has failed often
            return None  # Signal need for alternative
        
        return None
    
    def register_planning_rule(self, rule: PlanningRule) -> None:
        """
        Register a custom planning rule.
        
        Args:
            rule: PlanningRule to register
        """
        self.planning_rules.append(rule)


def create_default_planner(
    fact_store: MemoryFactStore,
    policy_engine: MemoryPolicyEngine | None = None,
) -> MemoryAwarePlanner:
    """
    Create a memory-aware planner with default configuration.
    
    Args:
        fact_store: MemoryFactStore for querying state
        policy_engine: Optional MemoryPolicyEngine for policy decisions
    
    Returns:
        Initialized MemoryAwarePlanner
    """
    return MemoryAwarePlanner(fact_store, policy_engine)
