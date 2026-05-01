import pytest
import main_rag_workflow
import json
from hashlib import sha256

@pytest.mark.asyncio
async def test_pipeline_貫通_ascii():
    def fake_gated_call(**kwargs):
        return json.dumps({"status": "success", "conclusion": "passed_ascii_test"})

    import main_rag_workflow
    from unittest.mock import MagicMock
    
    workflow = main_rag_workflow.RAGWorkflow(
        semantic_router=MagicMock(),
        llm_client=MagicMock(),
        api_key="test",
        enable_requests_fallback=False
    )
    
    # 模拟外部 gate_call 注入
    import sys
    import types
    m = MagicMock()
    m.gated_call = fake_gated_call
    sys.modules['model_call_gateway'] = m
    
    # 执行生成
    # 注意：这里主要验证逻辑流是否能跑到最后而不抛异常
    res = await workflow._generate_answer(
        user_query="test",
        focused_points=[],
        rag_evidence=[{"chunk_id": "c1", "text": "evidence"}],
        memory_hits=[]
    )
    
    data = json.loads(res)
    assert data["conclusion"] == "passed_ascii_test"
