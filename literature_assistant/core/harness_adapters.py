# -*- coding: utf-8 -*-
"""
Harness Adapters - Compatibility layer for legacy action calls.

Provides translation between existing action-based APIs and the new protocol layer,
ensuring backward compatibility while gradually migrating to protocol-first design.
"""

from __future__ import annotations

from typing import Any
from harness_protocols import (
    SessionMode,
    JobKind,
    WritingSession,
    WritingJob,
    WritingEvent,
    WritingArtifact,
    EventType,
    ArtifactType,
)
from skills.runtime import SkillRunResult, ExecutionStatus


class LegacyActionAdapter:
    """
    Adapts legacy action call patterns to the new protocol.
    
    Maps between:
    - Old: RunActionRequest -> SkillRunResultPayload
    - New: WritingJob -> WritingEvent -> WritingArtifact
    """

    @staticmethod
    def action_to_job(
        session_id: str,
        action_id: str,
        input_text: str,
        scope: str | None = None,
        output_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingJob:
        """
        Convert a legacy action request to a WritingJob.
        
        Args:
            session_id: Parent session ID
            action_id: Legacy action ID (e.g., "zh_to_en_translate")
            input_text: Text to transform
            scope: Scope of transformation ('selection', 'section', 'full_draft')
            output_mode: Output format ('latex', 'word_safe', 'plain')
            metadata: Optional metadata dict
        
        Returns:
            WritingJob with legacy action mapped to skill/action_id references
        """
        return WritingJob.create(
            session_id=session_id,
            kind=JobKind.SKILL_ACTION,
            input_text=input_text,
            action_id=action_id,  # Keep reference to legacy action
            skill_id=None,  # Will be resolved by service layer
            scope=scope or "section",
            output_mode=output_mode or "word_safe",
            metadata=metadata or {},
        )

    @staticmethod
    def skill_run_to_artifact(
        job_id: str,
        session_id: str,
        skill_run_result: SkillRunResult,
    ) -> WritingArtifact:
        """
        Convert a SkillRunResult to a WritingArtifact.
        
        Args:
            job_id: Associated job ID
            session_id: Associated session ID
            skill_run_result: Skill execution result
        
        Returns:
            WritingArtifact containing the transformed text
        """
        artifact_type = (
            ArtifactType.TRANSFORMED_TEXT
            if skill_run_result.is_success()
            else ArtifactType.AUDIT_RECORD
        )

        content = {
            "output_text": skill_run_result.output_text,
            "status": skill_run_result.status.value,
            "execution_time_ms": skill_run_result.execution_time_ms,
        } if skill_run_result.is_success() else {
            "error": f"Skill execution failed: {skill_run_result.warnings}",
            "input_text": skill_run_result.input_text,
        }

        return WritingArtifact.create(
            job_id=job_id,
            session_id=session_id,
            artifact_type=artifact_type,
            content=content,
            created_by=skill_run_result.skill_id,
            metadata={
                "execution_time_ms": skill_run_result.execution_time_ms,
                "warnings": skill_run_result.warnings,
                **skill_run_result.metadata
            },
            mime_type="application/json",
        )

    @staticmethod
    def event_from_skill_run(
        job_id: str,
        session_id: str,
        skill_run_result: SkillRunResult,
    ) -> WritingEvent:
        """
        Create a protocol event from skill execution result.
        
        Args:
            job_id: Associated job ID
            session_id: Associated session ID
            skill_run_result: Skill execution result
        
        Returns:
            WritingEvent capturing the execution completion
        """
        event_type = (
            EventType.ARTIFACT_CREATED
            if skill_run_result.is_success()
            else EventType.JOB_FAILED
        )

        return WritingEvent.create(
            job_id=job_id,
            session_id=session_id,
            event_type=event_type,
            data={
                "status": skill_run_result.status.value,
                "output_text": skill_run_result.output_text[:200],  # Preview
                "execution_time_ms": skill_run_result.execution_time_ms,
            },
            metadata={
                "skill_id": skill_run_result.skill_id,
                "warnings": skill_run_result.warnings,
            },
        )


class PipelineActionAdapter:
    """
    Adapts pipeline execution patterns to the protocol.
    
    Maps between PipelineRequest and WritingJob with pipeline semantics.
    """

    @staticmethod
    def pipeline_request_to_job(
        session_id: str,
        goal: str,
        input_path: str,
        metadata: dict[str, Any] | None = None,
    ) -> WritingJob:
        """
        Convert a pipeline execution request to a WritingJob.
        
        Args:
            session_id: Parent session ID
            goal: Pipeline execution goal
            input_path: Input document path
            metadata: Pipeline configuration metadata
        
        Returns:
            WritingJob representing the pipeline run
        """
        return WritingJob.create(
            session_id=session_id,
            kind=JobKind.PIPELINE_RUN,
            input_text=input_path,  # Input is the file path
            metadata={
                "goal": goal,
                "pipeline_version": "40.0",
                **(metadata or {}),
            },
        )


class SessionContextAdapter:
    """
    Manages session context for dual-track architecture.
    """

    def __init__(self):
        """Initialize session context adapter."""
        self._sessions: dict[str, WritingSession] = {}
        self._default_session: WritingSession | None = None

    def create_or_get_session(
        self,
        mode: SessionMode,
        user_id: str | None = None,
        force_new: bool = False,
    ) -> WritingSession:
        """
        Get or create a session for the given mode.
        
        Args:
            mode: SessionMode.PROMPT or SessionMode.SKILL
            user_id: Optional user ID
            force_new: Force creation of new session
        
        Returns:
            WritingSession (existing or newly created)
        """
        if not force_new and self._default_session and self._default_session.mode == mode:
            return self._default_session

        session = WritingSession.create(
            mode=mode,
            user_id=user_id,
            tags=[f"mode:{mode.value}"],
        )
        self._sessions[session.session_id] = session
        self._default_session = session
        return session

    def get_session(self, session_id: str) -> WritingSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[WritingSession]:
        """List all active sessions."""
        return list(self._sessions.values())

    def clear_sessions(self) -> None:
        """Clear all sessions (for process restart)."""
        self._sessions.clear()
        self._default_session = None
