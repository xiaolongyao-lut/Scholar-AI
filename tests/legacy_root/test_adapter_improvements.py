#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Comprehensive test suite for RAGFlow Adapter v1.5 improvements.
Demonstrates all fixes and optimizations.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import requests
import logging

from layers.e_ragflow_retrieval_adapter import RAGFlowAdapter


class TestBooleanTypeValidation(unittest.TestCase):
    """Test improvements for boolean type misjudgment fix."""

    def test_top_k_rejects_boolean(self):
        """Boolean values should be rejected for top_k."""
        with patch.dict('os.environ', {'RAGFLOW_API_KEY': 'test_key', 'RAGFLOW_BASE_URL': 'https://test.com'}):
            adapter = RAGFlowAdapter(api_key='test_key', base_url='https://test.com')

            with self.assertRaises(ValueError) as ctx:
                adapter._validate_parameters(
                    question="test",
                    dataset_ids=["test"],
                    top_k=True,  # Boolean!
                    similarity_threshold=0.5,
                    vector_similarity_weight=0.5
                )
            self.assertIn("not a boolean", str(ctx.exception))

    def test_similarity_threshold_rejects_boolean(self):
        """Boolean values should be rejected for similarity_threshold."""
        with patch.dict('os.environ', {'RAGFLOW_API_KEY': 'test_key'}):
            adapter = RAGFlowAdapter(api_key='test_key', base_url='https://test.com')

            with self.assertRaises(ValueError) as ctx:
                adapter._validate_parameters(
                    question="test",
                    dataset_ids=["test"],
                    top_k=10,
                    similarity_threshold=False,  # Boolean!
                    vector_similarity_weight=0.5
                )
            self.assertIn("not a boolean", str(ctx.exception))


class TestStringParameterValidation(unittest.TestCase):
    """Test improvements for optional string parameter validation."""

    def test_keyword_rejects_integer(self):
        """Keyword parameter should reject integer types."""
        with self.assertRaises(TypeError) as ctx:
            RAGFlowAdapter._validate_string_param(123, "keyword")
        self.assertIn("must be a string", str(ctx.exception))

    def test_keyword_accepts_string(self):
        """Keyword parameter should accept valid strings."""
        result = RAGFlowAdapter._validate_string_param("test_keyword", "keyword")
        self.assertEqual(result, "test_keyword")

    def test_keyword_strips_whitespace(self):
        """Keyword parameter should strip whitespace and return None if empty."""
        result = RAGFlowAdapter._validate_string_param("   ", "keyword")
        self.assertIsNone(result)

    def test_keyword_accepts_none(self):
        """Keyword parameter should accept None."""
        result = RAGFlowAdapter._validate_string_param(None, "keyword")
        self.assertIsNone(result)


class TestDocumentIdsValidation(unittest.TestCase):
    """Test improvements for document_ids list validation."""

    def test_document_ids_rejects_non_list(self):
        """document_ids should reject non-list types."""
        with self.assertRaises(TypeError) as ctx:
            RAGFlowAdapter._validate_document_ids("not_a_list")
        self.assertIn("must be a list", str(ctx.exception))

    def test_document_ids_rejects_non_string_elements(self):
        """document_ids list should reject non-string elements."""
        with self.assertRaises(ValueError) as ctx:
            RAGFlowAdapter._validate_document_ids([123, "valid_id"])
        self.assertIn("must be a string", str(ctx.exception))
        self.assertIn("document_ids[0]", str(ctx.exception))

    def test_document_ids_rejects_empty_strings(self):
        """document_ids list should reject empty strings."""
        with self.assertRaises(ValueError) as ctx:
            RAGFlowAdapter._validate_document_ids(["valid_id", ""])
        self.assertIn("non-empty string", str(ctx.exception))
        self.assertIn("document_ids[1]", str(ctx.exception))

    def test_document_ids_accepts_valid_list(self):
        """document_ids should accept valid string list."""
        result = RAGFlowAdapter._validate_document_ids(["id1", "id2"])
        self.assertEqual(result, ["id1", "id2"])

    def test_document_ids_strips_whitespace(self):
        """document_ids should strip whitespace from elements."""
        result = RAGFlowAdapter._validate_document_ids(["  id1  ", " id2"])
        self.assertEqual(result, ["id1", "id2"])

    def test_document_ids_accepts_none(self):
        """document_ids should accept None."""
        result = RAGFlowAdapter._validate_document_ids(None)
        self.assertIsNone(result)


class TestHTTPSecurityValidation(unittest.TestCase):
    """Test improvements for HTTP security validation."""

    def test_http_url_raises_runtime_error(self):
        """HTTP URLs should raise RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            RAGFlowAdapter(api_key='test_key', base_url='http://localhost:9380')
        self.assertIn("SECURITY ERROR", str(ctx.exception))
        self.assertIn("unencrypted HTTP", str(ctx.exception))

    def test_https_url_accepted(self):
        """HTTPS URLs should be accepted."""
        adapter = RAGFlowAdapter(api_key='test_key', base_url='https://localhost:9380')
        self.assertEqual(adapter.base_url, 'https://localhost:9380')


class TestTimeoutEnvironmentVariableParsing(unittest.TestCase):
    """Test improvements for timeout environment variable parsing."""

    def test_parse_timeout_with_parameter_value(self):
        """Parameter value should take precedence over environment variable."""
        result = RAGFlowAdapter._parse_timeout_env("TEST_VAR", 10, 5)
        self.assertEqual(result, 10)

    def test_parse_timeout_with_valid_env_var(self):
        """Valid environment variable should be parsed correctly."""
        with patch.dict('os.environ', {'TEST_TIMEOUT': '15'}):
            result = RAGFlowAdapter._parse_timeout_env("TEST_TIMEOUT", None, 5)
            self.assertEqual(result, 15)

    def test_parse_timeout_with_invalid_env_var(self):
        """Invalid environment variable should use default."""
        with patch.dict('os.environ', {'TEST_TIMEOUT': 'invalid'}):
            result = RAGFlowAdapter._parse_timeout_env("TEST_TIMEOUT", None, 5)
            self.assertEqual(result, 5)

    def test_parse_timeout_rejects_negative_parameter(self):
        """Negative timeout parameter should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            RAGFlowAdapter._parse_timeout_env("TEST_VAR", -1, 5)
        self.assertIn("must be positive", str(ctx.exception))


