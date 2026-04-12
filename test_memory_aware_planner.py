# -*- coding: utf-8 -*-
"""
Tests for Harness V2 Phase E: Memory-Aware Planner

Comprehensive test suite for:
- Planning contexts and inputs
- Execution plan generation
- Individual planning rules
- Memory-aware planner orchestration
- Integration with fact store and policy engine
"""

import unittest
from unittest.mock import MagicMock

from datetime_utils import utc_now_naive

from memory_aware_planner import (
    ExecutionPlan,
    MemoryAwarePlanner,
    MemoryContextRule,
    PlanningContext,
    ResourceConstraintRule,
    SkillAvailabilityRule,
    SuccessPatternRule,
    ExecutionStrategyRule,
    create_default_planner,
)


class TestPlanningContext(unittest.TestCase):
    """Tests for PlanningContext input model."""
    
    def test_context_creation_minimal(self):
        """Can create context with minimal fields."""
        ctx = PlanningContext(
            session_id="sess_001",
            job_kind="generate",
            user_id="user_001",
            constraints={},
        )
        
        self.assertEqual(ctx.session_id, "sess_001")
        self.assertEqual(ctx.job_kind, "generate")
        self.assertEqual(ctx.user_id, "user_001")
    
    def test_context_creation_with_memory_namespace(self):
        """Can specify memory namespace for consultation."""
        ctx = PlanningContext(
            session_id="sess_001",
            job_kind="analyze",
            user_id="user_001",
            constraints={"max_parallel": 2},
            memory_namespace="execution",
        )
        
        self.assertEqual(ctx.memory_namespace, "execution")
        self.assertEqual(ctx.constraints["max_parallel"], 2)
    
    def test_context_with_historical_context(self):
        """Can attach historical context from previous jobs."""
        hist = {"prev_job_id": "job_123", "prev_success": True}
        ctx = PlanningContext(
            session_id="sess_001",
            job_kind="refactor",
            user_id="user_001",
            constraints={},
            historical_context=hist,
        )
        
        self.assertEqual(ctx.historical_context["prev_job_id"], "job_123")


class TestExecutionPlan(unittest.TestCase):
    """Tests for ExecutionPlan output model."""
    
    def test_plan_creation_immutable(self):
        """ExecutionPlan is frozen."""
        plan = ExecutionPlan(
            plan_id="plan_001",
            session_id="sess_001",
            job_kind="generate",
            created_at=utc_now_naive(),
            parallelism_strategy="sequential",
            skill_sequence=["skill1", "skill2"],
            confidence=0.85,
        )
        
        self.assertEqual(plan.confidence, 0.85)
        
        # Should not be able to modify
        with self.assertRaises(AttributeError):
            plan.confidence = 0.5
    
    def test_plan_has_all_tracking_fields(self):
        """Plan includes full traceability."""
        plan = ExecutionPlan(
            plan_id="plan_001",
            session_id="sess_001",
            job_kind="analyze",
            created_at=utc_now_naive(),
            parallelism_strategy="parallel",
            skill_sequence=["analyzer"],
            fact_sources=["fact_1", "fact_2"],
            policy_sources=["policy_rule_1"],
            reasoning="Testing",
        )
        
        self.assertEqual(len(plan.fact_sources), 2)
        self.assertEqual(len(plan.policy_sources), 1)
        self.assertIn("Testing", plan.reasoning)
    
    def test_plan_confidence_levels(self):
        """Can interpret confidence levels."""
        planner = create_default_planner(MagicMock())
        
        plan_high = ExecutionPlan(
            plan_id="p1", session_id="s1", job_kind="gen",
            created_at=utc_now_naive(),
            parallelism_strategy="seq",
            skill_sequence=[],
            confidence=0.95,
        )
        
        self.assertEqual(planner.get_confidence_level(plan_high), "VERY_HIGH")


