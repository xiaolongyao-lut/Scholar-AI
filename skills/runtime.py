# -*- coding: utf-8 -*-
"""Skills runtime - Execution results and state management."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any
from enum import Enum
from uuid import uuid4

from datetime_utils import utc_now, utc_now_iso_z


class ExecutionStatus(str, Enum):
    """Execution result status."""
    SUCCESS = "success"
    PARTIAL = "partial"  # Partial success with warnings
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class SkillRunResult:
    """
    Immutable result from skill execution.
    
    Frozen dataclass ensures result integrity and prevents accidental mutations.
    Contains execution status, output, timing, and diagnostic information.
    """
    job_id: str
    skill_id: str
    status: ExecutionStatus
    input_text: str
    output_text: str = ""
    timestamp: str = field(default_factory=utc_now_iso_z)
    execution_time_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        data = asdict(self)
        # Convert enum to string
        data["status"] = self.status.value
        return data

    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == ExecutionStatus.SUCCESS

    def is_partial(self) -> bool:
        """Check if execution was partially successful."""
        return self.status == ExecutionStatus.PARTIAL

    def is_failed(self) -> bool:
        """Check if execution failed."""
        return self.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT, ExecutionStatus.CANCELLED)


class SkillTextTransformInput:
    """Typed input for text transformation operations."""

    def __init__(
        self,
        input_text: str,
        skill_id: str,
        job_id: str | None = None,
        scope: str | None = None,
        output_mode: str | None = None,
        parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.input_text = input_text
        self.skill_id = skill_id
        self.job_id = job_id or f"job_{uuid4().hex[:12]}"
        self.scope = scope or "section"
        self.output_mode = output_mode or "word_safe"
        self.parameters = parameters or {}
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "input_text": self.input_text,
            "skill_id": self.skill_id,
            "job_id": self.job_id,
            "scope": self.scope,
            "output_mode": self.output_mode,
            "parameters": self.parameters,
            "metadata": self.metadata,
        }


async def run_skill_text_transform(
    input_obj: SkillTextTransformInput,
    transform_fn: Any = None,
) -> SkillRunResult:
    """
    Execute a text transformation skill.
    
    Args:
        input_obj: Typed input for transformation
        transform_fn: Optional async function to perform transformation
    
    Returns:
        Immutable SkillRunResult with status and output
    """
    start_time = utc_now()

    try:
        # Execute transformation
        if transform_fn is None:
            # Default: echo transformation (identity function)
            output = input_obj.input_text
            warnings = ["Using default identity transformation"]
        else:
            output = await transform_fn(input_obj) if callable(transform_fn) else str(transform_fn)
            warnings = []

        end_time = utc_now()
        execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

        return SkillRunResult(
            job_id=input_obj.job_id,
            skill_id=input_obj.skill_id,
            status=ExecutionStatus.SUCCESS,
            input_text=input_obj.input_text,
            output_text=output,
            timestamp=utc_now_iso_z(),
            execution_time_ms=execution_time_ms,
            warnings=warnings,
            metadata=input_obj.metadata,
        )

    except TimeoutError:
        return SkillRunResult(
            job_id=input_obj.job_id,
            skill_id=input_obj.skill_id,
            status=ExecutionStatus.TIMEOUT,
            input_text=input_obj.input_text,
            output_text="",
            timestamp=utc_now_iso_z(),
            execution_time_ms=int((utc_now() - start_time).total_seconds() * 1000),
            warnings=["Skill execution timed out"],
            metadata=input_obj.metadata,
        )

    except Exception as exc:
        return SkillRunResult(
            job_id=input_obj.job_id,
            skill_id=input_obj.skill_id,
            status=ExecutionStatus.FAILED,
            input_text=input_obj.input_text,
            output_text="",
            timestamp=utc_now_iso_z(),
            execution_time_ms=int((utc_now() - start_time).total_seconds() * 1000),
            warnings=[f"Skill execution failed: {str(exc)}"],
            metadata=input_obj.metadata,
        )