class TestResourceClosureLogging(unittest.TestCase):
    """Test improvements for exception logging during resource closure."""

    def test_close_logs_closure_success(self):
        """Successful closure should log at DEBUG level."""
        with patch.dict('os.environ', {'RAGFLOW_API_KEY': 'test_key'}):
            adapter = RAGFlowAdapter(api_key='test_key', base_url='https://test.com')

            with patch.object(RAGFlowAdapter.logger, 'debug') as mock_debug:
                adapter.close()
                mock_debug.assert_called_once()
                self.assertIn("successfully", mock_debug.call_args[0][0])

    def test_close_logs_closure_exception(self):
        """Exception during closure should log warning."""
        with patch.dict('os.environ', {'RAGFLOW_API_KEY': 'test_key'}):
            adapter = RAGFlowAdapter(api_key='test_key', base_url='https://test.com')

            # Mock session.close() to raise an exception
            adapter.session.close = Mock(side_effect=Exception("Test error"))

            with patch.object(RAGFlowAdapter.logger, 'warning') as mock_warning:
                adapter.close()
                mock_warning.assert_called_once()
                self.assertIn("Exception during session closure", mock_warning.call_args[0][0])


class TestScoreTypeConversion(unittest.TestCase):
    """Test improvements for score type conversion in response parsing."""

    def test_convert_string_score_to_float(self):
        """String scores should be converted to float."""
        result = RAGFlowAdapter._convert_score_to_float("0.85", "similarity", 0)
        self.assertEqual(result, 0.85)

    def test_convert_integer_score_to_float(self):
        """Integer scores should be converted to float."""
        result = RAGFlowAdapter._convert_score_to_float(1, "similarity", 0)
        self.assertEqual(result, 1.0)

    def test_convert_none_score_returns_zero(self):
        """None score should return 0.0."""
        result = RAGFlowAdapter._convert_score_to_float(None, "similarity", 0)
        self.assertEqual(result, 0.0)

    def test_convert_invalid_score_returns_zero(self):
        """Invalid score should return 0.0 and log warning."""
        with patch.object(RAGFlowAdapter.logger, 'warning') as mock_warning:
            result = RAGFlowAdapter._convert_score_to_float("invalid", "similarity", 0)
            self.assertEqual(result, 0.0)
            mock_warning.assert_called_once()


class TestThreadSafetyInClosing(unittest.TestCase):
    """Test thread-safety improvements in close() method."""

    def test_close_is_idempotent(self):
        """Calling close() multiple times should be safe."""
        with patch.dict('os.environ', {'RAGFLOW_API_KEY': 'test_key'}):
            adapter = RAGFlowAdapter(api_key='test_key', base_url='https://test.com')

            # Call close multiple times
            adapter.close()
            adapter.close()
            adapter.close()

            # Verify the adapter is properly closed
            self.assertTrue(adapter._closed)
            self.assertIsNone(adapter.session)


class TestRetrieveExceptionHandling(unittest.TestCase):
    """Test improved exception handling in retrieve() method."""

    def test_retrieve_raises_on_invalid_parameter(self):
        """retrieve() should raise ValueError on invalid parameters."""
        with patch.dict('os.environ', {'RAGFLOW_API_KEY': 'test_key'}):
            adapter = RAGFlowAdapter(api_key='test_key', base_url='https://test.com')

            with self.assertRaises(ValueError):
                adapter.retrieve(
                    question="test",
                    dataset_ids=["test"],
                    keyword=123  # Invalid type
                )

    def test_retrieve_raises_on_invalid_document_ids(self):
        """retrieve() should raise ValueError on invalid document_ids."""
        with patch.dict('os.environ', {'RAGFLOW_API_KEY': 'test_key'}):
            adapter = RAGFlowAdapter(api_key='test_key', base_url='https://test.com')

            with self.assertRaises(ValueError):
                adapter.retrieve(
                    question="test",
                    dataset_ids=["test"],
                    document_ids=[123]  # Invalid type
                )


class TestPreCalculatedAPIURL(unittest.TestCase):
    """Test optimization of pre-calculated API URL."""

    def test_api_url_pre_calculated(self):
        """API URL should be pre-calculated in __init__."""
        with patch.dict('os.environ', {'RAGFLOW_API_KEY': 'test_key'}):
            adapter = RAGFlowAdapter(api_key='test_key', base_url='https://test.com')

            # Verify api_url is pre-calculated
            self.assertEqual(adapter.api_url, 'https://test.com/api/v1/retrieval')

            # Verify it matches constructed URL
            expected_url = f"{adapter.base_url}{adapter.API_ENDPOINT}"
            self.assertEqual(adapter.api_url, expected_url)


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    unittest.main()
