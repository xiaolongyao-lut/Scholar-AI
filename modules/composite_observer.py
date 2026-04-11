# -*- coding: utf-8 -*-
"""Concrete observers for logging and metrics."""

import logging
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from modules.pipeline_observer import PipelineObserver

logger = logging.getLogger("PipelineObserver")


class CompositeObserver:
    """Combines multiple observers into a single interface."""
    
    def __init__(self, observers: List[PipelineObserver]):
        self.observers = observers

    def on_run_start(self, pipeline_id: str, context: Dict[str, Any]):
        for obs in self.observers:
            try: obs.on_run_start(pipeline_id, context)
            except Exception as e: logger.error(f"Observer error: {e}")

    def on_phase_start(self, phase_name: str, pipeline_id: str):
        for obs in self.observers:
            try: obs.on_phase_start(phase_name, pipeline_id)
            except Exception as e: logger.error(f"Observer error: {e}")

    def on_phase_success(self, phase_name: str, pipeline_id: str, results: Dict[str, Any]):
        for obs in self.observers:
            try: obs.on_phase_success(phase_name, pipeline_id, results)
            except Exception as e: logger.error(f"Observer error: {e}")

    def on_run_success(self, pipeline_id: str, total_duration: float, summary: Dict[str, Any]):
        for obs in self.observers:
            try: obs.on_run_success(pipeline_id, total_duration, summary)
            except Exception as e: logger.error(f"Observer error: {e}")

    def on_error(self, pipeline_id: str, phase_name: Optional[str], error: Exception):
        for obs in self.observers:
            try: obs.on_error(pipeline_id, phase_name, error)
            except Exception as e: logger.error(f"Observer error: {e}")


class LoggingObserver:
    """Logs pipeline events to standard logging."""
    
    def on_run_start(self, pipeline_id: str, context: Dict[str, Any]):
        logger.info(f"Pipeline {pipeline_id} started. Context: {list(context.keys())}")

    def on_phase_start(self, phase_name: str, pipeline_id: str):
        logger.info(f"[{pipeline_id}] Starting phase: {phase_name}")

    def on_phase_success(self, phase_name: str, pipeline_id: str, results: Dict[str, Any]):
        logger.info(f"[{pipeline_id}] Phase {phase_name} succeeded.")

    def on_run_success(self, pipeline_id: str, total_duration: float, summary: Dict[str, Any]):
        logger.info(f"Pipeline {pipeline_id} completed successfully in {total_duration:.2f}s")

    def on_error(self, pipeline_id: str, phase_name: Optional[str], error: Exception):
        logger.error(f"Pipeline {pipeline_id} failed at phase {phase_name}: {error}")


class MetricsObserver:
    """Integrates with RecoveryMetricsCollector to export Prometheus metrics."""
    
    def __init__(self):
        from recovery_metrics_exporter import get_recovery_metrics_collector
        self.collector = get_recovery_metrics_collector()
        self._start_times: Dict[str, float] = {}

    def on_run_start(self, pipeline_id: str, context: Dict[str, Any]):
        self._start_times[f"{pipeline_id}_total"] = time.perf_counter()

    def on_phase_start(self, phase_name: str, pipeline_id: str):
        self._start_times[f"{pipeline_id}_{phase_name}"] = time.perf_counter()

    def on_phase_success(self, phase_name: str, pipeline_id: str, results: Dict[str, Any]):
        key = f"{pipeline_id}_{phase_name}"
        if key in self._start_times:
            duration = (time.perf_counter() - self._start_times.pop(key)) * 1000.0
            # Reuse trace span recording for phase durations
            self.collector.record_trace_span(f"pipeline.phase.{phase_name}", duration)

    def on_run_success(self, pipeline_id: str, total_duration: float, summary: Dict[str, Any]):
        self.collector.record_recovery_outcome(success=True)
        # Record total duration as a trace span
        self.collector.record_trace_span("pipeline.total", total_duration * 1000.0)

    def on_error(self, pipeline_id: str, phase_name: Optional[str], error: Exception):
        self.collector.record_recovery_outcome(success=False)
        self.collector.record_trace_span("pipeline.error", 0, error=True)
