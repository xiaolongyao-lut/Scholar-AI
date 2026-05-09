from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class LLMRequest:
    prompt: str
    model: str = "stub"
    max_tokens: int = 2000
    temperature: float = 0.7


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    tokens_used: int
    cost_usd: float = 0.0


class LLMGateway:
    def __init__(self, *, stub_mode: bool = True) -> None:
        self.stub_mode = stub_mode

    def generate(self, request: LLMRequest) -> LLMResponse:
        if self.stub_mode:
            return self._stub_generate(request)
        raise NotImplementedError("Real LLM integration not yet implemented")

    def _stub_generate(self, request: LLMRequest) -> LLMResponse:
        prompt_lower = request.prompt.lower()
        if "summary" in prompt_lower or "paper" in prompt_lower:
            text = json.dumps({
                "title": "Stub Paper Title",
                "summary": "This is a stub summary generated in test mode.",
                "key_findings": ["Finding 1", "Finding 2"],
            })
        elif "concept" in prompt_lower:
            text = json.dumps({
                "concepts": [
                    {"name": "Stub Concept", "aliases": ["SC"], "definition": "A test concept."}
                ],
            })
        elif "claim" in prompt_lower:
            text = json.dumps({
                "claims": [
                    {"claim": "Stub claim statement.", "evidence_refs": ["ref1"]}
                ],
            })
        elif "synthesis" in prompt_lower or "answer" in prompt_lower:
            text = json.dumps({
                "answer": "Stub synthesis answer.",
                "evidence_refs": ["ref1", "ref2"],
            })
        else:
            text = json.dumps({"result": "Stub response"})
        return LLMResponse(
            text=text,
            model="stub",
            tokens_used=len(request.prompt.split()) + len(text.split()),
            cost_usd=0.0,
        )


def validate_json_response(text: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(text, str):
        return None, "Response must be a string"
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return None, "Response must be a JSON object"
        return parsed, None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"


def calculate_token_budget(
    source_text: str,
    max_context: int = 100000,
    reserve_for_output: int = 2000,
) -> int:
    available = max_context - reserve_for_output
    estimated_tokens = len(source_text.split()) * 1.3
    if estimated_tokens > available:
        return int(available / 1.3)
    return len(source_text.split())


def truncate_to_budget(text: str, token_budget: int) -> str:
    words = text.split()
    if len(words) <= token_budget:
        return text
    return " ".join(words[:token_budget]) + "..."
