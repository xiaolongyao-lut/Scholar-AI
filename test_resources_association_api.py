# -*- coding: utf-8 -*-
"""FastAPI tests for associative-writing resource endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:  # pragma: no cover - environment-dependent guard
    HAS_FASTAPI = False
    FastAPI = None
    TestClient = None

from writing_resources import ContentType, WritingResourceStore


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestWritingAssociationAPI:
    """Validate the association endpoint against the real FastAPI app."""

    @pytest.fixture
    def client_and_context(self):
        """Create a test client with a fresh store and stub memory adapter."""
        from routers import resources_router

        store = WritingResourceStore()
        project = store.create_project(
            title="Association API Project",
            description="Validate memory-backed writing associations.",
            content_type=ContentType.ACADEMIC,
        )
        section = store.create_section(
            project.project_id,
            title="Literature Review",
            order=1,
            description="Cover contextual retrieval and linked drafting evidence.",
        )
        draft = store.create_draft(
            project.project_id,
            section_id=section.section_id,
            title="Review Draft",
            content="Contextual retrieval supports better literature review transitions.",
        )
        store.create_draft(
            project.project_id,
            title="Method Draft",
            content="Graph-based retrieval exposes complementary evidence paths.",
        )

        @dataclass(frozen=True)
        class StubMemoryHit:
            """Minimal memory hit compatible with router normalization."""

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
            """Stable response wrapper used by the route."""

            available: bool
            results: list[StubMemoryHit]

        class StubMemoryAdapter:
            """Memory adapter stub that returns one relevant hit."""

            def search(
                self,
                query: str,
                wing: str | None = None,
                room: str | None = None,
                limit: int | None = None,
            ) -> StubMemoryResponse:
                assert query
                return StubMemoryResponse(
                    available=True,
                    results=[
                        StubMemoryHit(
                            text="Long-term notes link contextual retrieval with smoother review transitions.",
                            wing=wing or "writing",
                            room=room or "associations",
                            source_file="notes.md",
                            similarity=0.91,
                        )
                    ][: limit or 1],
                )

        with patch.object(resources_router, "get_writing_resource_store", return_value=store), patch.object(
            resources_router, "get_memory_adapter", return_value=StubMemoryAdapter()
        ):
            app = FastAPI()
            app.include_router(resources_router.router)
            client = TestClient(app)
            yield client, project, section, draft

    def test_association_endpoint_returns_memory_backed_bundle(self, client_and_context):
        """Endpoint should combine project context with memory hits."""
        client, project, section, draft = client_and_context

        response = client.post(
            "/resources/association",
            json={
                "project_id": project.project_id,
                "query": "contextual retrieval transitions",
                "section_id": section.section_id,
                "draft_id": draft.draft_id,
                "use_memory": True,
                "memory_limit": 2,
                "signal_limit": 5,
                "angle_limit": 3,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["project_id"] == project.project_id
        assert payload["mode"] == "no_ai"
        assert payload["ai_enhanced"] is False
        assert payload["memory_used"] is True
        assert payload["memory_hit_count"] == 1
        assert payload["related_signals"]
        assert any(signal["source_type"] == "memory" for signal in payload["related_signals"])
        assert payload["association_angles"]
        assert payload["continuation_prompts"]

    def test_association_endpoint_supports_ai_mode_and_retrieval_hits(self, client_and_context):
        """AI mode should enhance prompts while preserving grounded retrieval evidence."""
        client, project, section, draft = client_and_context

        class StubAssociationAIAdapter:
            enabled = True

            def enhance_writing_association(self, **_: object) -> dict[str, object]:
                return {
                    "association_angles": [
                        {
                            "title": "AI bridge",
                            "prompt": "Use the retrieved experiment and long-term note to build a transition paragraph.",
                            "supporting_source_ids": ["rag_doc_1", "notes.md"],
                            "shared_terms": ["contextual", "retrieval"],
                            "confidence": 0.92,
                        }
                    ],
                    "continuation_prompts": [
                        "Write the next paragraph by contrasting the retrieved experiment with the memory note."
                    ],
                    "evidence_gaps": [
                        {
                            "gap": "The paragraph still lacks a direct limitation statement.",
                            "severity": "medium",
                            "recommendation": "Add one sentence clarifying the retrieval boundary.",
                        }
                    ],
                    "recommended_memory_queries": [
                        "contextual retrieval limitation transition"
                    ],
                }

        from routers import resources_router

        with patch.object(resources_router, "get_ai_adapter", return_value=StubAssociationAIAdapter()):
            response = client.post(
                "/resources/association",
                json={
                    "project_id": project.project_id,
                    "query": "contextual retrieval transitions",
                    "section_id": section.section_id,
                    "draft_id": draft.draft_id,
                    "mode": "ai",
                    "use_memory": True,
                    "retrieval_hits": [
                        {
                            "id": "rag_doc_1",
                            "text": "Retrieved evidence shows transition sentences improve grounded literature synthesis.",
                            "source": "ragflow_contextual.md",
                            "score": 0.88,
                        }
                    ],
                    "memory_limit": 2,
                    "signal_limit": 5,
                    "angle_limit": 3,
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "ai"
        assert payload["ai_enhanced"] is True
        assert any(signal["source_type"] == "retrieval" for signal in payload["related_signals"])
        assert payload["association_angles"][0]["title"] == "AI bridge"
        assert payload["continuation_prompts"][0].startswith("Write the next paragraph")
        assert payload["recommended_memory_queries"] == ["contextual retrieval limitation transition"]

    def test_association_endpoint_rejects_missing_project(self, client_and_context):
        """Endpoint should return 404 when the project does not exist."""
        client, _, _, _ = client_and_context

        response = client.post(
            "/resources/association",
            json={
                "project_id": "missing_project",
                "query": "contextual retrieval transitions",
            },
        )

        assert response.status_code == 404