class TestSkillAvailabilityRule(unittest.TestCase):
    """Tests for skill availability planning rule."""
    
    def test_rule_applies_to_skill_jobs(self):
        """Rule applies to job kinds that use skills."""
        rule = SkillAvailabilityRule()
        
        for job_kind in ["generate", "analyze", "refactor", "validate"]:
            ctx = PlanningContext(
                session_id="s1",
                job_kind=job_kind,
                user_id="u1",
                constraints={},
            )
            self.assertTrue(rule.can_apply(ctx, []))
    
    def test_filters_disabled_skills(self):
        """Filters plan to only enabled skills."""
        rule = SkillAvailabilityRule()
        plan_data = {
            "skill_sequence": ["skill1", "skill2", "skill3"],
            "confidence": 1.0,
            "reasoning": "Initial",
        }
        
        # Mock fact store
        fact_store = MagicMock()
        enabled_fact1 = MagicMock(subject="skill1", object="true")
        enabled_fact3 = MagicMock(subject="skill3", object="true")
        fact_store.get_current_facts.return_value = [enabled_fact1, enabled_fact3]
        
        ctx = PlanningContext("s1", "generate", "u1", {})
        rule.apply(ctx, plan_data, fact_store)
        
        self.assertEqual(plan_data["skill_sequence"], ["skill1", "skill3"])
    
    def test_reduces_confidence_no_skills(self):
        """Reduces confidence if no skills available."""
        rule = SkillAvailabilityRule()
        plan_data = {
            "skill_sequence": ["skill1", "skill2"],
            "confidence": 1.0,
            "reasoning": "Initial",
        }
        
        fact_store = MagicMock()
        fact_store.get_current_facts.return_value = []  # No enabled skills
        
        ctx = PlanningContext("s1", "generate", "u1", {})
        rule.apply(ctx, plan_data, fact_store)
        
        self.assertEqual(plan_data["skill_sequence"], [])
        self.assertEqual(plan_data["confidence"], 0.3)


class TestResourceConstraintRule(unittest.TestCase):
    """Tests for resource constraint planning rule."""
    
    def test_rule_applies_with_constraints(self):
        """Rule applies when constraints are present."""
        rule = ResourceConstraintRule()
        ctx = PlanningContext(
            "s1", "gen", "u1",
            constraints={"memory": "4GB"}
        )
        self.assertTrue(rule.can_apply(ctx, []))
    
    def test_rule_skips_without_constraints(self):
        """Rule doesn't apply without constraints."""
        rule = ResourceConstraintRule()
        ctx = PlanningContext("s1", "gen", "u1", constraints={})
        self.assertFalse(rule.can_apply(ctx, []))
    
    def test_marks_unavailable_resources(self):
        """Marks unavailable resources in plan."""
        rule = ResourceConstraintRule()
        plan_data = {
            "resource_constraints": {},
            "confidence": 1.0,
            "reasoning": "Initial",
        }
        
        fact_store = MagicMock()
        unavail_fact = MagicMock(subject="gpu_0", object="unavailable")
        fact_store.get_current_facts.return_value = [unavail_fact]
        
        ctx = PlanningContext("s1", "gen", "u1", constraints={"gpu": True})
        rule.apply(ctx, plan_data, fact_store)
        
        self.assertEqual(plan_data["resource_constraints"]["gpu_0"], "wait_or_skip")
        self.assertEqual(plan_data["confidence"], 0.7)


class TestExecutionStrategyRule(unittest.TestCase):
    """Tests for execution strategy planning rule."""
    
    def test_sequential_under_high_load(self):
        """Selects sequential strategy when many jobs running."""
        rule = ExecutionStrategyRule()
        plan_data = {
            "parallelism_strategy": "adaptive",
            "confidence": 1.0,
            "reasoning": "Initial",
        }
        
        fact_store = MagicMock()
        running_facts = [
            MagicMock(subject=f"job_{i}", object="running")
            for i in range(8)
        ]
        fact_store.get_current_facts.return_value = running_facts
        
        ctx = PlanningContext("s1", "gen", "u1", {})
        rule.apply(ctx, plan_data, fact_store)
        
        self.assertEqual(plan_data["parallelism_strategy"], "sequential")
        self.assertEqual(plan_data["confidence"], 0.8)
    
    def test_parallel_under_low_load(self):
        """Selects parallel strategy when few jobs running."""
        rule = ExecutionStrategyRule()
        plan_data = {
            "parallelism_strategy": "adaptive",
            "confidence": 1.0,
            "reasoning": "Initial",
        }
        
        fact_store = MagicMock()
        fact_store.get_current_facts.return_value = []
        
        ctx = PlanningContext("s1", "gen", "u1", {})
        rule.apply(ctx, plan_data, fact_store)
        
        self.assertEqual(plan_data["parallelism_strategy"], "parallel")
        self.assertEqual(plan_data["confidence"], 1.0)
    
    def test_adaptive_medium_load(self):
        """Selects adaptive strategy under medium load."""
        rule = ExecutionStrategyRule()
        plan_data = {
            "parallelism_strategy": "adaptive",
            "confidence": 1.0,
            "reasoning": "Initial",
        }
        
        fact_store = MagicMock()
        running_facts = [
            MagicMock(subject=f"job_{i}", object="running")
            for i in range(3)
        ]
        fact_store.get_current_facts.return_value = running_facts
        
        ctx = PlanningContext("s1", "gen", "u1", {})
        rule.apply(ctx, plan_data, fact_store)
        
        self.assertEqual(plan_data["parallelism_strategy"], "adaptive")
        self.assertEqual(plan_data["confidence"], 0.9)


