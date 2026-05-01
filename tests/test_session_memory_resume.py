from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_SRC = Path(__file__).resolve().parents[1] / "my-project" / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from session_memory import SessionMemory

pytestmark = pytest.mark.persistence_full

@pytest.mark.persistence_smoke
def test_session_memory_summary_includes_resume_metadata(tmp_path: Path) -> None:
    memory = SessionMemory("session_test", base_path=tmp_path)
    memory.add_turn(
        user_query="What is the key claim?",
        retrieved_chunks=[{"index": 1, "source": "paper.pdf", "content": "claim"}],
        context_metadata={
            "chunk_count": 1,
            "context_metadata": {
                "chunks": [{"index": 1, "source": "paper.pdf", "content": "claim"}],
                "truncated": False,
            },
        },
        llm_response="The key claim is grounded.",
        model_used="test-model",
        tokens_used={"prompt": 3, "completion": 4, "total": 7},
        tier_used="balanced",
    )

    summary = memory.get_session_summary()

    assert summary["session_id"] == "session_test"
    assert summary["total_turns"] == 1
    assert summary["total_tokens"] == 7
    assert summary["created_at"] is not None
    assert summary["updated_at"] is not None
    assert summary["preview"] == "What is the key claim?"


def test_session_memory_get_turns_returns_full_restore_payload(tmp_path: Path) -> None:
    memory = SessionMemory("session_restore", base_path=tmp_path)
    memory.add_turn(
        user_query="Find citation [chunk-1]",
        retrieved_chunks=[{"index": 1, "source": "paper.pdf", "content": "evidence"}],
        context_metadata={
            "chunk_count": 1,
            "context_metadata": {
                "chunks": [{"index": 1, "source": "paper.pdf", "content": "evidence"}],
                "truncated": False,
            },
        },
        llm_response="Citation is [chunk-1].",
        model_used="test-model",
        tokens_used={"prompt": 5, "completion": 6, "total": 11},
        tier_used="thorough",
    )

    turns = memory.get_turns(limit=10)

    assert len(turns) == 1
    assert turns[0]["turn_id"] == 1
    assert turns[0]["user_query"] == "Find citation [chunk-1]"
    assert turns[0]["retrieved_chunks"][0]["source"] == "paper.pdf"
    assert turns[0]["context_metadata"]["chunk_count"] == 1
    assert turns[0]["llm_response"] == "Citation is [chunk-1]."
    assert turns[0]["model"] == "test-model"
    assert turns[0]["tokens_used"]["total"] == 11
    assert turns[0]["tier"] == "thorough"
