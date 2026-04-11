# -*- coding: utf-8 -*-
"""Default Scorer Implementation - Replicates the legacy scoring logic."""

import logging
from typing import List, Dict, Any
from modules.scoring_interface import ScoringInterface
from modules.scoring_registry import ScoringRegistry

logger = logging.getLogger(__name__)


@ScoringRegistry.register("default")
class DefaultScorer:
    """Standard scoring logic used in baseline versions."""

    def __init__(self, **kwargs: Any):
        """Initialize optional settings."""
        self.settings = kwargs

    def calculate_goal_score(
        self, 
        goal: str, 
        scores: List[float], 
        evidence_types: List[str]
    ) -> Dict[str, Any]:
        """Legacy goal-level scoring logic."""
        if not scores:
            return {
                "max_score": 0.0,
                "average_score": 0.0,
                "quality_label": "Low"
            }
            
        max_score = max(scores)
        average_score = sum(scores) / len(scores)
        
        return {
            "max_score": max_score,
            "average_score": average_score,
        }

    def calculate_overall_report(
        self, 
        goal_results: Dict[str, Any], 
        total_chunks: int,
        goals: List[str]
    ) -> Dict[str, Any]:
        """Legacy paper-level aggregation logic."""
        total_weighted_score = 0.0
        active_goals = 0

        for goal in goals:
            res = goal_results.get(goal)
            if res and res.hits_count > 0:
                total_weighted_score += res.max_score
                active_goals += 1

        overall_score = (total_weighted_score / active_goals) if active_goals > 0 else 0.0
        overall_confidence = (active_goals / len(goals)) if goals else 0.0

        return {
            "overall_score": overall_score,
            "overall_confidence": overall_confidence,
        }
