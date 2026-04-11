# -*- coding: utf-8 -*-
"""Tests for pipeline observability and metrics integration."""

import pytest
from unittest.mock import MagicMock, patch
from modules.composite_observer import LoggingObserver, MetricsObserver, CompositeObserver
from recovery_metrics_exporter import reset_recovery_metrics_collector

@pytest.fixture
def clean_metrics():
    """Reset metrics before each test."""
    return reset_recovery_metrics_collector()

def test_metrics_observer_records_phases(clean_metrics):
    """Verify that MetricsObserver records phase durations as trace spans."""
    observer = MetricsObserver()
    pipeline_id = "test_pipe"
    
    observer.on_run_start(pipeline_id, {})
    observer.on_phase_start("extraction", pipeline_id)
    # Simulate work
    observer.on_phase_success("extraction", pipeline_id, {})
    
    snapshot = clean_metrics.snapshot()
    # MetricsObserver uses record_trace_span which increments trace_spans_total
    assert snapshot.trace_spans_total == 1

def test_composite_observer_broadcasting():
    """Verify that CompositeObserver broadcasts to all children."""
    obs1 = MagicMock()
    obs2 = MagicMock()
    composite = CompositeObserver([obs1, obs2])
    
    composite.on_phase_start("test", "id")
    obs1.on_phase_start.assert_called_once_with("test", "id")
    obs2.on_phase_start.assert_called_once_with("test", "id")

@patch("layers.e_layer_multimodal.full_extract")
@patch("layers.a_layer_agent_coordinator.infer_open_focus_points")
@patch("layers.r_layer_hybrid_retriever.hybrid_search")
@patch("layers.contracts.bind_evidence")
@patch("layers.g_layer_academic_generator.AcademicScorer.analyze_bound_data")
@patch("layers.k_layer_index_builder.KLayerManager.build_project_view")
@patch("layers.e_layer_multimodal.refine_multimodal_assets")
@patch("layers.p_layer_presentation_word.generate_docx_report")
def test_pipeline_triggers_observer(
    mock_docx, mock_refine, mock_k, mock_scoring, 
    mock_bind, mock_search, mock_focus, mock_extract
):
    # Import from the wrapper that supports the 00_ filename
    from integrated_pipeline import run_pipeline
    
    # Setup mocks
    mock_extract.return_value = {"chunks": []}
    mock_scoring.return_value = {"overall_score": 0.8}
    mock_refine.return_value = {"status": "ok"}
    
    observer = MagicMock()
    run_pipeline("test.pdf", "test goal", observer=observer)
    
    # Verify calls
    observer.on_run_start.assert_called()
    observer.on_phase_start.assert_any_call("extraction", "test")
    observer.on_phase_start.assert_any_call("retrieval", "test")
    observer.on_phase_start.assert_any_call("scoring", "test")
    from unittest.mock import ANY
    observer.on_phase_success.assert_any_call("presentation", "test", ANY)
    observer.on_run_success.assert_called()
