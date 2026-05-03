import pytest
import main_rag_workflow
import json
from hashlib import sha256
from unittest.mock import MagicMock, patch

@pytest.mark.asyncio
async def test_pipeline_通過_ascii():
    def fake_gated_call(**kwargs):
        return json.dumps({"status": "success", "conclusion": "passed_ascii_test"})

    workflow = main_rag_workflow.RAGWorkflow(
        semantic_router=MagicMock(),
        llm_client=MagicMock(),
        api_key="test",
        enable_requests_fallback=False
    )

    # Patch the already-bound name inside the main_rag_workflow module
    with patch.object(main_rag_workflow, "gated_call", side_effect=fake_gated_call):
        res = await workflow._generate_answer(
            user_query="test",
            focused_points=[],
            rag_evidence=[{"chunk_id": "c1", "text": "evidence"}],
            memory_hits=[]
        )

    data = json.loads(res)
    assert data["conclusion"] == "passed_ascii_test"