class TestSuccessPatternRule(unittest.TestCase):
    """Tests for success pattern planning rule."""
    
    def test_high_success_rate(self):
        """Increases confidence with high success rate."""
        rule = SuccessPatternRule()
        plan_data = {
            "skill_sequence": ["skill1"],
            "confidence": 1.0,
            "reasoning": "Initial",
        }
        
        fact_store = MagicMock()
        success_facts = [
            MagicMock(object="completed"),
            MagicMock(object="completed"),
            MagicMock(object="failed"),
        ]
        fact_store.get_fact_timeline.return_value = success_facts
        
        ctx = PlanningContext("s1", "gen", "u1", {})
        rule.apply(ctx, plan_data, fact_store)
        
        # 2 successes / 3 total = 66.7%
        self.assertAlmostEqual(plan_data["confidence"], 0.667, places=2)
    
    def test_all_failures(self):
        """Significantly reduces confidence if all failures."""
        rule = SuccessPatternRule()
        plan_data = {
            "skill_sequence": ["skill1"],
            "confidence": 1.0,
            "reasoning": "Initial",
        }
        
        fact_store = MagicMock()
        fail_facts = [
            MagicMock(object="failed"),
            MagicMock(object="failed"),
        ]
        fact_store.get_fact_timeline.return_value = fail_facts
        
        ctx = PlanningContext("s1", "gen", "u1", {})
        rule.apply(ctx, plan_data, fact_store)
        
        self.assertEqual(plan_data["confidence"], 0.0)


class TestMemoryContextRule(unittest.TestCase):
    """Tests for memory context injection rule."""
    
    def test_injects_memory_facts(self):
        """Injects matching memory facts into plan."""
        rule = MemoryContextRule()
        plan_data = {
            "injected_memory": {},
            "reasoning": "Initial",
        }
        
        fact_store = MagicMock()
        facts = [
            MagicMock(subject="res1", predicate="status", object="available"),
            MagicMock(subject="res2", predicate="status", object="available"),
        ]
        fact_store.get_current_facts.return_value = facts
        
        ctx = PlanningContext(
            "s1", "gen", "u1", {},
            memory_namespace="resources"
        )
        rule.apply(ctx, plan_data, fact_store)
        
        self.assertEqual(plan_data["injected_memory"]["namespace"], "resources")
        self.assertEqual(len(plan_data["injected_memory"]["facts"]), 2)
    
    def test_skips_without_namespace(self):
        """Doesn't inject if no memory_namespace."""
        rule = MemoryContextRule()
        plan_data = {
            "injected_memory": {},
            "reasoning": "Initial",
        }
        
        fact_store = MagicMock()
        ctx = PlanningContext("s1", "gen", "u1", {})
        
        rule.apply(ctx, plan_data, fact_store)
        
        self.assertEqual(plan_data["injected_memory"], {})


