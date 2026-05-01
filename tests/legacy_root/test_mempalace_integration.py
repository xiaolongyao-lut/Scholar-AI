# -*- coding: utf-8 -*-
"""Regression tests for the MemPalace integration layer."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from harness_protocols import (
    ArtifactType,
    EventType,
    JobKind,
    SessionMode,
    WritingArtifact,
    WritingEvent,
    WritingJob,
    WritingSession,
)
from layers.m_layer_mempalace_memory import MempalaceMemoryAdapter, MempalaceSettings
from writing_runtime import WritingRuntime


class _FakeAdapter:
    """Minimal sync adapter for runtime tests."""

    class _Settings:
        auto_sync_runtime_jobs = True

    def __init__(self) -> None:
        self.settings = self._Settings()
        self.calls: list[dict[str, str]] = []

    def sync_runtime_job(self, job, session, artifacts, events, *, wing=None, room=None):
        self.calls.append(
            {
                "job_id": job.job_id,
                "session_id": session.session_id if session else "",
                "wing": wing or "",
                "room": room or "",
                "artifact_count": str(len(artifacts)),
                "event_count": str(len(events)),
            }
        )

        class _Result:
            def to_dict(self_inner):
                return {
                    "success": True,
                    "available": True,
                    "wing": wing or "wing_test",
                    "room": room or "runtime-jobs-prompt-action",
                    "drawer_id": "drawer_test",
                    "duplicate": False,
                    "reason": None,
                }

        return _Result()


class MempalaceIntegrationTests(unittest.TestCase):
    """Cover the adapter layer and runtime auto-sync behavior."""

    def test_compose_runtime_memory_content_contains_context(self) -> None:
        settings = MempalaceSettings(
            enabled=True,
            vendor_repo_path=Path("."),
            palace_path=Path("."),
            collection_name="mempalace_drawers",
            default_wing="wing_modular_pipeline",
            default_room="runtime-jobs",
            search_limit=3,
            max_content_chars=4000,
            auto_sync_runtime_jobs=True,
        )
        adapter = MempalaceMemoryAdapter(settings)
        session = WritingSession.create(
            mode=SessionMode.HYBRID,
            user_id="user_demo",
            settings={"mempalace_wing": "wing_custom_project"},
            tags=["memory", "test"],
        )
        job = WritingJob.create(
            session_id=session.session_id,
            kind=JobKind.SKILL_ACTION,
            input_text="请整合历史决策与当前文献证据。",
            action_id="action_integrate_memory",
            skill_id="skill.memory.merge",
            scope="full_draft",
            output_mode="plain",
            tags=["memory"],
        )
        artifact = WritingArtifact.create(
            job_id=job.job_id,
            session_id=session.session_id,
            artifact_type=ArtifactType.TRANSFORMED_TEXT,
            content="这是整合后的写作输出。",
            created_by="system",
        )
        event = WritingEvent.create(
            job_id=job.job_id,
            session_id=session.session_id,
            event_type=EventType.JOB_COMPLETED,
            data={"result_artifact_count": 1},
        )

        content = adapter.compose_runtime_memory_content(job, session, [artifact], [event])

        self.assertIn("Runtime Job Memory", content)
        self.assertIn("skill.memory.merge", content)
        self.assertIn("wing_custom_project", content)
        self.assertIn("这是整合后的写作输出。", content)

    def test_runtime_auto_sync_uses_adapter_on_completion(self) -> None:
        runtime = WritingRuntime()
        fake_adapter = _FakeAdapter()
        runtime._memory_adapter = fake_adapter
        runtime._memory_adapter_resolved = True

        session = runtime.create_session(
            mode=SessionMode.PROMPT,
            user_id="user_demo",
            settings={"mempalace_wing": "wing_runtime_test"},
            tags=["memory"],
        )
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
            input_text="记录这次重构结论。",
            action_id="action_record_memory",
            scope="section",
            output_mode="plain",
            tags=["memory"],
        )

        asyncio.run(runtime.complete_job(job.job_id, result="重构完成，记忆已同步。"))

        self.assertEqual(len(fake_adapter.calls), 1)
        self.assertEqual(fake_adapter.calls[0]["job_id"], job.job_id)
        self.assertEqual(fake_adapter.calls[0]["artifact_count"], "1")
        self.assertGreaterEqual(int(fake_adapter.calls[0]["event_count"]), 1)

    def test_runtime_manual_sync_raises_for_unknown_job(self) -> None:
        runtime = WritingRuntime()
        with self.assertRaises(ValueError):
            runtime.sync_job_to_memory("job_missing")


if __name__ == "__main__":
    unittest.main()
