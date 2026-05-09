from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest

import rag_integration_entry


def test_serialize_rag_result_preserves_evidence_refs() -> None:
    result = SimpleNamespace(
        query="laser porosity",
        focused_points=["porosity"],
        memory_hits=[],
        rag_evidence=[
            {
                "chunk_id": "chunk-1",
                "text": "Evidence text.",
                "score": float("inf"),
            }
        ],
        evidence_refs=[
            {
                "chunk_id": "chunk-1",
                "material_id": "paper-a",
                "text": "Evidence text.",
                "score": 0.98,
                "source_labels": ["bm25", "dense"],
            }
        ],
        generated_answer='{"status": "success"}',
        confidence_score=0.91,
        trace={"step_3_generation": {"evidence_ref_count": 1}},
        association_bundle=None,
    )

    payload = rag_integration_entry._serialize_rag_result(result)

    assert payload["query"] == "laser porosity"
    assert payload["evidence_refs"] == [
        {
            "chunk_id": "chunk-1",
            "material_id": "paper-a",
            "text": "Evidence text.",
            "score": 0.98,
            "source_labels": ["bm25", "dense"],
        }
    ]
    assert payload["rag_evidence"] == [
        {
            "chunk_id": "chunk-1",
            "text": "Evidence text.",
            "score": "inf",
        }
    ]


@pytest.mark.asyncio
async def test_cmd_ask_json_output_includes_evidence_refs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _FakeWorkflow:
        def __init__(self, **_kwargs: Any) -> None:
            self.closed = False

        async def ask_my_literature(self, **kwargs: Any) -> SimpleNamespace:
            assert kwargs["user_query"] == "laser porosity"
            assert kwargs["dataset_ids"] == ["ds-1"]
            return SimpleNamespace(
                query=kwargs["user_query"],
                focused_points=["porosity"],
                memory_hits=[],
                rag_evidence=[{"chunk_id": "chunk-1", "text": "Evidence text."}],
                evidence_refs=[{"chunk_id": "chunk-1", "text": "Evidence text."}],
                generated_answer='{"status": "success"}',
                confidence_score=0.8,
                trace={"step_3_generation": {"evidence_ref_count": 1}},
                association_bundle=None,
            )

        async def close(self) -> None:
            self.closed = True

    fake_main_rag_workflow = SimpleNamespace(RAGWorkflow=_FakeWorkflow)
    monkeypatch.setitem(sys.modules, "main_rag_workflow", fake_main_rag_workflow)
    monkeypatch.setattr(rag_integration_entry, "_init_ragflow_adapter", lambda _cfg: None)

    await rag_integration_entry.cmd_ask(
        {"workflow": {"top_k_points": 1, "top_k_evidence": 1}, "ragflow": {}},
        "laser porosity",
        dataset_ids=["ds-1"],
        json_output=True,
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "laser porosity"
    assert payload["evidence_refs"] == [{"chunk_id": "chunk-1", "text": "Evidence text."}]
    assert payload["generated_answer"] == '{"status": "success"}'
