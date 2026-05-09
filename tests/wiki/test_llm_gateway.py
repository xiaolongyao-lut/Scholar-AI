from __future__ import annotations

import json

import pytest

from literature_assistant.core.wiki.llm_gateway import (
    LLMGateway,
    LLMRequest,
    calculate_token_budget,
    truncate_to_budget,
    validate_json_response,
)


class TestLLMGateway:
    def test_stub_mode_summary(self) -> None:
        gateway = LLMGateway(stub_mode=True)
        request = LLMRequest(prompt="Generate a summary of this paper.")
        response = gateway.generate(request)
        assert response.model == "stub"
        assert response.tokens_used > 0
        parsed = json.loads(response.text)
        assert "title" in parsed
        assert "summary" in parsed

    def test_stub_mode_concept(self) -> None:
        gateway = LLMGateway(stub_mode=True)
        request = LLMRequest(prompt="Extract concepts from this text.")
        response = gateway.generate(request)
        parsed = json.loads(response.text)
        assert "concepts" in parsed

    def test_stub_mode_claim(self) -> None:
        gateway = LLMGateway(stub_mode=True)
        request = LLMRequest(prompt="Extract claims from this text.")
        response = gateway.generate(request)
        parsed = json.loads(response.text)
        assert "claims" in parsed

    def test_stub_mode_synthesis(self) -> None:
        gateway = LLMGateway(stub_mode=True)
        request = LLMRequest(prompt="Synthesize an answer to this question.")
        response = gateway.generate(request)
        parsed = json.loads(response.text)
        assert "answer" in parsed

    def test_real_mode_not_implemented(self) -> None:
        gateway = LLMGateway(stub_mode=False)
        request = LLMRequest(prompt="Test")
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            gateway.generate(request)


class TestValidateJsonResponse:
    def test_valid_json(self) -> None:
        text = '{"key": "value"}'
        parsed, error = validate_json_response(text)
        assert error is None
        assert parsed == {"key": "value"}

    def test_invalid_json(self) -> None:
        text = "{invalid json"
        parsed, error = validate_json_response(text)
        assert parsed is None
        assert "Invalid JSON" in error

    def test_non_object(self) -> None:
        text = '["array"]'
        parsed, error = validate_json_response(text)
        assert parsed is None
        assert "must be a JSON object" in error

    def test_non_string(self) -> None:
        parsed, error = validate_json_response(123)  # type: ignore
        assert parsed is None
        assert "must be a string" in error


class TestCalculateTokenBudget:
    def test_within_budget(self) -> None:
        text = "short text"
        budget = calculate_token_budget(text, max_context=100000)
        assert budget == 2

    def test_exceeds_budget(self) -> None:
        text = " ".join(["word"] * 100000)
        budget = calculate_token_budget(text, max_context=10000, reserve_for_output=2000)
        assert budget < 100000
        assert budget == int(8000 / 1.3)

    def test_custom_reserve(self) -> None:
        text = " ".join(["word"] * 10000)
        budget = calculate_token_budget(text, max_context=20000, reserve_for_output=5000)
        assert budget == 10000


class TestTruncateToBudget:
    def test_within_budget(self) -> None:
        text = "short text"
        result = truncate_to_budget(text, token_budget=10)
        assert result == text

    def test_exceeds_budget(self) -> None:
        text = " ".join(["word"] * 100)
        result = truncate_to_budget(text, token_budget=10)
        assert len(result.split()) <= 11
        assert result.endswith("...")

    def test_exact_budget(self) -> None:
        text = " ".join(["word"] * 10)
        result = truncate_to_budget(text, token_budget=10)
        assert result == text
