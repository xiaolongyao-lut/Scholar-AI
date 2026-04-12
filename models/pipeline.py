"""
Pipeline-related Pydantic models for REST API.

Includes models for pipeline execution, task management, and results.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class PipelineRequest(BaseModel):
    """Pipeline execution request payload."""

    input_path: str
    goal: str
    output_dir: str = "output"
    writing_language: str = "zh"
    writing_output_mode: str = "word"
    grounding_mode: str = "compatible"
    draft_scope: str = "full_paper"
    style_profile_path: Optional[str] = None
    enable_asset_pipeline: bool = False
    asset_markdown_path: Optional[str] = None
    screenshot_image_dir: Optional[str] = None
    render_backend: str = "default"
    experimental_renderer_script: Optional[str] = None
    include_association: bool = False
    association_mode: str = Field(default="no_ai", pattern="^(ai|no_ai)$")
    association_project_id: Optional[str] = None
    association_draft_id: Optional[str] = None
    association_section_id: Optional[str] = None
    association_query: Optional[str] = None
    association_use_memory: bool = True
    association_wing: Optional[str] = None
    association_room: Optional[str] = None
    association_memory_limit: int = Field(default=4, ge=1, le=12)


class PipelineTaskSubmitResponse(BaseModel):
    """Accepted response for async pipeline jobs."""

    task_id: str
    status: str


class PipelineTaskStatusResponse(BaseModel):
    """Status response for async pipeline jobs."""

    task_id: str
    status: str
    progress: float = 0.0
    stage: str = "queued"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
