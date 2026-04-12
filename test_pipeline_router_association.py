# -*- coding: utf-8 -*-
"""Pipeline router tests for optional association bundle output."""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:  # pragma: no cover - environment dependent
    HAS_FASTAPI = False
    FastAPI = None
    TestClient = None


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestPipelineAssociationRouter:
    """Validate pipeline association enrichment without touching the core pipeline."""

    @staticmethod
    def _write_pipeline_artifacts(root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        with open(root / "02_hybrid_retrieval.json", "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "status": "hybrid_retrieval_ready",
                    "focus_points": ["contextual retrieval", "transition writing"],
                    "top_chunks": [
                        {
                            "id": "chunk_1",
                            "text": "Retrieved evidence shows contextual retrieval improves transition quality.",
                            "source": "paper_a.pdf",
                            "hybrid_score": 0.88,
                        },
                        {
                            "id": "chunk_2",
                            "text": "A second study links retrieval grounding with literature review coherence.",
                            "source": "paper_b.pdf",
                            "hybrid_score": 0.79,
                        },
                    ],
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        with open(root / "03_academic_scoring.json", "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "scoring": {
                        "selected_writing_points": [
                            {
                                "writing_point_id": "wp001",
                                "claim": "Grounded retrieval improves transition quality when evidence is explicit.",
                                "point_type": "discussion",
                                "relevance_score": 0.91,
                                "goal_hits": ["grounded retrieval", "transition quality"],
                            }
                        ],
                        "semantic_themes": [
                            {
                                "theme_title": "Grounding",
                                "summary": "Grounded retrieval helps structure the review bridge and bound claims.",
                                "writing_points": [],
                            }
                        ],
                    },
                    "view": {},
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        with open(root / "04_reasoning_chain.json", "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "query": "improve literature review transitions",
                    "final_conclusion": "Transition claims should be bounded by explicit evidence and limitations.",
                    "conflicts": [
                        {
                            "severity_level": 3,
                            "type": "DIRECT_CONFLICT",
                            "interpretation": (
                                "One study reports stronger transitions, while another only supports the claim "
                                "when explicit grounding is present."
                            ),
                            "authority_summary": "paper_a.pdf and paper_b.pdf disagree on the required grounding strength.",
                            "resolution_path": [
                                "State whether the cited evidence is explicit or implied.",
                                "Compare the grounding condition before claiming improvement.",
                            ],
                            "claims_involved": [
                                {
                                    "subject": "transition quality",
                                    "predicate": "improves",
                                    "object": "literature review coherence",
                                },
                                {
                                    "subject": "transition quality",
                                    "predicate": "depends on",
                                    "object": "grounding clarity",
                                },
                            ],
                        }
                    ],
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )

    @pytest.fixture
    def client_and_output_dir(self):
        from routers import pipeline_router

        temp_dir = tempfile.TemporaryDirectory()
        output_dir = Path(temp_dir.name) / "demo_doc"
        self._write_pipeline_artifacts(output_dir)

        @dataclass(frozen=True)
        class StubMemoryHit:
            text: str
            wing: str
            room: str
            source_file: str
            similarity: float

            def to_dict(self) -> dict[str, object]:
                return {
                    "text": self.text,
                    "wing": self.wing,
                    "room": self.room,
                    "source_file": self.source_file,
                    "similarity": self.similarity,
                }

        @dataclass(frozen=True)
        class StubMemoryResponse:
            available: bool
            results: list[StubMemoryHit]

        class StubMemoryAdapter:
            def search(self, **_: object) -> StubMemoryResponse:
                return StubMemoryResponse(
                    available=True,
                    results=[
                        StubMemoryHit(
                            text="Long-term notes connect grounded retrieval with smoother section transitions.",
                            wing="writing",
                            room="associations",
                            source_file="notes.md",
                            similarity=0.91,
                        )
                    ],
                )

        class StubAssociationAIAdapter:
            enabled = True

            def enhance_writing_association(self, **_: object) -> dict[str, object]:
                return {
                    "association_angles": [
                        {
                            "title": "Pipeline AI bridge",
                            "prompt": "Use the retrieved studies and the memory note to draft the next section bridge.",
                            "supporting_source_ids": ["chunk_1", "notes.md"],
                            "shared_terms": ["contextual", "retrieval"],
                            "confidence": 0.94,
                        }
                    ],
                    "continuation_prompts": [
                        "Draft the next paragraph by combining the two retrieved studies with the memory note."
                    ],
                    "evidence_gaps": [
                        {
                            "gap": "The section still lacks an explicit limitation statement.",
                            "severity": "medium",
                            "recommendation": "Add one sentence explaining where retrieval grounding may fail.",
                        }
                    ],
                    "recommended_memory_queries": [
                        "contextual retrieval limitation writing transition"
                    ],
                }

        def stub_run_pipeline_core(request):
            return {
                "status": "success",
                "output_dir": str(output_dir),
                "docx": str(output_dir / "demo_doc_report.docx"),
                "duration": 1.23,
            }

        app = FastAPI()
        app.include_router(pipeline_router.router)
        with patch.object(pipeline_router, "_run_pipeline_core", side_effect=stub_run_pipeline_core), patch.object(
            pipeline_router,
            "_resolve_pipeline_memory_hits",
            return_value=StubMemoryAdapter().search().results[0:1] and [StubMemoryAdapter().search().results[0].to_dict()],
        ), patch.object(
            pipeline_router,
            "_resolve_pipeline_ai_adapter",
            return_value=StubAssociationAIAdapter(),
        ):
            client = TestClient(app)
            yield client, output_dir

        temp_dir.cleanup()

    def test_pipeline_run_returns_no_ai_association_bundle(self, client_and_output_dir):
        """Synchronous pipeline result should include a deterministic no-AI bundle when requested."""
        client, _ = client_and_output_dir

        response = client.post(
            "/run",
            json={
                "input_path": "demo.pdf",
                "goal": "improve literature review transitions",
                "include_association": True,
                "association_mode": "no_ai",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "success"
        assert payload["association_bundle"]["mode"] == "no_ai"
        assert payload["association_bundle"]["ai_enhanced"] is False
        assert payload["association_bundle"]["source"] == "pipeline"
        assert payload["association_bundle"]["analysis_enriched"] is True
        assert payload["association_bundle"]["related_signals"]
        assert any(
            gap["gap"] == "Conflicting evidence around 'transition quality' is not yet resolved"
            for gap in payload["association_bundle"]["evidence_gaps"]
        )
        assert any(
            angle["title"] == "Resolve conflict on 'transition quality'"
            for angle in payload["association_bundle"]["association_angles"]
        )

    def test_pipeline_run_returns_ai_association_bundle(self, client_and_output_dir):
        """Synchronous pipeline result should include AI-enhanced association output in AI mode."""
        client, _ = client_and_output_dir

        response = client.post(
            "/run",
            json={
                "input_path": "demo.pdf",
                "goal": "improve literature review transitions",
                "include_association": True,
                "association_mode": "ai",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["association_bundle"]["mode"] == "ai"
        assert payload["association_bundle"]["ai_enhanced"] is True
        assert payload["association_bundle"]["association_angles"][0]["title"] == "Pipeline AI bridge"

    def test_pipeline_async_task_persists_association_bundle(self, client_and_output_dir):
        """Async task storage should persist the same association bundle after completion."""
        _, _ = client_and_output_dir
        from models import PipelineRequest, TaskState
        from routers import pipeline_router

        task_id = "async_assoc_task"
        request = PipelineRequest(
            input_path="demo.pdf",
            goal="improve literature review transitions",
            include_association=True,
            association_mode="no_ai",
        )

        async def run_test() -> dict[str, object]:
            async with pipeline_router.TASKS_LOCK:
                pipeline_router.TASKS[task_id] = {
                    "status": TaskState.queued.value,
                    "progress": 0.0,
                    "stage": "queued",
                    "result": None,
                    "error": None,
                    "updated_at": pipeline_router._now_ts(),
                }

            await pipeline_router._run_pipeline_async(task_id, request)
            async with pipeline_router.TASKS_LOCK:
                return dict(pipeline_router.TASKS[task_id])

        payload = asyncio.run(run_test())
        assert payload["status"] == "succeeded"
        assert payload["result"]["association_bundle"]["mode"] == "no_ai"

    def test_pipeline_analysis_enriched_strict_logic(self, client_and_output_dir):
        """Verify that analysis_enriched is False if analysis payloads provide no increment."""
        client, output_dir = client_and_output_dir
        
        # Overwrite a payload to be empty/useless
        with open(output_dir / "03_academic_scoring.json", "w", encoding="utf-8") as handle:
            json.dump({}, handle)
        with open(output_dir / "04_reasoning_chain.json", "w", encoding="utf-8") as handle:
            json.dump({"nothing": "here"}, handle)

        response = client.post(
            "/run",
            json={
                "input_path": "demo.pdf",
                "goal": "improve literature review transitions",
                "include_association": True,
                "association_mode": "no_ai",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        bundle = payload["association_bundle"]
        
        # If payload is present but yields no extra angles/gaps, analysis_enriched should be False
        assert bundle["analysis_enriched"] is False, "Should be False if no actionable increments were found"
