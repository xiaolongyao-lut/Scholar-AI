# -*- coding: utf-8 -*-
"""Scoring Interface Module - Defines protocols for paper result aggregation."""

from typing import Protocol, List, Dict, Any, runtime_checkable


@runtime_checkable
class ScoringInterface(Protocol):
    """
    Protocol for scoring engines that aggregate evidence into results.
    Separates the calculation logic from PaperProcessor's orchestration.
    """

    def calculate_goal_score(
        self, 
        goal: str, 
        scores: List[float], 
        evidence_types: List[str]
    ) -> Dict[str, Any]:
        """
        Calculate metrics for a single research goal.
        
        Args:
            goal: The research goal name
            scores: List of scores for hits in this goal
            evidence_types: List of evidence types found
            
        Returns:
            Dictionary with calculated metrics (e.g., max_score, average_score)
        """
        ...

    def calculate_overall_report(
        self, 
        goal_results: Dict[str, Any], 
        total_chunks: int,
        goals: List[str]
    ) -> Dict[str, Any]:
        """
        Calculate overall paper-level metrics.
        
        Args:
            goal_results: Dictionary of goal results
            total_chunks: Total number of chunks processed
            goals: List of expected goals
            
        Returns:
            Dictionary with overall metrics (e.g., overall_score, overall_confidence)
        """
        ...
