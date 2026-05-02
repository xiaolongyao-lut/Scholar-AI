"""Regression: ``_generate_answer`` persists ``output/last_answer.json``.

Asserts DoD §3.8.4 grep-based citation audit can find ``[chunk_id`` in
the persisted artifact.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from main_rag_workflow import RAGWorkflow


@pytest.fixture()
def isolated_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def workflow() -> RAGWorkflow:
    # router/adapter/local_data are not used by _generate_answer's persistence
    # path, so plain stubs suffice.
    return RAGWorkflow(
        semantic_router=object(),
        ragflow_adapter=None,
        local_data=None,
        api_key="test-key",
        llm_client=object(),  # avoid creating real httpx client
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_last_answer_json_written_with_chunk_ids(
    isolated_output: Path, workflow: RAGWorkflow
) -> None:
    rag_evidence = [
        {
            "chunk_id": "chunk_id_001",
            "material_id": "mat_a",
            "text": "Welding parameters affect porosity.",
            "score": 0.9,
        },
        {
            "chunk_id": "chunk_id_002",
            "material_id": "mat_b",
            "text": "Beam power correlates with penetration depth.",
            "score": 0.8,
        },
    ]
    fake_answer = (
        "Welding porosity is driven by gas entrapment [chunk_id_001]. "
        "Beam power affects penetration [chunk_id_002]."
    )

    with patch("main_rag_workflow.gated_call", return_value=fake_answer):
        result = asyncio.run(
            workflow._generate_answer(
                user_query="What drives porosity in laser welding?",
                focused_points=["porosity"],
                rag_evidence=rag_evidence,
                memory_hits=[],
            )
        )

    assert result == fake_answer
    out_file = isolated_output / "last_answer.json"
    assert out_file.exists(), "last_answer.json must be written"

    raw = out_file.read_text(encoding="utf-8")
    assert "[chunk_id" in raw, "DoD grep target [chunk_id must appear in artifact"

    data = json.loads(raw)
    assert data["answer"] == fake_answer
    assert data["query"] == "What drives porosity in laser welding?"
    assert "chunk_id_001" in data["chunk_ids"]
    assert "chunk_id_002" in data["chunk_ids"]
    assert data["evidence_refs"][0]["chunk_id"] == "chunk_id_001"
    assert data["evidence_refs"][0]["material_id"] == "mat_a"
    assert data["evidence_refs"][0]["text"] == "Welding parameters affect porosity."
    assert data["evidence_refs"][0]["score"] == 0.9
    assert data["model"]
    assert data["ts"].endswith("Z")
    assert "error" not in data


def test_last_answer_json_preserves_compressed_evidence_refs(
    isolated_output: Path, workflow: RAGWorkflow
) -> None:
    rag_evidence = [
        {
            "chunk_id": "chunk_id_003",
            "material_id": "mat_c",
            "text": "Full source text stays available.",
            "compressed_text": "Compressed traceable evidence.",
            "quote": "traceable evidence",
            "label": "relevant",
            "score": 0.77,
            "page": "5",
            "source_labels": ["dense", "rerank"],
        }
    ]

    with patch("main_rag_workflow.gated_call", return_value='{"status": "success"}'):
        asyncio.run(
            workflow._generate_answer(
                user_query="Q",
                focused_points=[],
                rag_evidence=rag_evidence,
                memory_hits=[],
            )
        )

    data = json.loads((isolated_output / "last_answer.json").read_text(encoding="utf-8"))
    assert data["evidence_refs"] == [
        {
            "chunk_id": "chunk_id_003",
            "material_id": "mat_c",
            "text": "Full source text stays available.",
            "compressed_text": "Compressed traceable evidence.",
            "quote": "traceable evidence",
            "label": "relevant",
            "score": 0.77,
            "page": 5,
            "source_labels": ["dense", "rerank"],
            "rank": 0,
        }
    ]


def test_last_answer_json_records_error_on_failure(
    isolated_output: Path, workflow: RAGWorkflow
) -> None:
    rag_evidence = [{"chunk_id": "c1", "material_id": "m", "text": "t", "score": 1.0}]

    def boom(*_a, **_kw):
        raise RuntimeError("HTTP 401 Unauthorized")

    with patch("main_rag_workflow.gated_call", side_effect=boom):
        result = asyncio.run(
            workflow._generate_answer(
                user_query="Q",
                focused_points=[],
                rag_evidence=rag_evidence,
                memory_hits=[],
            )
        )

    assert "生成失败" in result or "不可用" in result
    data = json.loads((isolated_output / "last_answer.json").read_text(encoding="utf-8"))
    assert data["answer"] == ""
    assert data["error"]
    assert "401" in data["error"]
    assert data["evidence_refs"][0]["chunk_id"] == "c1"
