# -*- coding: utf-8 -*-
"""Pipeline Observer Module - Defines hooks for pipeline execution monitoring."""

from typing import Protocol, Any, Dict, Optional, runtime_checkable
from datetime import datetime


@runtime_checkable
class PipelineObserver(Protocol):
    """
    Interface for objects that observe pipeline execution events.
    Enables decoupled logging, metrics, and telemetry.
    """

    def on_run_start(self, pipeline_id: str, context: Dict[str, Any]):
        """Called when a new pipeline run begins."""
        ...

    def on_phase_start(self, phase_name: str, pipeline_id: str):
        """Called when a specific phase starts."""
        ...

    def on_phase_success(self, phase_name: str, pipeline_id: str, results: Dict[str, Any]):
        """Called when a phase completes successfully."""
        ...

    def on_run_success(self, pipeline_id: str, total_duration: float, summary: Dict[str, Any]):
        """Called when the entire pipeline run succeeds."""
        ...

    def on_error(self, pipeline_id: str, phase_name: Optional[str], error: Exception):
        """Called when an error occurs during execution."""
        ...
