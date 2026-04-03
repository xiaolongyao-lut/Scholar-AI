# -*- coding: utf-8 -*-
"""
Integration Test for RAGFlow + Fallback Retrieval (REST Version)
"""

import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from main_rag_workflow import RAGWorkflow, RAGResult
from layers.e_ragflow_retrieval_adapter import RAGFlowAdapter

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

if __name__ == "__main__":
    unittest.main()
