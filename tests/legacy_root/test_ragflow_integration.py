# -*- coding: utf-8 -*-
"""
Integration Test for RAGFlow + Fallback Retrieval (REST Version)
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from main_rag_workflow import RAGWorkflow, RAGResult
from layers.e_ragflow_retrieval_adapter import RAGFlowAdapter


class _StubMemoryHit:
    """Deterministic MemPalace search hit for workflow tests."""

    def __init__(self, text, wing, room, source_file, similarity):
        self._payload = {
            "text": text,
            "wing": wing,
            "room": room,
            "source_file": source_file,
            "similarity": similarity,
        }

    def to_dict(self):
        return dict(self._payload)


class _StubMemorySearchResponse:
    """Typed-like response carrying deterministic memory hits."""

    def __init__(self, results, available=True):
        self.results = list(results)
        self.available = available


class _StubMemoryAdapter:
    """Simple adapter stub that returns the same response for every query."""

    def __init__(self, response):
        self._response = response

    def search(self, query, wing=None):
        return self._response


class _StubAssociationAIAdapter:
    """Deterministic AI enhancer used to validate workflow AI mode."""

    enabled = True

    def enhance_writing_association(self, **kwargs):
        related_signals = kwargs.get("related_signals", [])
        source_ids = [signal.get("source_id", "") for signal in related_signals[:2]]
        return {
            "association_angles": [
                {
                    "title": "AI workflow bridge",
                    "prompt": "Use the retrieved evidence and memory note to draft the next paragraph.",
                    "supporting_source_ids": source_ids,
                    "shared_terms": ["氮传输", "激光功率"],
                    "confidence": 0.93,
                }
            ],
            "continuation_prompts": [
                "Draft the next paragraph by connecting the retrieved evidence with the memory hit."
            ],
            "evidence_gaps": [
                {
                    "gap": "缺少对限制条件的明确句子",
                    "severity": "medium",
                    "recommendation": "补一条说明该结论适用边界的句子",
                }
            ],
            "recommended_memory_queries": ["氮传输 激光功率 限制条件"],
        }


class TestRAGFlowIntegration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # 准备模拟的本地数据
        self.mock_local_data = {
            "chunks": [
                {"text": "本地关于氮传输的研究结论...", "source": "local_paper_01.pdf", "hybrid_score": 0.8},
                {"text": "激光功率对熔池的影响分析...", "source": "local_paper_02.pdf", "hybrid_score": 0.7}
            ]
        }

        # 模拟语义路由器 - 使用 AsyncMock 支持 async/await
        self.mock_router = MagicMock()
        self.mock_router.route_query = AsyncMock(return_value=["氮传输", "激光功率"])

        # 模拟异步 LLM 客户端，避免测试访问真实外网
        self.mock_llm_client = MagicMock()
        self.mock_llm_client.post = AsyncMock()
        self.mock_llm_client.aclose = AsyncMock()

        # 环境变量模拟
        self.api_key = "test_siliconflow_key"

    @patch("requests.Session.post")
    async def test_ragflow_priority_success(self, mock_session_post):
        """测试 RAGFlow 检索成功时的优先级"""

        # 1. 配置 RAGFlow REST Mock
        mock_rag_response = MagicMock()
        mock_rag_response.status_code = 200
        mock_rag_response.json.return_value = {
            "code": 0,
            "data": {
                "chunks": [
                    {
                        "content": "来自 RAGFlow 的真实证据内容",
                        "document_keyword": "ragflow_doc.pdf",
                        "similarity": 0.95,
                        "vector_similarity": 0.93,
                        "term_similarity": 0.87,
                        "id": "chunk_001",
                        "document_id": "doc_001",
                        "chunk_index": 0
                    }
                ]
            }
        }

        # 2. 配置异步 LLM Mock
        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "基于 RAGFlow 证据生成的答案。"}}]
        }
        self.mock_llm_client.post.return_value = mock_llm_response

        # 仅 patch RAGFlow retrieval
        mock_session_post.return_value = mock_rag_response

        # 3. 初始化工作流
        adapter = RAGFlowAdapter(api_key="test_rag_key")
        workflow = RAGWorkflow(
            semantic_router=self.mock_router,
            ragflow_adapter=adapter,
            local_data=self.mock_local_data,
            api_key=self.api_key,
            llm_client=self.mock_llm_client,
            enable_requests_fallback=False
        )

        # 4. 执行查询
        result = await workflow.ask_my_literature(
            "测试查询", 
            dataset_ids=["dataset_001"]
        )

        # 5. 验证
        print(f"Evidence Source: {result.rag_evidence[0]['source']}")
        self.assertEqual(result.rag_evidence[0]['source'], "ragflow_doc.pdf")
        self.assertIn("RAGFlow", result.generated_answer)
        await workflow.close()

    @patch("requests.Session.post")
    async def test_fallback_to_local(self, mock_session_post):
        """测试 RAGFlow 失败时回退到本地检索"""

        # 1. 配置 RAGFlow Mock 失败
        mock_session_post.side_effect = Exception("Connection Timeout")

        # 2. 初始化工作流
        adapter = RAGFlowAdapter(api_key="test_rag_key")
        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "这是基于本地数据生成的答案。"}}]
        }
        self.mock_llm_client.post.return_value = mock_llm_response
        workflow = RAGWorkflow(
            semantic_router=self.mock_router,
            ragflow_adapter=adapter,
            local_data=self.mock_local_data,
            api_key=self.api_key,
            llm_client=self.mock_llm_client,
            enable_requests_fallback=False
        )

        # 3. 执行查询
        result = await workflow.ask_my_literature(
            "氮传输测试", 
            dataset_ids=["dataset_001"]
        )

        # 4. 验证
        print(f"Fallback Source: {result.rag_evidence[0]['source']}")
        self.assertEqual(result.rag_evidence[0]['source'], "local_paper_01.pdf")
        self.assertEqual(result.trace['step_2_rag_search']['evidence_count'], 2)
        await workflow.close()

    async def test_memory_hits_preserve_distinct_chunks_from_same_source(self):
        """长期记忆检索应保留同一源文件的不同片段，只去重完全重复的命中。"""

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "结合长期记忆和证据的答案。"}}]
        }
        self.mock_llm_client.post.return_value = mock_llm_response

        memory_hits = [
            _StubMemoryHit("相同源文件中的第一段记忆。", "wing_modular_pipeline", "runtime-jobs", "memory-a.md", 0.95),
            _StubMemoryHit("相同源文件中的第二段记忆。", "wing_modular_pipeline", "runtime-jobs", "memory-a.md", 0.91),
            _StubMemoryHit("相同源文件中的第一段记忆。", "wing_modular_pipeline", "runtime-jobs", "memory-a.md", 0.95),
        ]
        memory_adapter = _StubMemoryAdapter(_StubMemorySearchResponse(memory_hits))

        workflow = RAGWorkflow(
            semantic_router=self.mock_router,
            local_data=self.mock_local_data,
            api_key=self.api_key,
            llm_client=self.mock_llm_client,
            enable_requests_fallback=False,
            memory_adapter=memory_adapter,
            memory_wing="wing_modular_pipeline",
        )

        result = await workflow.ask_my_literature("测试长期记忆命中")

        self.assertEqual(len(result.memory_hits), 2)
        self.assertEqual(
            {hit["text"] for hit in result.memory_hits},
            {"相同源文件中的第一段记忆。", "相同源文件中的第二段记忆。"},
        )
        self.assertEqual(result.trace["step_0_memory"]["memory_hit_count"], 2)
        await workflow.close()

    async def test_association_bundle_defaults_to_no_ai_mode(self):
        """Workflow should expose a grounded no-AI association bundle when requested."""

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "这是基于本地数据生成的答案。"}}]
        }
        self.mock_llm_client.post.return_value = mock_llm_response

        workflow = RAGWorkflow(
            semantic_router=self.mock_router,
            local_data=self.mock_local_data,
            api_key=self.api_key,
            llm_client=self.mock_llm_client,
            enable_requests_fallback=False,
        )

        result = await workflow.ask_my_literature(
            "氮传输测试",
            include_association=True,
        )

        self.assertIsNotNone(result.association_bundle)
        self.assertEqual(result.association_bundle["mode"], "no_ai")
        self.assertFalse(result.association_bundle["ai_enhanced"])
        self.assertTrue(result.association_bundle["ephemeral_project"])
        self.assertTrue(result.association_bundle["related_signals"])
        await workflow.close()

    async def test_association_bundle_supports_ai_mode(self):
        """Workflow AI mode should enhance the association bundle while keeping evidence grounded."""

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "结合长期记忆和证据的答案。"}}]
        }
        self.mock_llm_client.post.return_value = mock_llm_response

        memory_hits = [
            _StubMemoryHit("关于氮传输限制条件的长期记忆。", "wing_modular_pipeline", "runtime-jobs", "memory-a.md", 0.95),
        ]
        memory_adapter = _StubMemoryAdapter(_StubMemorySearchResponse(memory_hits))

        workflow = RAGWorkflow(
            semantic_router=self.mock_router,
            local_data=self.mock_local_data,
            api_key=self.api_key,
            llm_client=self.mock_llm_client,
            enable_requests_fallback=False,
            memory_adapter=memory_adapter,
            association_ai_adapter=_StubAssociationAIAdapter(),
        )

        result = await workflow.ask_my_literature(
            "氮传输测试",
            include_association=True,
            association_mode="ai",
        )

        self.assertIsNotNone(result.association_bundle)
        self.assertEqual(result.association_bundle["mode"], "ai")
        self.assertTrue(result.association_bundle["ai_enhanced"])
        self.assertEqual(result.association_bundle["association_angles"][0]["title"], "AI workflow bridge")
        self.assertTrue(
            any(signal["source_type"] == "retrieval" for signal in result.association_bundle["related_signals"])
        )
        await workflow.close()

if __name__ == "__main__":
    unittest.main()