class TestMemoryAwarePlannerCore(unittest.TestCase):
    """Tests for core MemoryAwarePlanner functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.fact_store = MagicMock()
        self.planner = MemoryAwarePlanner(self.fact_store)
    
    def test_planner_initializes_with_default_rules(self):
        """Planner initializes with all default rules."""
        self.assertEqual(len(self.planner.planning_rules), 5)
        rule_types = [type(r).__name__ for r in self.planner.planning_rules]
        self.assertIn("SkillAvailabilityRule", rule_types)
        self.assertIn("ResourceConstraintRule", rule_types)
        self.assertIn("ExecutionStrategyRule", rule_types)
    
    def test_register_custom_rule(self):
        """Can register custom planning rules."""
        custom_rule = MagicMock()
        self.planner.register_planning_rule(custom_rule)
        
        self.assertIn(custom_rule, self.planner.planning_rules)
    
    def test_generate_basic_plan(self):
        """Can generate a basic execution plan."""
        # Mock to return skills as enabled by default
        enabled_fact = MagicMock(subject="code_generator", object="true")
        enabled_fact2 = MagicMock(subject="formatter", object="true")
        
        # Set up return values for get_current_facts
        def mock_get_current_facts(namespace, predicate=None):
            if namespace == "skills" and predicate == "enabled":
                return [enabled_fact, enabled_fact2]
            return []
        
        self.fact_store.get_current_facts.side_effect = mock_get_current_facts
        self.fact_store.get_fact_timeline.return_value = []
        
        ctx = PlanningContext("sess_001", "generate", "user_001", {})
        plan = self.planner.plan_job(ctx)
        
        self.assertEqual(plan.session_id, "sess_001")
        self.assertEqual(plan.job_kind, "generate")
        self.assertGreater(len(plan.skill_sequence), 0)
    
    def test_plan_has_default_skills(self):
        """Plan includes default skills for job kind."""
        # Mock enabled skills
        enabled_fact1 = MagicMock(subject="analyzer", object="true")
        enabled_fact2 = MagicMock(subject="reviewer", object="true")
        
        def mock_get_current_facts(namespace, predicate=None):
            if namespace == "skills" and predicate == "enabled":
                return [enabled_fact1, enabled_fact2]
            return []
        
        self.fact_store.get_current_facts.side_effect = mock_get_current_facts
        self.fact_store.get_fact_timeline.return_value = []
        
        ctx = PlanningContext("s1", "analyze", "u1", {})
        plan = self.planner.plan_job(ctx)
        
        # Analyze jobs should have analyzer skill
        self.assertIn("analyzer", plan.skill_sequence)
    
    def test_plan_with_custom_skills(self):
        """Can provide custom skill sequence."""
        # Mock all custom skills as enabled
        custom_skills = ["custom_skill_1", "custom_skill_2"]
        enabled_facts = [
            MagicMock(subject=s, object="true") for s in custom_skills
        ]
        
        def mock_get_current_facts(namespace, predicate=None):
            if namespace == "skills" and predicate == "enabled":
                return enabled_facts
            return []
        
        self.fact_store.get_current_facts.side_effect = mock_get_current_facts
        self.fact_store.get_fact_timeline.return_value = []
        
        ctx = PlanningContext("s1", "generate", "u1", {})
        plan = self.planner.plan_job(ctx, default_skills=custom_skills)
        
        self.assertEqual(plan.skill_sequence, custom_skills)


class TestMemoryAwarePlannerIntegration(unittest.TestCase):
    """Integration tests for memory-aware planner."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        self.fact_store = MagicMock()
        self.planner = MemoryAwarePlanner(self.fact_store)
    
    def test_plan_applies_all_rules_in_order(self):
        """Plan applies all planning rules sequentially."""
        # Set up progressive constraints
        self.fact_store.get_current_facts.return_value = []
        
        ctx = PlanningContext(
            "sess_001",
            "generate",
            "user_001",
            constraints={"memory": "4GB"},
            memory_namespace="resources",
        )
        
        plan = self.planner.plan_job(
            ctx,
            default_skills=["skill1", "skill2"]
        )
        
        # Plan should have applied reasoning from multiple rules
        self.assertGreater(len(plan.reasoning), 20)
        self.assertIn("Planning", plan.reasoning)
    
    def test_plan_under_high_system_load(self):
        """Plan adjusts strategy under high system load."""
        # Simulate high load
        running_jobs = [
            MagicMock(subject=f"job_{i}", object="running")
            for i in range(10)
        ]
        self.fact_store.get_current_facts.return_value = running_jobs
        
        ctx = PlanningContext("s1", "generate", "u1", {})
        plan = self.planner.plan_job(ctx)
        
        self.assertEqual(plan.parallelism_strategy, "sequential")
        self.assertLess(plan.confidence, 1.0)
    
    def test_plan_confidence_combines_factors(self):
        """Confidence scores combine multiple factors."""
        # Mock mixed scenario: some unavailable resources, high load
        running_facts = [
            MagicMock(subject=f"job_{i}", object="running")
            for i in range(4)
        ]
        # Also mock enabled skills to prevent them from being filtered out
        enabled_skills = [
            MagicMock(subject="refactor_skill", object="true"),
            MagicMock(subject="analyzer", object="true"),
        ]
        
        def mock_get_current_facts(namespace, predicate=None):
            if namespace == "execution":
                return running_facts
            elif namespace == "skills" and predicate == "enabled":
                return enabled_skills
            return []
        
        self.fact_store.get_current_facts.side_effect = mock_get_current_facts
        self.fact_store.get_fact_timeline.return_value = []
        
        ctx = PlanningContext(
            "s1", "refactor", "u1",
            constraints={"resources": True}
        )
        plan = self.planner.plan_job(ctx)
        
        # Confidence should be reasonable (0.5-1.0)
        # Even with constraints, should be above 0.5 if skills are available
        self.assertGreater(plan.confidence, 0.5)
        self.assertLessEqual(plan.confidence, 1.0)


class TestCreateDefaultPlanner(unittest.TestCase):
    """Tests for factory function."""
    
    def test_creates_planner_with_fact_store(self):
        """Factory creates planner with fact store."""
        fact_store = MagicMock()
        planner = create_default_planner(fact_store)
        
        self.assertIsInstance(planner, MemoryAwarePlanner)
        self.assertEqual(planner.fact_store, fact_store)
    
    def test_creates_planner_with_policy_engine(self):
        """Factory can attach policy engine."""
        fact_store = MagicMock()
        policy_engine = MagicMock()
        planner = create_default_planner(fact_store, policy_engine)
        
        self.assertEqual(planner.policy_engine, policy_engine)


if __name__ == "__main__":
    unittest.main()
