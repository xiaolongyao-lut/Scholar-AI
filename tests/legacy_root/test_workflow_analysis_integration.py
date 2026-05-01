# -*- coding: utf-8 -*-
"""
Test for RAGWorkflow Research Analysis Integration
"""

import unittest
from unittest.mock import MagicMock, AsyncMock
from main_rag_workflow import RAGWorkflow

class TestWorkflowAnalysisIntegration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Prepare mock local data
        self.mock_local_data = {
            "chunks": [
                {"text": "Laser power significantly affects nitrogen transport.", "source": "paper_a.pdf", "hybrid_score": 0.9},
            ]
        }

        # Mock Semantic Router to return deterministic points
        self.mock_router = MagicMock()
        self.mock_router.route_query = AsyncMock(return_value=["Nitrogen Transport", "Laser Power"])

        # Mock LLM Client
        self.mock_llm_client = MagicMock()
        self.mock_llm_client.post = AsyncMock()
        self.mock_llm_client.aclose = AsyncMock()

        # Mock LLM Response
        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 200
        mock_llm_response.json.return_value = {
            "choices": [{"message": {"content": "The laser power increases the temperature, which accelerates nitrogen transport."}}]
        }
        self.mock_llm_client.post.return_value = mock_llm_response

    async def test_association_bundle_is_enriched_with_analysis(self):
        """Verify that workflow association bundle picks up analysis payloads."""
        
        workflow = RAGWorkflow(
            semantic_router=self.mock_router,
            local_data=self.mock_local_data,
            api_key="test_key",
            llm_client=self.mock_llm_client,
            enable_requests_fallback=False
        )

        result = await workflow.ask_my_literature(
            "How does laser power affect nitrogen?",
            include_association=True,
            association_mode="no_ai"
        )

        bundle = result.association_bundle
        self.assertIsNotNone(bundle)
        # Should be true because focused_points and answer are valid
        self.assertTrue(bundle.get("analysis_enriched"), "Bundle should be marked as analysis_enriched")
        
        angles = bundle.get("association_angles", [])
        theme_angles = [a for a in angles if "analysis_theme" in a.get("angle_id", "")]
        self.assertTrue(len(theme_angles) > 0, "Should have angles derived from semantic themes")
        
        await workflow.close()

    async def test_no_ai_mode_seed_isolation(self):
        """Verify that no_ai mode does NOT use the LLM generated answer as seed."""
        # This requires mocking the underlying writing_resources call to see what seed was passed
        import writing_resources
        original_build = writing_resources.build_association_bundle_from_runtime_context
        
        mock_build = MagicMock(side_effect=original_build)
        writing_resources.build_association_bundle_from_runtime_context = mock_build
        
        try:
            workflow = RAGWorkflow(
                semantic_router=self.mock_router,
                local_data=self.mock_local_data,
                api_key="test_key",
                llm_client=self.mock_llm_client,
                enable_requests_fallback=False
            )

            mock_answer = "The laser power increases the temperature"
            
            await workflow.ask_my_literature(
                "Test query",
                include_association=True,
                association_mode="no_ai"
            )
            
            # Check the draft_seed argument passed to the mock
            # In _build_association_bundle, it's called via asyncio.to_thread
            # So we check the call arguments of the mock
            _, kwargs = mock_build.call_args
            passed_seed = kwargs.get('draft_seed')
            
            self.assertIsNotNone(passed_seed)
            self.assertNotIn(mock_answer, passed_seed, "no_ai seed should not contain LLM generated answer")
            self.assertIn("Test query", passed_seed, "no_ai seed should be grounded in the query")

            no_ai_payloads = getattr(workflow, "_collect_workflow_analysis_payloads")(
                user_query="Test query",
                focused_points=["Nitrogen Transport", "Laser Power"],
                generated_answer=mock_answer,
                association_mode="no_ai",
            )
            self.assertTrue(any(payload.get("semantic_themes") for payload in no_ai_payloads))
            self.assertFalse(
                any("reasoning_chain" in payload for payload in no_ai_payloads),
                "no_ai analysis payloads should not include generated-answer reasoning chains",
            )

            ai_payloads = getattr(workflow, "_collect_workflow_analysis_payloads")(
                user_query="Test query",
                focused_points=["Nitrogen Transport", "Laser Power"],
                generated_answer=mock_answer,
                association_mode="ai",
            )
            self.assertTrue(
                any("reasoning_chain" in payload for payload in ai_payloads),
                "ai analysis payloads should be allowed to include generated-answer reasoning chains",
            )
            
        finally:
            writing_resources.build_association_bundle_from_runtime_context = original_build
            await workflow.close()

    async def test_analysis_enriched_strict_logic(self):
        """Verify that analysis_enriched is False if payloads don't add actual value."""
        workflow = RAGWorkflow(
            semantic_router=self.mock_router,
            local_data=self.mock_local_data,
            api_key="test_key",
            llm_client=self.mock_llm_client,
            enable_requests_fallback=False
        )

        # Mock analysis payloads to be empty or useless
        setattr(workflow, "_collect_workflow_analysis_payloads", MagicMock(return_value=[{}, {"invalid": True}]))
        
        result = await workflow.ask_my_literature(
            "Test",
            include_association=True,
            association_mode="no_ai"
        )
        
        bundle = result.association_bundle
        self.assertFalse(bundle.get("analysis_enriched"), "Should be False when payloads add no value")
        
        await workflow.close()

    async def test_association_bundle_no_enrichment_if_no_points(self):
        """Verify that bundle is not enriched if no focused points or answer are available."""
        
        self.mock_router.route_query = AsyncMock(return_value=[])
        
        workflow = RAGWorkflow(
            semantic_router=self.mock_router,
            local_data=self.mock_local_data,
            api_key="test_key",
            llm_client=self.mock_llm_client,
            enable_requests_fallback=False
        )

        mock_llm_response = MagicMock()
        mock_llm_response.status_code = 500
        mock_llm_response.json.return_value = {"error": "failed"}
        self.mock_llm_client.post.return_value = mock_llm_response

        # With error answer and no points, _collect_workflow_analysis_payloads returns []
        result = await workflow.ask_my_literature(
            "Empty query",
            include_association=True
        )

        bundle = result.association_bundle
        if bundle:
            self.assertFalse(bundle.get("analysis_enriched"))

        await workflow.close()

if __name__ == "__main__":
    unittest.main()
