# -*- coding: utf-8 -*-
"""Unit tests for the Scoring Plugin System."""

import pytest
from unittest.mock import MagicMock
from modules.scoring_registry import ScoringRegistry
from modules.scoring_interface import ScoringInterface
from modules.paper_processor import PaperProcessor, PaperGoalResult
from modules.container import ContainerBuilder

def test_scoring_registry_registration():
    """Verify that scorers can be registered and created."""
    @ScoringRegistry.register("mock_test_scorer")
    class MockScorer:
        def calculate_goal_score(self, goal, scores, ev_types):
            return {"max_score": 100.0}
        def calculate_overall_report(self, goal_results, total_chunks, goals):
            return {"overall_score": 100.0}

    scorer = ScoringRegistry.create("mock_test_scorer")
    assert isinstance(scorer, ScoringInterface)
    assert scorer.calculate_goal_score("test", [], [])["max_score"] == 100.0

def test_paper_processor_uses_injected_scorer():
    """Verify that PaperProcessor uses the injected scorer."""
    mock_scorer = MagicMock(spec=ScoringInterface)
    mock_scorer.calculate_goal_score.return_value = {"average_score": 9.9, "max_score": 10.0}
    mock_scorer.calculate_overall_report.return_value = {"overall_score": 0.88, "overall_confidence": 0.5}

    processor = PaperProcessor(scorer=mock_scorer)
    
    # Mock data with one chunk and one goal
    data = {"chunks": [{"text": "Target goal keywords present", "chunk_id": "c1", "page": 1}]}
    processor.config = MagicMock()
    processor.config.goal_mapping = {"goal1": ["target"]}
    processor.config.get_goal_keywords.return_value = ["target"]
    
    # Mock classifier to avoid actual classification
    processor.classifier = MagicMock()
    mock_score = MagicMock()
    mock_score.final_score = 10.0
    mock_score.evidence_type.value = "test"
    processor.classifier.classify_evidence.return_value = mock_score

    report = processor.process_data(data, "p1")
    
    # Assert scorer was called
    mock_scorer.calculate_goal_score.assert_called()
    mock_scorer.calculate_overall_report.assert_called()
    
    # Assert values from mock scorer are in report
    assert report.overall_score == 0.88
    assert report.goal_results["goal1"].average_score == 9.9

def test_container_injects_scorer():
    """Verify that the container correctly wires the scorer."""
    builder = ContainerBuilder()
    container = (
        builder.add_configuration()
        .add_classifier()
        .add_scorer()
        .add_processor()
        .build()
    )
    
    processor = container.get("processor")
    assert hasattr(processor, "scorer")
    assert processor.scorer.__class__.__name__ == "DefaultScorer"
